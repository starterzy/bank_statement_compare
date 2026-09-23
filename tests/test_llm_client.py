from app.llm.client import build_prompt, _parse_json


def test_parse_json_plain():
    d = _parse_json('{"date": "交易时间", "debit": "借方发生额"}')
    assert d["date"] == "交易时间"


def test_parse_json_with_code_fence():
    d = _parse_json('```json\n{"date": "交易时间"}\n```')
    assert d["date"] == "交易时间"


def test_build_prompt_mentions_headers_and_fields():
    p = build_prompt(["交易时间", "借方发生额"], [{"交易时间": "20260101"}], ["date", "debit"])
    assert "date" in p
    assert "交易时间" in p
    assert "JSON" in p
