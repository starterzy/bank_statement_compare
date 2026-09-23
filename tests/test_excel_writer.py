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


def test_write_result_excel_bank_merged_sides():
    r = MatchResult(
        merged=[MergeGroup(target=_tx("bank", "还本付息", "30"),
                           parts=[_tx("db", "归还委贷", "10"), _tx("db", "利息", "20")],
                           kind="bank_merged")],
    )
    tmp = os.path.join(tempfile.mkdtemp(), "out.xlsx")
    write_result_excel(r, [], [], [], tmp)
    ws = openpyxl.load_workbook(tmp)["逐笔明细"]
    # row 2 = target（银行侧）→ 银行摘要(G=7) 有值，数据库摘要(I=9) 为空
    assert ws.cell(row=2, column=7).value == "还本付息"
    assert ws.cell(row=2, column=9).value in (None, "")
    # row 3 = part（数据库侧）→ 数据库摘要(I=9) 有值，银行摘要(G=7) 为空
    assert ws.cell(row=3, column=9).value == "归还委贷"
    assert ws.cell(row=3, column=7).value in (None, "")
