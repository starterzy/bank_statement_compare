"""直连 Oracle 财务库，读取银行流水（GL_DETAIL 里银行存款科目的明细）。

连接参数与查询口径来自 .env（可选覆盖），密码只放在本机 .env，不进仓库。
Oracle 11g 需 thick 模式 + Instant Client（本机已装，路径见 .env）。

查询口径（与 NC 系统导出口径一致）：
- 公司 org_orgs(pk_org) ↔ 账簿 org_accountingbook：用 PK_RELORG 关联（PK_ORG 存的是集团）；
- 账簿 PK_CURRACCCHART → bd_accchart（科目体系）→ bd_accasoa（科目+辅助核算）；
- 银行存款的人民币子户 dispname='100201\\银行存款\\人民币'，pk_accasoa 即查询用科目；
- GL_DETAIL 关联单据自由项 GL_DOCFREE1（assid），F11 = bd_bankaccsub.pk_bankaccsub 唯一锁定银行账户；
- 期初余额在 GL_BALANCE（adjustperiod='00'），各月发生额在 adjustperiod='01'..'12'。
"""
import os
import re
from collections import OrderedDict
from decimal import Decimal
from typing import Dict, List, Optional

from ..config import DB_COLUMN_MAP, GROUP_COMPANY_ROOT, GROUP_ORG
from ..models import Transaction
from ..parsing.column_mapper import build_transactions
from ..parsing.excel_reader import RawTable

ENV_PATH = ".env"

# 非敏感默认值；密码等敏感项只在 .env / 环境变量里出现。
DEFAULTS: Dict[str, str] = {
    "ORACLE_HOST": "10.8.190.61",
    "ORACLE_PORT": "1521",
    "ORACLE_SERVICE": "ZNKGNCC",
    "ORACLE_USER": "nccread_zy",
    "ORACLE_PASSWORD": "",
    "ORACLE_LIB_DIR": "",
    # 默认公司/账簿/科目（银行存款·人民币）；前端公司选择会动态覆盖
    "DB_ACCOUNTING_BOOK": "1001A11000000000F1XL",
    "DB_PK_ACCASOA": "1001A11000000000ENQP",
    "DB_ORG": "0001A110000000001I2D",
    "DB_YEAR": "2026",
    "DB_PERIOD_FROM": "01",
    "DB_PERIOD_TO": "12",
}

# GL_DETAIL 里映射到 DB_COLUMN_MAP 的列（顺序即 SELECT 顺序）。
DB_SELECT_COLUMNS = ["PREPAREDDATEV", "DEBITAMOUNT", "CREDITAMOUNT", "EXPLANATION", "NOV", "DETAILINDEX"]


def load_env(path: str = ENV_PATH) -> Dict[str, str]:
    """极简 .env 解析：按首个 '=' 切分，值原样保留（不剥注释、不做变量插值）。

    用自研解析而非 python-dotenv，是为了让密码里的 '#'、'$' 等特殊字符原样通过。
    """
    if not os.path.exists(path):
        return {}
    out: Dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            out[k.strip()] = v
    return out


def get_db_config() -> Dict[str, str]:
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in load_env().items() if v != ""})
    for k in DEFAULTS:
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    return cfg


def map_db_rows(rows: List[Dict]) -> List[Transaction]:
    """把 GL_DETAIL 查询结果行（键为 DB_SELECT_COLUMNS）映射成 Transaction 列表。"""
    raw = RawTable(headers=list(DB_SELECT_COLUMNS), rows=rows)
    return build_transactions(raw, DB_COLUMN_MAP, "db")


# 与 NC 系统导出口径一致的核心 WHERE（关联单据自由项 + 期间等过滤）。
# {fcond} 由调用方填入账户过滤条件：具体账户 = F11=:f11，全部账户 = F11<>'N/A'。
# {pcond} 期间条件：单月 = adjustperiod=:month，全年 = adjustperiod 在 :pfrom..:pto。
_QUERY_SQL = """
SELECT DISTINCT {cols}
FROM NCCDATA.gl_detail gl_detail, NCCDATA.gl_docfree1
WHERE gl_detail.yearv = :year
  {pcond}
  AND gl_detail.assid = gl_docfree1.assid
  AND gl_detail.pk_accountingbook = :book
  AND gl_detail.pk_managerv <> 'N/A'
  AND gl_detail.discardflagv <> 'Y'
  AND gl_detail.dr = 0
  AND gl_detail.voucherkindv NOT IN (2, 255, 5)
  AND gl_detail.tempsaveflag <> 'Y'
  AND gl_detail.pk_accasoa = :accasoa
  {fcond}
ORDER BY gl_detail.prepareddatev, gl_detail.detailindex
"""

