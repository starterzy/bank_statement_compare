from decimal import Decimal

from app.matching.monthly import compare_monthly, monthly_totals
from app.models import Transaction


def _tx(source, month, direction, amount):
    debit = Decimal(amount) if direction == "debit" else Decimal("0")
    credit = Decimal(amount) if direction == "credit" else Decimal("0")
    return Transaction(source=source, date=f"{month}-01", month=month,
                       debit_amount=debit, credit_amount=credit)


def _txb(source, month, direction, amount, balance=None, day="01"):
    debit = Decimal(amount) if direction == "debit" else Decimal("0")
    credit = Decimal(amount) if direction == "credit" else Decimal("0")
    return Transaction(source=source, date=f"{month}-{day}", month=month,
                       debit_amount=debit, credit_amount=credit, balance=balance)


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


def test_compare_monthly_balances_from_authoritative_db():
    # 银行侧：期初 1000 + 收 100 = 期末 1100；DB 权威月余额表一致。
    bank = [_txb("bank", "2026-01", "debit", "100", balance=Decimal("1100"))]
    db = [_txb("db", "2026-01", "debit", "100")]
    db_monthly = {"2026-01": {"opening": Decimal("1000"), "closing": Decimal("1100")}}
    d = compare_monthly(bank, db, db_monthly_balances=db_monthly)[0]
    assert d.bank_opening == Decimal("1000")
    assert d.bank_closing == Decimal("1100")
    assert d.db_opening == Decimal("1000")
    assert d.db_closing == Decimal("1100")
    assert d.balance_consistent is True
    assert d.balance_mismatch is False


def test_compare_monthly_balance_mismatch():
    bank = [_txb("bank", "2026-01", "debit", "100", balance=Decimal("1100"))]
    db = [_txb("db", "2026-01", "debit", "100")]
    db_monthly = {"2026-01": {"opening": Decimal("1000"), "closing": Decimal("1200")}}
    d = compare_monthly(bank, db, db_monthly_balances=db_monthly)[0]
    assert d.balance_mismatch is True
    assert d.closing_diff == Decimal("-100")
    assert d.opening_diff == Decimal("0")


def test_compare_monthly_opening_from_first_row():
    # 第一笔余额 1100 − 其发生额 100 = 期初 1000；后续行余额链有断点（识别误差），
    # 期初应按第一笔推导，而不是「期末 − 本月净额」（那会是 1200 − 150 = 1050）。
    bank = [
        _txb("bank", "2026-01", "debit", "100", balance=Decimal("1100"), day="01"),
        _txb("bank", "2026-01", "debit", "50", balance=Decimal("1200"), day="05"),
    ]
    db = [_txb("db", "2026-01", "debit", "150")]
    db_monthly = {"2026-01": {"opening": Decimal("1000"), "closing": Decimal("1200")}}
    d = compare_monthly(bank, db, db_monthly_balances=db_monthly)[0]
    assert d.bank_opening == Decimal("1000")
    assert d.bank_closing == Decimal("1200")
    assert d.opening_diff == Decimal("0")


def test_compare_monthly_descending_file_picks_true_month_end():
    """导出文件整体倒序（新→旧）时，同一天内也是「后发生的在前」，
    月末余额要取当天第一行的余额，而不是按 date 稳定排序后的最后一行。"""
    bank = [
        _txb("bank", "2026-01", "credit", "100", balance=Decimal("900"), day="30"),  # 当天最后一笔
        _txb("bank", "2026-01", "credit", "50", balance=Decimal("1000"), day="30"),  # 当天较早一笔
        _txb("bank", "2026-01", "debit", "100", balance=Decimal("1050"), day="10"),
    ]
    db = [_txb("db", "2026-01", "debit", "100")]
    db_monthly = {"2026-01": {"opening": Decimal("950"), "closing": Decimal("900")}}

    d = compare_monthly(bank, db, db_monthly_balances=db_monthly)[0]

    assert d.bank_closing == Decimal("900")
    assert d.bank_opening == Decimal("950")
    assert d.balance_consistent is True


def test_compare_monthly_ascending_file_picks_last_row_of_day():
    bank = [
        _txb("bank", "2026-01", "debit", "100", balance=Decimal("1050"), day="10"),
        _txb("bank", "2026-01", "credit", "50", balance=Decimal("1000"), day="30"),
        _txb("bank", "2026-01", "credit", "100", balance=Decimal("900"), day="30"),
    ]
    db = [_txb("db", "2026-01", "debit", "100")]
    db_monthly = {"2026-01": {"opening": Decimal("950"), "closing": Decimal("900")}}

    d = compare_monthly(bank, db, db_monthly_balances=db_monthly)[0]

    assert d.bank_closing == Decimal("900")
    assert d.bank_opening == Decimal("950")


def test_compare_monthly_no_balance_data_is_consistent():
    bank = [_txb("bank", "2026-01", "debit", "100")]
    db = [_txb("db", "2026-01", "debit", "100")]
    d = compare_monthly(bank, db)[0]
    assert d.bank_closing is None
    assert d.db_closing is None
    assert d.balance_consistent is True
    assert d.balance_mismatch is False
