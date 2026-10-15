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
        "方向口径（必须遵守）：银行对账单与 NC 账簿的借贷方向「相反」。",
        "本系统输出统一用「账簿资产口径」：debit=借=收(钱进来)、credit=贷=付(钱出去)。",
        "因此对账单方向要反向对齐：对账单「借方」=支取(钱出去)→credit；对账单「贷方」=存入(钱进来)→debit。",
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


def map_bank_columns_openai(headers: List[str], samples: List[Dict], api_key: str, model: str,
                            base_url: str, max_tokens: int = 32000) -> Dict:
    """OpenAI 兼容接口的字段识别（如阿里云百炼 /compatible-mode/v1）。"""
    import openai

    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": build_prompt(headers, samples, CANONICAL_FIELDS)}],
    )
    text = (resp.choices[0].message.content or "").strip() if resp.choices else ""
    if not text:
        raise RuntimeError("模型未返回字段识别结果")
    return _parse_json(text)


async def stream_map_bank_columns_openai(headers: List[str], samples: List[Dict], api_key: str,
                                         model: str, base_url: str, max_tokens: int = 32000):
    """OpenAI 兼容接口的字段识别（流式），产出 {"type": "mapping", "mapping": {...}} 事件。"""
    import openai

    client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
    text_parts: List[str] = []
    stream = await client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        stream=True,
        messages=[{"role": "user", "content": build_prompt(headers, samples, CANONICAL_FIELDS)}],
    )
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
            text_parts.append(chunk.choices[0].delta.content)
    text = "".join(text_parts).strip()
    if not text:
        raise RuntimeError("模型未返回字段识别结果")
    yield {"type": "mapping", "mapping": _parse_json(text)}


