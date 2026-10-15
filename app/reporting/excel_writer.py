from decimal import Decimal
from typing import List

import openpyxl

from ..matching.engine import MatchResult
from ..matching.monthly import MonthlyDiff


def _amt(d: Decimal) -> str:
    return format(d, ".2f")


def write_result_excel(match_result: MatchResult, monthly_diffs: List[MonthlyDiff],
                       bank_txs, db_txs, out_path: str) -> None:
    wb = openpyxl.Workbook()

    ws = wb.active
    ws.title = "逐笔明细"
    ws.append(["状态", "月份", "方向", "金额", "银行日期", "银行对方", "银行摘要",
               "数据库日期", "数据库摘要", "数据库凭证号", "数据库明细序号"])
    for p in match_result.matched:
        ws.append(["已匹配", p.bank.month, _dir(p.bank), _amt(p.bank.amount),
                   p.bank.date, p.bank.counterparty, p.bank.summary,
                   p.db.date, p.db.summary, p.db.voucher_no, p.db.detail_index])
    for g in match_result.merged:
        if g.kind == "bank_merged":
            # 银行一条 = 数据库多条：target 在银行侧，parts 在数据库侧
            ws.append(["合并记账", g.target.month, _dir(g.target), _amt(g.target.amount),
                       g.target.date, g.target.counterparty, g.target.summary,
                       "", "", "", ""])
            for part in g.parts:
                ws.append(["  └ 拆分", part.month, _dir(part), _amt(part.amount),
                           "", "", "",
                           part.date, part.summary, part.voucher_no, part.detail_index])
        else:
            # 数据库一条 = 银行多条：target 在数据库侧，parts 在银行侧
            ws.append(["合并记账", g.target.month, _dir(g.target), _amt(g.target.amount),
                       "", "", "",
                       g.target.date, g.target.summary, g.target.voucher_no, g.target.detail_index])
            for part in g.parts:
                ws.append(["  └ 拆分", part.month, _dir(part), _amt(part.amount),
                           part.date, part.counterparty, part.summary, "", "", "", ""])
    for t in match_result.unmatched_bank:
        ws.append(["仅银行有", t.month, _dir(t), _amt(t.amount), t.date, t.counterparty, t.summary,
                   "", "", "", ""])
    for t in match_result.unmatched_db:
        ws.append(["仅数据库有", t.month, _dir(t), _amt(t.amount), "", "", "",
                   t.date, t.summary, t.voucher_no, t.detail_index])

    ws2 = wb.create_sheet("月度汇总")
    ws2.append(["月份", "银行借方", "数据库借方", "借方差额", "银行贷方", "数据库贷方", "贷方差额",
                "银行期初", "数据库期初", "期初差额", "银行期末", "数据库期末", "期末差额", "是否一致"])
    for d in monthly_diffs:
        ws2.append([d.month, _amt(d.bank_debit), _amt(d.db_debit), _amt(d.debit_diff),
                    _amt(d.bank_credit), _amt(d.db_credit), _amt(d.credit_diff),
                    _amt(d.bank_opening) if d.bank_opening is not None else "",
                    _amt(d.db_opening) if d.db_opening is not None else "",
                    _amt(d.opening_diff) if d.opening_diff is not None else "",
                    _amt(d.bank_closing) if d.bank_closing is not None else "",
                    _amt(d.db_closing) if d.db_closing is not None else "",
                    _amt(d.closing_diff) if d.closing_diff is not None else "",
                    "一致" if d.consistent else "不一致"])

    wb.save(out_path)


def _dir(t) -> str:
    return "借" if t.direction == "debit" else "贷"
