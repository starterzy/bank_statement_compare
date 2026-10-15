from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import List, Tuple

from ..models import Transaction
from .merge import find_subsets


@dataclass
class MatchPair:
    bank: Transaction
    db: Transaction


@dataclass
class MergeGroup:
    target: Transaction
    parts: List[Transaction]
    kind: str  # "db_merged" / "bank_merged"


@dataclass
class MatchResult:
    matched: List[MatchPair] = field(default_factory=list)
    merged: List[MergeGroup] = field(default_factory=list)
    unmatched_bank: List[Transaction] = field(default_factory=list)
    unmatched_db: List[Transaction] = field(default_factory=list)


def _date_dist(a: str, b: str) -> int:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def _greedy_1to1(bank, db) -> Tuple[List[MatchPair], List[Transaction], List[Transaction]]:
    remaining_db = list(db)
    matched = []
    unmatched_bank = []
    for b in sorted(bank, key=lambda t: t.date):
        cands = [d for d in remaining_db if d.amount == b.amount]
        if not cands:
            unmatched_bank.append(b)
            continue
        best = min(cands, key=lambda d: _date_dist(b.date, d.date))
        matched.append(MatchPair(bank=b, db=best))
        remaining_db.remove(best)
    return matched, unmatched_bank, remaining_db


def _detect_merges(targets, candidates, kind, max_size):
    groups = []
    remaining_targets = []
    used = set()
    for t in targets:
        cand = [c for c in candidates if id(c) not in used]
        subsets = find_subsets([c.amount for c in cand], t.amount, max_size)
        if subsets:
            parts = [cand[i] for i in subsets[0]]
            groups.append(MergeGroup(target=t, parts=parts, kind=kind))
            for p in parts:
                used.add(id(p))
        else:
            remaining_targets.append(t)
    remaining_candidates = [c for c in candidates if id(c) not in used]
    return groups, remaining_targets, remaining_candidates


def reconcile_bank_direction(bank_txs, db_txs) -> int:
    """用数据库的权威方向纠正银行对账单里识别反了的单笔方向。

    图像 OCR 偶把某笔流水的「借/贷」看反（尤其小金额行），而余额纠错只能兜住
    「方向反了但余额读对」的情况。数据库方向是权威的：对每笔银行流水，若数据库
    中存在「同月份+同金额」且方向相反的一条（且没有同方向的），说明银行侧识别
    反了，翻转之。不匹配日期——图像 OCR 的日期也可能读错。返回翻转的笔数。
    """
    by_key = defaultdict(list)
    for d in db_txs:
        by_key[(d.month, d.amount)].append(d)
    flipped = 0
    for b in bank_txs:
        same = by_key.get((b.month, b.amount), [])
        if not same:
            continue
        if any(d.direction == b.direction for d in same):
            continue  # 有同方向的数据库记录，说明不是翻反
        b.debit_amount, b.credit_amount = b.credit_amount, b.debit_amount
        flipped += 1
    return flipped


def diagnose_amount_suspects(bank_txs: List[Transaction],
                             unmatched_bank: List[Transaction]) -> List[dict]:
    """对未匹配的银行行，用上下行余额判断金额是否识别错误。

    余额列是「交易后余额」，账簿资产口径下满足 balance[i] = balance[i-1] + 借 − 贷。
    若某未匹配行金额与本行余额较上一行的变动不符（且变动非零），说明该行金额可能
    识别错误。返回该行与上下行的识别数据及按余额链推得的应有金额，供人工核对。
    """
    ordered = sorted(bank_txs, key=lambda t: t.date)
    pos = {id(t): i for i, t in enumerate(ordered)}

    def row(t: Transaction) -> dict:
        return {
            "date": t.date,
            "amount": str(t.amount),
            "balance": str(t.balance) if t.balance is not None else None,
            "summary": t.summary,
        }

    suspects: List[dict] = []
    for t in unmatched_bank:
        i = pos.get(id(t))
        if i is None or i == 0 or t.balance is None:
            continue
        prev = ordered[i - 1]
        if prev.balance is None:
            continue
        expected = abs(t.balance - prev.balance)
        if expected == 0:
            continue  # 余额无变化，无法据此判断金额
        if t.amount == expected:
            continue  # 金额与余额链自洽，不是识别金额错误
        nxt = ordered[i + 1] if i + 1 < len(ordered) else None
        suspects.append({
            "date": t.date,
            "amount": str(t.amount),
            "expected_amount": str(expected),
            "balance": str(t.balance),
            "summary": t.summary,
            "prev": row(prev),
            "next": row(nxt) if nxt else None,
        })
    return suspects


def match_transactions(bank_txs, db_txs, max_merge_size=8) -> MatchResult:
    result = MatchResult()
    bank_groups = defaultdict(list)
    db_groups = defaultdict(list)
    for t in bank_txs:
        bank_groups[(t.month, t.direction)].append(t)
    for t in db_txs:
        db_groups[(t.month, t.direction)].append(t)

    for key in sorted(set(bank_groups) | set(db_groups)):
        matched, un_bank, un_db = _greedy_1to1(bank_groups.get(key, []), db_groups.get(key, []))
        result.matched.extend(matched)
        # 正向：数据库一条 = 银行多条
        merged_db, un_db, un_bank = _detect_merges(un_db, un_bank, "db_merged", max_merge_size)
        result.merged.extend(merged_db)
        # 反向：银行一条 = 数据库多条
        merged_bank, un_bank, un_db = _detect_merges(un_bank, un_db, "bank_merged", max_merge_size)
        result.merged.extend(merged_bank)
        result.unmatched_bank.extend(un_bank)
        result.unmatched_db.extend(un_db)
    return result
