import os
from decimal import Decimal

from app.config import DB_COLUMN_MAP, BANK_COLUMN_MAP
from app.parsing.excel_reader import read_excel
from app.parsing.column_mapper import build_transactions

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def test_build_db_transactions():
    raw = read_excel(os.path.join(FIXTURES, "db.xlsx"))
    txs = build_transactions(raw, DB_COLUMN_MAP, "db")
    assert len(txs) == 117
    # 校验一笔已知交易：缴12月税金 598092.61 在贷方
    t = next(x for x in txs if x.credit_amount == Decimal("598092.61"))
    assert t.summary == "缴12月税金"
    assert t.direction == "credit"
    assert t.month == "2026-01"


def test_build_bank_transactions():
    raw = read_excel(os.path.join(FIXTURES, "bank.xls"))
    txs = build_transactions(raw, BANK_COLUMN_MAP, "bank")
    assert len(txs) == 118
    # 一笔电费 12.83 在贷方（银行对账单方向已对齐到账簿口径：贷=付）
    t = next(x for x in txs if x.credit_amount == Decimal("12.83"))
    assert t.counterparty == "国网浙江省电力有限公司"
    assert t.direction == "credit"
    assert t.month == "2026-01"


def test_skip_rows_without_amount():
    raw = read_excel(os.path.join(FIXTURES, "db.xlsx"))
    txs = build_transactions(raw, DB_COLUMN_MAP, "db")
    assert all(x.debit_amount != 0 or x.credit_amount != 0 for x in txs)
