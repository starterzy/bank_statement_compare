import pandas as pd

from app.parsing.excel_reader import (RawTable, _detect_header_row,
                                      extract_account_from_table, read_excel)

NAN = float("nan")


# ---------- 表头行识别 ----------

def test_detect_header_skips_title_row():
    data = [
        ["账户明细查询列表2026", NAN, NAN, NAN],
        ["交易时间", "收入金额", "支出金额", "账户余额"],
        ["2026-01-08 15:51:12", NAN, 4161.47, 1646092.92],
        ["2026-01-08 15:51:13", NAN, 4007.5, 1641931.45],
    ]
    assert _detect_header_row(data) == 1


def test_detect_header_skips_account_info_row():
    """标题行 + 账户信息行（第 2 行）+ 真表头：不能把账户信息行当表头。"""
    data = [
        ["账户明细查询列表", NAN, NAN, NAN],
        ["账户名称：安吉华都", "账号：33001647135053010603",
         "查询期间：2026-01-01 至 2026-12-31", NAN],
        ["交易时间", "收入金额", "支出金额", "账户余额"],
        ["2026-01-08 15:51:12", NAN, 4161.47, 1646092.92],
        ["2026-01-08 15:51:13", NAN, 4007.5, 1641931.45],
    ]
    assert _detect_header_row(data) == 2


def test_detect_header_without_title():
    data = [
        ["交易时间", "收入金额", "支出金额"],
        ["2026-01-08 15:51:12", NAN, 4161.47],
        ["2026-01-08 15:51:13", NAN, 4007.5],
    ]
    assert _detect_header_row(data) == 0


def test_detect_header_none_and_nan_consistent():
    """空单元格是 None 还是 NaN，结果必须一致。"""
    rows_nan = [
        ["账户明细", NAN, NAN],
        ["交易时间", "支出金额", "账户余额"],
        ["2026-01-08 15:51:12", 4161.47, 1646092.92],
    ]
    rows_none = [
        ["账户明细", None, None],
        ["交易时间", "支出金额", "账户余额"],
        ["2026-01-08 15:51:12", 4161.47, 1646092.92],
    ]
    assert _detect_header_row(rows_nan) == _detect_header_row(rows_none) == 1


def test_read_excel_keeps_preamble_and_finds_header(tmp_path):
    df = pd.DataFrame([
        ["账户明细", None, None],
        ["账户名称：安吉华都", "账号：33001647135053010603", None],
        ["交易时间", "支出金额", "账户余额"],
        ["2026-01-08 15:51:12", 4161.47, 1646092.92],
        ["2026-01-08 15:51:13", 4007.5, 1641931.45],
    ])
    p = tmp_path / "bank.xlsx"
    df.to_excel(p, header=False, index=False)

    raw = read_excel(str(p))

    assert raw.headers == ["交易时间", "支出金额", "账户余额"]
    assert len(raw.rows) == 2
    # 表头之前的标题/账户信息行保留下来，供账号抽取使用
    assert extract_account_from_table(raw) == {
        "account_no": "33001647135053010603",
        "account_name": "安吉华都",
    }


# ---------- 本方账号抽取 ----------

def test_extract_account_from_account_column():
    raw = RawTable(
        headers=["客户账号", "账户名称", "交易时间", "余额"],
        rows=[
            {"客户账号": "33001647135053010603", "账户名称": "安吉华都房地产开发有限公司",
             "交易时间": "20260101 17:05:53", "余额": "75065.93"},
            {"客户账号": "33001647135053010603", "账户名称": "安吉华都房地产开发有限公司",
             "交易时间": "20260101 17:05:53", "余额": "75059.79"},
        ],
    )
    got = extract_account_from_table(raw)
    assert got["account_no"] == "33001647135053010603"
    assert got["account_name"] == "安吉华都房地产开发有限公司"


def test_extract_account_ignores_counterparty_column():
    raw = RawTable(
        headers=["对方账号", "客户账号"],
        rows=[{"对方账号": "6222021200001234567", "客户账号": "33001647135053010603"}],
    )
    got = extract_account_from_table(raw)
    assert got["account_no"] == "33001647135053010603"


def test_extract_account_fallback_most_frequent():
    raw = RawTable(
        headers=["A", "B"],
        rows=[{"A": "账号 33001647135053010603", "B": "x"},
              {"A": "账号 33001647135053010603", "B": "y"}],
    )
    got = extract_account_from_table(raw)
    assert got["account_no"] == "33001647135053010603"


def test_extract_account_fallback_ignores_counterparty_only_file():
    """只有「对方账号」列时，不能把对方账号当成本方账号。"""
    raw = RawTable(
        headers=["交易时间", "支出金额", "对方账号", "对方户名", "摘要"],
        rows=[
            {"交易时间": "2026-01-08 15:51:12", "支出金额": 4161.47,
             "对方账号": "19999901010002402", "对方户名": "某银行", "摘要": "转取"},
            {"交易时间": "2026-01-08 15:51:13", "支出金额": 4007.5,
             "对方账号": "19999901010002402", "对方户名": "某银行", "摘要": "转取"},
            {"交易时间": "2026-01-08 15:51:14", "支出金额": 7250,
             "对方账号": "6228481078487255072", "对方户名": "张三", "摘要": "转取"},
        ],
    )
    got = extract_account_from_table(raw)
    assert got["account_no"] is None


def test_extract_account_fallback_requires_dominant_value():
    """无表头标注时，只有每行都相同的账号才视为本方账号。"""
    raw = RawTable(
        headers=["A"],
        rows=[{"A": "6222021200001234567"},
              {"A": "6228481078487255072"},
              {"A": "6214855700340025"}],
    )
    got = extract_account_from_table(raw)
    assert got["account_no"] is None


def test_extract_account_empty():
    raw = RawTable(headers=["日期", "金额"], rows=[{"日期": "20260101", "金额": "12.83"}])
    got = extract_account_from_table(raw)
    assert got["account_no"] is None
    assert got["account_name"] is None