def _dashscope_call(base_url: str, api_key: str, model: str, messages: List[Dict], max_tokens: int) -> str:
    """阿里云百炼原生 multimodal-generation 接口（阻塞），返回拼接后的正文文本。

    messages 的 content 可为字符串（纯文本）或 [{"image": dataURI}, {"text": ...}]（图文）。
    响应 output.choices[0].message.content 为字符串或 [{"text": ...}] 列表。
    """
    import urllib.request

    url = base_url.rstrip("/") + "/services/aigc/multimodal-generation/generation"
    payload = {
        "model": model,
        "input": {"messages": messages},
        "parameters": {"result_format": "message", "max_tokens": max_tokens},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    choices = (data.get("output") or {}).get("choices") or []
    content = choices[0].get("message", {}).get("content") if choices else ""
    if isinstance(content, str):
        return content
    parts = []
    for p in content or []:
        if isinstance(p, dict):
            parts.append(p.get("text", "") or "")
        elif isinstance(p, str):
            parts.append(p)
    return "".join(parts)


def map_bank_columns_dashscope(headers: List[str], samples: List[Dict], api_key: str, model: str,
                               base_url: str, max_tokens: int = 32000) -> Dict:
    """阿里云百炼原生接口的字段识别。"""
    text = _dashscope_call(base_url, api_key, model,
                           [{"role": "user", "content": build_prompt(headers, samples, CANONICAL_FIELDS)}],
                           max_tokens)
    if not text.strip():
        raise RuntimeError("模型未返回字段识别结果")
    return _parse_json(text)


async def stream_map_bank_columns_dashscope(headers: List[str], samples: List[Dict], api_key: str,
                                            model: str, base_url: str, max_tokens: int = 32000):
    """阿里云百炼原生接口的字段识别（产出 {"type": "mapping", "mapping": {...}} 事件）。"""
    import asyncio

    text = await asyncio.to_thread(_dashscope_call, base_url, api_key, model,
                                   [{"role": "user", "content": build_prompt(headers, samples, CANONICAL_FIELDS)}],
                                   max_tokens)
    if not text.strip():
        raise RuntimeError("模型未返回字段识别结果")
    yield {"type": "mapping", "mapping": _parse_json(text)}


def build_image_prompt() -> str:
    """银行对账单截图 → 流水行数组的提示词。

    只要求如实读出「借方列→debit、贷方列→credit」，不做任何方向变换；
    与账簿口径相反的方向对齐统一在 column_mapper 里硬编码翻转，避免模型自行判断方向。
    """
    return "\n".join([
        "你是财务对账系统的银行对账单识别助手。",
        "这是一张银行对账单的截图/照片，请逐行识别其中的每一条交易流水，只输出一个 JSON 数组，不要输出任何解释。",
        "每一项是一个对象，字段如下：",
        '  date: 交易日期（字符串，YYYY-MM-DD）',
        '  debit: 借方发生额（支取/支出）金额（数字，无则 0）',
        '  credit: 贷方发生额（存入/收入）金额（数字，无则 0）',
        '  counterparty: 对方户名（字符串，无则 null）',
        '  summary: 摘要/用途（字符串，无则 null）',
        '  remark: 备注（字符串，无则 null）',
        '  balance: 交易后余额（字符串，无则 null）',
        "金额识别要点（非常重要）：",
        "  对账单里的金额可能含千分位逗号，例如 19,400,000.00。",
        "  请去掉千分位逗号、保留全部数字位与两位小数，输出完整数值 19400000.00。",
        "  不要遗漏任何数位、不要改变数量级、不要省略末尾的零。",
        "  余额 balance 一律输出为带双引号的字符串（如 \"19400000.00\"）。",
        "方向口径（必须遵守）：按对账单原文如实输出，不要做任何方向变换或推断。",
        "  发生额落在「借方」列就填 debit，落在「贷方」列就填 credit，两列都要识别。",
        "  严禁用摘要判断方向，摘要/备注/对方户名只照抄原文。",
        "  余额列必须逐字精确抄录（去掉千分位逗号），不要自行推算或补算余额，只照原样读出每一行的余额数字。"
    ])


def _parse_json_array(text: str) -> List[Dict]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        text = text[start:end + 1]
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError(f"预期 JSON 数组，实际得到 {type(data).__name__}")
    return data


async def stream_map_bank_image(image_bytes: bytes, media_type: str, api_key: str, model: str,
                                base_url: str = "https://api.deepseek.com/anthropic",
                                max_tokens: int = 32000):
    """图像识别银行对账单截图：直接产出流水行数组。

    禁用思考（图像识别只需结构化结果，思考会极慢且占满输出预算）。
    产出事件：{"type": "image_rows", "rows": [...]}。
    """
    import anthropic
    import base64

    client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)
    msg = {"role": "user", "content": [
        {"type": "image",
         "source": {"type": "base64", "media_type": media_type,
                    "data": base64.b64encode(image_bytes).decode()}},
        {"type": "text", "text": build_image_prompt()},
    ]}
    text_parts: List[str] = []
    async with client.messages.stream(model=model, max_tokens=max_tokens,
                                      thinking={"type": "disabled"}, messages=[msg]) as stream:
        async for event in stream:
            if getattr(event, "type", None) != "content_block_delta":
                continue
            delta = getattr(event, "delta", None)
            if getattr(delta, "type", None) == "text_delta":
                text_parts.append(getattr(delta, "text", "") or "")
    text = "".join(text_parts)
    if not text.strip():
        raise RuntimeError("DeepSeek 未返回图片识别结果")
    yield {"type": "image_rows", "rows": _parse_json_array(text)}


async def stream_map_bank_image_openai(image_bytes: bytes, media_type: str, api_key: str, model: str,
                                       base_url: str, max_tokens: int = 32000):
    """OpenAI 兼容接口的图像识别银行对账单截图：产出 {"type": "image_rows", "rows": [...]} 事件。"""
    import base64

    import openai

    client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
    data_uri = f"data:{media_type};base64," + base64.b64encode(image_bytes).decode()
    text_parts: List[str] = []
    stream = await client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        stream=True,
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_uri}},
            {"type": "text", "text": build_image_prompt()},
        ]}],
    )
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
            text_parts.append(chunk.choices[0].delta.content)
    text = "".join(text_parts).strip()
    if not text:
        raise RuntimeError("模型未返回图片识别结果")
    yield {"type": "image_rows", "rows": _parse_json_array(text)}


