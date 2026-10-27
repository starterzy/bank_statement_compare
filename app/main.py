import asyncio
import json
import os
import tempfile
import uuid
from decimal import Decimal
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, Header, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auth import (User, UserStore, create_session, current_user, destroy_session,
                   ensure_seed, require_admin, set_password, verify_password)
from .config import DB_COLUMN_MAP, DEFAULT_MODEL_ID, LLM_MODELS, get_model
from .db.oracle import (fetch_bank_detail, fetch_org_tree, fetch_statement, find_accounts_by_code,
                        list_bank_accounts, list_companies, list_years, load_env)
from .llm.client import (analyze_statement, analyze_statement_dashscope, analyze_statement_openai,
                         extract_account_no, map_bank_columns, map_bank_columns_dashscope,
                         map_bank_columns_openai, orient_images, stream_analyze_statement,
                         stream_map_bank_columns, stream_map_bank_columns_dashscope,
                         stream_map_bank_columns_openai, stream_map_bank_image_dashscope,
                         stream_map_bank_image_openai, stream_map_bank_images)
from .parsing.column_mapper import build_transactions, build_transactions_from_rows
from .parsing.excel_reader import (extract_account_from_table, read_excel, read_grid, read_table,
                                   sample_rows)
from .parsing.pdf import render_pdf_pages
from .parsing.statement import StatementAnalysis, build_from_analysis
from .pipeline import CompareResult, run_compare, run_compare_with_db, run_matching
from .reporting.excel_writer import write_result_excel
from .reporting.summary import build_detail_rows

app = FastAPI(title="银行流水对账")
RESULTS = {}
ensure_seed(UserStore())


