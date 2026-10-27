"""模型分析结果 → 流水：任意表结构都由模型给出表头行、列号与方向口径。"""
from decimal import Decimal

from app.llm.client import build_analyze_prompt
from app.parsing.statement import StatementAnalysis, build_from_analysis

# 中行导出：前置信息 + 双语表头 + 单列带符号金额
BANK_CSV = [
    ["查询账号[ Inquirer account number ]", "376674731895"],
    ["总笔数[ Total number ]", "2"],
    ["交易类型[ Transaction Type ]", "付款人账号[ Debit Account No. ]",
     "收款人账号[ Payee's Account Number ]", "交易日期[ Transaction Date ]",
     "交易金额[ Trade Amount ]", "交易后余额[ After-transaction balance ]"],
    ["来账", "4900004008", "376674731895", "20250102", "10,457.04", "2,855,707.29"],
    ["往账", "376674731895", "07549", "20250113", "-11", "2,874,351.90"],
]

SIGNED_ANALYSIS = {
    "header_row": 3,
    "columns": {"date": 4, "amount": 5, "balance": 6,
                "counterparty": None, "counterparty_account": None, "summary": 1},
    "amount_style": "signed",
    "amount_sign": {"positive": "in", "negative": "out"},
    "direction_column": 1,
    "direction_values": {"来账": "in", "往账": "out"},
    "own_account": {"account_no": "376674731895", "account_name": "衢州新华都置业有限公司",
                    "evidence": "第1行：查询账号 = 376674731895"},
}


def test_build_signed_amount_uses_sign_for_direction():
    txs = build_from_analysis(BANK_CSV, StatementAnalysis.from_dict(SIGNED_ANALYSIS))

    assert len(txs) == 2
    assert txs[0].date == "2025-01-02"
    assert txs[0].debit_amount == Decimal("10457.04")   # 来账 → 收（借）
    assert txs[0].credit_amount == Decimal("0")
    assert txs[0].balance == Decimal("2855707.29")
    assert txs[1].credit_amount == Decimal("11.00")     # 往账 → 付（贷）
    assert txs[1].debit_amount == Decimal("0")


def test_build_uses_direction_column_over_sign():
    analysis = StatementAnalysis.from_dict({
        **SIGNED_ANALYSIS,
        "amount_style": "signed",
        # 金额恒为正、方向全靠「交易类型」列
        "direction_values": {"来账": "in", "往账": "out"},
    })
    grid = [BANK_CSV[0], BANK_CSV[1], BANK_CSV[2],
            ["来账", "a", "b", "20250102", "100", "1000"],
            ["往账", "a", "b", "20250103", "200", "800"]]

    txs = build_from_analysis(grid, analysis)

    assert [t.debit_amount for t in txs] == [Decimal("100.00"), Decimal("0")]
    assert [t.credit_amount for t in txs] == [Decimal("0"), Decimal("200.00")]


def test_build_income_expense_columns():
    grid = [
        ["账户明细"],
        ["交易时间", "收入金额", "支出金额", "账户余额"],
        ["2026-01-08 15:51:12", "", "4161.47", "1646092.92"],
        ["2026-01-09 10:00:00", "500.00", "", "1646592.92"],
    ]
    analysis = StatementAnalysis.from_dict({
        "header_row": 2,
        "columns": {"date": 1, "debit": 2, "credit": 3, "balance": 4},
        "amount_style": "income_expense",
        "own_account": {"account_no": None, "account_name": None, "evidence": "表中无账号"},
    })

    txs = build_from_analysis(grid, analysis)

    assert txs[0].credit_amount == Decimal("4161.47")   # 支出 → 付（贷）
    assert txs[1].debit_amount == Decimal("500.00")     # 收入 → 收（借）


def test_build_skips_rows_without_date_or_amount():
    grid = [["日期", "金额"], ["合计", "100"], ["20250102", "0"]]
    analysis = StatementAnalysis.from_dict({
        "header_row": 1, "columns": {"date": 1, "amount": 2},
        "amount_style": "signed", "own_account": {},
    })
    assert build_from_analysis(grid, analysis) == []


def test_analysis_from_dict_is_lenient():
    a = StatementAnalysis.from_dict({"header_row": 8})
    assert a.header_row == 8 and a.columns == {} and a.account_no is None
    assert a.amount_style == "debit_credit"


def test_analyze_prompt_mentions_own_account_anywhere_and_evidence():
    prompt = build_analyze_prompt(BANK_CSV, ncols=6)

    assert "本方账号" in prompt and "evidence" in prompt
    assert "任何位置" in prompt
    assert "header_row" in prompt and "amount_style" in prompt
    assert "376674731895" in prompt          # 原始单元格原样喂给模型