async def stream_map_bank_image_dashscope(image_bytes: bytes, media_type: str, api_key: str, model: str,
                                          base_url: str, max_tokens: int = 32000):
    """阿里云百炼原生接口的图像识别银行对账单截图：产出 {"type": "image_rows", "rows": [...]} 事件。"""
    import asyncio
    import base64

    data_uri = f"data:{media_type};base64," + base64.b64encode(image_bytes).decode()
    text = await asyncio.to_thread(_dashscope_call, base_url, api_key, model,
                                   [{"role": "user", "content": [{"image": data_uri},
                                                                 {"text": build_image_prompt()}]}],
                                   max_tokens)
    if not text.strip():
        raise RuntimeError("模型未返回图片识别结果")
    yield {"type": "image_rows", "rows": _parse_json_array(text)}


async def _recognize_one_image(fn, image_bytes, media_type, api_key, model, base_url, max_tokens):
    rows = None
    async for ev in fn(image_bytes, media_type, api_key, model, base_url, max_tokens):
        if ev["type"] == "image_rows":
            rows = ev["rows"]
    return rows


async def stream_map_bank_images(images, api_key, model,
                                 base_url="https://api.deepseek.com/anthropic",
                                 max_tokens=32000, image_stream_fn=None):
    """识别多张银行对账单截图（同一对账单分页），并发识别各页后按页顺序拼接流水行。

    images: [(bytes, media_type), ...]，按页顺序传入。
    image_stream_fn: 单张图片的识别流函数（默认 Anthropic 接口，可传 OpenAI / 百炼原生版）。
    各页互不依赖，并发请求以缩短总耗时；每页识别完成即实时推送进度，结果仍按页顺序
    拼接，保证余额链顺序不变。
    产出事件：{"type": "stage", "text": ...}、{"type": "image_rows", "rows": 全部行}。
    最后把各行拼成一份完整流水，交给 build_transactions_from_rows 统一做余额方向校验。
    """
    import asyncio

    fn = image_stream_fn or stream_map_bank_image
    total = len(images)

    async def _recognize(idx: int, b, mt):
        rows = await _recognize_one_image(fn, b, mt, api_key, model, base_url, max_tokens)
        return idx, rows

    tasks = [asyncio.create_task(_recognize(i, b, mt)) for i, (b, mt) in enumerate(images)]
    per_page: List = [None] * total
    done = 0
    for fut in asyncio.as_completed(tasks):
        idx, rows = await fut
        done += 1
        if rows is None:
            raise RuntimeError(f"第 {idx + 1} 张图片识别失败")
        per_page[idx] = rows
        yield {"type": "stage", "text": f"图片识别进度 {done}/{total} 张（第 {idx + 1} 张完成）"}

    all_rows: List[Dict] = []
    for rows in per_page:
        all_rows.extend(rows)
    yield {"type": "image_rows", "rows": all_rows}


ORIENTATION_PROMPT = (
    "这是一张银行对账单的扫描图片，方向可能不对。"
    "请判断：要让文字水平正读，需要把图片顺时针旋转多少度？"
    "只输出一个数字：0、90、180 或 270，不要输出任何其他内容。"
)


def _parse_angle(text: str) -> int:
    """从方向判断的输出里提取 0/90/180/270，取不到则 0（不旋转）。"""
    import re

    # 用数字边界而非 \b：中文在 Unicode 里是 \w，\b 会把「转180度」的数字相邻处判成无边界。
    m = re.search(r"(?<!\d)(0|90|180|270)(?!\d)", text or "")
    return int(m.group(1)) if m else 0


def rotate_image(image_bytes: bytes, angle_cw: int) -> bytes:
    """把图片顺时针旋转 angle_cw 度（0/90/180/270），白底填充，返回 PNG 字节。"""
    import io

    from PIL import Image

    if angle_cw not in (90, 180, 270):
        return image_bytes
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    # PIL 的 rotate 是逆时针，顺时针 angle_cw 等价于逆时针 -angle_cw。
    out = img.rotate(-angle_cw, expand=True, resample=Image.BICUBIC, fillcolor=(255, 255, 255))
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


