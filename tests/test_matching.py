from decimal import Decimal

from app.matching.engine import match_transactions
from app.models import Transaction


def _tx(source, month, direction, amount, day="01"):
    debit = Decimal(amount) if direction == "debit" else Decimal("0")
    credit = Decimal(amount) if direction == "credit" else Decimal("0")
    return Transaction(source=source, date=f"{month}-{day}", month=month,
                       debit_amount=debit, credit_amount=credit, summary=amount)


def test_match_same_amount_same_month():
    bank = [_tx("bank", "2026-01", "debit", "6.14", "01")]
    db = [_tx("db", "2026-01", "debit", "6.14", "02")]
    r = match_transactions(bank, db)
    assert len(r.matched) == 1
    assert r.unmatched_bank == [] and r.unmatched_db == []


def test_no_match_different_month():
    bank = [_tx("bank", "2026-01", "debit", "6.14")]
    db = [_tx("db", "2026-02", "debit", "6.14")]
    r = match_transactions(bank, db)
    assert r.matched == []
    assert len(r.unmatched_bank) == 1 and len(r.unmatched_db) == 1


def test_no_match_different_direction():
    bank = [_tx("bank", "2026-01", "debit", "100")]
    db = [_tx("db", "2026-01", "credit", "100")]
    r = match_transactions(bank, db)
    assert r.matched == []


def test_duplicate_amount_uses_nearest_date():
    bank = [_tx("bank", "2026-01", "debit", "30", "05"),
            _tx("bank", "2026-01", "debit", "30", "20")]
    db = [_tx("db", "2026-01", "debit", "30", "21"),
          _tx("db", "2026-01", "debit", "30", "06")]
    r = match_transactions(bank, db)
    assert len(r.matched) == 2
    # 05 应配 06，20 应配 21
    for p in r.matched:
        assert abs(int(p.bank.date[-2:]) - int(p.db.date[-2:])) <= 1


def test_partition_invariant_and_merged_empty():
    bank = [_tx("bank", "2026-01", "debit", "30", "05"),
            _tx("bank", "2026-01", "debit", "6.14", "08")]
    db = [_tx("db", "2026-01", "debit", "30", "06")]
    r = match_transactions(bank, db)
    assert r.merged == []
    assert len(r.matched) + len(r.unmatched_bank) == len(bank)
    assert len(r.matched) + len(r.unmatched_db) == len(db)
