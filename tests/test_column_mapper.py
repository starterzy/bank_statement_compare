import os
from decimal import Decimal

from app.config import DB_COLUMN_MAP, BANK_COLUMN_MAP
from app.parsing.excel_reader import read_excel
from app.parsing.column_mapper import build_transactions, build_transactions_from_rows

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


def test_build_transactions_from_rows():
    # 图片识别按「银行口径」如实输出：借方=支取(付)、贷方=存入(收)；
    # 代码硬编码翻转为账簿资产口径（借=收、贷=付）。
    rows = [
        {"date": "2025-05-06", "debit": 19400000.00, "credit": 0,
         "counterparty": None, "summary": "支取", "balance": "19481026.78"},
        {"date": "2025-05-06", "debit": 0, "credit": 20044166.66,
         "counterparty": None, "summary": "存入", "balance": "39525193.44"},
        {"date": None, "debit": 100, "credit": 0, "summary": "无日期应跳过"},
        {"date": "2025-05-08", "debit": 0, "credit": 0, "summary": "无金额应跳过"},
    ]
    txs = build_transactions_from_rows(rows, "bank")
    assert len(txs) == 2
    assert txs[0].date == "2025-05-06"
    assert txs[0].credit_amount == Decimal("19400000.00")  # 借方支取 → 翻转后付
    assert txs[0].direction == "credit"
    assert txs[0].summary == "支取"
    assert txs[0].month == "2025-05"
    assert txs[1].debit_amount == Decimal("20044166.66")  # 贷方存入 → 翻转后收
    assert txs[1].direction == "debit"


def test_build_transactions_from_rows_sorts_by_date():
    # 多页并发识别按页序拼回时可能乱序，这里应按交易时间稳定排序后再做余额链纠错。
    rows = [
        {"date": "2025-05-03", "debit": 500.0, "credit": 0, "summary": "支取", "balance": "300.00"},
        {"date": "2025-05-01", "debit": 0, "credit": 1000.0, "summary": "存入", "balance": "1000.00"},
        {"date": "2025-05-02", "debit": 200.0, "credit": 0, "summary": "支取", "balance": "800.00"},
    ]
    txs = build_transactions_from_rows(rows, "bank")
    assert [t.date for t in txs] == ["2025-05-01", "2025-05-02", "2025-05-03"]
    # 排序后余额链方向纠错仍正常：第 2 笔「支取」翻转后为付(credit)
    assert txs[1].direction == "credit"
    assert txs[1].credit_amount == Decimal("200.00")


def test_correct_direction_by_balance():
    # 银行口径原始行：借方=支取、贷方=存入。第 2 笔误把「支取 200」读到贷方，
    # 翻转后成了 debit(收)，但余额在减少，余额纠错应再翻回 credit(付)。
    rows = [
        {"date": "2025-05-01", "debit": 0, "credit": 1000.0, "summary": "存入", "balance": "1000.00"},
        {"date": "2025-05-02", "debit": 0, "credit": 200.0, "summary": "支取", "balance": "800.00"},
        {"date": "2025-05-03", "debit": 500.0, "credit": 0, "summary": "支取", "balance": "300.00"},
    ]
    txs = build_transactions_from_rows(rows, "bank")
    assert len(txs) == 3
    assert txs[0].direction == "debit"  # 存入 → 翻转后收
    assert txs[0].debit_amount == Decimal("1000.00")
    assert txs[1].direction == "credit"  # 支取（误读贷方）→ 余额减少纠正为付
    assert txs[1].credit_amount == Decimal("200.00")
    assert txs[2].direction == "credit"  # 支取（借方）→ 翻转后付
    assert txs[2].credit_amount == Decimal("500.00")


def test_correct_amounts_by_balance_fixes_digit_error():
    # 第 3 笔「存入 300」金额误读成 30；上下行余额自洽，应用余额变化量更正金额。
    rows = [
        {"date": "2025-05-01", "debit": 0, "credit": 1000.0, "summary": "存入", "balance": "1000.00"},
        {"date": "2025-05-02", "debit": 200.0, "credit": 0, "summary": "支取", "balance": "800.00"},
        {"date": "2025-05-03", "debit": 0, "credit": 30.0, "summary": "存入", "balance": "1100.00"},
    ]
    txs = build_transactions_from_rows(rows, "bank")
    assert txs[2].direction == "debit"  # 存入 → 收
    assert txs[2].debit_amount == Decimal("300.00")  # 由余额变化量 1100-800 更正


def test_correct_amounts_by_balance_skips_scale_error_block():
    # 整段余额按 /1000 读错（金额正确），相邻行都不自洽，金额应保持不变。
    rows = [
        {"date": "2025-05-01", "debit": 0, "credit": 50000.0, "summary": "存入", "balance": "50.00"},
        {"date": "2025-05-02", "debit": 0, "credit": 260541.0, "summary": "存入", "balance": "310.54"},
        {"date": "2025-05-03", "debit": 100000.0, "credit": 0, "summary": "支取", "balance": "210.54"},
    ]
    txs = build_transactions_from_rows(rows, "bank")
    assert txs[0].debit_amount == Decimal("50000.00")
    assert txs[1].debit_amount == Decimal("260541.00")
    assert txs[2].credit_amount == Decimal("100000.00")


def test_correct_amounts_by_balance_skips_scale_error_last_row():
    # 末行无下一行可供复核，靠「数量级差异 >10 倍」挡住余额 /1000 错位，不误改金额。
    rows = [
        {"date": "2025-05-01", "debit": 0, "credit": 50000.0, "summary": "存入", "balance": "50.00"},
        {"date": "2025-05-02", "debit": 0, "credit": 260541.0, "summary": "存入", "balance": "310.54"},
    ]
    txs = build_transactions_from_rows(rows, "bank")
    assert txs[1].debit_amount == Decimal("260541.00")


def test_correct_amounts_by_balance_skips_single_balance_error():
    # 单笔余额读错（第 3 笔余额 1100 误读 1200），金额本身正确，不应被误改。
    rows = [
        {"date": "2025-05-01", "debit": 0, "credit": 1000.0, "summary": "存入", "balance": "1000.00"},
        {"date": "2025-05-02", "debit": 200.0, "credit": 0, "summary": "支取", "balance": "800.00"},
        {"date": "2025-05-03", "debit": 0, "credit": 300.0, "summary": "存入", "balance": "1200.00"},
        {"date": "2025-05-04", "debit": 100.0, "credit": 0, "summary": "支取", "balance": "1000.00"},
    ]
    txs = build_transactions_from_rows(rows, "bank")
    assert txs[2].debit_amount == Decimal("300.00")
    assert txs[3].credit_amount == Decimal("100.00")
