import os
from decimal import Decimal

from app.config import DB_COLUMN_MAP, BANK_COLUMN_MAP
from app.pipeline import run_compare

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _fake_mapper(headers, samples):
    return BANK_COLUMN_MAP


def test_end_to_end_golden():
    r = run_compare(os.path.join(FIXTURES, "bank.xls"),
                    os.path.join(FIXTURES, "db.xlsx"),
                    _fake_mapper, DB_COLUMN_MAP)
    # 笔数
    assert len(r.bank_txs) == 118
    assert len(r.db_txs) == 117
    # 月度总额（样例借贷口径相反，银行借方=数据库贷方）
    d = {x.month: x for x in r.monthly_diffs}
    assert d["2026-01"].bank_debit == Decimal("725973.26")
    assert d["2026-01"].bank_credit == Decimal("800144.94")
    assert d["2026-01"].db_debit == Decimal("800144.94")
    assert d["2026-01"].db_credit == Decimal("725973.26")
    # 对称错位诊断全部触发
    assert all(x.swap_suspected for x in r.monthly_diffs)
