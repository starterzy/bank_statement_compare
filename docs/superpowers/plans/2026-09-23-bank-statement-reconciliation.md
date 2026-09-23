# 银行流水对账工具 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个本地 Web 应用，把「银行对账单」与「数据库系统银行流水」逐笔对应、核对月度借/贷发生额、识别合并记账并输出 Excel 标注表与文字总结。

**Architecture:** FastAPI 后端 + 原生 HTML/JS 前端。解析 Excel 后，银行侧用 LLM 判断字段与数据库字段的对应关系、数据库侧用固定配置映射，统一成标准交易模型；再用确定性算法做 1:1 匹配、合并记账拆分、月度核对，最后生成 Excel + 总结。

**Tech Stack:** Python 3.13、FastAPI、uvicorn、openpyxl、xlrd、pandas、anthropic SDK、pytest、`decimal.Decimal`（金额不用 float）。

**Spec:** `docs/superpowers/specs/2026-09-23-bank-statement-reconciliation-design.md`

## Global Constraints

- 金额一律用 `Decimal`，禁 float 运算。
- **借对借、贷对贷**：借方与借方比、贷方与贷方比，**不做方向归一化**（不引入带符号净额）。
- 匹配规则：金额优先 + 同月 + 同方向（借/贷）；重复金额用「日期距离最近」消歧。
- 合并记账：一条 = 多条之和，子集求和，`MAX_MERGE_SIZE = 8`。
- 数据库导出格式视为确定，用固定配置映射（`DB_COLUMN_MAP`），不走 LLM；银行对账单用 LLM 判断字段对应。
- 总结严重度顺序：月度总额不一致 > 未匹配项 > 合并记账提示 > 全部对应。
- 首版只支持 Excel（.xls/.xlsx）；PDF/PNG 后续迭代。
- 所有 git commit 信息末尾追加 `Co-Authored-By: Claude Code <noreply@anthropic.com>`。
- 运行目录为 `d:\HuaweiMoveData\Users\90887\Desktop\bank_compare`（非 git 仓库，Task 1 里 `git init`）。

---

## 文件结构

```
bank_compare/
├── app/
│   ├── __init__.py
│   ├── models.py            # Transaction 数据模型 + parse_date/to_decimal/to_int/clean_str
│   ├── config.py            # DB_COLUMN_MAP / BANK_COLUMN_MAP / LLM_MODEL / MAX_MERGE_SIZE
│   ├── pipeline.py          # run_compare 编排 + CompareResult
│   ├── main.py              # FastAPI 路由
│   ├── parsing/
│   │   ├── __init__.py
│   │   ├── excel_reader.py  # read_excel → RawTable / sample_rows
│   │   └── column_mapper.py # build_transactions / map_bank_via_llm
│   ├── matching/
│   │   ├── __init__.py
│   │   ├── engine.py        # match_transactions / MatchPair / MergeGroup / MatchResult
│   │   ├── merge.py         # find_subsets
│   │   └── monthly.py       # monthly_totals / compare_monthly / MonthlyDiff
│   ├── reporting/
│   │   ├── __init__.py
│   │   ├── summary.py       # build_summary
│   │   └── excel_writer.py  # write_result_excel
│   └── llm/
│       ├── __init__.py
│       └── client.py        # claude_map_bank_columns
├── web/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── tests/
│   ├── __init__.py
│   ├── fixtures/            # 三份真实样例（Task 1 复制进来）
│   ├── test_models.py
│   ├── test_excel_reader.py
│   ├── test_column_mapper.py
│   ├── test_matching.py
│   ├── test_merge.py
│   ├── test_monthly.py
│   ├── test_summary.py
│   ├── test_pipeline.py
│   └── test_end_to_end.py
├── pytest.ini
├── requirements.txt
└── .gitignore
```

---

### Task 1: 项目脚手架 + 标准交易模型

**Files:**
- Create: `pytest.ini`, `requirements.txt`, `.gitignore`
- Create: `app/__init__.py`, `app/models.py`
- Create: `tests/__init__.py`, `tests/test_models.py`, `tests/fixtures/`（复制三份样例文件）

**Interfaces:**
- Produces: `Transaction`（dataclass）、`parse_date(value) -> Optional[date]`、`to_decimal(value) -> Decimal`、`to_int(value) -> Optional[int]`、`clean_str(value) -> Optional[str]`

- [ ] **Step 1: 初始化 git 仓库并复制样例文件**

```bash
cd "d:/HuaweiMoveData/Users/90887/Desktop/bank_compare"
git init
mkdir -p app/parsing app/matching app/reporting app/llm tests/fixtures web
cp "活期账户明细202609220950422790106031(1).xls" tests/fixtures/bank.xls
cp "银行流水0603.xlsx" tests/fixtures/db.xlsx
cp "活期账户明细_匹配结果.xls" tests/fixtures/previous_result.xls
```

- [ ] **Step 2: 写依赖与配置骨架**

`requirements.txt`:
```
fastapi
uvicorn[standard]
openpyxl
xlrd
pandas
anthropic
python-multipart
pytest
```

`pytest.ini`:
```ini
[pytest]
pythonpath = .
```

`.gitignore`:
```
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
venv/
.venv/
data_results/
.env
~$*
*.png
/*.xls
/*.xlsx
```

`app/__init__.py`、`app/parsing/__init__.py`、`app/matching/__init__.py`、`app/reporting/__init__.py`、`app/llm/__init__.py`、`tests/__init__.py`：均为空文件。

- [ ] **Step 3: 写失败测试**

