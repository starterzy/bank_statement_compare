from datetime import date
from decimal import Decimal

from app.models import Transaction, parse_date, to_decimal, to_int, clean_str


def test_to_decimal_handles_various():
    assert to_decimal("12.83") == Decimal("12.83")
    assert to_decimal(12.83) == Decimal("12.83")
    assert to_decimal("1,234.56") == Decimal("1234.56")
    assert to_decimal("") == Decimal("0")
    assert to_decimal(None) == Decimal("0")
    assert to_decimal("~") == Decimal("0")


def test_parse_date_handles_formats():
    assert parse_date("20260101 17:05:53") == date(2026, 1, 1)
    assert parse_date("20260101") == date(2026, 1, 1)
    assert parse_date("2026-01-13 10:01:55") == date(2026, 1, 13)
    assert parse_date("2026/03/02") == date(2026, 3, 2)
    assert parse_date("~") is None
    assert parse_date(None) is None


def test_transaction_amount_and_direction():
    t = Transaction(source="bank", date="2026-01-01", month="2026-01",
                    debit_amount=Decimal("6.14"), credit_amount=Decimal("0"))
    assert t.amount == Decimal("6.14")
    assert t.direction == "debit"
    t2 = Transaction(source="db", date="2026-01-01", month="2026-01",
                     debit_amount=Decimal("0"), credit_amount=Decimal("800000"))
    assert t2.amount == Decimal("800000")
    assert t2.direction == "credit"


def test_to_int_and_clean_str():
    assert to_int("3") == 3
    assert to_int(5.0) == 5
    assert to_int("~") is None
    assert clean_str(" 电费 ") == "电费"
    assert clean_str("~") is None


def test_to_decimal_nan_inf_and_bad_string():
    assert to_decimal(float("nan")) == Decimal("0")
    assert to_decimal(float("inf")) == Decimal("0")
    assert to_decimal(float("-inf")) == Decimal("0")
    assert to_decimal(Decimal("NaN")) == Decimal("0")
    assert to_decimal("abc") == Decimal("0")


def test_to_int_nan_inf():
    assert to_int(float("nan")) is None
    assert to_int(float("inf")) is None


def test_parse_date_nat():
    import pandas as pd
    assert parse_date(pd.NaT) is None
