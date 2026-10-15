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


def _tx(t) -> dict:
    """把一笔流水序列化成前端可直接渲染的字段（空行用 None 占位）。"""
    return {
        "date": t.date,
        "month": t.month,
        "direction": "借" if t.direction == "debit" else "贷",
        "amount": str(t.amount),
        "counterparty": t.counterparty,
        "summary": t.summary,
        "voucher_no": t.voucher_no,
        "detail_index": t.detail_index,
    }


def build_detail_rows(match_result: MatchResult) -> list:
    """逐笔匹配明细：与 Excel「逐笔明细」页同构的扁平行列表。"""
    rows = []
    for p in match_result.matched:
        rows.append({"status": "已匹配", "bank": _tx(p.bank), "db": _tx(p.db)})
    for g in match_result.merged:
        if g.kind == "bank_merged":
            # 银行一条 = 数据库多条：target 在银行侧，parts 在数据库侧
            rows.append({"status": "合并记账", "bank": _tx(g.target), "db": None})
            for part in g.parts:
                rows.append({"status": "└ 拆分", "bank": None, "db": _tx(part)})
        else:
            # 数据库一条 = 银行多条：target 在数据库侧，parts 在银行侧
            rows.append({"status": "合并记账", "bank": None, "db": _tx(g.target)})
            for part in g.parts:
                rows.append({"status": "└ 拆分", "bank": _tx(part), "db": None})
    for t in match_result.unmatched_bank:
        rows.append({"status": "仅银行有", "bank": _tx(t), "db": None})
    for t in match_result.unmatched_db:
        rows.append({"status": "仅数据库有", "bank": None, "db": _tx(t)})
    return rows


def build_summary(match_result: MatchResult, monthly_diffs: List[MonthlyDiff],
                  amount_suspects: List[dict] = None) -> dict:
    mismatches = [d for d in monthly_diffs if not d.single_sided and not d.consistent]
    balance_mismatches = [d for d in monthly_diffs if not d.single_sided and d.balance_mismatch]
    unmatched_bank = match_result.unmatched_bank
    unmatched_db = match_result.unmatched_db
    merged = match_result.merged

    if mismatches or balance_mismatches:
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
        "balance_warning": bool(balance_mismatches),
        "single_sided_months": [
            {"month": d.month, "only_in": "bank" if (d.bank_debit or d.bank_credit) else "db"}
            for d in monthly_diffs if d.single_sided
        ],
        "monthly_mismatches": [
            {"month": d.month, "debit_diff": str(d.debit_diff), "credit_diff": str(d.credit_diff)}
            for d in mismatches
        ],
        "balance_mismatches": [
            {"month": d.month,
             "opening_diff": str(d.opening_diff),
             "closing_diff": str(d.closing_diff),
             "bank_opening": str(d.bank_opening) if d.bank_opening is not None else None,
             "db_opening": str(d.db_opening) if d.db_opening is not None else None,
             "bank_closing": str(d.bank_closing) if d.bank_closing is not None else None,
             "db_closing": str(d.db_closing) if d.db_closing is not None else None}
            for d in balance_mismatches
        ],
        "unmatched_bank_count": len(unmatched_bank),
        "unmatched_db_count": len(unmatched_db),
        "amount_suspects": amount_suspects or [],
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
