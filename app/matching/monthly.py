from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List

from ..models import Transaction


def monthly_totals(txs: List[Transaction]) -> Dict[str, Dict[str, Decimal]]:
    totals: Dict[str, Dict[str, Decimal]] = {}
    for t in txs:
        m = totals.setdefault(t.month, {"debit": Decimal("0"), "credit": Decimal("0")})
        m["debit"] += t.debit_amount
        m["credit"] += t.credit_amount
    return totals


@dataclass
class MonthlyDiff:
    month: str
    bank_debit: Decimal
    db_debit: Decimal
    debit_diff: Decimal
    bank_credit: Decimal
    db_credit: Decimal
    credit_diff: Decimal
    swap_suspected: bool = False

    @property
    def consistent(self) -> bool:
        return self.debit_diff == 0 and self.credit_diff == 0


def compare_monthly(bank_txs: List[Transaction], db_txs: List[Transaction]) -> List[MonthlyDiff]:
    bank = monthly_totals(bank_txs)
    db = monthly_totals(db_txs)
    zero = {"debit": Decimal("0"), "credit": Decimal("0")}
    diffs = []
    for month in sorted(set(bank) | set(db)):
        b = bank.get(month, zero)
        d = db.get(month, zero)
        diff = MonthlyDiff(
            month=month,
            bank_debit=b["debit"], db_debit=d["debit"], debit_diff=b["debit"] - d["debit"],
            bank_credit=b["credit"], db_credit=d["credit"], credit_diff=b["credit"] - d["credit"],
        )
        # 对称错位诊断：银行借方≈数据库贷方 且 银行贷方≈数据库借方
        diff.swap_suspected = (b["debit"] == d["credit"] and b["credit"] == d["debit"]
                               and (b["debit"] != d["debit"] or b["credit"] != d["credit"]))
        diffs.append(diff)
    return diffs
