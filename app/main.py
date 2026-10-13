import json
import os
import tempfile
import uuid

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import DB_COLUMN_MAP, LLM_BASE_URL, LLM_MODEL
from .db.oracle import fetch_bank_detail, fetch_statement, list_bank_accounts, list_companies, list_years, load_env
from .llm.client import map_bank_columns, stream_map_bank_columns
from .parsing.column_mapper import build_transactions
from .parsing.excel_reader import read_excel, sample_rows
from .pipeline import CompareResult, run_compare, run_compare_with_db, run_matching
from .reporting.excel_writer import write_result_excel

app = FastAPI(title="银行流水对账")
RESULTS = {}


def _ndjson(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"


def _resolve_api_key(api_key: str) -> str:
    """字段识别用的 DeepSeek key：表单 > 环境变量 > .env，任一即可。"""
    return (api_key
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or load_env().get("LLM_API_KEY")
            or "")


def _make_bank_mapper(api_key: str, model: str):
    def mapper(headers, samples):
        return map_bank_columns(headers, samples, api_key, model, LLM_BASE_URL)
    return mapper


@app.post("/api/compare")
async def compare(bank: UploadFile = File(...), db: UploadFile = File(None),
                  api_key: str = Form(""), db_source: str = Form("database"),
                  account: str = Form(""), book: str = Form(""), accasoa: str = Form(""),
                  year: str = Form(""), month: str = Form(""), month_to: str = Form("")):
    key = _resolve_api_key(api_key)
    if not key:
        return {"error": "缺少 DeepSeek API key"}
    tmp = tempfile.mkdtemp()
    bank_path = os.path.join(tmp, bank.filename or "bank.xls")
    with open(bank_path, "wb") as f:
        f.write(await bank.read())

    try:
        if db_source == "database":
            db_txs = fetch_bank_detail(f11=account or None, book=book or None,
                                       accasoa=accasoa or None, year=year or None,
                                       month=month or None, month_to=month_to or None)
            result = run_compare_with_db(bank_path, db_txs, _make_bank_mapper(key, LLM_MODEL))
        else:
            if db is None or db.filename is None:
                return {"error": "缺少数据库流水文件"}
            db_path = os.path.join(tmp, db.filename)
            with open(db_path, "wb") as f:
                f.write(await db.read())
            result = run_compare(bank_path, db_path, _make_bank_mapper(key, LLM_MODEL), DB_COLUMN_MAP)
    except Exception as e:
        return {"error": f"对比失败: {e}"}

    rid = uuid.uuid4().hex
    RESULTS[rid] = result
    return {"id": rid, "summary": result.summary, "matched_count": len(result.match_result.matched)}


@app.post("/api/compare/stream")
async def compare_stream(bank: UploadFile = File(...), db: UploadFile = File(None),
                         db_source: str = Form("database"), account: str = Form(""),
                         book: str = Form(""), accasoa: str = Form(""),
                         year: str = Form(""), month: str = Form(""), month_to: str = Form("")):
    """流式对比：NDJSON 逐条推送 stage / thinking / mapping / done / error 事件。"""
    key = _resolve_api_key("")
    if not key:
        return {"error": "缺少 DeepSeek API key"}

    tmp = tempfile.mkdtemp()
    bank_path = os.path.join(tmp, bank.filename or "bank.xls")
    with open(bank_path, "wb") as f:
        f.write(await bank.read())

    db_path = None
    if db_source != "database":
        if db is None or db.filename is None:
            return {"error": "缺少数据库流水文件"}
        db_path = os.path.join(tmp, db.filename)
        with open(db_path, "wb") as f:
            f.write(await db.read())

    async def gen():
        try:
            yield _ndjson({"type": "stage", "text": "读取银行对账单…"})
            bank_raw = read_excel(bank_path)
            if not bank_raw.headers:
                yield _ndjson({"type": "error", "message": "银行对账单为空或无法识别表头"})
                return

            if db_source == "database":
                yield _ndjson({"type": "stage", "text": "查询数据库银行流水…"})
                db_txs = fetch_bank_detail(f11=account or None, book=book or None,
                                           accasoa=accasoa or None, year=year or None,
                                           month=month or None, month_to=month_to or None)
            else:
                db_txs = None

            yield _ndjson({"type": "stage",
                           "text": f"DeepSeek 识别字段（{len(bank_raw.headers)} 列，展示思考过程）…"})
            column_map = None
            async for ev in stream_map_bank_columns(bank_raw.headers, sample_rows(bank_raw),
                                                    key, LLM_MODEL, LLM_BASE_URL):
                if ev["type"] == "thinking":
                    yield _ndjson({"type": "thinking", "text": ev["text"]})
                elif ev["type"] == "mapping":
                    column_map = ev["mapping"]
                    yield _ndjson({"type": "mapping", "mapping": column_map})
            if not column_map:
                yield _ndjson({"type": "error", "message": "字段识别失败"})
                return

            bank_txs = build_transactions(bank_raw, column_map, "bank")
            yield _ndjson({"type": "stage",
                           "text": f"字段识别完成，银行流水 {len(bank_txs)} 笔，逐笔匹配与月度核对…"})

            if db_txs is None:
                db_raw = read_excel(db_path)
                db_txs = build_transactions(db_raw, DB_COLUMN_MAP, "db")

            result = run_matching(bank_txs, db_txs)
            rid = uuid.uuid4().hex
            RESULTS[rid] = result
            yield _ndjson({
                "type": "done",
                "id": rid,
                "summary": result.summary,
                "matched_count": len(result.match_result.matched),
            })
        except Exception as e:
            yield _ndjson({"type": "error", "message": f"对比失败: {e}"})

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.get("/api/companies")
async def companies():
    try:
        return {"companies": list_companies()}
    except Exception as e:
        return {"error": f"数据库读取失败: {e}"}


@app.get("/api/bank_accounts")
async def bank_accounts(org: str = ""):
    try:
        return {"accounts": list_bank_accounts(org=org or None)}
    except Exception as e:
        return {"error": f"数据库读取失败: {e}"}


@app.get("/api/years")
async def years(book: str = "", accasoa: str = ""):
    try:
        return {"years": list_years(book=book or None, accasoa=accasoa or None)}
    except Exception as e:
        return {"error": f"数据库读取失败: {e}"}


@app.get("/api/statement")
async def statement(f11: str = "", book: str = "", accasoa: str = "", year: str = "",
                    month: str = "", month_to: str = ""):
    try:
        return fetch_statement(f11=f11 or None, book=book or None, accasoa=accasoa or None,
                               year=year or None, month=month or None, month_to=month_to or None)
    except Exception as e:
        return {"error": f"数据库读取失败: {e}"}


@app.get("/api/result/{rid}/excel")
async def download(rid: str):
    result = RESULTS.get(rid)
    if result is None:
        return {"error": "not found"}
    out = os.path.join(tempfile.mkdtemp(), "对账结果.xlsx")
    write_result_excel(result.match_result, result.monthly_diffs, result.bank_txs, result.db_txs, out)
    return FileResponse(out, filename="对账结果.xlsx")


app.mount("/", StaticFiles(directory="web", html=True), name="web")
