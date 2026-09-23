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