async def detect_orientation(image_bytes: bytes, media_type: str, api_key: str, model: str,
                             base_url: str, max_tokens: int = 100) -> int:
    """用 flash（Anthropic 兼容接口）判断单张图需顺时针旋转的角度，返回 0/90/180/270。

    方向判断是极简单任务：小 max_tokens、禁用思考，尽量快。
    """
    import base64

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)
    msg = {"role": "user", "content": [
        {"type": "image",
         "source": {"type": "base64", "media_type": media_type,
                    "data": base64.b64encode(image_bytes).decode()}},
        {"type": "text", "text": ORIENTATION_PROMPT},
    ]}
    text_parts: List[str] = []
    async with client.messages.stream(model=model, max_tokens=max_tokens,
                                      thinking={"type": "disabled"}, messages=[msg]) as stream:
        async for event in stream:
            if getattr(event, "type", None) != "content_block_delta":
                continue
            delta = getattr(event, "delta", None)
            if getattr(delta, "type", None) == "text_delta":
                text_parts.append(getattr(delta, "text", "") or "")
    return _parse_angle("".join(text_parts))


async def orient_images(images, api_key, model, base_url, max_tokens: int = 100):
    """并发判断每张图的方向并旋转到正立（flash）。

    images: [(bytes, media_type), ...]，按页顺序传入。
    每页完成即实时推送进度；最后产出 {"type": "oriented", "images": 旋转后的同序列表}。
    """
    import asyncio

    total = len(images)

    async def _orient_one(idx: int, b, mt):
        angle = await detect_orientation(b, mt, api_key, model, base_url, max_tokens)
        if angle not in (0, 90, 180, 270):
            angle = 0
        if angle:
            return idx, angle, (rotate_image(b, angle), "image/png")
        return idx, angle, (b, mt)

    tasks = [asyncio.create_task(_orient_one(i, b, mt)) for i, (b, mt) in enumerate(images)]
    oriented = [None] * total
    done = 0
    for fut in asyncio.as_completed(tasks):
        idx, angle, out = await fut
        done += 1
        oriented[idx] = out
        yield {"type": "stage", "text": f"方向校正 {done}/{total} 张（第 {idx + 1} 张旋转 {angle}°）"}
    yield {"type": "oriented", "images": oriented}


ACCOUNT_PROMPT = (
    "这是一张银行对账单/账户明细的表头截图。"
    "请精确抄录银行账号（卡号）与户名，只输出一个 JSON 对象："
    '{"account_no": "账号完整数字（去掉空格、横线等分隔符）", "account_name": "户名"}。'
    "账号要逐位精确，不要漏位、不要打码、不要省略；找不到的字段填 null。"
)


async def extract_account_no(image_bytes: bytes, media_type: str, api_key: str, model: str,
                             base_url: str, max_tokens: int = 500) -> dict:
    """用 flash 读表头，抽取银行账号与户名，返回 {"account_no": str, "account_name": str|None}。

    账号是完整数字（去分隔符），供 find_accounts_by_code 精确反查账户。
    """
    import base64

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)
    msg = {"role": "user", "content": [
        {"type": "image",
         "source": {"type": "base64", "media_type": media_type,
                    "data": base64.b64encode(image_bytes).decode()}},
        {"type": "text", "text": ACCOUNT_PROMPT},
    ]}
    text_parts: List[str] = []
    async with client.messages.stream(model=model, max_tokens=max_tokens,
                                      thinking={"type": "disabled"}, messages=[msg]) as stream:
        async for event in stream:
            if getattr(event, "type", None) != "content_block_delta":
                continue
            delta = getattr(event, "delta", None)
            if getattr(delta, "type", None) == "text_delta":
                text_parts.append(getattr(delta, "text", "") or "")
    data = _parse_json("".join(text_parts))
    return {
        "account_no": (data.get("account_no") or "").strip(),
        "account_name": data.get("account_name") or None,
    }