def _ndjson(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"


def _resolve_api_key(cfg: dict, api_key: str = "") -> str:
    """字段识别用的 LLM key：表单 > 该模型声明的环境变量/.env > 通用 Anthropic 环境变量。"""
    env_name = cfg.get("api_key_env") or ""
    val = (api_key
           or os.environ.get(env_name)
           or load_env().get(env_name)
           or "")
    if not val and cfg.get("protocol") == "anthropic":
        val = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or ""
    return val


def _make_bank_mapper(cfg: dict, api_key: str):
    model = cfg["model"]
    base_url = cfg["base_url"]
    if cfg.get("protocol") == "openai":
        fn = map_bank_columns_openai
    elif cfg.get("protocol") == "dashscope":
        fn = map_bank_columns_dashscope
    else:
        fn = map_bank_columns

    def mapper(headers, samples):
        return fn(headers, samples, api_key, model, base_url)
    return mapper


def _analyze_grid(cfg: dict, key: str, grid: List[List[str]]) -> Optional[StatementAnalysis]:
    """整表分析（同步）：表头行 + 字段列号 + 本方账号；失败返回 None 交给调用方兜底。"""
    ncols = max((len(r) for r in grid), default=0)
    preview = grid[:30]
    protocol = cfg.get("protocol")
    try:
        if protocol == "openai":
            d = analyze_statement_openai(preview, ncols, key, cfg["model"], cfg["base_url"])
        elif protocol == "dashscope":
            d = analyze_statement_dashscope(preview, ncols, key, cfg["model"], cfg["base_url"])
        else:
            d = analyze_statement(preview, ncols, key, cfg["model"], cfg["base_url"])
    except Exception:
        return None
    return StatementAnalysis.from_dict(d)


def _make_bank_parser(cfg: dict, key: str):
    """非流式接口用的对账单解析器：原始网格 → 模型分析 → 流水。"""
    def parse(path: str):
        grid = read_grid(path)
        analysis = _analyze_grid(cfg, key, grid)
        if analysis is None:
            raise RuntimeError("对账单结构分析失败")
        txs = build_from_analysis(grid, analysis)
        if not txs:
            raise RuntimeError("模型给出的表头/字段无法解析出流水")
        return txs
    return parse


def _scope_error(user: User, book: str) -> Optional[str]:
    """非管理员只能访问其可见公司对应的账簿；返回错误信息或 None。"""
    if user.is_admin:
        return None
    if not book:
        return "无权访问：未指定账簿"
    visible = list_companies(org_roots=user.org_roots)
    if book not in {c["book"] for c in visible}:
        return "无权访问该公司的账簿"
    return None


# ---------- 登录 / 用户管理 ----------

class LoginBody(BaseModel):
    username: str
    password: str


class UserBody(BaseModel):
    username: str
    password: str = ""  # 为空表示编辑时不改密码
    display_name: str = ""
    is_admin: bool = False
    org_roots: list = []


@app.post("/api/login")
async def login(body: LoginBody):
    store = UserStore()
    user = store.get(body.username)
    if user is None or not verify_password(user, body.password):
        return {"error": "用户名或密码错误"}
    return {"token": create_session(user.username), "user": user.to_dict()}


@app.post("/api/logout")
async def logout(user: User = Depends(current_user), authorization: Optional[str] = Header(None)):
    destroy_session((authorization or "").removeprefix("Bearer ").strip())
    return {"ok": True}


@app.get("/api/me")
async def me(user: User = Depends(current_user)):
    return {"user": user.to_dict()}


@app.get("/api/org_tree")
async def org_tree(_: User = Depends(require_admin)):
    try:
        return fetch_org_tree()
    except Exception as e:
        return {"error": f"数据库读取失败: {e}"}


@app.get("/api/users")
async def list_users(_: User = Depends(require_admin)):
    return {"users": [u.to_dict() for u in UserStore().list()]}


@app.post("/api/users")
async def create_user(body: UserBody, _: User = Depends(require_admin)):
    store = UserStore()
    if not body.username:
        return {"error": "用户名不能为空"}
    if store.get(body.username):
        return {"error": "用户名已存在"}
    if not body.password:
        return {"error": "请设置密码"}
    u = User(username=body.username, display_name=body.display_name,
             is_admin=body.is_admin, org_roots=body.org_roots)
    set_password(u, body.password)
    store.upsert(u)
    return {"user": u.to_dict()}


@app.put("/api/users/{username}")
async def update_user(username: str, body: UserBody, _: User = Depends(require_admin)):
    store = UserStore()
    u = store.get(username)
    if u is None:
        return {"error": "用户不存在"}
    u.display_name = body.display_name
    u.is_admin = body.is_admin
    u.org_roots = body.org_roots
    if body.password:
        set_password(u, body.password)
    store.upsert(u)
    return {"user": u.to_dict()}


@app.delete("/api/users/{username}")
async def delete_user(username: str, actor: User = Depends(require_admin)):
    if username == actor.username:
        return {"error": "不能删除当前登录用户"}
    store = UserStore()
    target = store.get(username)
    if target is None:
        return {"error": "用户不存在"}
    if target.is_admin and not any(u.is_admin and u.username != username for u in store.list()):
        return {"error": "不能删除最后一个管理员"}
    store.delete(username)
    return {"ok": True}


# ---------- 对账 ----------

@app.get("/api/models")
async def list_models(user: User = Depends(current_user)):
    return {"models": [{"id": m["id"], "label": m["label"]} for m in LLM_MODELS],
            "default": DEFAULT_MODEL_ID}


@app.post("/api/compare")
async def compare(bank: UploadFile = File(...), db: UploadFile = File(None),
                  api_key: str = Form(""), db_source: str = Form("database"),
                  account: str = Form(""), book: str = Form(""), accasoa: str = Form(""),
                  year: str = Form(""), month: str = Form(""), month_to: str = Form(""),
                  model: str = Form(""), user: User = Depends(current_user)):
    model_cfg = get_model(model or DEFAULT_MODEL_ID)
    key = _resolve_api_key(model_cfg, api_key)
    if not key:
        return {"error": f"缺少 LLM API key（{model_cfg['label']}）"}
    if db_source == "database":
        err = _scope_error(user, book)
        if err:
            return {"error": err}
    tmp = tempfile.mkdtemp()
    bank_path = os.path.join(tmp, bank.filename or "bank.xls")
    with open(bank_path, "wb") as f:
        f.write(await bank.read())

    try:
        mapper = _make_bank_mapper(model_cfg, key)
        parser = _make_bank_parser(model_cfg, key)
        if db_source == "database":
            db_txs = fetch_bank_detail(f11=account or None, book=book or None,
                                       accasoa=accasoa or None, year=year or None,
                                       month=month or None, month_to=month_to or None)
            result = run_compare_with_db(bank_path, db_txs, mapper, bank_parser=parser)
        else:
            if db is None or db.filename is None:
                return {"error": "缺少数据库流水文件"}
            db_path = os.path.join(tmp, db.filename)
            with open(db_path, "wb") as f:
                f.write(await db.read())
            result = run_compare(bank_path, db_path, mapper, DB_COLUMN_MAP, bank_parser=parser)
    except Exception as e:
        return {"error": f"对比失败: {e}"}

    rid = uuid.uuid4().hex
    RESULTS[rid] = result
    return {"id": rid, "summary": result.summary, "matched_count": len(result.match_result.matched),
            "detail": build_detail_rows(result.match_result)}


@app.post("/api/compare/stream")
async def compare_stream(banks: List[UploadFile] = File(...), db: UploadFile = File(None),
                         db_source: str = Form("database"), account: str = Form(""),
                         book: str = Form(""), accasoa: str = Form(""),
                         year: str = Form(""), month: str = Form(""), month_to: str = Form(""),
                         model: str = Form(""), user: User = Depends(current_user)):
    """流式对比：NDJSON 逐条推送 stage / thinking / mapping / done / error 事件。"""
    model_cfg = get_model(model or DEFAULT_MODEL_ID)
    key = _resolve_api_key(model_cfg)
    if not key:
        return {"error": f"缺少 LLM API key（{model_cfg['label']}）"}
    llm_label = model_cfg["label"]
    llm_model = model_cfg["model"]
    llm_base_url = model_cfg["base_url"]
    protocol = model_cfg.get("protocol")
    is_openai = protocol == "openai"
    is_dashscope = protocol == "dashscope"
    auto_mode = (db_source == "database" and not account and not book and not accasoa
                 and not year and not month)
    if db_source == "database" and not auto_mode:
        err = _scope_error(user, book)
        if err:
            return {"error": err}

    tmp = tempfile.mkdtemp()
    _IMAGE_MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".webp": "image/webp", ".bmp": "image/bmp"}
    image_files = []   # [(bytes, media_type)]，按选择顺序
    bank_path = None   # 单个 Excel 的临时路径
    for bf in banks:
        name = bf.filename or ""
        data = await bf.read()
        ext = os.path.splitext(name)[1].lower()
        if ext == ".pdf":
            try:
                pages = render_pdf_pages(data)
            except Exception as e:
                return {"error": f"PDF 解析失败: {e}"}
            image_files.extend((p, "image/png") for p in pages)
        elif ext in _IMAGE_MEDIA:
            image_files.append((data, _IMAGE_MEDIA[ext]))
        else:
            if bank_path is not None:
                return {"error": "银行对账单仅支持：多张截图 / 一个 PDF / 单个 Excel 文件，且不能混用"}
            bank_path = os.path.join(tmp, name or "bank.xls")
            with open(bank_path, "wb") as f:
                f.write(data)

    if image_files and bank_path is not None:
        return {"error": "截图/PDF 与 Excel 不能混用，请分开对比"}
    if not image_files and bank_path is None:
        return {"error": "缺少银行对账单文件"}
    bank_is_image = bool(image_files)

    db_path = None
    if db_source != "database":
        if db is None or db.filename is None:
            return {"error": "缺少数据库流水文件"}
        db_path = os.path.join(tmp, db.filename)
        with open(db_path, "wb") as f:
            f.write(await db.read())

    async def gen():
        try:
            # ---- 阶段一：识别银行对账单 ----
            bank_txs = None
            account_info = None   # auto 模式：{"account_no", "account_name"}
            # 局部副本：auto 模式会在内部改写，避免污染外层闭包变量（否则 Python 视作局部变量）。
            imgs = image_files
            f11 = account or None
            bk = book or None
            acc = accasoa or None
            yr = year or None
            mo = month or None
            mo_to = month_to or None
            if bank_is_image:
                # 方向校正：用 flash 逐页判断旋转角度并转正（并发）。
                flash_cfg = get_model("deepseek-flash")
                flash_key = _resolve_api_key(flash_cfg)
                if not flash_key:
                    yield _ndjson({"type": "error",
                                   "message": f"缺少方向判断用模型 key（{flash_cfg['label']}）"})
                    return
                yield _ndjson({"type": "stage",
                               "text": f"方向校正（{flash_cfg['label']}，共 {len(imgs)} 页）…"})
                oriented = imgs
                async for ev in orient_images(imgs, flash_key, flash_cfg["model"],
                                              flash_cfg["base_url"]):
                    if ev["type"] == "stage":
                        yield _ndjson({"type": "stage", "text": ev["text"]})
                    elif ev["type"] == "oriented":
                        oriented = ev["images"]
                imgs = oriented

                if auto_mode:
                    yield _ndjson({"type": "stage",
                                   "text": f"{flash_cfg['label']} 识别对账单账号与户名…"})
                    account_info = await extract_account_no(imgs[0][0], imgs[0][1],
                                                            flash_key, flash_cfg["model"],
                                                            flash_cfg["base_url"])

                yield _ndjson({"type": "stage",
                               "text": f"{llm_label} 识别银行对账单图片（共 {len(imgs)} 张）…"})
                rows = None
                image_fn = (stream_map_bank_image_openai if is_openai
                            else stream_map_bank_image_dashscope if is_dashscope else None)
                async for ev in stream_map_bank_images(imgs, key, llm_model, llm_base_url,
                                                       image_stream_fn=image_fn):
                    if ev["type"] == "stage":
                        yield _ndjson({"type": "stage", "text": ev["text"]})
                    elif ev["type"] == "image_rows":
                        rows = ev["rows"]
                if rows is None:
                    yield _ndjson({"type": "error", "message": "图片识别失败"})
                    return
                bank_txs = build_transactions_from_rows(rows, "bank")
            else:
                # 任意表格格式（xls/xlsx/csv/txt）：先读成原始网格，再让模型整表分析
                # （表头行、字段列号、本方账号一次问清），不再依赖固定表头/固定格式。
                yield _ndjson({"type": "stage", "text": "读取银行对账单…"})
                grid = read_grid(bank_path)
                if not grid:
                    yield _ndjson({"type": "error", "message": "银行对账单为空或无法读取"})
                    return
                ncols = max((len(r) for r in grid), default=0)
                yield _ndjson({"type": "stage",
                               "text": f"{llm_label} 分析表格结构（{len(grid)} 行 × {ncols} 列："
                                       f"表头 / 字段 / 本方账号，展示思考过程）…"})
                analysis_dict = None
                if is_openai or is_dashscope:
                    ana_fn = analyze_statement_openai if is_openai else analyze_statement_dashscope
                    try:
                        analysis_dict = await asyncio.to_thread(
                            ana_fn, grid[:30], ncols, key, llm_model, llm_base_url)
                    except Exception:
                        analysis_dict = None
                else:
                    async for ev in stream_analyze_statement(grid[:30], ncols, key, llm_model, llm_base_url):
                        if ev["type"] == "thinking":
                            yield _ndjson({"type": "thinking", "text": ev["text"]})
                        elif ev["type"] == "analysis":
                            analysis_dict = ev["analysis"]
                analysis = StatementAnalysis.from_dict(analysis_dict) if analysis_dict else None
                bank_txs = build_from_analysis(grid, analysis) if analysis else []

                if bank_txs:
                    if analysis.account_no or analysis.account_name:
                        hint = f"（依据：{analysis.evidence}）" if analysis.evidence else ""
                        yield _ndjson({"type": "stage",
                                       "text": f"识别到本方账号：{analysis.account_no or '—'} / "
                                               f"{analysis.account_name or '—'}{hint}"})
                    if auto_mode:
                        account_info = {"account_no": analysis.account_no,
                                        "account_name": analysis.account_name}
                else:
                    # 兜底：模型分析不可用时回到「启发式表头 + 字段映射提示词」
                    yield _ndjson({"type": "stage", "text": "模型分析未得出可用流水，改用表头启发式识别…"})
                    bank_raw = read_table(bank_path)
                    if not bank_raw.headers:
                        yield _ndjson({"type": "error", "message": "银行对账单为空或无法识别表头"})
                        return
                    if auto_mode:
                        account_info = extract_account_from_table(bank_raw)

                    yield _ndjson({"type": "stage",
                                   "text": f"{llm_label} 识别字段（{len(bank_raw.headers)} 列）…"})
                    column_map = None
                    if is_openai or is_dashscope:
                        col_fn = stream_map_bank_columns_openai if is_openai else stream_map_bank_columns_dashscope
                        async for ev in col_fn(bank_raw.headers, sample_rows(bank_raw),
                                               key, llm_model, llm_base_url):
                            if ev["type"] == "mapping":
                                column_map = ev["mapping"]
                                yield _ndjson({"type": "mapping", "mapping": column_map})
                    else:
                        async for ev in stream_map_bank_columns(bank_raw.headers, sample_rows(bank_raw),
                                                                key, llm_model, llm_base_url):
                            if ev["type"] == "thinking":
                                yield _ndjson({"type": "thinking", "text": ev["text"]})
                            elif ev["type"] == "mapping":
                                column_map = ev["mapping"]
                                yield _ndjson({"type": "mapping", "mapping": column_map})
                    if not column_map:
                        yield _ndjson({"type": "error", "message": "字段识别失败"})
                        return

                    bank_txs = build_transactions(bank_raw, column_map, "bank")

            # ---- 阶段二：解析数据库侧（auto 模式先反查账户 + 自动月份） ----
            db_monthly_balances = None
            if db_source == "database":
                if auto_mode:
                    code = (account_info or {}).get("account_no") or ""
                    if not code:
                        yield _ndjson({"type": "error",
                                       "message": "未能从对账单识别到本方银行账号（对账单中没有本方账号信息）；"
                                                  "请在上方手动选择公司/账户后重试，或改用「上传文件」模式"})
                        return
                    yield _ndjson({"type": "stage", "text": f"按账号 {code} 反查账户…"})
                    if user.is_admin:
                        cands = find_accounts_by_code(code)
                        if not cands:
                            yield _ndjson({"type": "error",
                                           "message": f"系统中未找到账号 {code} 对应的银行账户"})
                            return
                    else:
                        global_cands = find_accounts_by_code(code)
                        if not global_cands:
                            yield _ndjson({"type": "error",
                                           "message": f"系统中未找到账号 {code} 对应的银行账户"})
                            return
                        cands = find_accounts_by_code(code, org_roots=user.org_roots)
                        if not cands:
                            yield _ndjson({"type": "error",
                                           "message": f"无权访问账号 {code} 对应的银行账户（不在你的可见公司范围内）"})
                            return
                    months = sorted({t.month for t in bank_txs})
                    if not months:
                        yield _ndjson({"type": "error", "message": "未能从对账单识别到交易月份"})
                        return
                    if len(cands) > 1:
                        yield _ndjson({"type": "choose_account",
                                       "account_no": code,
                                       "account_name": (account_info or {}).get("account_name"),
                                       "months": months,
                                       "candidates": cands})
                        return
                    c = cands[0]
                    f11, bk, acc = c["f11"], c["book"], c["accasoa"]
                    yr = months[0][:4]
                    if len(months) == 1:
                        mo, mo_to = months[0][5:7], None
                    else:
                        mo, mo_to = None, months[-1][5:7]
                    period_txt = months[0] if len(months) == 1 else f"{months[0]} ~ {months[-1]}"
                    yield _ndjson({"type": "stage",
                                   "text": f"命中账户：{c['org_name']} / {c['name']}，账期 {period_txt}…"})
                    yield _ndjson({"type": "account_resolved",
                                   "org": c["org"], "org_name": c["org_name"],
                                   "f11": f11, "account_name": c["name"], "account_code": c["code"],
                                   "year": yr, "month": mo or "", "month_to": mo_to or "",
                                   "months": months})

                yield _ndjson({"type": "stage", "text": "查询数据库银行流水…"})
                db_txs = fetch_bank_detail(f11=f11, book=bk,
                                           accasoa=acc, year=yr,
                                           month=mo, month_to=mo_to)
                # 权威月余额表（期初/期末），用于对比月度期初额与期末额。
                stmt = fetch_statement(f11=f11, book=bk,
                                       accasoa=acc, year=yr,
                                       month=mo, month_to=mo_to)
                db_monthly_balances = {
                    m["month"]: {"opening": Decimal(m["opening"]), "closing": Decimal(m["balance"])}
                    for m in stmt.get("monthly", [])
                }
            else:
                db_txs = None

            if db_txs is None:
                db_raw = read_excel(db_path)
                db_txs = build_transactions(db_raw, DB_COLUMN_MAP, "db")

            yield _ndjson({"type": "stage",
                           "text": f"银行流水 {len(bank_txs)} 笔，逐笔匹配与月度核对…"})
            result = run_matching(bank_txs, db_txs, db_monthly_balances=db_monthly_balances)
            rid = uuid.uuid4().hex
            RESULTS[rid] = result
            yield _ndjson({
                "type": "done",
                "id": rid,
                "summary": result.summary,
                "matched_count": len(result.match_result.matched),
                "detail": build_detail_rows(result.match_result),
            })
        except Exception as e:
            yield _ndjson({"type": "error", "message": f"对比失败: {e}"})

    return StreamingResponse(gen(), media_type="application/x-ndjson")


