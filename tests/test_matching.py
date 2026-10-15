from decimal import Decimal

from app.matching.engine import diagnose_amount_suspects, match_transactions, reconcile_bank_direction
from app.models import Transaction


def _tx(source, month, direction, amount, day="01"):
    debit = Decimal(amount) if direction == "debit" else Decimal("0")
    credit = Decimal(amount) if direction == "credit" else Decimal("0")
    return Transaction(source=source, date=f"{month}-{day}", month=month,
                       debit_amount=debit, credit_amount=credit, summary=amount)


def _txb(source, month, direction, amount, day="01", balance=None):
    debit = Decimal(amount) if direction == "debit" else Decimal("0")
    credit = Decimal(amount) if direction == "credit" else Decimal("0")
    return Transaction(source=source, date=f"{month}-{day}", month=month,
                       debit_amount=debit, credit_amount=credit, summary=amount,
                       balance=balance)


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


def test_reconcile_bank_direction_flips_reversed_row():
    bank = [_tx("bank", "2026-01", "debit", "3", "20")]
    db = [_tx("db", "2026-01", "credit", "3", "20")]
    flipped = reconcile_bank_direction(bank, db)
    assert flipped == 1
    assert bank[0].direction == "credit"
    assert bank[0].credit_amount == Decimal("3")


def test_reconcile_bank_direction_keeps_same_direction_row():
    bank = [_tx("bank", "2026-01", "debit", "3", "20")]
    db = [_tx("db", "2026-01", "debit", "3", "20")]
    flipped = reconcile_bank_direction(bank, db)
    assert flipped == 0
    assert bank[0].direction == "debit"


def test_reconcile_bank_direction_skips_when_both_directions_exist():
    bank = [_tx("bank", "2026-01", "debit", "3", "20")]
    db = [_tx("db", "2026-01", "debit", "3", "20"),
          _tx("db", "2026-01", "credit", "3", "20")]
    flipped = reconcile_bank_direction(bank, db)
    assert flipped == 0
    assert bank[0].direction == "debit"


def test_reconcile_bank_direction_ignores_date_mismatch():
    # 日期读错（同月不同日）也应能靠金额+月份纠正方向
    bank = [_tx("bank", "2026-01", "debit", "3", "20")]
    db = [_tx("db", "2026-01", "credit", "3", "08")]
    flipped = reconcile_bank_direction(bank, db)
    assert flipped == 1
    assert bank[0].direction == "credit"


def test_reconcile_bank_direction_ignores_no_matching_db():
    bank = [_tx("bank", "2026-01", "debit", "3", "20")]
    db = [_tx("db", "2026-01", "credit", "5", "21")]
    flipped = reconcile_bank_direction(bank, db)
    assert flipped == 0
    assert bank[0].direction == "debit"


def test_diagnose_amount_suspects_flags_misrecognized_amount():
    bank = [
        _txb("bank", "2026-01", "debit", "100", "01", balance=Decimal("1000")),
        _txb("bank", "2026-01", "debit", "50", "02", balance=Decimal("1600")),
    ]
    suspects = diagnose_amount_suspects(bank, [bank[1]])
    assert len(suspects) == 1
    assert suspects[0]["amount"] == "50"
    assert suspects[0]["expected_amount"] == "600"
    assert suspects[0]["prev"]["balance"] == "1000"


def test_diagnose_amount_suspects_skips_consistent_amount():
    bank = [
        _txb("bank", "2026-01", "debit", "100", "01", balance=Decimal("1000")),
        _txb("bank", "2026-01", "debit", "500", "02", balance=Decimal("1500")),
    ]
    assert diagnose_amount_suspects(bank, [bank[1]]) == []


def test_diagnose_amount_suspects_skips_first_row():
    bank = [_txb("bank", "2026-01", "debit", "100", "01", balance=Decimal("1000"))]
    assert diagnose_amount_suspects(bank, [bank[0]]) == []


def test_diagnose_amount_suspects_ignores_direction_only_mismatch():
    # 金额数量对但方向反（余额变动 500、识别金额也是 500），不应报「金额识别错误」。
    bank = [
        _txb("bank", "2026-01", "debit", "100", "01", balance=Decimal("1000")),
        _txb("bank", "2026-01", "credit", "500", "02", balance=Decimal("500")),
    ]
    assert diagnose_amount_suspects(bank, [bank[1]]) == []


def test_partition_invariant_and_merged_empty():
    bank = [_tx("bank", "2026-01", "debit", "30", "05"),
            _tx("bank", "2026-01", "debit", "6.14", "08")]
    db = [_tx("db", "2026-01", "debit", "30", "06")]
    r = match_transactions(bank, db)
    assert r.merged == []
    assert len(r.matched) + len(r.unmatched_bank) == len(bank)
    assert len(r.matched) + len(r.unmatched_db) == len(db)
