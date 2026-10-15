from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd


@dataclass
class RawTable:
    headers: List[str] = field(default_factory=list)
    rows: List[Dict] = field(default_factory=list)


def _detect_header_row(data) -> int:
    for idx, row in enumerate(data):
        cells = [c for c in row if c is not None and str(c).strip() != ""]
        if not cells:
            continue
        str_cells = [c for c in cells if isinstance(c, str)]
        if len(str_cells) / len(cells) >= 0.5:
            return idx
    return 0


def read_excel(path: str) -> RawTable:
    engine = "xlrd" if path.lower().endswith(".xls") else "openpyxl"
    df = pd.read_excel(path, header=None, dtype=object, engine=engine)
    data = df.values.tolist()
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
    return RawTable(headers=headers, rows=rows)


def sample_rows(raw: RawTable, n: int = 8) -> List[Dict]:
    return raw.rows[:n]


def extract_account_from_table(raw: RawTable) -> Dict[str, Optional[str]]:
    """从银行对账单 Excel 抽取账号与户名，返回 {"account_no": str|None, "account_name": str|None}。

    账号优先取表头含「账号」且不含「对方/对手」的列（如「客户账号」）首个非空值；
    兜底扫全表出现次数最多的 15~30 位纯数字串（避免把日期/金额误判成账号）。
    """
    import re

    account_no: Optional[str] = None
    account_name: Optional[str] = None

    def _first_nonempty(col: str) -> Optional[str]:
        for r in raw.rows:
            v = r.get(col)
            if v is not None and str(v).strip():
                return str(v).strip()
        return None

    # 账号列：表头含「账号」，不含「对方/对手」
    for h in raw.headers:
        hs = (h or "").strip()
        if "账号" in hs and "对方" not in hs and "对手" not in hs:
            v = _first_nonempty(h)
            if v:
                norm = re.sub(r"\D", "", v)
                if 12 <= len(norm) <= 30:
                    account_no = norm
            break

    # 户名列：表头含「户名/账户名称」，不含「对方」
    if account_name is None:
        for h in raw.headers:
            hs = (h or "").strip()
            if ("户名" in hs or "账户名称" in hs) and "对方" not in hs:
                account_name = _first_nonempty(h)
                break

    # 兜底：全表最常出现的 15~30 位纯数字串
    if not account_no:
        cnt: Counter = Counter()
        for h in raw.headers:
            for r in raw.rows:
                v = r.get(h)
                if v is None:
                    continue
                for m in re.findall(r"\d{15,30}", str(v)):
                    cnt[m] += 1
        if cnt:
            account_no = cnt.most_common(1)[0][0]

    return {"account_no": account_no, "account_name": account_name}
