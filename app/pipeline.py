from dataclasses import dataclass, field
from typing import Callable, List

from .config import MAX_MERGE_SIZE
from .matching.engine import MatchResult, match_transactions
from .matching.monthly import MonthlyDiff, compare_monthly
from .models import Transaction
from .parsing.column_mapper import build_transactions, map_bank_via_llm
from .parsing.excel_reader import read_excel
from .reporting.summary import build_summary


@dataclass
class CompareResult:
    bank_txs: List[Transaction] = field(default_factory=list)
    db_txs: List[Transaction] = field(default_factory=list)
    match_result: MatchResult = field(default_factory=MatchResult)
    monthly_diffs: List[MonthlyDiff] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _run(bank_txs: List[Transaction], db_txs: List[Transaction]) -> CompareResult:
    match_result = match_transactions(bank_txs, db_txs, max_merge_size=MAX_MERGE_SIZE)
    monthly_diffs = compare_monthly(bank_txs, db_txs)
    summary = build_summary(match_result, monthly_diffs)
    return CompareResult(bank_txs=bank_txs, db_txs=db_txs, match_result=match_result,
                         monthly_diffs=monthly_diffs, summary=summary)


def run_compare(bank_path: str, db_path: str, bank_mapper: Callable, db_column_map: dict) -> CompareResult:
    bank_raw = read_excel(bank_path)
    db_raw = read_excel(db_path)
    bank_txs = map_bank_via_llm(bank_raw, bank_mapper)
    db_txs = build_transactions(db_raw, db_column_map, "db")
    return _run(bank_txs, db_txs)


def run_compare_with_db(bank_path: str, db_txs: List[Transaction], bank_mapper: Callable) -> CompareResult:
    """数据库流水由 DB 直连查询得到（不再读文件）。"""
    bank_raw = read_excel(bank_path)
    bank_txs = map_bank_via_llm(bank_raw, bank_mapper)
    return _run(bank_txs, db_txs)
