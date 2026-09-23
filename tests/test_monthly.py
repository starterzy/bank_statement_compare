from decimal import Decimal

from app.matching.monthly import compare_monthly, monthly_totals
from app.models import Transaction


def _tx(source, month, direction, amount):
    debit = Decimal(amount) if direction == "debit" else Decimal("0")
    credit = Decimal(amount) if direction == "credit" else Decimal("0")
    return Transaction(source=source, date=f"{month}-01", month=month,
                       debit_amount=debit, credit_amount=credit)


def test_monthly_totals():
    txs = [_tx("bank", "2026-01", "debit", "6.14"),
           _tx("bank", "2026-01", "debit", "5.02"),
           _tx("bank", "2026-01", "credit", "800000")]
    t = monthly_totals(txs)
    assert t["2026-01"]["debit"] == Decimal("11.16")
    assert t["2026-01"]["credit"] == Decimal("800000")


def test_compare_monthly_consistent():
    bank = [_tx("bank", "2026-01", "debit", "100"), _tx("bank", "2026-01", "credit", "50")]
    db = [_tx("db", "2026-01", "debit", "100"), _tx("db", "2026-01", "credit", "50")]
    diffs = compare_monthly(bank, db)
    assert len(diffs) == 1
    assert diffs[0].consistent is True
    assert diffs[0].swap_suspected is False


def test_compare_monthly_mismatch_and_swap():
    bank = [_tx("bank", "2026-01", "debit", "100"), _tx("bank", "2026-01", "credit", "50")]
    db = [_tx("db", "2026-01", "debit", "50"), _tx("db", "2026-01", "credit", "100")]
    diffs = compare_monthly(bank, db)
    assert diffs[0].consistent is False
    assert diffs[0].swap_suspected is True
    assert diffs[0].debit_diff == Decimal("50")
    assert diffs[0].credit_diff == Decimal("-50")


def test_compare_monthly_single_sided_not_consistent_flag():
    bank = [_tx("bank", "2026-01", "debit", "100")]
    db = [_tx("db", "2026-01", "debit", "100"), _tx("db", "2026-02", "debit", "50")]
    diffs = {d.month: d for d in compare_monthly(bank, db)}
    assert diffs["2026-01"].single_sided is False
    assert diffs["2026-01"].consistent is True
    assert diffs["2026-02"].single_sided is True
    assert diffs["2026-02"].consistent is False  # arithmetic diff nonzero, but flagged single_sided
