import os
import tempfile
from decimal import Decimal

import openpyxl

from app.matching.engine import MatchResult, MatchPair, MergeGroup
from app.matching.monthly import MonthlyDiff
from app.models import Transaction
from app.reporting.excel_writer import write_result_excel


def _tx(source, summary="x", amount="10"):
    return Transaction(source=source, date="2026-01-01", month="2026-01",
                       debit_amount=Decimal(amount), credit_amount=Decimal("0"), summary=summary)


def test_write_result_excel():
    r = MatchResult(
        matched=[MatchPair(_tx("bank", "电费"), _tx("db", "付电费"))],
        merged=[MergeGroup(target=_tx("db", "合并", "30"),
                           parts=[_tx("bank", "a", "10"), _tx("bank", "b", "20")],
                           kind="db_merged")],
        unmatched_bank=[_tx("bank", "仅银行")],
        unmatched_db=[_tx("db", "仅数据库")],
    )
    diffs = [MonthlyDiff(month="2026-01", bank_debit=Decimal("10"), db_debit=Decimal("10"),
                         debit_diff=Decimal("0"), bank_credit=Decimal("0"), db_credit=Decimal("0"),
                         credit_diff=Decimal("0"))]
    tmp = os.path.join(tempfile.mkdtemp(), "out.xlsx")
    write_result_excel(r, diffs, [], [], tmp)
    wb = openpyxl.load_workbook(tmp)
    assert "逐笔明细" in wb.sheetnames
    assert "月度汇总" in wb.sheetnames
    ws = wb["逐笔明细"]
    assert ws.max_row >= 5