`tests/test_models.py`:
```python
from datetime import date
from decimal import Decimal

from app.models import Transaction, parse_date, to_decimal, to_int, clean_str


def test_to_decimal_handles_various():
    assert to_decimal("12.83") == Decimal("12.83")
    assert to_decimal(12.83) == Decimal("12.83")
    assert to_decimal("1,234.56") == Decimal("1234.56")
    assert to_decimal("") == Decimal("0")
    assert to_decimal(None) == Decimal("0")
    assert to_decimal("~") == Decimal("0")


def test_parse_date_handles_formats():
    assert parse_date("20260101 17:05:53") == date(2026, 1, 1)
    assert parse_date("20260101") == date(2026, 1, 1)
    assert parse_date("2026-01-13 10:01:55") == date(2026, 1, 13)
    assert parse_date("2026/03/02") == date(2026, 3, 2)
    assert parse_date("~") is None
    assert parse_date(None) is None


def test_transaction_amount_and_direction():
    t = Transaction(source="bank", date="2026-01-01", month="2026-01",
                    debit_amount=Decimal("6.14"), credit_amount=Decimal("0"))
    assert t.amount == Decimal("6.14")
    assert t.direction == "debit"
    t2 = Transaction(source="db", date="2026-01-01", month="2026-01",
                     debit_amount=Decimal("0"), credit_amount=Decimal("800000"))
    assert t2.amount == Decimal("800000")
    assert t2.direction == "credit"


def test_to_int_and_clean_str():
    assert to_int("3") == 3
    assert to_int(5.0) == 5
    assert to_int("~") is None
    assert clean_str(" 电费 ") == "电费"
    assert clean_str("~") is None
```

- [ ] **Step 4: 运行测试确认失败**

Run: `pytest tests/test_models.py -v`
Expected: FAIL（`ModuleNotFoundError: app.models`）

- [ ] **Step 5: 实现 `app/models.py`**

```python
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional


def to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    if isinstance(value, bool):
        return Decimal("0")
    if isinstance(value, (int, float)):
        return Decimal(str(value)).quantize(Decimal("0.01"))
    s = str(value).strip().replace(",", "").replace("，", "")
    if s in ("", "-", "~", "None", "nan", "NaN", "NaT", "null"):
        return Decimal("0")
    return Decimal(s).quantize(Decimal("0.01"))


def to_int(value) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    s = str(value).strip()
    if s in ("", "~", "None", "nan", "NaN", "NaT", "null"):
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def clean_str(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float) and value != value:  # NaN
        return None
    s = str(value).strip()
    if s in ("", "~", "None", "nan", "NaN", "NaT", "null"):
        return None
    return s


def parse_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if s in ("", "~", "None", "nan", "NaN", "NaT", "null"):
        return None
    for fmt in (
        "%Y%m%d %H:%M:%S", "%Y%m%d %H:%M", "%Y%m%d",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
        "%Y.%m.%d %H:%M:%S", "%Y.%m.%d",
    ):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


@dataclass
class Transaction:
    source: str
    date: str
    month: str
    debit_amount: Decimal
    credit_amount: Decimal
    counterparty: Optional[str] = None
    counterparty_account: Optional[str] = None
    summary: Optional[str] = None
    remark: Optional[str] = None
    voucher_no: Optional[str] = None
    detail_index: Optional[int] = None
    transaction_id: Optional[str] = None
    balance: Optional[Decimal] = None
    currency: Optional[str] = None
    raw: dict = field(default_factory=dict)

    @property
    def amount(self) -> Decimal:
        return self.debit_amount if self.debit_amount != 0 else self.credit_amount

    @property
    def direction(self) -> str:
        return "debit" if self.debit_amount != 0 else "credit"
```

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/test_models.py -v`
Expected: PASS（4 passed）

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "feat: 项目脚手架与标准交易模型

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: Excel 读取

**Files:**
- Create: `app/parsing/excel_reader.py`
- Create: `tests/test_excel_reader.py`

**Interfaces:**
- Produces: `RawTable(headers: list[str], rows: list[dict])`、`read_excel(path: str) -> RawTable`、`sample_rows(raw: RawTable, n=8) -> list[dict]`

- [ ] **Step 1: 写失败测试**

`tests/test_excel_reader.py`:
```python
import os
from app.parsing.excel_reader import read_excel, sample_rows

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def test_read_bank_xls():
    raw = read_excel(os.path.join(FIXTURES, "bank.xls"))
    assert "客户账号" in raw.headers
    assert "对方户名" in raw.headers
    assert len(raw.rows) >= 118


def test_read_db_xlsx():
    raw = read_excel(os.path.join(FIXTURES, "db.xlsx"))
    assert "PK_ACCOUNTINGBOOK" in raw.headers
    assert "EXPLANATION" in raw.headers
    assert len(raw.rows) >= 117


def test_sample_rows():
    raw = read_excel(os.path.join(FIXTURES, "db.xlsx"))
    samples = sample_rows(raw, 3)
    assert len(samples) == 3
    assert "EXPLANATION" in samples[0]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_excel_reader.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 `app/parsing/excel_reader.py`**

