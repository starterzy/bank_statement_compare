import os
from decimal import Decimal

from app.config import DB_COLUMN_MAP, BANK_COLUMN_MAP
from app.pipeline import run_compare

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _fake_mapper(headers, samples):
    return BANK_COLUMN_MAP


def test_run_compare_on_fixtures():
    bank_path = os.path.join(FIXTURES, "bank.xls")
    db_path = os.path.join(FIXTURES, "db.xlsx")
    r = run_compare(bank_path, db_path, _fake_mapper, DB_COLUMN_MAP)
    assert len(r.bank_txs) == 118
    assert len(r.db_txs) == 117
    # 8 个月都在
    assert len(r.monthly_diffs) == 8
    # 方向对齐后各月一致，无对称错位
    assert all(d.consistent for d in r.monthly_diffs)
    assert not any(d.swap_suspected for d in r.monthly_diffs)
    assert r.summary["status"] == "merged"
