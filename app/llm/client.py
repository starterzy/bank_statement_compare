import json
from typing import Dict, List

CANONICAL_FIELDS = [
    "date", "debit", "credit", "counterparty", "counterparty_account",
    "summary", "remark", "voucher_no", "detail_index", "transaction_id",
    "balance", "currency",
]


def build_prompt(headers: List[str], samples: List[Dict], fields: List[str]) -> str:
    lines = [
        "你是财务对账系统的字段识别助手。",
        "请判断银行对账单各列与标准字段的对应关系，只输出一个 JSON 对象。",
        "标准字段：" + "、".join(fields),
        "银行对账单表头：" + json.dumps(headers, ensure_ascii=False),
        "样例行：" + json.dumps(samples[:5], ensure_ascii=False, default=str),
        "",
        "JSON 的键为标准字段名，值为对应的银行列名（找不到则为 null）。",
        "借贷按财务含义识别：哪列是「借方金额」、哪列是「贷方金额」。",
    ]
    return "\n".join(lines)


def _parse_json(text: str) -> Dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"预期 JSON 对象，实际得到 {type(data).__name__}")
    return data


def claude_map_bank_columns(headers: List[str], samples: List[Dict], api_key: str, model: str) -> Dict:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=1500,
        messages=[{"role": "user", "content": build_prompt(headers, samples, CANONICAL_FIELDS)}],
    )
    return _parse_json(resp.content[0].text)
