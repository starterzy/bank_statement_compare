"""对账单结构分析：表头行、字段列号、本方账号都由模型给出，不依赖固定格式。

读取层只产出原始网格（app/parsing/excel_reader.read_grid），这里把模型的
分析结果（JSON）落成 StatementAnalysis，再按它把网格转成 Transaction。
模型不可用时，调用方退回 read_table + 启发式（excel_reader / column_mapper）。
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional

from ..models import Transaction, clean_str, parse_date, to_decimal, to_int

# 标准字段（模型输出的 columns 键）
STANDARD_FIELDS = [
    "date", "time", "debit", "credit", "amount", "balance",
    "counterparty", "counterparty_account", "summary", "remark",
    "voucher_no", "detail_index", "transaction_id", "currency",
    # 收支两方分别记在「付款人/收款人」两列时，用带方向后缀的写法
    "counterparty_in", "counterparty_out",
    "counterparty_account_in", "counterparty_account_out",
]

# 金额列的三种写法
AMOUNT_STYLES = ("signed", "debit_credit", "income_expense")


@dataclass
class StatementAnalysis:
    header_row: Optional[int] = None          # 表头所在行（1 起）
    columns: Dict[str, Optional[int]] = field(default_factory=dict)  # 字段 → 列号（1 起）
    amount_style: str = "debit_credit"        # signed 单列带符号 / debit_credit 借贷两列 / income_expense 收支两列
    amount_sign: Dict[str, str] = field(default_factory=lambda: {"positive": "in", "negative": "out"})
    direction_column: Optional[int] = None    # 「交易类型」这类决定方向的列
    direction_values: Dict[str, str] = field(default_factory=dict)   # {"来账": "in", "往账": "out"}
    account_no: Optional[str] = None          # 本方账号（原文，可能带「19-」前缀）
    account_name: Optional[str] = None
    evidence: Optional[str] = None            # 模型给出的依据（哪一行哪一列）
    raw: Dict = field(default_factory=dict)

    @staticmethod
    def from_dict(d: Optional[Dict]) -> "StatementAnalysis":
        """宽容解析模型输出：缺项、类型不对都不应抛异常。"""
        d = d or {}
        own = d.get("own_account") or {}
        cols: Dict[str, Optional[int]] = {}
        for key, val in (d.get("columns") or {}).items():
            try:
                cols[key] = int(val) if val is not None else None
            except (TypeError, ValueError):
                cols[key] = None
        sign = d.get("amount_sign") or {}
        direction_values = {str(k).strip(): v for k, v in (d.get("direction_values") or {}).items()}
        style = str(d.get("amount_style") or "debit_credit")
        return StatementAnalysis(
            header_row=_as_int(d.get("header_row")),
            columns=cols,
            amount_style=style if style in AMOUNT_STYLES else "debit_credit",
            amount_sign={"positive": sign.get("positive", "in"),
                         "negative": sign.get("negative", "out")},
            direction_column=_as_int(d.get("direction_column")),
            direction_values=direction_values,
            account_no=clean_str(own.get("account_no")),
            account_name=clean_str(own.get("account_name")),
            evidence=clean_str(own.get("evidence")),
            raw=d,
        )


def _as_int(v) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _cell(row: List[str], idx: Optional[int]) -> str:
    """按 1 起的列号取值，越界返回空串。"""
    if not idx or idx < 1 or idx > len(row):
        return ""
    return (row[idx - 1] or "").strip()


def _pick(row: List[str], columns: Dict[str, Optional[int]],
          name: str, direction: Optional[str]) -> str:
    """优先取带方向后缀的列（counterparty_in / counterparty_out），否则取通用列。"""
    if direction:
        v = _cell(row, columns.get(f"{name}_{direction}"))
        if v:
            return v
    return _cell(row, columns.get(name))


def _direction(row: List[str], analysis: StatementAnalysis, amount: Decimal) -> str:
    """收付方向：方向列优先，其次金额符号（口径由模型在 amount_sign 里说明）。"""
    if analysis.direction_column:
        val = _cell(row, analysis.direction_column)
        if val:
            hit = analysis.direction_values.get(val)
            if hit in ("in", "out"):
                return hit
            for key, d in analysis.direction_values.items():   # 「来账-商户收单」这类带后缀的写法
                if key and key in val and d in ("in", "out"):
                    return d
    if amount < 0:
        return analysis.amount_sign.get("negative", "out")
    return analysis.amount_sign.get("positive", "in")


def build_from_analysis(grid: List[List[str]], analysis: StatementAnalysis) -> List[Transaction]:
    """按模型给出的表头行/列号/金额写法，把网格转成流水（账簿资产口径：借=收、贷=付）。"""
    cols = analysis.columns
    start = analysis.header_row or 1        # 数据从表头下一行开始
    txs: List[Transaction] = []
    for row in grid[start:]:
        date_text = _cell(row, cols.get("date"))
        time_text = _cell(row, cols.get("time"))
        if date_text and time_text and " " not in date_text:
            date_text = f"{date_text} {time_text}"
        d = parse_date(date_text)
        if d is None:
            continue

        single_amount = analysis.amount_style == "signed" or (
            cols.get("amount") and not cols.get("debit") and not cols.get("credit"))
        if single_amount:
            amount = to_decimal(_cell(row, cols.get("amount")))
            if amount == 0:
                continue
            direction = _direction(row, analysis, amount)
            debit_amount = abs(amount) if direction == "in" else Decimal("0")
            credit_amount = abs(amount) if direction == "out" else Decimal("0")
        else:
            debit_amount = to_decimal(_cell(row, cols.get("debit")))    # 收入 → 借
            credit_amount = to_decimal(_cell(row, cols.get("credit")))  # 支出 → 贷
            if debit_amount == 0 and credit_amount == 0:
                continue
            direction = "in" if debit_amount else "out"

        balance_text = _cell(row, cols.get("balance"))
        txs.append(Transaction(
            source="bank",
            date=d.isoformat(),
            month=d.strftime("%Y-%m"),
            debit_amount=debit_amount,
            credit_amount=credit_amount,
            counterparty=clean_str(_pick(row, cols, "counterparty", direction)),
            counterparty_account=clean_str(_pick(row, cols, "counterparty_account", direction)),
            summary=clean_str(_cell(row, cols.get("summary"))),
            remark=clean_str(_cell(row, cols.get("remark"))),
            voucher_no=clean_str(_cell(row, cols.get("voucher_no"))),
            detail_index=to_int(_cell(row, cols.get("detail_index"))),
            transaction_id=clean_str(_cell(row, cols.get("transaction_id"))),
            balance=to_decimal(balance_text) if balance_text else None,
            currency=clean_str(_cell(row, cols.get("currency"))),
            raw={"row": row, **analysis.raw},
        ))
    return txs
