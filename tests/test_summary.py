from decimal import Decimal

from app.matching.engine import MatchResult, MatchPair, MergeGroup
from app.matching.monthly import MonthlyDiff
from app.reporting.summary import build_summary
from app.models import Transaction


def _tx(source, summary="x"):
    return Transaction(source=source, date="2026-01-01", month="2026-01",
                       debit_amount=Decimal("10"), credit_amount=Decimal("0"), summary=summary)


def _diff(consistent=True):
    return MonthlyDiff(month="2026-01", bank_debit=Decimal("10"),
                       db_debit=Decimal("10") if consistent else Decimal("0"),
                       debit_diff=Decimal("0") if consistent else Decimal("10"),
                       bank_credit=Decimal("0"), db_credit=Decimal("0"),
                       credit_diff=Decimal("0"), swap_suspected=not consistent)


def test_summary_all_matched():
    r = MatchResult(matched=[MatchPair(_tx("bank"), _tx("db"))])
    s = build_summary(r, [_diff(True)])
    assert s["status"] == "all_matched"
    assert s["message"] == "全部对应"


def test_summary_unmatched_before_merged():
    r = MatchResult(unmatched_bank=[_tx("bank")],
                    merged=[MergeGroup(target=_tx("db"), parts=[_tx("bank")], kind="db_merged")])
    s = build_summary(r, [_diff(True)])
    assert s["status"] == "unmatched"


def test_summary_merged_only():
    r = MatchResult(merged=[MergeGroup(target=_tx("db"), parts=[_tx("bank")], kind="db_merged")])
    s = build_summary(r, [_diff(True)])
    assert s["status"] == "merged"
    assert s["message"] == "存在合并记账"


def test_summary_monthly_mismatch_most_severe():
    r = MatchResult(matched=[MatchPair(_tx("bank"), _tx("db"))], unmatched_bank=[_tx("bank")])
    s = build_summary(r, [_diff(False)])
    assert s["status"] == "monthly_mismatch"
    assert s["swap_warning"] is True


def test_summary_single_sided_month_not_mismatch():
    r = MatchResult(matched=[MatchPair(_tx("bank"), _tx("db"))])
    single = MonthlyDiff(month="2026-02", bank_debit=Decimal("0"), db_debit=Decimal("50"),
                         debit_diff=Decimal("-50"), bank_credit=Decimal("0"), db_credit=Decimal("0"),
                         credit_diff=Decimal("0"), single_sided=True)
    s = build_summary(r, [_diff(True), single])
    assert s["status"] == "all_matched"
    assert s["single_sided_months"] == [{"month": "2026-02", "only_in": "db"}]
