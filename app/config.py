# 数据库流水（格式确定）：标准字段 -> 数据库列名。
# 口径统一为企业账簿「资产口径」：借=收(钱进来)、贷=付(钱出去)。
# NC GL_DETAIL 的 DEBITAMOUNT/CREDITAMOUNT 已是此口径，直接对应。
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

# 样例银行对账单的固定映射（用于测试与 LLM 兜底）。
# 银行对账单按「银行口径」：借=支取(钱出去)、贷=收入(钱进来)，与企业账簿相反。
# 这里已把方向对齐到账簿资产口径：debit=收(收入列)、credit=付(支取列)。
BANK_COLUMN_MAP = {
    "date": "交易时间",
    "debit": "贷方发生额（收入）",
    "credit": "借方发生额（支取）",
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

# LLM 字段识别走 DeepSeek 的 Anthropic 兼容接口（https://api.deepseek.com/anthropic）。
LLM_MODEL = "deepseek-flash"
LLM_BASE_URL = "https://api.deepseek.com/anthropic"
MAX_MERGE_SIZE = 8
