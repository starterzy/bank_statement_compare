from typing import List

from ..matching.engine import MatchResult
from ..matching.monthly import MonthlyDiff


def _message(status: str) -> str:
    if status == "all_matched":
        return "全部对应"
    if status == "monthly_mismatch":
        return "存在月度总额不一致，请优先核对"
    if status == "unmatched":
        return "存在未匹配项"
    return "存在合并记账"


def build_summary(match_result: MatchResult, monthly_diffs: List[MonthlyDiff]) -> dict:
    mismatches = [d for d in monthly_diffs if not d.single_sided and not d.consistent]
    unmatched_bank = match_result.unmatched_bank
    unmatched_db = match_result.unmatched_db
    merged = match_result.merged

    if mismatches:
        status = "monthly_mismatch"
    elif unmatched_bank or unmatched_db:
        status = "unmatched"
    elif merged:
        status = "merged"
    else:
        status = "all_matched"

    return {
        "status": status,
        "message": _message(status),
        "swap_warning": any(d.swap_suspected for d in monthly_diffs),
        "single_sided_months": [
            {"month": d.month, "only_in": "bank" if (d.bank_debit or d.bank_credit) else "db"}
            for d in monthly_diffs if d.single_sided
        ],
        "monthly_mismatches": [
            {"month": d.month, "debit_diff": str(d.debit_diff), "credit_diff": str(d.credit_diff)}
            for d in mismatches
        ],
        "unmatched_bank_count": len(unmatched_bank),
        "unmatched_db_count": len(unmatched_db),
        "unmatched_bank": [
            {"date": t.date, "amount": str(t.amount), "summary": t.summary} for t in unmatched_bank
        ],
        "unmatched_db": [
            {"date": t.date, "amount": str(t.amount), "summary": t.summary} for t in unmatched_db
        ],
        "merged_count": len(merged),
        "merged": [
            {"kind": g.kind, "target_amount": str(g.target.amount), "target_summary": g.target.summary,
             "parts": [{"amount": str(p.amount), "summary": p.summary} for p in g.parts]}
            for g in merged
        ],
        "matched_count": len(match_result.matched),
    }
