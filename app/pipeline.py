from dataclasses import dataclass, field
from typing import Callable, List

from .config import MAX_MERGE_SIZE
from .matching.engine import (MatchResult, diagnose_amount_suspects, match_transactions,
                               reconcile_bank_direction)
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


def _run(bank_txs: List[Transaction], db_txs: List[Transaction],
         db_monthly_balances: dict = None) -> CompareResult:
    reconcile_bank_direction(bank_txs, db_txs)
    match_result = match_transactions(bank_txs, db_txs, max_merge_size=MAX_MERGE_SIZE)
    monthly_diffs = compare_monthly(bank_txs, db_txs, db_monthly_balances=db_monthly_balances)
    amount_suspects = diagnose_amount_suspects(bank_txs, match_result.unmatched_bank)
    summary = build_summary(match_result, monthly_diffs, amount_suspects)
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


def run_matching(bank_txs: List[Transaction], db_txs: List[Transaction],
                 db_monthly_balances: dict = None) -> CompareResult:
    """对已解析好的两份流水做逐笔匹配 + 月度核对 + 生成摘要（供流式接口复用）。

    db_monthly_balances：DB 侧权威月余额表 {month: {"opening": Decimal, "closing": Decimal}}，
    用于对比月度期初/期末余额（来自 Oracle 期初链；文件数据源可省略）。
    """
    return _run(bank_txs, db_txs, db_monthly_balances=db_monthly_balances)
