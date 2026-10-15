from app.parsing.excel_reader import RawTable, extract_account_from_table


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


def test_extract_account_empty():
    raw = RawTable(headers=["日期", "金额"], rows=[{"日期": "20260101", "金额": "12.83"}])
    got = extract_account_from_table(raw)
    assert got["account_no"] is None
    assert got["account_name"] is None