```python
from dataclasses import dataclass, field
from typing import Dict, List

import pandas as pd


@dataclass
class RawTable:
    headers: List[str] = field(default_factory=list)
    rows: List[Dict] = field(default_factory=list)


def _detect_header_row(data) -> int:
    for idx, row in enumerate(data):
        cells = [c for c in row if c is not None and str(c).strip() != ""]
        if not cells:
            continue
        str_cells = [c for c in cells if isinstance(c, str)]
        if len(str_cells) / len(cells) >= 0.5:
            return idx
    return 0


def read_excel(path: str) -> RawTable:
    engine = "xlrd" if path.lower().endswith(".xls") else "openpyxl"
    df = pd.read_excel(path, header=None, dtype=object, engine=engine)
    data = df.values.tolist()
    header_idx = _detect_header_row(data)
    headers = [str(c).strip() if c is not None else "" for c in data[header_idx]]
    rows = []
    for row in data[header_idx + 1:]:
        d = {}
        for i, h in enumerate(headers):
            d[h] = row[i] if i < len(row) else None
        rows.append(d)
    return RawTable(headers=headers, rows=rows)


def sample_rows(raw: RawTable, n: int = 8) -> List[Dict]:
    return raw.rows[:n]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_excel_reader.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: Excel 读取为原始表

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: 字段对应与标准化（固定配置）

**Files:**
- Create: `app/config.py`
- Create: `app/parsing/column_mapper.py`
- Create: `tests/test_column_mapper.py`

**Interfaces:**
- Consumes: `RawTable`、`read_excel`、`Transaction`、`parse_date`、`to_decimal`、`to_int`、`clean_str`
- Produces: `build_transactions(raw, column_map, source) -> list[Transaction]`、`CANONICAL_FIELDS`、`DB_COLUMN_MAP`、`BANK_COLUMN_MAP`

- [ ] **Step 1: 写失败测试**

`tests/test_column_mapper.py`:
```python
import os
from decimal import Decimal

from app.config import DB_COLUMN_MAP, BANK_COLUMN_MAP
from app.parsing.excel_reader import read_excel
from app.parsing.column_mapper import build_transactions

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def test_build_db_transactions():
    raw = read_excel(os.path.join(FIXTURES, "db.xlsx"))
    txs = build_transactions(raw, DB_COLUMN_MAP, "db")
    assert len(txs) == 117
    # 校验一笔已知交易：缴12月税金 598092.61 在贷方
    t = next(x for x in txs if x.credit_amount == Decimal("598092.61"))
    assert t.summary == "缴12月税金"
    assert t.direction == "credit"
    assert t.month == "2026-01"


def test_build_bank_transactions():
    raw = read_excel(os.path.join(FIXTURES, "bank.xls"))
    txs = build_transactions(raw, BANK_COLUMN_MAP, "bank")
    assert len(txs) == 118
    # 一笔电费 12.83 在借方
    t = next(x for x in txs if x.debit_amount == Decimal("12.83"))
    assert t.counterparty == "国网浙江省电力有限公司"
    assert t.direction == "debit"
    assert t.month == "2026-01"


def test_skip_rows_without_amount():
    raw = read_excel(os.path.join(FIXTURES, "db.xlsx"))
    txs = build_transactions(raw, DB_COLUMN_MAP, "db")
    assert all(x.debit_amount != 0 or x.credit_amount != 0 for x in txs)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_column_mapper.py -v`
Expected: FAIL（`ModuleNotFoundError: app.config`）

- [ ] **Step 3: 实现 `app/config.py`**

```python
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
```

- [ ] **Step 4: 实现 `app/parsing/column_mapper.py`**

```python
from typing import Callable, Dict, List

from ..models import Transaction, clean_str, parse_date, to_decimal, to_int
from .excel_reader import RawTable, sample_rows

CANONICAL_FIELDS = [
    "date", "debit", "credit", "counterparty", "counterparty_account",
    "summary", "remark", "voucher_no", "detail_index", "transaction_id",
    "balance", "currency",
]


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
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_column_mapper.py -v`
Expected: PASS（3 passed）

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: 字段对应与标准化（固定配置）

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: LLM 字段识别（银行侧）

**Files:**
- Create: `app/llm/client.py`
- Create: `tests/test_llm_client.py`

**Interfaces:**
- Consumes: `CANONICAL_FIELDS`、`map_bank_via_llm`
- Produces: `claude_map_bank_columns(headers, samples, api_key, model) -> dict`、`build_prompt(headers, samples, fields) -> str`、`_parse_json(text) -> dict`

- [ ] **Step 1: 写失败测试（只测不联网的部分）**

`tests/test_llm_client.py`:
```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_llm_client.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 `app/llm/client.py`**

```python
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
    return json.loads(text)


def claude_map_bank_columns(headers: List[str], samples: List[Dict], api_key: str, model: str) -> Dict:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=1500,
        messages=[{"role": "user", "content": build_prompt(headers, samples, CANONICAL_FIELDS)}],
    )
    return _parse_json(resp.content[0].text)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_llm_client.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: LLM 字段识别（银行侧）

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: 逐笔 1:1 匹配

**Files:**
- Create: `app/matching/engine.py`（本任务先实现 1:1 部分 + MatchResult 骨架）
- Create: `tests/test_matching.py`

**Interfaces:**
- Consumes: `Transaction`
- Produces: `MatchPair(bank, db)`、`MatchResult`、`match_transactions(bank_txs, db_txs, max_merge_size=8) -> MatchResult`（本任务 merge 列表恒为空，Task 6 补全）

- [ ] **Step 1: 写失败测试（用对齐的合成数据）**

`tests/test_matching.py`:
```python
from decimal import Decimal

from app.matching.engine import match_transactions
from app.models import Transaction


def _tx(source, month, direction, amount, day="01"):
    debit = Decimal(amount) if direction == "debit" else Decimal("0")
    credit = Decimal(amount) if direction == "credit" else Decimal("0")
    return Transaction(source=source, date=f"{month}-{day}", month=month,
                       debit_amount=debit, credit_amount=credit, summary=amount)


def test_match_same_amount_same_month():
    bank = [_tx("bank", "2026-01", "debit", "6.14", "01")]
    db = [_tx("db", "2026-01", "debit", "6.14", "02")]
    r = match_transactions(bank, db)
    assert len(r.matched) == 1
    assert r.unmatched_bank == [] and r.unmatched_db == []


