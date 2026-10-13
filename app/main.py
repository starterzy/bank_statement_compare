import os
import tempfile
import uuid

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import DB_COLUMN_MAP, LLM_BASE_URL, LLM_MODEL
from .db.oracle import fetch_bank_detail, fetch_statement, list_bank_accounts, list_companies, list_years, load_env
from .llm.client import map_bank_columns
from .pipeline import run_compare, run_compare_with_db
from .reporting.excel_writer import write_result_excel

app = FastAPI(title="银行流水对账")
RESULTS = {}


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
                  year: str = Form(""), month: str = Form("")):
    key = _resolve_api_key(api_key)
    if not key:
        return {"error": "缺少 DeepSeek API key"}
    tmp = tempfile.mkdtemp()
    bank_path = os.path.join(tmp, bank.filename or "bank.xls")
    with open(bank_path, "wb") as f:
        f.write(await bank.read())

    if db_source == "database":
        try:
            db_txs = fetch_bank_detail(f11=account or None, book=book or None,
                                       accasoa=accasoa or None, year=year or None,
                                       month=month or None)
        except Exception as e:
            return {"error": f"数据库读取失败: {e}"}
        result = run_compare_with_db(bank_path, db_txs, _make_bank_mapper(key, LLM_MODEL))
    else:
        if db is None or db.filename is None:
            return {"error": "缺少数据库流水文件"}
        db_path = os.path.join(tmp, db.filename)
        with open(db_path, "wb") as f:
            f.write(await db.read())
        result = run_compare(bank_path, db_path, _make_bank_mapper(key, LLM_MODEL), DB_COLUMN_MAP)

    rid = uuid.uuid4().hex
    RESULTS[rid] = result
    return {"id": rid, "summary": result.summary, "matched_count": len(result.match_result.matched)}


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
async def statement(f11: str = "", book: str = "", accasoa: str = "", year: str = "", month: str = ""):
    try:
        return fetch_statement(f11=f11 or None, book=book or None, accasoa=accasoa or None,
                               year=year or None, month=month or None)
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
