# 数据库流水（格式确定）：标准字段 -> 数据库列名。
# 注意：样例 银行流水0603.xlsx 用的是企业总账资产口径（借=收、贷=付），
# 与银行对账单（借=付、贷=收）相反。真实导出格式确定后，按实际口径调整此映射。
DB_COLUMN_MAP = {
    "date": "PREPAREDDATEV",
    "debit": "DEBITAMOUNT",
    "credit": "CREDITAMOUNT",
    "summary": "EXPLANATION",
    "voucher_no": "NOV",
    "detail_index": "DETAILINDEX",
    "counterparty": None,
    "counterparty_account": None,
    "remark": None,
    "transaction_id": None,
    "balance": None,
    "currency": None,
}

# 样例银行对账单的固定映射（用于测试与 LLM 兜底）
BANK_COLUMN_MAP = {
    "date": "交易时间",
    "debit": "借方发生额（支取）",
    "credit": "贷方发生额（收入）",
    "counterparty": "对方户名",
    "counterparty_account": "对方账号",
    "summary": "摘要",
    "remark": "备注",
    "voucher_no": None,
    "detail_index": None,
    "transaction_id": "账户明细编号-交易流水号",
    "balance": "余额",
    "currency": "币种",
}

LLM_MODEL = "claude-sonnet-5"
MAX_MERGE_SIZE = 8
