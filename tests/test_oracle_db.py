from decimal import Decimal

from app.db.oracle import _code_matches, get_db_config, load_env, map_db_rows


def test_load_env_handles_special_chars(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "ORACLE_PASSWORD=Zp7#nR5+?uC2$sDm\n"
        "ORACLE_PORT=1521\n"
        "# 注释行\n"
        "ORACLE_USER='nccread_zy'\n",
        encoding="utf-8",
    )
    d = load_env(str(p))
    assert d["ORACLE_PASSWORD"] == "Zp7#nR5+?uC2$sDm"  # '#'、'$' 原样保留
    assert d["ORACLE_PORT"] == "1521"
    assert d["ORACLE_USER"] == "nccread_zy"  # 引号被剥掉
    assert "# 注释行" not in d


def test_load_env_missing_file(tmp_path):
    assert load_env(str(tmp_path / "nope.env")) == {}


def test_get_db_config_defaults():
    cfg = get_db_config()
    # 新口径：账簿 + 科目定位「银行存款」，DB_ORG 用于列出账户；账户(F11)由前端动态选择
    assert cfg["DB_ACCOUNTING_BOOK"] == "1001A11000000000F1XL"
    assert cfg["DB_PK_ACCASOA"] == "1001A11000000000ENQP"
    assert cfg["DB_ORG"] == "0001A110000000001I2D"
    assert cfg["DB_YEAR"] == "2026"
    assert cfg["DB_PERIOD_FROM"] == "01"
    assert cfg["DB_PERIOD_TO"] == "12"
    assert "DB_ACCOUNT_CODE" not in cfg
    assert "DB_DOCFREE_F11" not in cfg


def test_code_matches_exact():
    assert _code_matches("720101040019411", "720101040019411")
    assert _code_matches("720101040019411", "7201 0104 0019 411")  # NC 里带空格/横线也算同一个


def test_code_matches_statement_region_prefix():
    """对账单印「19-720101040019411」，NC 只存后 15 位 720101040019411。"""
    assert _code_matches("19720101040019411", "720101040019411")
    assert _code_matches("720101040019411", "19-720101040019411")


def test_code_matches_rejects_short_or_other():
    assert not _code_matches("411", "720101040019411")            # 太短，容易误伤
    assert not _code_matches("", "720101040019411")
    assert not _code_matches("6228481079410825775", "720101040019411")  # 对方账号
    assert not _code_matches("7201010400194110", "720101040019411")     # 多一位不算


def test_map_db_rows_builds_transactions():
    rows = [
        {"PREPAREDDATEV": "2026-01-13 10:01:55", "DEBITAMOUNT": 0, "CREDITAMOUNT": 598092.61,
         "EXPLANATION": "缴12月税费", "NOV": 38, "DETAILINDEX": 14},
        {"PREPAREDDATEV": "2026-01-08 08:52:36", "DEBITAMOUNT": 109.25, "CREDITAMOUNT": 0,
         "EXPLANATION": "付物业管理费", "NOV": 28, "DETAILINDEX": 2},
    ]
    txs = map_db_rows(rows)
    assert len(txs) == 2
    assert txs[0].month == "2026-01"
    assert txs[0].credit_amount == Decimal("598092.61")
    assert txs[0].direction == "credit"
    assert txs[0].voucher_no == "38"
    assert txs[1].debit_amount == Decimal("109.25")
    assert txs[1].direction == "debit"
    assert txs[1].detail_index == 2


def test_map_db_rows_skips_zero_and_bad_date():
    rows = [
        {"PREPAREDDATEV": "~", "DEBITAMOUNT": 100, "CREDITAMOUNT": 0,
         "EXPLANATION": "x", "NOV": 1, "DETAILINDEX": 1},
        {"PREPAREDDATEV": "2026-01-01 00:00:00", "DEBITAMOUNT": 0, "CREDITAMOUNT": 0,
         "EXPLANATION": "零金额", "NOV": 2, "DETAILINDEX": 2},
    ]
    assert map_db_rows(rows) == []
