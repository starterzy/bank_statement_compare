import math
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional


def to_decimal(value) -> Decimal:
    if value is None or isinstance(value, bool):
        return Decimal("0")
    if isinstance(value, Decimal):
        if not value.is_finite():
            return Decimal("0")
        return value.quantize(Decimal("0.01"))
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return Decimal("0")
        return Decimal(str(value)).quantize(Decimal("0.01"))
    if isinstance(value, int):
        return Decimal(value).quantize(Decimal("0.01"))
    s = str(value).strip().replace(",", "").replace("，", "")
    if s in ("", "-", "~", "None", "nan", "NaN", "NaT", "null"):
        return Decimal("0")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def to_int(value) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return int(value)
    s = str(value).strip()
    if s in ("", "~", "None", "nan", "NaN", "NaT", "null"):
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError, OverflowError):
        return None


def clean_str(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    s = str(value).strip()
    if s in ("", "~", "None", "nan", "NaN", "NaT", "null"):
        return None
    return s


def parse_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        result = value.date()
        if isinstance(result, datetime):  # pandas NaT.date() returns NaT (a datetime subclass)
            return None
        return result
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if s in ("", "~", "None", "nan", "NaN", "NaT", "null"):
        return None
    for fmt in (
        "%Y%m%d %H:%M:%S", "%Y%m%d %H:%M", "%Y%m%d",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
        "%Y-%m-%d-%H:%M:%S", "%Y-%m-%d-%H:%M",   # 浙商银行导出：2025-12-31-22:11
        "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
        "%Y.%m.%d %H:%M:%S", "%Y.%m.%d",
    ):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


@dataclass
class Transaction:
    source: str
    date: str
    month: str
    debit_amount: Decimal
    credit_amount: Decimal
    counterparty: Optional[str] = None
    counterparty_account: Optional[str] = None
    summary: Optional[str] = None
    remark: Optional[str] = None
    voucher_no: Optional[str] = None
    detail_index: Optional[int] = None
    transaction_id: Optional[str] = None
    balance: Optional[Decimal] = None
    currency: Optional[str] = None
    raw: dict = field(default_factory=dict)

    @property
    def amount(self) -> Decimal:
        return self.debit_amount if self.debit_amount != 0 else self.credit_amount

    @property
    def direction(self) -> str:
        return "debit" if self.debit_amount != 0 else "credit"
