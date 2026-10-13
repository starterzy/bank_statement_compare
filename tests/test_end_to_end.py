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
    # 月度总额（银行对账单方向已对齐到账簿口径：借=收、贷=付）
    d = {x.month: x for x in r.monthly_diffs}
    assert d["2026-01"].bank_debit == Decimal("800144.94")
    assert d["2026-01"].bank_credit == Decimal("725973.26")
    assert d["2026-01"].db_debit == Decimal("800144.94")
    assert d["2026-01"].db_credit == Decimal("725973.26")
    # 方向对齐后各月一致，无对称错位
    assert all(x.consistent for x in r.monthly_diffs)
    assert not any(x.swap_suspected for x in r.monthly_diffs)
