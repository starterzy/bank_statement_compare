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