def test_no_match_different_month():
    bank = [_tx("bank", "2026-01", "debit", "6.14")]
    db = [_tx("db", "2026-02", "debit", "6.14")]
    r = match_transactions(bank, db)
    assert r.matched == []
    assert len(r.unmatched_bank) == 1 and len(r.unmatched_db) == 1


def test_no_match_different_direction():
    bank = [_tx("bank", "2026-01", "debit", "100")]
    db = [_tx("db", "2026-01", "credit", "100")]
    r = match_transactions(bank, db)
    assert r.matched == []


def test_duplicate_amount_uses_nearest_date():
    bank = [_tx("bank", "2026-01", "debit", "30", "05"),
            _tx("bank", "2026-01", "debit", "30", "20")]
    db = [_tx("db", "2026-01", "debit", "30", "06"),
          _tx("db", "2026-01", "debit", "30", "21")]
    r = match_transactions(bank, db)
    assert len(r.matched) == 2
    # 05 应配 06，20 应配 21
    for p in r.matched:
        assert abs(int(p.bank.date[-2:]) - int(p.db.date[-2:])) <= 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_matching.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 `app/matching/engine.py`**

```python
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import List, Tuple

from ..models import Transaction


@dataclass
class MatchPair:
    bank: Transaction
    db: Transaction


@dataclass
class MergeGroup:
    target: Transaction
    parts: List[Transaction]
    kind: str  # "db_merged" / "bank_merged"


@dataclass
class MatchResult:
    matched: List[MatchPair] = field(default_factory=list)
    merged: List[MergeGroup] = field(default_factory=list)
    unmatched_bank: List[Transaction] = field(default_factory=list)
    unmatched_db: List[Transaction] = field(default_factory=list)


def _date_dist(a: str, b: str) -> int:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def _greedy_1to1(bank, db) -> Tuple[List[MatchPair], List[Transaction], List[Transaction]]:
    remaining_db = list(db)
    matched = []
    for b in sorted(bank, key=lambda t: t.date):
        cands = [d for d in remaining_db if d.amount == b.amount]
        if not cands:
            continue
        best = min(cands, key=lambda d: _date_dist(b.date, d.date))
        matched.append(MatchPair(bank=b, db=best))
        remaining_db.remove(best)
    matched_bank_ids = {id(p.bank) for p in matched}
    unmatched_bank = [b for b in bank if id(b) not in matched_bank_ids]
    return matched, unmatched_bank, remaining_db


def match_transactions(bank_txs, db_txs, max_merge_size=8) -> MatchResult:
    result = MatchResult()
    bank_groups = defaultdict(list)
    db_groups = defaultdict(list)
    for t in bank_txs:
        bank_groups[(t.month, t.direction)].append(t)
    for t in db_txs:
        db_groups[(t.month, t.direction)].append(t)

    for key in set(bank_groups) | set(db_groups):
        matched, un_bank, un_db = _greedy_1to1(bank_groups.get(key, []), db_groups.get(key, []))
        result.matched.extend(matched)
        # 合并检测在 Task 6 补全；此处直接归入未匹配
        result.unmatched_bank.extend(un_bank)
        result.unmatched_db.extend(un_db)
    return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_matching.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: 逐笔 1:1 匹配

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: 合并记账检测

**Files:**
- Create: `app/matching/merge.py`
- Modify: `app/matching/engine.py`（接入合并检测）
- Create: `tests/test_merge.py`

**Interfaces:**
- Consumes: `Transaction`、`MatchResult`、`MergeGroup`
- Produces: `find_subsets(amounts: list[Decimal], target: Decimal, max_size: int) -> list[list[int]]`

- [ ] **Step 1: 写失败测试**

`tests/test_merge.py`:
```python
from decimal import Decimal

from app.matching.merge import find_subsets
from app.matching.engine import match_transactions
from app.models import Transaction


def test_find_subsets_exact_sum():
    r = find_subsets([Decimal("140000000"), Decimal("8050505.55")], Decimal("148050505.55"), 8)
    assert r and set(r[0]) == {0, 1}


def test_find_subsets_no_match():
    assert find_subsets([Decimal("1.00"), Decimal("2.00")], Decimal("10.00"), 8) == []


def _tx(source, month, direction, amount, summary, day="01"):
    debit = Decimal(amount) if direction == "debit" else Decimal("0")
    credit = Decimal(amount) if direction == "credit" else Decimal("0")
    return Transaction(source=source, date=f"{month}-{day}", month=month,
                       debit_amount=debit, credit_amount=credit, summary=summary)


def test_merge_detection_db_side():
    # 数据库一条 = 银行两条（同月同方向）
    db = [_tx("db", "2026-07", "debit", "148050505.55", "归还委贷及利息", "01")]
    bank = [_tx("bank", "2026-07", "debit", "140000000", "归还委贷", "01"),
            _tx("bank", "2026-07", "debit", "8050505.55", "利息", "01")]
    r = match_transactions(bank, db)
    assert len(r.matched) == 0
    assert len(r.merged) == 1
    g = r.merged[0]
    assert g.kind == "db_merged"
    assert g.target.summary == "归还委贷及利息"
    assert len(g.parts) == 2
    assert r.unmatched_bank == [] and r.unmatched_db == []


def test_reverse_merge_bank_side():
    bank = [_tx("bank", "2026-07", "debit", "148050505.55", "还本付息", "01")]
    db = [_tx("db", "2026-07", "debit", "140000000", "归还委贷", "01"),
          _tx("db", "2026-07", "debit", "8050505.55", "利息", "01")]
    r = match_transactions(bank, db)
    assert len(r.merged) == 1
    assert r.merged[0].kind == "bank_merged"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_merge.py -v`
Expected: FAIL（`ModuleNotFoundError: app.matching.merge`）

- [ ] **Step 3: 实现 `app/matching/merge.py`**

```python
from decimal import Decimal
from typing import List


