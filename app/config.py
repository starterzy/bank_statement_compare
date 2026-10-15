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

# 可选 LLM 模型（前端下拉 + 后端解析）。
# protocol: "anthropic" 走 Anthropic 兼容接口（anthropic SDK）；
#           "openai"    走 OpenAI 兼容接口（openai SDK，如阿里云百炼 /compatible-mode/v1）；
#           "dashscope" 走阿里云百炼原生接口（/api/v1，multimodal-generation）。
# api_key_env: 该模型 API key 在 .env / 环境变量里的键名。
LLM_MODELS = [
    {
        "id": "deepseek-flash",
        "label": "DeepSeek Flash",
        "model": "deepseek-flash",
        "base_url": "https://api.deepseek.com/anthropic",
        "protocol": "anthropic",
        "api_key_env": "LLM_API_KEY",
    },
    {
        "id": "qwen3.8-max",
        "label": "通义千问 Qwen3.8-Max",
        "model": "qwen3.8-max",
        "base_url": "https://llm-r46dokrmgm96dlfe.cn-beijing.maas.aliyuncs.com/api/v1",
        "protocol": "dashscope",
        "api_key_env": "QWEN_API_KEY",
    },
]
DEFAULT_MODEL_ID = "deepseek-flash"
MAX_MERGE_SIZE = 8


def get_model(model_id: str) -> dict:
    """按 id 取模型配置；未知 id 回退到默认模型。"""
    for m in LLM_MODELS:
        if m["id"] == model_id:
            return m
    return LLM_MODELS[0]

# 组织树与可见公司范围：只展示「浙农控股」这一集团根下的公司。
# 集团根 pk_group = GROUP_ORG；组织树的顶层公司节点是「浙农控股集团有限公司」（code 10）。
GROUP_ORG = "0001A1100000000008TT"          # 浙农控股（ZNKG）集团根
GROUP_COMPANY_ROOT = "0001A110000000001HBQ"  # 浙农控股集团有限公司（组织树根）
