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
        "注意借贷方向：企业账簿为资产口径，借=收(钱进来)、贷=付(钱出去)。",
        "银行对账单列名上的「借/贷」通常相反——「借方」是支取(钱出去)、「贷方」是收入(钱进来)。",
        "请按金额的实际收付含义映射：把「收入/进账」列映射到 debit，把「支取/支出」列映射到 credit。",
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


def _collect_stream_text(client, msg: Dict, model: str, max_tokens: int,
                         thinking: "dict | None" = None) -> str:
    """同步流式收集正文文本（兼容 thinking 模型），返回拼接后的 text。

    用流式而非 messages.create，是因为 max_tokens 较大时非流式会被 SDK 拒绝
    （要求流式处理可能超过 10 分钟的请求）。
    """
    kwargs = {"model": model, "max_tokens": max_tokens, "messages": [msg]}
    if thinking is not None:
        kwargs["thinking"] = thinking
    text_parts: List[str] = []
    with client.messages.stream(**kwargs) as stream:
        for event in stream:
            if getattr(event, "type", None) != "content_block_delta":
                continue
            delta = getattr(event, "delta", None)
            if getattr(delta, "type", None) == "text_delta":
                text_parts.append(getattr(delta, "text", "") or "")
    return "".join(text_parts)


def map_bank_columns(headers: List[str], samples: List[Dict], api_key: str, model: str,
                     base_url: str = "https://api.deepseek.com/anthropic",
                     max_tokens: int = 32000) -> Dict:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
    msg = {"role": "user", "content": build_prompt(headers, samples, CANONICAL_FIELDS)}
    text = _collect_stream_text(client, msg, model, max_tokens)
    if not text.strip():
        # 思考占满输出预算时，禁用思考重试一次，保证拿到结果。
        text = _collect_stream_text(client, msg, model, 4000, {"type": "disabled"})
    if not text.strip():
        raise RuntimeError("DeepSeek 未返回字段识别结果")
    return _parse_json(text)


async def stream_map_bank_columns(headers: List[str], samples: List[Dict], api_key: str,
                                  model: str, base_url: str = "https://api.deepseek.com/anthropic",
                                  max_tokens: int = 32000):
    """流式调用字段识别：逐块产出思考/正文事件，最后产出 mapping 事件。

    产出事件：{"type": "thinking", "text": ...}、{"type": "mapping", "mapping": {...}}。
    若思考占满输出预算，自动禁用思考重试一次。
    """
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)
    msg = {"role": "user", "content": build_prompt(headers, samples, CANONICAL_FIELDS)}
    text_parts: List[str] = []
    async with client.messages.stream(model=model, max_tokens=max_tokens, messages=[msg]) as stream:
        async for event in stream:
            if getattr(event, "type", None) != "content_block_delta":
                continue
            delta = getattr(event, "delta", None)
            d_type = getattr(delta, "type", None)
            if d_type == "thinking_delta":
                yield {"type": "thinking", "text": getattr(delta, "thinking", "") or ""}
            elif d_type == "text_delta":
                t = getattr(delta, "text", "") or ""
                text_parts.append(t)
    text = "".join(text_parts)
    if text.strip():
        yield {"type": "mapping", "mapping": _parse_json(text)}
        return
    # 思考占满输出预算：禁用思考直接要结果。
    yield {"type": "thinking", "text": "\n（思考过长，已切换为直接识别）\n"}
    resp = await client.messages.create(model=model, max_tokens=4000,
                                        thinking={"type": "disabled"}, messages=[msg])
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    if not text.strip():
        raise RuntimeError("DeepSeek 未返回字段识别结果")
    yield {"type": "mapping", "mapping": _parse_json(text)}
