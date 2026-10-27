import csv
import io
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional

import pandas as pd


@dataclass
class RawTable:
    headers: List[str] = field(default_factory=list)
    rows: List[Dict] = field(default_factory=list)
    # 表头之前的行（标题行、账户信息行等），供抽取本方账号/户名使用
    preamble: List[List] = field(default_factory=list)


# 日期型单元格（整格匹配）：2026-01-08 / 2026/1/8 / 2026年1月8日 / 20260108，可带时间
_DATE_CELL = re.compile(
    r"^\d{4}[-/年.]\d{1,2}([-/月.]\d{1,2})?日?"
    r"([ T]\d{1,2}:\d{2}(:\d{2})?)?$"
    r"|^\d{8}$"
)
# 金额型字符串单元格（整格匹配）：4161.47 / 4,161.47 / -1200
_NUM_CELL = re.compile(r"^[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$")
# 「字段名：值」式单元格（账户信息行特征），如「账号：3300…」
_LABEL_CELL = re.compile(r"^[一-龥A-Za-z（）() ]{1,16}[:：]")


def _is_empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    if isinstance(v, str) and not v.strip():
        return True
    return False


def _is_data_cell(v) -> bool:
    """整格看像数据（数字/金额/日期）而非字段名。"""
    if _is_empty(v):
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return True
    s = str(v).strip()
    return bool(_DATE_CELL.match(s) or _NUM_CELL.match(s))


def _is_label_cell(v) -> bool:
    """「账号：xxx」这类字段名+值同格的单元格。"""
    return isinstance(v, str) and bool(_LABEL_CELL.match(v.strip()))


def _row_is_data(row) -> bool:
    cells = [c for c in row if not _is_empty(c)]
    if len(cells) < 2:
        return False
    if any(_is_label_cell(c) for c in cells):
        return False
    return any(_is_data_cell(c) for c in cells)


def _looks_like_header(row) -> bool:
    cells = [c for c in row if not _is_empty(c)]
    if len(cells) < 2:
        return False
    str_cells = [c for c in cells if isinstance(c, str)]
    return len(str_cells) / len(cells) >= 0.6 and not any(_is_data_cell(c) for c in cells)


def _detect_header_row(data) -> int:
    """定位表头行。

    银行导出常见「标题行 → 账户信息行 → 表头 → 明细」，不能简单取第一行文本行：
    先找连续的数据行（数字/日期整格且无「字段：值」标签），再向上取最近的一行
    文本行作为表头。空单元格无论 None / NaN / 空串都按空处理。
    """
    data_start = None
    for i in range(len(data) - 1):
        if _row_is_data(data[i]) and _row_is_data(data[i + 1]):
            data_start = i
            break
    if data_start is None:  # 只有一行数据（或数据全是无法识别的文本）时退化为单行判断
        for i, row in enumerate(data):
            if _row_is_data(row):
                data_start = i
                break

    if data_start is not None:
        for j in range(data_start - 1, -1, -1):
            if _looks_like_header(data[j]):
                return j

    # 兜底：第一行像表头的行（跳过单格标题行）
    for idx, row in enumerate(data):
        if _looks_like_header(row):
            return idx
    return 0


def _cell_str(v) -> str:
    """网格里的单元格一律转成字符串：日期格式化、整数别写成 6.2e+18、空值统一成空串。"""
    if v is None:
        return ""
    if isinstance(v, float):
        if math.isnan(v):
            return ""
        return f"{v:.0f}" if v.is_integer() else str(v)
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def _decode(raw: bytes) -> str:
    """银行导出的编码五花八门：BOM 优先，其次 utf-8，再退 gb18030（GBK 超集）。"""
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        first = sample.splitlines()[0] if sample else ""
        counts = {d: first.count(d) for d in ",;\t|"}
        best = max(counts, key=counts.get)
        return best if counts[best] else ","


_CSV_EXTS = (".csv", ".txt", ".tsv")

