from typing import Callable, Dict, List

from ..models import Transaction, clean_str, parse_date, to_decimal, to_int
from .excel_reader import RawTable, sample_rows


def build_transactions(raw: RawTable, column_map: Dict[str, str], source: str) -> List[Transaction]:
    txs = []
    for row in raw.rows:
        def get(field):
            col = column_map.get(field)
            return row.get(col) if col else None

        d = parse_date(get("date"))
        if d is None:
            continue
        debit = to_decimal(get("debit"))
        credit = to_decimal(get("credit"))
        if debit == 0 and credit == 0:
            continue
        balance = get("balance")
        txs.append(Transaction(
            source=source,
            date=d.isoformat(),
            month=d.strftime("%Y-%m"),
            debit_amount=debit,
            credit_amount=credit,
            counterparty=clean_str(get("counterparty")),
            counterparty_account=clean_str(get("counterparty_account")),
            summary=clean_str(get("summary")),
            remark=clean_str(get("remark")),
            voucher_no=clean_str(get("voucher_no")),
            detail_index=to_int(get("detail_index")),
            transaction_id=clean_str(get("transaction_id")),
            balance=to_decimal(balance) if balance is not None else None,
            currency=clean_str(get("currency")),
            raw=row,
        ))
    return txs


def map_bank_via_llm(raw: RawTable, llm_fn: Callable[[List[str], List[Dict]], Dict[str, str]]) -> List[Transaction]:
    column_map = llm_fn(raw.headers, sample_rows(raw))
    return build_transactions(raw, column_map, "bank")