# 期初余额（GL_BALANCE，adjustperiod='00'）。
_OPENING_SQL = """
SELECT SUM(gl_balan.debitamount), SUM(gl_balan.creditamount)
FROM NCCDATA.gl_balance gl_balan, NCCDATA.gl_docfree1
WHERE gl_balan.assid = gl_docfree1.assid
  AND gl_balan.pk_accountingbook = :book
  AND gl_balan.year = :year
  AND gl_balan.adjustperiod >= '00' AND gl_balan.adjustperiod < '01'
  AND gl_balan.voucherkind <> 5
  AND gl_balan.pk_accasoa = :accasoa
  AND gl_docfree1.F11 <> 'N/A'
  {fcond}
"""


def _connect(cfg: Dict[str, str]):
    import oracledb

    lib_dir = cfg.get("ORACLE_LIB_DIR") or ""
    if lib_dir:
        oracledb.init_oracle_client(lib_dir=lib_dir)
    else:
        oracledb.init_oracle_client()
    dsn = f"{cfg['ORACLE_HOST']}:{cfg['ORACLE_PORT']}/{cfg['ORACLE_SERVICE']}"
    return oracledb.connect(user=cfg["ORACLE_USER"], password=cfg["ORACLE_PASSWORD"], dsn=dsn)


def list_companies(cfg: Optional[Dict[str, str]] = None,
                   org_roots: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """列出有启用银行账户的公司，返回 [{"org": pk_org, "name": 公司名, "book": 账簿, "accasoa": 银行存款·人民币科目}]。

    只展示「浙农控股」集团根（GROUP_ORG）下的公司（没有银行账号的不展示）。

    org_roots 用于按用户可见范围过滤：
    - None → 不过滤（全部，管理员用）；
    - [] → 无可见公司（返回空）；
    - 非空 → 只保留这些子树根（含其自身）之下的公司。

    公司 ↔ 账簿用 org_accountingbook.PK_RELORG 关联（PK_ORG 存的是集团）。
    """
    if org_roots is not None and not org_roots:
        return []
    cfg = cfg or get_db_config()
    conn = _connect(cfg)
    try:
        cur = conn.cursor()
        sql = (
            "SELECT o.pk_org, o.name, b.pk_accountingbook, a.pk_accasoa "
            "FROM NCCDATA.org_orgs o "
            "JOIN NCCDATA.org_accountingbook b ON b.pk_relorg = o.pk_org "
            "JOIN NCCDATA.bd_accasoa a ON a.pk_accchart = b.pk_curraccchart "
            "  AND a.dispname LIKE '1002%' AND a.name = '人民币' "
            "WHERE o.dr = 0 "
            "AND o.pk_group = :org_group "
            "AND o.pk_org IN (SELECT DISTINCT pk_org FROM NCCDATA.bd_bankaccbas WHERE enablestate IN (1, 2)) "
        )
        params: Dict[str, str] = {"org_group": GROUP_ORG}
        if org_roots:
            binds = {f"r{i}": r for i, r in enumerate(org_roots)}
            inlist = ", ".join(f":r{i}" for i in range(len(org_roots)))
            sql += ("AND o.pk_org IN (SELECT pk_org FROM NCCDATA.org_orgs "
                    f"START WITH pk_org IN ({inlist}) CONNECT BY NOCYCLE PRIOR pk_org = pk_fatherorg) ")
            params.update(binds)
        sql += "ORDER BY o.code"
        cur.execute(sql, params)
        return [{"org": r[0], "name": r[1], "book": r[2], "accasoa": r[3]} for r in cur.fetchall()]
    finally:
        conn.close()


def fetch_org_tree(cfg: Optional[Dict[str, str]] = None) -> dict:
    """返回浙农控股集团下的组织树（嵌套），供用户管理界面勾选可见公司子树。

    每个节点：{pk_org, code, name, is_company（有启用银行账号）, children[]}。
    只保留「有银行账号的公司 + 其控股中间节点」，部门/虚拟组织等无公司子树的节点被剪掉。
    """
    cfg = cfg or get_db_config()
    conn = _connect(cfg)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT o.pk_org, o.code, o.name, o.pk_fatherorg, "
            "  CASE WHEN o.pk_org IN (SELECT DISTINCT pk_org FROM NCCDATA.bd_bankaccbas "
            "                            WHERE enablestate IN (1, 2)) THEN 1 ELSE 0 END "
            "FROM NCCDATA.org_orgs o "
            "WHERE o.dr = 0 AND o.pk_group = :org_group",
            org_group=GROUP_ORG,
        )
        nodes = {r[0]: {"pk_org": r[0], "code": r[1], "name": r[2],
                        "father": r[3], "is_company": bool(r[4])} for r in cur.fetchall()}
    finally:
        conn.close()

    children: Dict[str, List[str]] = {}
    for pk, n in nodes.items():
        children.setdefault(n["father"], []).append(pk)

    def build(pk: str) -> Optional[dict]:
        n = nodes.get(pk)
        if n is None:
            return None
        kids = [k for k in (build(c) for c in children.get(pk, [])) if k is not None]
        if not n["is_company"] and not kids:
            return None  # 无公司子树的中间节点剪掉
        return {"pk_org": n["pk_org"], "code": n["code"], "name": n["name"],
                "is_company": n["is_company"], "children": kids}

    root = build(GROUP_COMPANY_ROOT)
    if root is None:
        root = {"pk_org": GROUP_COMPANY_ROOT, "code": "", "name": "浙农控股集团有限公司",
                "is_company": False, "children": []}
    return root


