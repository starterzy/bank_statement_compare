from decimal import Decimal

from app.matching.merge import find_subsets
from app.matching.engine import match_transactions
from app.models import Transaction


def test_find_subsets_exact_sum():
    r = find_subsets([Decimal("140000000"), Decimal("8050505.55")], Decimal("148050505.55"), 8)
    assert r and set(r[0]) == {0, 1}


def test_find_subsets_no_match():
    assert find_subsets([Decimal("1.00"), Decimal("2.00")], Decimal("10.00"), 8) == []


def _tx(source, month, direction, amount, summary, day="01"):
    debit = Decimal(amount) if direction == "debit" else Decimal("0")
    credit = Decimal(amount) if direction == "credit" else Decimal("0")
    return Transaction(source=source, date=f"{month}-{day}", month=month,
                       debit_amount=debit, credit_amount=credit, summary=summary)


def test_merge_detection_db_side():
    # 数据库一条 = 银行两条（同月同方向）
    db = [_tx("db", "2026-07", "debit", "148050505.55", "归还委贷及利息", "01")]
    bank = [_tx("bank", "2026-07", "debit", "140000000", "归还委贷", "01"),
            _tx("bank", "2026-07", "debit", "8050505.55", "利息", "01")]
    r = match_transactions(bank, db)
    assert len(r.matched) == 0
    assert len(r.merged) == 1
    g = r.merged[0]
    assert g.kind == "db_merged"
    assert g.target.summary == "归还委贷及利息"
    assert len(g.parts) == 2
    assert r.unmatched_bank == [] and r.unmatched_db == []


def test_reverse_merge_bank_side():
    bank = [_tx("bank", "2026-07", "debit", "148050505.55", "还本付息", "01")]
    db = [_tx("db", "2026-07", "debit", "140000000", "归还委贷", "01"),
          _tx("db", "2026-07", "debit", "8050505.55", "利息", "01")]
    r = match_transactions(bank, db)
    assert len(r.merged) == 1
    assert r.merged[0].kind == "bank_merged"
