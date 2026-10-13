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
from collections import OrderedDict
from decimal import Decimal
from typing import Dict, List, Optional

from ..config import DB_COLUMN_MAP
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
_QUERY_SQL = """
SELECT DISTINCT {cols}
FROM NCCDATA.gl_detail gl_detail, NCCDATA.gl_docfree1
WHERE gl_detail.yearv = :year
  AND gl_detail.adjustperiod >= :pfrom
  AND gl_detail.adjustperiod <= :pto
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


def list_companies(cfg: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
    """列出有启用银行账户的公司，返回 [{"org": pk_org, "name": 公司名, "book": 账簿, "accasoa": 银行存款·人民币科目}]。

    公司 ↔ 账簿用 org_accountingbook.PK_RELORG 关联（PK_ORG 存的是集团）。
    """
    cfg = cfg or get_db_config()
    conn = _connect(cfg)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT o.pk_org, o.name, b.pk_accountingbook, a.pk_accasoa "
            "FROM NCCDATA.org_orgs o "
            "JOIN NCCDATA.org_accountingbook b ON b.pk_relorg = o.pk_org "
            "JOIN NCCDATA.bd_accasoa a ON a.pk_accchart = b.pk_curraccchart "
            "  AND a.dispname LIKE '1002%' AND a.name = '人民币' "
            "WHERE o.pk_org IN (SELECT DISTINCT pk_org FROM NCCDATA.bd_bankaccbas WHERE enablestate IN (1, 2)) "
            "ORDER BY o.code"
        )
        return [{"org": r[0], "name": r[1], "book": r[2], "accasoa": r[3]} for r in cur.fetchall()]
    finally:
        conn.close()


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


def fetch_bank_detail(cfg: Optional[Dict[str, str]] = None, year: Optional[str] = None,
                      f11: Optional[str] = None, book: Optional[str] = None,
                      accasoa: Optional[str] = None) -> List[Transaction]:
    """连库查询银行流水，返回 Transaction 列表。

    f11 为空（None/""）→ 查该科目+账簿下「全部银行账户」的流水（对照所有）；
    f11 给出 → 只查该账户（F11 = bd_bankaccsub.pk_bankaccsub）。
    """
    cfg = cfg or get_db_config()
    year = year or cfg["DB_YEAR"]
    book = book or cfg["DB_ACCOUNTING_BOOK"]
    accasoa = accasoa or cfg["DB_PK_ACCASOA"]

    if f11:
        fcond = "AND gl_docfree1.F11 = :f11"
    else:
        fcond = "AND gl_docfree1.F11 <> 'N/A'"

    conn = _connect(cfg)
    try:
        cur = conn.cursor()
        cols = ", ".join(f"gl_detail.{c}" for c in DB_SELECT_COLUMNS)
        params = {
            "year": year,
            "pfrom": cfg["DB_PERIOD_FROM"],
            "pto": cfg["DB_PERIOD_TO"],
            "book": book,
            "accasoa": accasoa,
        }
        if f11:
            params["f11"] = f11
        cur.execute(_QUERY_SQL.format(cols=cols, fcond=fcond), params)
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
                    year: Optional[str] = None) -> Dict:
    """一次取全「期初/期末 + 月度发生额 + 每笔流水」，供查询页展示。"""
    cfg = cfg or get_db_config()
    year = year or cfg["DB_YEAR"]
    book = book or cfg["DB_ACCOUNTING_BOOK"]
    accasoa = accasoa or cfg["DB_PK_ACCASOA"]

    txs = fetch_bank_detail(cfg, year=year, f11=f11, book=book, accasoa=accasoa)
    opening = fetch_opening_balance(cfg, year=year, f11=f11, book=book, accasoa=accasoa)

    monthly: "OrderedDict[str, Dict]" = OrderedDict()
    total_debit = Decimal(0)
    total_credit = Decimal(0)
    for t in txs:
        m = monthly.setdefault(t.month, {"debit": Decimal(0), "credit": Decimal(0), "count": 0})
        m["debit"] += t.debit_amount
        m["credit"] += t.credit_amount
        m["count"] += 1
        total_debit += t.debit_amount
        total_credit += t.credit_amount

    running = opening
    monthly_rows = []
    for month, m in monthly.items():
        running += m["debit"] - m["credit"]
        monthly_rows.append({
            "month": month,
            "debit": _fmt(m["debit"]),
            "credit": _fmt(m["credit"]),
            "count": m["count"],
            "balance": _fmt(running),
        })

    transactions = [{
        "date": t.date,
        "voucher_no": t.voucher_no or "",
        "detail_index": t.detail_index if t.detail_index is not None else "",
        "summary": t.summary or "",
        "debit": _fmt(t.debit_amount),
        "credit": _fmt(t.credit_amount),
    } for t in txs]

    closing = opening + total_debit - total_credit
    return {
        "opening": _fmt(opening),
        "total_debit": _fmt(total_debit),
        "total_credit": _fmt(total_credit),
        "closing": _fmt(closing),
        "monthly": monthly_rows,
        "transactions": transactions,
        "count": len(txs),
    }