def find_subsets(amounts: List[Decimal], target: Decimal, max_size: int) -> List[List[int]]:
    """返回金额之和恰等于 target 的原始下标子集（大小 2..max_size）。"""
    indexed = sorted(enumerate(amounts), key=lambda x: x[1], reverse=True)
    results: List[List[int]] = []

    def dfs(start, path, total):
        if len(path) >= 2 and total == target:
            results.append(list(path))
            return
        if len(path) >= max_size or total >= target:
            return
        for i in range(start, len(indexed)):
            idx, amt = indexed[i]
            if total + amt > target:
                continue
            path.append(idx)
            dfs(i + 1, path, total + amt)
            path.pop()

    dfs(0, [], Decimal("0"))
    return results
```

- [ ] **Step 4: 修改 `app/matching/engine.py` 接入合并检测**

在 `match_transactions` 里替换合并检测段（并新增 `_detect_merges`）：

```python
from .merge import find_subsets


def _detect_merges(targets, candidates, kind, max_size):
    groups = []
    remaining_targets = []
    used = set()
    for t in targets:
        cand = [c for c in candidates if id(c) not in used]
        subsets = find_subsets([c.amount for c in cand], t.amount, max_size)
        if subsets:
            parts = [cand[i] for i in subsets[0]]
            groups.append(MergeGroup(target=t, parts=parts, kind=kind))
            for p in parts:
                used.add(id(p))
        else:
            remaining_targets.append(t)
    remaining_candidates = [c for c in candidates if id(c) not in used]
    return groups, remaining_targets, remaining_candidates
```

并把 `match_transactions` 中的循环体改为：

```python
    for key in set(bank_groups) | set(db_groups):
        bank = bank_groups.get(key, [])
        db = db_groups.get(key, [])
        matched, un_bank, un_db = _greedy_1to1(bank, db)
        result.matched.extend(matched)
        # 正向：数据库一条 = 银行多条
        merged_db, un_db, un_bank = _detect_merges(un_db, un_bank, "db_merged", max_merge_size)
        result.merged.extend(merged_db)
        # 反向：银行一条 = 数据库多条
        merged_bank, un_bank, un_db = _detect_merges(un_bank, un_db, "bank_merged", max_merge_size)
        result.merged.extend(merged_bank)
        result.unmatched_bank.extend(un_bank)
        result.unmatched_db.extend(un_db)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_merge.py tests/test_matching.py -v`
Expected: PASS（全部通过）

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: 合并记账检测（子集求和）

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: 月度核对 + 总结

**Files:**
- Create: `app/matching/monthly.py`
- Create: `app/reporting/summary.py`
- Create: `tests/test_monthly.py`、`tests/test_summary.py`

**Interfaces:**
- Consumes: `Transaction`、`MatchResult`、`MonthlyDiff`
- Produces: `monthly_totals(txs) -> dict`、`compare_monthly(bank_txs, db_txs) -> list[MonthlyDiff]`、`build_summary(match_result, monthly_diffs) -> dict`

- [ ] **Step 1: 写失败测试**

`tests/test_monthly.py`:
```python
from decimal import Decimal

from app.matching.monthly import compare_monthly, monthly_totals
from app.models import Transaction


def _tx(source, month, direction, amount):
    debit = Decimal(amount) if direction == "debit" else Decimal("0")
    credit = Decimal(amount) if direction == "credit" else Decimal("0")
    return Transaction(source=source, date=f"{month}-01", month=month,
                       debit_amount=debit, credit_amount=credit)


def test_monthly_totals():
    txs = [_tx("bank", "2026-01", "debit", "6.14"),
           _tx("bank", "2026-01", "debit", "5.02"),
           _tx("bank", "2026-01", "credit", "800000")]
    t = monthly_totals(txs)
    assert t["2026-01"]["debit"] == Decimal("11.16")
    assert t["2026-01"]["credit"] == Decimal("800000")


def test_compare_monthly_consistent():
    bank = [_tx("bank", "2026-01", "debit", "100"), _tx("bank", "2026-01", "credit", "50")]
    db = [_tx("db", "2026-01", "debit", "100"), _tx("db", "2026-01", "credit", "50")]
    diffs = compare_monthly(bank, db)
    assert len(diffs) == 1
    assert diffs[0].consistent is True
    assert diffs[0].swap_suspected is False


def test_compare_monthly_mismatch_and_swap():
    bank = [_tx("bank", "2026-01", "debit", "100"), _tx("bank", "2026-01", "credit", "50")]
    db = [_tx("db", "2026-01", "debit", "50"), _tx("db", "2026-01", "credit", "100")]
    diffs = compare_monthly(bank, db)
    assert diffs[0].consistent is False
    assert diffs[0].swap_suspected is True
```

`tests/test_summary.py`:
```python
from decimal import Decimal

from app.matching.engine import MatchResult, MatchPair, MergeGroup
from app.matching.monthly import MonthlyDiff
from app.reporting.summary import build_summary
from app.models import Transaction


def _tx(source, summary="x"):
    return Transaction(source=source, date="2026-01-01", month="2026-01",
                       debit_amount=Decimal("10"), credit_amount=Decimal("0"), summary=summary)


def _diff(consistent=True):
    return MonthlyDiff(month="2026-01", bank_debit=Decimal("10"), db_debit=Decimal("10"),
                       debit_diff=Decimal("0"), bank_credit=Decimal("0"), db_credit=Decimal("0"),
                       credit_diff=Decimal("0"), swap_suspected=not consistent)


def test_summary_all_matched():
    r = MatchResult(matched=[MatchPair(_tx("bank"), _tx("db"))])
    s = build_summary(r, [_diff(True)])
    assert s["status"] == "all_matched"
    assert s["message"] == "全部对应"


