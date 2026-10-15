from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional

from ..models import Transaction


def monthly_totals(txs: List[Transaction]) -> Dict[str, Dict[str, Decimal]]:
    totals: Dict[str, Dict[str, Decimal]] = {}
    for t in txs:
        m = totals.setdefault(t.month, {"debit": Decimal("0"), "credit": Decimal("0")})
        m["debit"] += t.debit_amount
        m["credit"] += t.credit_amount
    return totals


def _last_balance_by_month(txs: List[Transaction]) -> Dict[str, Decimal]:
    """取每月「最后一笔」的余额（按日期稳定排序，同日内保持原始顺序），作为该月期末余额。

    银行对账单的余额列是「交易后余额」，每月最后一行即当月期末余额；
    若余额缺失则该月不参与余额对比。
    """
    last: Dict[str, Decimal] = {}
    for t in sorted(txs, key=lambda t: t.date):
        if t.balance is not None:
            last[t.month] = t.balance
    return last


def _first_opening_by_month(txs: List[Transaction]) -> Dict[str, Optional[Decimal]]:
    """取每月「第一笔」（发生时间最早）推导该月期初余额。

    余额列是「交易后余额」，第一笔之前的余额即该月期初：
    opening = 第一笔余额 − 第一笔净额（借 − 贷）。
    首笔余额缺失则该月无法推导期初（记 None，不参与余额对比）。
    """
    first: Dict[str, Transaction] = {}
    for t in sorted(txs, key=lambda t: t.date):
        if t.month not in first:
            first[t.month] = t
    opening: Dict[str, Optional[Decimal]] = {}
    for month, t in first.items():
        opening[month] = (t.balance - (t.debit_amount - t.credit_amount)) \
            if t.balance is not None else None
    return opening


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
    single_sided: bool = False
    # 期初/期末余额对比（无余额数据时为 None，不视为不一致）
    bank_opening: Optional[Decimal] = None
    db_opening: Optional[Decimal] = None
    opening_diff: Optional[Decimal] = None
    bank_closing: Optional[Decimal] = None
    db_closing: Optional[Decimal] = None
    closing_diff: Optional[Decimal] = None

    @property
    def consistent(self) -> bool:
        return self.debit_diff == 0 and self.credit_diff == 0

    @property
    def balance_consistent(self) -> bool:
        """期初/期末是否一致；没有可对比的余额数据时视为一致（不误报）。"""
        if self.opening_diff is None or self.closing_diff is None:
            return True
        return self.opening_diff == 0 and self.closing_diff == 0

    @property
    def balance_mismatch(self) -> bool:
        return (self.opening_diff is not None and self.opening_diff != 0) or \
               (self.closing_diff is not None and self.closing_diff != 0)


def compare_monthly(bank_txs: List[Transaction], db_txs: List[Transaction],
                    db_monthly_balances: Optional[Dict[str, Dict[str, Decimal]]] = None) -> List[MonthlyDiff]:
    """逐月对比发生额（借/贷合计）与期初/期末余额。

    - 银行侧期初/期末：期末 = 余额列该月最后一笔（发生时间最晚），
      期初 = 第一笔（发生时间最早）余额 − 第一笔净额（借-贷）。
    - DB 侧期初/期末：优先用调用方传入的权威月余额表 db_monthly_balances
      （{month: {"opening": ..., "closing": ...}}，来自 Oracle 期初链），
      否则退回用 db_txs 的余额列推导（文件数据源若带余额列也可用）。
    余额是绝对金额，借贷方向相反不影响余额口径，可直接对比。
    """
    bank = monthly_totals(bank_txs)
    db = monthly_totals(db_txs)
    bank_closing = _last_balance_by_month(bank_txs)
    bank_opening = _first_opening_by_month(bank_txs)
    db_closing = _last_balance_by_month(db_txs)
    zero = {"debit": Decimal("0"), "credit": Decimal("0")}
    auth = db_monthly_balances or {}
    diffs = []
    for month in sorted(set(bank) | set(db)):
        b = bank.get(month, zero)
        d = db.get(month, zero)
        net_d = d["debit"] - d["credit"]

        b_close = bank_closing.get(month)
        b_open = bank_opening.get(month)

        am = auth.get(month)
        if am is not None:
            d_open = am.get("opening")
            d_close = am.get("closing")
        else:
            d_close = db_closing.get(month)
            d_open = (d_close - net_d) if d_close is not None else None

        opening_diff = (b_open - d_open) if (b_open is not None and d_open is not None) else None
        closing_diff = (b_close - d_close) if (b_close is not None and d_close is not None) else None

        diff = MonthlyDiff(
            month=month,
            bank_debit=b["debit"], db_debit=d["debit"], debit_diff=b["debit"] - d["debit"],
            bank_credit=b["credit"], db_credit=d["credit"], credit_diff=b["credit"] - d["credit"],
            single_sided=(month not in bank) or (month not in db),
            bank_opening=b_open, db_opening=d_open, opening_diff=opening_diff,
            bank_closing=b_close, db_closing=d_close, closing_diff=closing_diff,
        )
        # 对称错位诊断：银行借方≈数据库贷方 且 银行贷方≈数据库借方
        diff.swap_suspected = (b["debit"] == d["credit"] and b["credit"] == d["debit"]
                               and (b["debit"] != d["debit"] or b["credit"] != d["credit"]))
        diffs.append(diff)
    return diffs