# ---------- 查询 ----------

@app.get("/api/companies")
async def companies(user: User = Depends(current_user)):
    try:
        roots = None if user.is_admin else user.org_roots
        return {"companies": list_companies(org_roots=roots)}
    except Exception as e:
        return {"error": f"数据库读取失败: {e}"}


@app.get("/api/bank_accounts")
async def bank_accounts(org: str = "", user: User = Depends(current_user)):
    try:
        return {"accounts": list_bank_accounts(org=org or None)}
    except Exception as e:
        return {"error": f"数据库读取失败: {e}"}


@app.get("/api/years")
async def years(book: str = "", accasoa: str = "", user: User = Depends(current_user)):
    try:
        return {"years": list_years(book=book or None, accasoa=accasoa or None)}
    except Exception as e:
        return {"error": f"数据库读取失败: {e}"}


@app.get("/api/statement")
async def statement(f11: str = "", book: str = "", accasoa: str = "", year: str = "",
                    month: str = "", month_to: str = "", user: User = Depends(current_user)):
    err = _scope_error(user, book)
    if err:
        return {"error": err}
    try:
        return fetch_statement(f11=f11 or None, book=book or None, accasoa=accasoa or None,
                               year=year or None, month=month or None, month_to=month_to or None)
    except Exception as e:
        return {"error": f"数据库读取失败: {e}"}


@app.get("/api/result/{rid}/excel")
async def download(rid: str, user: User = Depends(current_user)):
    result = RESULTS.get(rid)
    if result is None:
        return {"error": "not found"}
    out = os.path.join(tempfile.mkdtemp(), "对账结果.xlsx")
    write_result_excel(result.match_result, result.monthly_diffs, result.bank_txs, result.db_txs, out)
    return FileResponse(out, filename="对账结果.xlsx")


app.mount("/", StaticFiles(directory="web", html=True), name="web")