def test_summary_unmatched_before_merged():
    r = MatchResult(unmatched_bank=[_tx("bank")])
    s = build_summary(r, [_diff(True)])
    assert s["status"] == "unmatched"


def test_summary_monthly_mismatch_most_severe():
    r = MatchResult(matched=[MatchPair(_tx("bank"), _tx("db"))], unmatched_bank=[_tx("bank")])
    s = build_summary(r, [_diff(False)])
    assert s["status"] == "monthly_mismatch"
    assert s["swap_warning"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_monthly.py tests/test_summary.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 `app/matching/monthly.py`**

```python
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List

from ..models import Transaction


def monthly_totals(txs: List[Transaction]) -> Dict[str, Dict[str, Decimal]]:
    totals: Dict[str, Dict[str, Decimal]] = {}
    for t in txs:
        m = totals.setdefault(t.month, {"debit": Decimal("0"), "credit": Decimal("0")})
        m["debit"] += t.debit_amount
        m["credit"] += t.credit_amount
    return totals


@dataclass
class MonthlyDiff:
    month: str
    bank_debit: Decimal
    db_debit: Decimal
    debit_diff: Decimal
    bank_credit: Decimal
    db_credit: Decimal
    credit_diff: Decimal
    swap_suspected: bool = False

    @property
    def consistent(self) -> bool:
        return self.debit_diff == 0 and self.credit_diff == 0


def compare_monthly(bank_txs: List[Transaction], db_txs: List[Transaction]) -> List[MonthlyDiff]:
    bank = monthly_totals(bank_txs)
    db = monthly_totals(db_txs)
    zero = {"debit": Decimal("0"), "credit": Decimal("0")}
    diffs = []
    for month in sorted(set(bank) | set(db)):
        b = bank.get(month, zero)
        d = db.get(month, zero)
        diff = MonthlyDiff(
            month=month,
            bank_debit=b["debit"], db_debit=d["debit"], debit_diff=b["debit"] - d["debit"],
            bank_credit=b["credit"], db_credit=d["credit"], credit_diff=b["credit"] - d["credit"],
        )
        # 对称错位诊断：银行借方≈数据库贷方 且 银行贷方≈数据库借方
        diff.swap_suspected = (b["debit"] == d["credit"] and b["credit"] == d["debit"]
                               and (b["debit"] != d["debit"] or b["credit"] != d["credit"]))
        diffs.append(diff)
    return diffs
```

- [ ] **Step 4: 实现 `app/reporting/summary.py`**

```python
from typing import List

from ..matching.engine import MatchResult
from ..matching.monthly import MonthlyDiff


def _message(status: str) -> str:
    if status == "all_matched":
        return "全部对应"
    if status == "monthly_mismatch":
        return "存在月度总额不一致，请优先核对"
    if status == "unmatched":
        return "存在未匹配项"
    return "存在合并记账"


def build_summary(match_result: MatchResult, monthly_diffs: List[MonthlyDiff]) -> dict:
    mismatches = [d for d in monthly_diffs if not d.consistent]
    unmatched_bank = match_result.unmatched_bank
    unmatched_db = match_result.unmatched_db
    merged = match_result.merged

    if mismatches:
        status = "monthly_mismatch"
    elif unmatched_bank or unmatched_db:
        status = "unmatched"
    elif merged:
        status = "merged"
    else:
        status = "all_matched"

    return {
        "status": status,
        "message": _message(status),
        "swap_warning": any(d.swap_suspected for d in monthly_diffs),
        "monthly_mismatches": [
            {"month": d.month, "debit_diff": str(d.debit_diff), "credit_diff": str(d.credit_diff)}
            for d in mismatches
        ],
        "unmatched_bank_count": len(unmatched_bank),
        "unmatched_db_count": len(unmatched_db),
        "unmatched_bank": [
            {"date": t.date, "amount": str(t.amount), "summary": t.summary} for t in unmatched_bank
        ],
        "unmatched_db": [
            {"date": t.date, "amount": str(t.amount), "summary": t.summary} for t in unmatched_db
        ],
        "merged_count": len(merged),
        "merged": [
            {"kind": g.kind, "target_amount": str(g.target.amount), "target_summary": g.target.summary,
             "parts": [{"amount": str(p.amount), "summary": p.summary} for p in g.parts]}
            for g in merged
        ],
        "matched_count": len(match_result.matched),
    }
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_monthly.py tests/test_summary.py -v`
Expected: PASS（全部通过）

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: 月度核对与文字总结

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: Excel 报告

**Files:**
- Create: `app/reporting/excel_writer.py`
- Create: `tests/test_excel_writer.py`

**Interfaces:**
- Consumes: `MatchResult`、`MonthlyDiff`、`Transaction`
- Produces: `write_result_excel(match_result, monthly_diffs, bank_txs, db_txs, out_path) -> None`

- [ ] **Step 1: 写失败测试**

`tests/test_excel_writer.py`:
```python
import os
import tempfile
from decimal import Decimal

import openpyxl

from app.matching.engine import MatchResult, MatchPair, MergeGroup
from app.matching.monthly import MonthlyDiff
from app.models import Transaction
from app.reporting.excel_writer import write_result_excel


def _tx(source, summary="x", amount="10"):
    return Transaction(source=source, date="2026-01-01", month="2026-01",
                       debit_amount=Decimal(amount), credit_amount=Decimal("0"), summary=summary)


def test_write_result_excel():
    r = MatchResult(
        matched=[MatchPair(_tx("bank", "电费"), _tx("db", "付电费"))],
        merged=[MergeGroup(target=_tx("db", "合并", "30"),
                           parts=[_tx("bank", "a", "10"), _tx("bank", "b", "20")],
                           kind="db_merged")],
        unmatched_bank=[_tx("bank", "仅银行")],
        unmatched_db=[_tx("db", "仅数据库")],
    )
    diffs = [MonthlyDiff(month="2026-01", bank_debit=Decimal("10"), db_debit=Decimal("10"),
                         debit_diff=Decimal("0"), bank_credit=Decimal("0"), db_credit=Decimal("0"),
                         credit_diff=Decimal("0"))]
    tmp = os.path.join(tempfile.mkdtemp(), "out.xlsx")
    write_result_excel(r, diffs, [], [], tmp)
    wb = openpyxl.load_workbook(tmp)
    assert "逐笔明细" in wb.sheetnames
    assert "月度汇总" in wb.sheetnames
    ws = wb["逐笔明细"]
    assert ws.max_row >= 5
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_excel_writer.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 `app/reporting/excel_writer.py`**

```python
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
        ws.append(["合并记账", g.target.month, _dir(g.target), _amt(g.target.amount),
                   "", "", g.target.summary,
                   "", g.target.summary, g.target.voucher_no, g.target.detail_index])
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
    ws2.append(["月份", "银行借方", "数据库借方", "借方差额", "银行贷方", "数据库贷方", "贷方差额", "是否一致"])
    for d in monthly_diffs:
        ws2.append([d.month, _amt(d.bank_debit), _amt(d.db_debit), _amt(d.debit_diff),
                    _amt(d.bank_credit), _amt(d.db_credit), _amt(d.credit_diff),
                    "一致" if d.consistent else "不一致"])

    wb.save(out_path)


def _dir(t) -> str:
    return "借" if t.direction == "debit" else "贷"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_excel_writer.py -v`
Expected: PASS（1 passed）

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: Excel 报告输出

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: 编排管线 + Web 后端

**Files:**
- Create: `app/pipeline.py`
- Create: `app/main.py`
- Create: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `read_excel`、`build_transactions`、`map_bank_via_llm`、`match_transactions`、`compare_monthly`、`build_summary`、`write_result_excel`、`DB_COLUMN_MAP`
- Produces: `CompareResult`、`run_compare(bank_path, db_path, bank_mapper, db_column_map) -> CompareResult`、FastAPI `app`

- [ ] **Step 1: 写失败测试**

`tests/test_pipeline.py`:
```python
import os
from decimal import Decimal

from app.config import DB_COLUMN_MAP, BANK_COLUMN_MAP
from app.pipeline import run_compare

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _fake_mapper(headers, samples):
    return BANK_COLUMN_MAP


def test_run_compare_on_fixtures():
    bank_path = os.path.join(FIXTURES, "bank.xls")
    db_path = os.path.join(FIXTURES, "db.xlsx")
    r = run_compare(bank_path, db_path, _fake_mapper, DB_COLUMN_MAP)
    assert len(r.bank_txs) == 118
    assert len(r.db_txs) == 117
    # 8 个月都在
    assert len(r.monthly_diffs) == 8
    # 样例借贷口径相反 → 诊断出对称错位
    assert all(d.swap_suspected for d in r.monthly_diffs)
    assert r.summary["status"] == "monthly_mismatch"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL（`ModuleNotFoundError: app.pipeline`）

- [ ] **Step 3: 实现 `app/pipeline.py`**

```python
from dataclasses import dataclass, field
from typing import Callable, List

from .matching.engine import MatchResult, match_transactions
from .matching.monthly import MonthlyDiff, compare_monthly
from .models import Transaction
from .parsing.column_mapper import build_transactions, map_bank_via_llm
from .parsing.excel_reader import read_excel
from .reporting.summary import build_summary


@dataclass
class CompareResult:
    bank_txs: List[Transaction] = field(default_factory=list)
    db_txs: List[Transaction] = field(default_factory=list)
    match_result: MatchResult = field(default_factory=MatchResult)
    monthly_diffs: List[MonthlyDiff] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def run_compare(bank_path: str, db_path: str, bank_mapper: Callable, db_column_map: dict) -> CompareResult:
    bank_raw = read_excel(bank_path)
    db_raw = read_excel(db_path)
    bank_txs = map_bank_via_llm(bank_raw, bank_mapper)
    db_txs = build_transactions(db_raw, db_column_map, "db")
    match_result = match_transactions(bank_txs, db_txs)
    monthly_diffs = compare_monthly(bank_txs, db_txs)
    summary = build_summary(match_result, monthly_diffs)
    return CompareResult(bank_txs=bank_txs, db_txs=db_txs, match_result=match_result,
                         monthly_diffs=monthly_diffs, summary=summary)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS（1 passed）

- [ ] **Step 5: 实现 `app/main.py`**

```python
import os
import tempfile
import uuid

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import DB_COLUMN_MAP, LLM_MODEL
from .llm.client import claude_map_bank_columns
from .pipeline import run_compare
from .reporting.excel_writer import write_result_excel

app = FastAPI(title="银行流水对账")
RESULTS = {}


def _make_bank_mapper(api_key: str, model: str):
    def mapper(headers, samples):
        return claude_map_bank_columns(headers, samples, api_key, model)
    return mapper


@app.post("/api/compare")
async def compare(bank: UploadFile = File(...), db: UploadFile = File(...), api_key: str = Form("")):
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return {"error": "缺少 Claude API key"}
    tmp = tempfile.mkdtemp()
    bank_path = os.path.join(tmp, bank.filename)
    db_path = os.path.join(tmp, db.filename)
    with open(bank_path, "wb") as f:
        f.write(await bank.read())
    with open(db_path, "wb") as f:
        f.write(await db.read())
    result = run_compare(bank_path, db_path, _make_bank_mapper(key, LLM_MODEL), DB_COLUMN_MAP)
    rid = uuid.uuid4().hex
    RESULTS[rid] = result
    return {"id": rid, "summary": result.summary, "matched_count": len(result.match_result.matched)}


@app.get("/api/result/{rid}/excel")
async def download(rid: str):
    result = RESULTS.get(rid)
    if result is None:
        return {"error": "not found"}
    out = os.path.join(tempfile.mkdtemp(), "对账结果.xlsx")
    write_result_excel(result.match_result, result.monthly_diffs, result.bank_txs, result.db_txs, out)
    return FileResponse(out, filename="对账结果.xlsx")


app.mount("/", StaticFiles(directory="web", html=True), name="web")
```

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: 编排管线与 FastAPI 后端

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 10: Web 前端

**Files:**
- Create: `web/index.html`, `web/app.js`, `web/style.css`

**Interfaces:**
- Consumes: FastAPI 的 `/api/compare`、`/api/result/{id}/excel`
- Produces: 单页上传界面 + 结果展示 + Excel 下载

- [ ] **Step 1: 写 `web/index.html`**

```html
<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <title>银行流水对账</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <h1>银行流水对账</h1>
  <form id="form">
    <label>银行对账单 <input type="file" id="bank" accept=".xls,.xlsx" required></label>
    <label>数据库流水 <input type="file" id="db" accept=".xls,.xlsx,.csv" required></label>
    <label>Claude API Key <input type="password" id="api_key"></label>
    <button type="submit">开始对比</button>
  </form>
  <div id="status"></div>
  <div id="summary"></div>
  <a id="download" style="display:none">下载 Excel 结果</a>
  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: 写 `web/app.js`**

```js
const form = document.getElementById("form");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");
const downloadEl = document.getElementById("download");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  statusEl.textContent = "对比中…";
  const fd = new FormData();
  fd.append("bank", document.getElementById("bank").files[0]);
  fd.append("db", document.getElementById("db").files[0]);
  fd.append("api_key", document.getElementById("api_key").value);
  const resp = await fetch("/api/compare", { method: "POST", body: fd });
  const data = await resp.json();
  if (data.error) { statusEl.textContent = "错误：" + data.error; return; }
  statusEl.textContent = "完成";
  summaryEl.textContent = JSON.stringify(data.summary, null, 2);
  downloadEl.href = "/api/result/" + data.id + "/excel";
  downloadEl.style.display = "inline";
});
```

- [ ] **Step 3: 写 `web/style.css`**

```css
body { font-family: sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
form { display: flex; flex-direction: column; gap: 0.8rem; max-width: 420px; }
label { display: flex; flex-direction: column; gap: 0.2rem; }
button { padding: 0.5rem 1rem; cursor: pointer; }
#summary { white-space: pre-wrap; background: #f6f6f6; padding: 1rem; margin-top: 1rem; }
```

- [ ] **Step 4: 手动验证**

Run: `uvicorn app.main:app --reload`（在项目根目录）
验证：打开 `http://127.0.0.1:8000`，上传两个样例文件 + API key，点击「开始对比」，能看到总结 JSON 与下载链接。

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: Web 前端页面

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 11: 端到端金标准测试

**Files:**
- Create: `tests/test_end_to_end.py`

**Interfaces:**
- Consumes: 全链路

- [ ] **Step 1: 写端到端测试（断言真实样例的确定结果）**

`tests/test_end_to_end.py`:
```python
import os
from decimal import Decimal

from app.config import DB_COLUMN_MAP, BANK_COLUMN_MAP
from app.pipeline import run_compare

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _fake_mapper(headers, samples):
    return BANK_COLUMN_MAP


def test_end_to_end_golden():
    r = run_compare(os.path.join(FIXTURES, "bank.xls"),
                    os.path.join(FIXTURES, "db.xlsx"),
                    _fake_mapper, DB_COLUMN_MAP)
    # 笔数
    assert len(r.bank_txs) == 118
    assert len(r.db_txs) == 117
    # 月度总额（样例借贷口径相反，银行借方=数据库贷方）
    d = {x.month: x for x in r.monthly_diffs}
    assert d["2026-01"].bank_debit == Decimal("725973.26")
    assert d["2026-01"].bank_credit == Decimal("800144.94")
    assert d["2026-01"].db_debit == Decimal("800144.94")
    assert d["2026-01"].db_credit == Decimal("725973.26")
    # 对称错位诊断全部触发
    assert all(x.swap_suspected for x in r.monthly_diffs)
```

- [ ] **Step 2: 运行全量测试**

Run: `pytest -v`
Expected: 全部 PASS

- [ ] **Step 3: 提交**

```bash
git add -A
git commit -m "test: 端到端金标准测试

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 自审记录

- **Spec 覆盖**：逐笔匹配（Task 5）、合并记账（Task 6）、月度核对（Task 7）、总结（Task 7）、Excel 报告（Task 8）、字段对应（Task 3/4）、Web UI（Task 9/10）、方向借对借（Task 5/7）、金额 Decimal（Task 1）。无遗漏。
- **类型一致性**：`Transaction` 字段（`source/date/month/debit_amount/credit_amount/…`）在 Task 1 定义，后续 Task 一致引用；`amount`/`direction` 属性一致；`MatchResult.matched/merged/unmatched_bank/unmatched_db` 与 `summary.py`/`excel_writer.py` 引用一致；`MonthlyDiff` 含 `swap_suspected` 字段，Task 7 与 Task 8/9 一致。
- **已知注意**：样例 `bank.xls`/`db.xlsx` 借贷口径相反，端到端测试据此断言「诊断触发」而非「全部对应」；真实导出格式确定后调整 `DB_COLUMN_MAP` 并更新金标准断言。
