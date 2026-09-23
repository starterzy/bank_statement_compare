from dataclasses import dataclass, field
from typing import Dict, List

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
