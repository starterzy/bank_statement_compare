import os
from app.parsing.excel_reader import read_excel, sample_rows

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def test_read_bank_xls():
    raw = read_excel(os.path.join(FIXTURES, "bank.xls"))
    assert "客户账号" in raw.headers
    assert "对方户名" in raw.headers
    assert len(raw.rows) >= 118


def test_read_db_xlsx():
    raw = read_excel(os.path.join(FIXTURES, "db.xlsx"))
    assert "PK_ACCOUNTINGBOOK" in raw.headers
    assert "EXPLANATION" in raw.headers
    assert len(raw.rows) >= 117


def test_sample_rows():
    raw = read_excel(os.path.join(FIXTURES, "db.xlsx"))
    samples = sample_rows(raw, 3)
    assert len(samples) == 3
    assert "EXPLANATION" in samples[0]