# 按文件内容而不是扩展名判断真实格式：不少银行/业务系统导出的「.csv」其实是
# Excel 97-2003（OLE2 复合文档）或 xlsx（zip）二进制，按文本读会报
# new-line character seen in unquoted field 或读出乱码。
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGIC = b"PK\x03\x04"


def _excel_grid(path: str, engine: str) -> List[List[str]]:
    df = pd.read_excel(path, header=None, dtype=object, engine=engine)
    return [[_cell_str(c) for c in row] for row in df.values.tolist()]


def read_grid(path: str) -> List[List[str]]:
    """把任意表格文件读成原始二维网格（单元格字符串），不判断表头、不抽账号。

    只负责「把文件变成表」：先按魔数分流（OLE2→xlrd、zip→openpyxl），
    否则按扩展名走 CSV/TXT（编码与分隔符嗅探）或 Excel。
    表头、字段、本方账号一律交给模型分析（见 app/parsing/statement.py）。
    """
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as f:
        head = f.read(8)
    if head.startswith(_OLE2_MAGIC):
        rows = _excel_grid(path, "xlrd")
    elif head.startswith(_ZIP_MAGIC):
        rows = _excel_grid(path, "openpyxl")
    elif ext in _CSV_EXTS:
        with open(path, "rb") as f:
            text = _decode(f.read())
        delim = _sniff_delimiter(text[:4096])
        # newline=""：让 csv 自己做通用换行（\r、\n、\r\n）。默认 newline="\n" 时
        # 只用 \r 换行的导出文件整份会被当成一行，报 new-line character seen in unquoted field。
        rows = [[(c or "").strip() for c in r]
                for r in csv.reader(io.StringIO(text, newline=""), delimiter=delim)]
    else:
        rows = _excel_grid(path, "xlrd" if ext == ".xls" else "openpyxl")
    return [r for r in rows if any(c for c in r)]   # 丢掉整行空白


def grid_to_table(grid: List[List[str]]) -> RawTable:
    """原始网格 → RawTable（启发式猜表头，模型分析不可用时的兜底）。"""
    data = grid
    if not data:
        return RawTable()
    header_idx = _detect_header_row(data)
    headers = [str(c).strip() if c is not None else "" for c in data[header_idx]]
    rows = []
    for row in data[header_idx + 1:]:
        d = {}
        for i, h in enumerate(headers):
            d[h] = row[i] if i < len(row) else None
        rows.append(d)
    return RawTable(headers=headers, rows=rows, preamble=data[:header_idx])


def read_table(path: str) -> RawTable:
    """任意表格文件（xls/xlsx/csv/txt）→ RawTable，表头用启发式猜。"""
    return grid_to_table(read_grid(path))


def read_excel(path: str) -> RawTable:
    """兼容旧接口：现在按扩展名分派，CSV 也能读。"""
    return read_table(path)


def sample_rows(raw: RawTable, n: int = 8) -> List[Dict]:
    return raw.rows[:n]


# 本方账号：表头列名不能含「对方/对手/收付」等字样
_COUNTERPARTY_HINTS = ("对方", "对手", "收款", "付款", "收方", "付方")
_ACCOUNT_LABELS = ("账号", "账户号码", "银行账号", "卡号", "客户账号")
_ACCOUNT_LABEL_RE = re.compile(
    r"(?:账\s*号|账户号码|银行账号|卡号|客户账号)\s*[:：]?\s*([0-9][0-9\-\s]{10,30})"
)
_NAME_LABEL_RE = re.compile(
    r"(?:户\s*名|账户名称|账户名|客户名称|单位名称)\s*[:：]\s*([^\s|,，;；]{2,50})"
)


def _norm_account(v) -> Optional[str]:
    norm = re.sub(r"\D", "", str(v))
    return norm if 12 <= len(norm) <= 30 else None


def _is_counterparty_header(h: str) -> bool:
    hs = (h or "").strip()
    return any(k in hs for k in _COUNTERPARTY_HINTS)


