from decimal import Decimal
from typing import Callable, Dict, List, Optional

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


# 图像识别等直接产出「标准字段字典」时的字段集（与 build_transactions 取用的字段一致）。
_IMAGE_FIELDS = ["date", "debit", "credit", "counterparty", "counterparty_account",
                 "summary", "remark", "voucher_no", "detail_index", "transaction_id",
                 "balance", "currency"]


def build_transactions_from_rows(rows: List[Dict], source: str) -> List[Transaction]:
    """把图像识别等直接产出标准字段字典的 rows 转成 Transaction（跳过无日期/无金额的行）。

    图片识别按「银行口径」如实读出（借方=支取→debit、贷方=存入→credit），
    这里先硬编码翻转成账簿资产口径（借=收、贷=付），再用余额列兜底纠正个别看反列的行。
    """
    raw = RawTable(headers=_IMAGE_FIELDS, rows=rows)
    txs = build_transactions(raw, {f: f for f in _IMAGE_FIELDS}, source)
    # 多页图片并发识别后按页序拼回，这里再按交易时间稳定排序（同日保持原序），
    # 保证余额链按真实时序处理，避免页序/返回序错乱导致方向与金额纠错失效。
    # date 已是零填充 ISO（YYYY-MM-DD），字符串排序即时间排序。
    txs.sort(key=lambda t: t.date)
    _flip_bank_direction(txs)
    _correct_direction_by_balance(txs)
    _correct_amounts_by_balance(txs)
    return txs


def _flip_bank_direction(txs: List[Transaction]) -> None:
    """银行对账单口径 → 账簿资产口径的方向翻转（硬编码）。

    银行对账单「借方=支取(钱出去)、贷方=存入(钱进来)」与账簿资产口径
    （借=收、贷=付）恰好相反。方向对齐统一在这里硬编码翻转，识别环节不做方向变换，
    避免模型在提示词里做反向判断时看错列。
    """
    for t in txs:
        t.debit_amount, t.credit_amount = t.credit_amount, t.debit_amount


def _correct_direction_by_balance(txs: List[Transaction]) -> None:
    """用余额列校验并纠正借贷方向（账簿资产口径）：余额递增=收(debit)、递减=付(credit)。

    图像识别偶把「借/贷」列看反（尤其小金额行）。余额是单一数字、更可靠，
    当某行识别到的方向与余额变化方向矛盾时，直接翻转该行借贷方向。
    只在「余额变化量恰好等于本行发生额」时才翻转，避免误伤。
    """
    prev: Optional[Decimal] = None
    for t in txs:
        if t.balance is None:
            prev = None  # 余额断档，重新起算
            continue
        if prev is not None:
            delta = t.balance - prev
            if (t.debit_amount != 0 and t.credit_amount == 0
                    and delta < 0 and t.debit_amount + delta == 0):
                # 识别为收(debit)，但余额在减少 → 应为付(credit)
                t.debit_amount, t.credit_amount = t.credit_amount, t.debit_amount
            elif (t.credit_amount != 0 and t.debit_amount == 0
                  and delta > 0 and t.credit_amount == delta):
                # 识别为付(credit)，但余额在增加 → 应为收(debit)
                t.debit_amount, t.credit_amount = t.credit_amount, t.debit_amount
        prev = t.balance


def _correct_amounts_by_balance(txs: List[Transaction]) -> None:
    """用上下行余额更正识别错误的金额（数字位数读错/漏位等）。

    余额列是「交易后余额」的滚动累计，满足 balance[i] = balance[i-1] + 收 - 付。
    当某行金额与余额变化量 delta 不符时，若上一行、下一行的金额都与各自余额变化自洽
    （说明本行的上一行余额、本行余额都可信），则判定是本行金额读错，用 delta 更正金额。

    这样单笔金额读错会被纠正；而「整段余额读错（数量级整体错位）」或「单笔余额读错」
    会破坏相邻行的自洽，从而被跳过，不会误伤金额。
    """
    n = len(txs)
    consistent = [False] * n
    for i in range(n):
        if i == 0:
            consistent[i] = True  # 首行无前值，作为余额链锚点
            continue
        t, p = txs[i], txs[i - 1]
        consistent[i] = (t.balance is not None and p.balance is not None
                         and (t.debit_amount - t.credit_amount) == (t.balance - p.balance))

    for i in range(1, n):
        t, p = txs[i], txs[i - 1]
        if t.balance is None or p.balance is None or consistent[i]:
            continue
        delta = t.balance - p.balance
        if delta == 0:
            continue
        # 数量级差异过大（如整段余额按 /1000 错位）时，是余额读错而非金额读错，不更正。
        amount = t.debit_amount if t.debit_amount != 0 else t.credit_amount
        if amount == 0:
            continue
        bigger = max(amount, abs(delta))
        smaller = min(amount, abs(delta))
        if bigger > smaller * 10:
            continue
        prev_ok = consistent[i - 1]
        next_ok = (i + 1 >= n) or consistent[i + 1]
        if not (prev_ok and next_ok):
            continue
        if delta > 0:
            t.debit_amount = delta
            t.credit_amount = Decimal(0)
        else:
            t.debit_amount = Decimal(0)
            t.credit_amount = -delta