def list_bank_accounts(cfg: Optional[Dict[str, str]] = None, org: Optional[str] = None) -> List[Dict[str, str]]:
    """列出某公司（org）启用的银行账户，返回 [{"f11": pk_bankaccsub, "code": 账号, "name": 账户名}]。"""
    cfg = cfg or get_db_config()
    org = org or cfg["DB_ORG"]
    conn = _connect(cfg)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT s.pk_bankaccsub, b.code, b.name "
            "FROM NCCDATA.bd_bankaccbas b, NCCDATA.bd_bankaccsub s "
            "WHERE b.pk_bankaccbas = s.pk_bankaccbas "
            "AND b.pk_org = :org AND b.enablestate IN (1, 2) "
            "ORDER BY b.code",
            org=org,
        )
        return [{"f11": r[0], "code": r[1], "name": r[2]} for r in cur.fetchall()]
    finally:
        conn.close()


def _norm_code(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def _code_matches(norm: str, nc_code: str) -> bool:
    """两侧账号规范化后是否为同一个账户。

    对账单与 NC 的账号写法可能不同：农行对账单印「19-720101040019411」，
    NC 只存后 15 位「720101040019411」，也可能反过来。因此任一方向的后缀
    包含即算命中；短账号（<9 位）不参与后缀匹配，避免「411」命中一大片。
    """
    nc = _norm_code(nc_code)
    n = _norm_code(norm)
    if not nc or not n:
        return False
    if nc == n:
        return True
    return ((len(nc) >= 9 and n.endswith(nc)) or
            (len(n) >= 9 and nc.endswith(n)))


def find_accounts_by_code(code: str, cfg: Optional[Dict[str, str]] = None,
                          org_roots: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """按银行账号（bd_bankaccbas.code）反查账户，返回候选列表。

    每个候选：{"code": 账号, "name": 账户名, "org": pk_org, "org_name": 公司名,
              "org_code": 公司编码, "f11": pk_bankaccsub, "book": 账簿, "accasoa": 科目}。
    账号先规范化成纯数字再精确匹配（对账单可能含空格/横线）；只在启用账户里搜。
    精确匹配不到时（对账单带「19-」这类省市前缀、NC 只存后几位），退回本地后缀比对。
    org_roots 用于按用户可见范围过滤：None=不过滤，[]=空，非空=只保留这些子树下的公司。
    同一账号可能命中多个公司（或一账号多子户），返回全部候选由调用方决定选哪个。
    """
    if org_roots is not None and not org_roots:
        return []
    norm = _norm_code(code)
    if not norm:
        return []
    cfg = cfg or get_db_config()
    conn = _connect(cfg)
    try:
        cur = conn.cursor()
        sql = (
            "SELECT b.code, b.name, b.pk_org, o.name, o.code, s.pk_bankaccsub, "
            "       bk.pk_accountingbook, a.pk_accasoa "
            "FROM NCCDATA.bd_bankaccbas b "
            "JOIN NCCDATA.bd_bankaccsub s ON b.pk_bankaccbas = s.pk_bankaccbas "
            "JOIN NCCDATA.org_orgs o ON o.pk_org = b.pk_org AND o.dr = 0 "
            "JOIN NCCDATA.org_accountingbook bk ON bk.pk_relorg = o.pk_org "
            "JOIN NCCDATA.bd_accasoa a ON a.pk_accchart = bk.pk_curraccchart "
            "  AND a.dispname LIKE '1002%' AND a.name = '人民币' "
            "WHERE b.enablestate IN (1, 2) "
            "AND o.pk_group = :org_group "
        )
        params: Dict[str, str] = {"org_group": GROUP_ORG}
        if org_roots:
            binds = {f"r{i}": r for i, r in enumerate(org_roots)}
            inlist = ", ".join(f":r{i}" for i in range(len(org_roots)))
            sql += ("AND o.pk_org IN (SELECT pk_org FROM NCCDATA.org_orgs "
                    f"START WITH pk_org IN ({inlist}) CONNECT BY NOCYCLE PRIOR pk_org = pk_fatherorg) ")
            params.update(binds)

        def _rows() -> List[Dict[str, str]]:
            return [{"code": r[0], "name": r[1], "org": r[2], "org_name": r[3], "org_code": r[4],
                     "f11": r[5], "book": r[6], "accasoa": r[7]} for r in cur.fetchall()]

        cur.execute(sql + "AND REGEXP_REPLACE(b.code, '[^0-9]', '') = :norm", {**params, "norm": norm})
        rows = _rows()
        if not rows:
            cur.execute(sql, params)  # 账号写法不一致：取全部启用账户本地比对
            rows = [r for r in _rows() if _code_matches(norm, r["code"])]
        return rows
    finally:
        conn.close()


def list_years(cfg: Optional[Dict[str, str]] = None, book: Optional[str] = None,
               accasoa: Optional[str] = None) -> List[str]:
    """列出某账簿+科目下 GL_DETAIL 存在数据的年份（降序），供年份下拉选择。"""
    cfg = cfg or get_db_config()
    book = book or cfg["DB_ACCOUNTING_BOOK"]
    accasoa = accasoa or cfg["DB_PK_ACCASOA"]
    conn = _connect(cfg)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT gl_detail.yearv "
            "FROM NCCDATA.gl_detail gl_detail "
            "WHERE gl_detail.pk_accountingbook = :book AND gl_detail.pk_accasoa = :accasoa "
            "ORDER BY gl_detail.yearv DESC",
            book=book, accasoa=accasoa,
        )
        return [r[0] for r in cur.fetchall() if r[0]]
    finally:
        conn.close()


def fetch_bank_detail(cfg: Optional[Dict[str, str]] = None, year: Optional[str] = None,
                      f11: Optional[str] = None, book: Optional[str] = None,
                      accasoa: Optional[str] = None, month: Optional[str] = None,
                      month_to: Optional[str] = None) -> List[Transaction]:
    """连库查询银行流水，返回 Transaction 列表。

    f11 为空（None/""）→ 查该科目+账簿下「全部银行账户」的流水（对照所有）；
    f11 给出 → 只查该账户（F11 = bd_bankaccsub.pk_bankaccsub）。
    month 给出（"01".."12"）→ 只查该月；为空 → 查 DB_PERIOD_FROM..截止月，
    其中截止月 = month_to（未给则用 DB_PERIOD_TO）。
    """
    cfg = cfg or get_db_config()
    year = year or cfg["DB_YEAR"]
    book = book or cfg["DB_ACCOUNTING_BOOK"]
    accasoa = accasoa or cfg["DB_PK_ACCASOA"]

    if f11:
        fcond = "AND gl_docfree1.F11 = :f11"
    else:
        fcond = "AND gl_docfree1.F11 <> 'N/A'"

    if month:
        pcond = "AND gl_detail.adjustperiod = :month"
    else:
        pcond = "AND gl_detail.adjustperiod >= :pfrom AND gl_detail.adjustperiod <= :pto"

    conn = _connect(cfg)
    try:
        cur = conn.cursor()
        cols = ", ".join(f"gl_detail.{c}" for c in DB_SELECT_COLUMNS)
        params = {
            "year": year,
            "book": book,
            "accasoa": accasoa,
        }
        if month:
            params["month"] = month
        else:
            params["pfrom"] = cfg["DB_PERIOD_FROM"]
            params["pto"] = month_to or cfg["DB_PERIOD_TO"]
        if f11:
            params["f11"] = f11
        cur.execute(_QUERY_SQL.format(cols=cols, fcond=fcond, pcond=pcond), params)
        rows = [dict(zip(DB_SELECT_COLUMNS, r)) for r in cur.fetchall()]
    finally:
        conn.close()
    return map_db_rows(rows)


def fetch_opening_balance(cfg: Optional[Dict[str, str]] = None, year: Optional[str] = None,
                          f11: Optional[str] = None, book: Optional[str] = None,
                          accasoa: Optional[str] = None) -> Decimal:
    """期初余额（资产类银行账户：借-贷）。"""
    cfg = cfg or get_db_config()
    year = year or cfg["DB_YEAR"]
    book = book or cfg["DB_ACCOUNTING_BOOK"]
    accasoa = accasoa or cfg["DB_PK_ACCASOA"]

    fcond = "AND gl_docfree1.F11 = :f11" if f11 else ""

    conn = _connect(cfg)
    try:
        cur = conn.cursor()
        params = {"book": book, "accasoa": accasoa, "year": year}
        if f11:
            params["f11"] = f11
        cur.execute(_OPENING_SQL.format(fcond=fcond), params)
        d, c = cur.fetchone()
    finally:
        conn.close()
    return Decimal(d or 0) - Decimal(c or 0)


def _fmt(v: Decimal) -> str:
    return f"{v:.2f}"


def fetch_statement(cfg: Optional[Dict[str, str]] = None, f11: Optional[str] = None,
                    book: Optional[str] = None, accasoa: Optional[str] = None,
                    year: Optional[str] = None, month: Optional[str] = None,
                    month_to: Optional[str] = None) -> Dict:
    """一次取全「期初/期末 + 月度发生额 + 每笔流水」，供查询页展示。

    month 为空 → 全年口径（期初=年初，期末=年末，发生额=全年合计，流水=全部）；
    month_to 给出时限定到该月（例如 08 → 只取 1-8 月）；
    month 给出（"01".."12"）→ 该月口径：期初=年初+之前各月净额，发生额/流水只含该月，
    期末=期初+该月净额；monthly 仍返回各月（供前端高亮选中月）。
    """
    cfg = cfg or get_db_config()
    year = year or cfg["DB_YEAR"]
    book = book or cfg["DB_ACCOUNTING_BOOK"]
    accasoa = accasoa or cfg["DB_PK_ACCASOA"]

    txs = fetch_bank_detail(cfg, year=year, f11=f11, book=book, accasoa=accasoa, month_to=month_to)
    opening = fetch_opening_balance(cfg, year=year, f11=f11, book=book, accasoa=accasoa)

    monthly: "OrderedDict[str, Dict]" = OrderedDict()
    for t in txs:
        m = monthly.setdefault(t.month, {"debit": Decimal(0), "credit": Decimal(0), "count": 0})
        m["debit"] += t.debit_amount
        m["credit"] += t.credit_amount
        m["count"] += 1

    running = opening
    monthly_rows = []
    for mo, m in monthly.items():
        month_open = running
        running += m["debit"] - m["credit"]
        monthly_rows.append({
            "month": mo,
            "opening": _fmt(month_open),
            "debit": _fmt(m["debit"]),
            "credit": _fmt(m["credit"]),
            "count": m["count"],
            "balance": _fmt(running),
        })

    selected = f"{year}-{int(month):02d}" if month else None
    if selected:
        # 选中月期初 = 年初 + 之前各月净额；期末 = 期初 + 该月净额。
        month_open = opening
        for mo in monthly:
            if mo < selected:
                month_open += monthly[mo]["debit"] - monthly[mo]["credit"]
        m = monthly.get(selected, {"debit": Decimal(0), "credit": Decimal(0), "count": 0})
        total_debit = m["debit"]
        total_credit = m["credit"]
        closing = month_open + total_debit - total_credit
        opening = month_open
        txs = [t for t in txs if t.month == selected]
    else:
        total_debit = sum(m["debit"] for m in monthly.values())
        total_credit = sum(m["credit"] for m in monthly.values())
        closing = opening + total_debit - total_credit

    transactions = [{
        "date": t.date,
        "voucher_no": t.voucher_no or "",
        "detail_index": t.detail_index if t.detail_index is not None else "",
        "summary": t.summary or "",
        "debit": _fmt(t.debit_amount),
        "credit": _fmt(t.credit_amount),
    } for t in txs]

    return {
        "opening": _fmt(opening),
        "total_debit": _fmt(total_debit),
        "total_credit": _fmt(total_credit),
        "closing": _fmt(closing),
        "selected_month": selected,
        "monthly": monthly_rows,
        "transactions": transactions,
        "count": len(txs),
    }