def _extract_from_preamble(preamble: List[List]) -> Dict[str, Optional[str]]:
    """从表头之前的标题/账户信息行抽取本方账号与户名。

    支持两种写法：同格「账号：330016…」、相邻两格「账号 | 330016…」。
    """
    account_no: Optional[str] = None
    account_name: Optional[str] = None
    for row in preamble:
        cells = [c for c in row if not _is_empty(c)]
        # 相邻两格：标签 + 值
        for i, c in enumerate(cells[:-1]):
            label = str(c).strip()
            nxt = cells[i + 1]
            if account_no is None and label in _ACCOUNT_LABELS:
                account_no = _norm_account(nxt)
            if account_name is None and label in ("户名", "账户名称", "账户名",
                                                  "客户名称", "单位名称"):
                account_name = str(nxt).strip()
        # 同格：「账号：xxx」「账户名称：xxx」
        for c in cells:
            s = str(c).strip()
            if account_no is None:
                m = _ACCOUNT_LABEL_RE.search(s)
                if m:
                    account_no = _norm_account(m.group(1))
            if account_name is None:
                m = _NAME_LABEL_RE.search(s)
                if m:
                    account_name = m.group(1).strip()
    return {"account_no": account_no, "account_name": account_name}


def _extract_from_columns(raw: RawTable) -> Dict[str, Optional[str]]:
    """从表头列名 + 数据列抽取本方账号/户名。"""
    account_no: Optional[str] = None
    account_name: Optional[str] = None

    def _first_nonempty(col: str) -> Optional[str]:
        for r in raw.rows:
            v = r.get(col)
            if v is not None and str(v).strip():
                return str(v).strip()
        return None

    # 账号列：表头含「账号」，不含「对方/对手/收付」
    for h in raw.headers:
        hs = (h or "").strip()
        if "账号" in hs and not _is_counterparty_header(hs):
            v = _first_nonempty(h)
            if v:
                account_no = _norm_account(v)
                if account_no:
                    break

    # 户名列：表头含「户名/账户名称」，不含「对方/对手/收付」
    for h in raw.headers:
        hs = (h or "").strip()
        if ("户名" in hs or "账户名称" in hs) and not _is_counterparty_header(hs):
            account_name = _first_nonempty(h)
            if account_name:
                break

    return {"account_no": account_no, "account_name": account_name}


def _extract_dominant_account(raw: RawTable) -> Optional[str]:
    """兜底：找「每行都相同」的账号列。

    本方账号列在每条明细里重复出现；对方账号列通常有大量不同值。
    因此只接受覆盖 ≥50% 行、且只有唯一取值的列。只取单元格内独立的
    15~30 位数字串，避免把 1001A11000000000F1XL 这类编码去字母后误判成账号。
    """
    n = len(raw.rows)
    if n < 2:
        return None
    for h in raw.headers:
        if _is_counterparty_header(h):
            continue
        vals = []
        for r in raw.rows:
            v = r.get(h)
            if v is None:
                continue
            m = re.search(r"\d{15,30}", str(v))
            if m:
                vals.append(m.group(0))
        if len(vals) >= max(2, n * 0.5) and len(set(vals)) == 1:
            return vals[0]
    return None


def extract_account_from_table(raw: RawTable) -> Dict[str, Optional[str]]:
    """从银行对账单 Excel 抽取本方账号与户名，返回 {"account_no": str|None, "account_name": str|None}。

    优先级：表头前的账户信息行（如「账号：3300…」）→ 表头里的本方账号/户名列 →
    兜底找每行都相同的账号列。任何情况下都不会把「对方账号」当成本方账号。
    """
    info: Dict[str, Optional[str]] = {"account_no": None, "account_name": None}

    pre = _extract_from_preamble(raw.preamble)
    info["account_no"] = pre["account_no"]
    info["account_name"] = pre["account_name"]

    cols = _extract_from_columns(raw)
    if info["account_no"] is None:
        info["account_no"] = cols["account_no"]
    if info["account_name"] is None:
        info["account_name"] = cols["account_name"]

    if info["account_no"] is None:
        info["account_no"] = _extract_dominant_account(raw)

    return info
