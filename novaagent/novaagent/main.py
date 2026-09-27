"""NovaAgent FastAPI 入口:认证 / 知识库管理 / 检索增强对话 / 周报"""
from __future__ import annotations

import io
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config, db, llm, rag
from .agent import AgentService
from .config import ROLE_RANK, ROLE_ZH, configured

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
security = HTTPBearer(auto_error=False)
agent = AgentService()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    missing = configured()
    if missing:
        raise RuntimeError(f"缺少配置项: {missing}(检查 novaagent/.env)")
    db.connect()
    await agent.start()
    logger.info("NovaAgent started")
    yield
    await agent.stop()


app = FastAPI(title="NovaAgent", lifespan=lifespan)


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(security)):
    if cred is None:
        raise HTTPException(401, "未登录")
    user = db.user_by_token(cred.credentials)
    if user is None:
        raise HTTPException(401, "登录已失效,请重新登录")
    return user


def require_role(min_role: str):
    def checker(user=Depends(current_user)):
        if ROLE_RANK[user["role"]] < ROLE_RANK[min_role]:
            raise HTTPException(403, f"该操作需要 {ROLE_ZH[min_role]} 及以上权限")
        return user
    return checker


# ---------- 认证 ----------

@app.post("/api/login")
async def login(body: dict):
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    user = db.verify_user(username, password)
    if user is None:
        raise HTTPException(401, "用户名或密码错误")
    token = db.create_session(user["id"])
    return {"token": token, "username": user["username"], "role": user["role"], "role_zh": ROLE_ZH[user["role"]]}


@app.get("/api/me")
async def me(user=Depends(current_user)):
    return {"username": user["username"], "role": user["role"], "role_zh": ROLE_ZH[user["role"]]}


# ---------- 个人设置(模型选择 / 自定义 API) ----------

@app.get("/api/me/settings")
async def get_settings(user=Depends(current_user)):
    s = db.get_user_settings(user["id"])
    eff = agent.effective_llm(user["id"])
    return {
        "model": s["model"] or config.LLM_MODEL,
        "candidates": config.MODEL_CANDIDATES,
        "custom": {
            "enabled": bool(s["custom_model"] and s["llm_base_url"] and s["llm_api_key"]),
            "model": s["custom_model"],
            "base_url": s["llm_base_url"],
            "api_key_set": bool(s["llm_api_key"]),
        },
        "effective_model": eff["model"],
        "username": user["username"], "role": user["role"], "role_zh": ROLE_ZH[user["role"]],
    }


@app.put("/api/me/settings")
async def put_settings(body: dict, user=Depends(current_user)):
    custom = body.get("custom")
    if custom is not None:
        if not isinstance(custom, dict):
            raise HTTPException(400, "custom 格式错误")
        cm = (custom.get("model") or "").strip()
        bu = (custom.get("base_url") or "").strip().rstrip("/")
        ak = (custom.get("api_key") or "").strip()
        if cm or bu or ak:  # 任一填写即视为启用自定义
            if not (cm and bu and ak):
                raise HTTPException(400, "自定义 API 需同时填写模型名、Base URL 和 API Key")
            if not bu.startswith(("http://", "https://")):
                raise HTTPException(400, "Base URL 必须以 http(s):// 开头")
            db.set_user_settings(user["id"], custom_model=cm, llm_base_url=bu,
                                 llm_api_key=ak or db.get_user_settings(user["id"])["llm_api_key"])
        else:  # 全部留空 = 关闭自定义
            db.set_user_settings(user["id"], custom_model="", llm_base_url="")
        model = (body.get("model") or "").strip()
        if model and not custom:
            if model not in [m["id"] for m in config.MODEL_CANDIDATES]:
                raise HTTPException(400, "不支持的模型")
            db.set_user_settings(user["id"], model=model)
    else:
        model = (body.get("model") or "").strip()
        if not model or model not in [m["id"] for m in config.MODEL_CANDIDATES]:
            raise HTTPException(400, "不支持的模型")
        db.set_user_settings(user["id"], model=model)
    eff = agent.effective_llm(user["id"])
    return {"effective_model": eff["model"]}


@app.post("/api/me/settings/test")
async def test_settings(body: dict, user=Depends(current_user)):
    """测试模型连通性(内置候选或自定义 API)"""
    model = (body.get("model") or "").strip()
    base_url = (body.get("base_url") or "").strip().rstrip("/")
    api_key = (body.get("api_key") or "").strip()
    if base_url or api_key or model not in [m["id"] for m in config.MODEL_CANDIDATES]:
        if not (model and base_url and (api_key or db.get_user_settings(user["id"])["llm_api_key"])):
            raise HTTPException(400, "测试自定义 API 需要模型名、Base URL 和 API Key")
        api_key = api_key or db.get_user_settings(user["id"])["llm_api_key"]
    try:
        msg = await llm.chat(
            [{"role": "user", "content": "回复:ok"}],
            model=model or config.LLM_MODEL, base_url=base_url, api_key=api_key,
            max_tokens=8, temperature=0,
        )
        content = (msg.get("content") or "").strip()
        return {"ok": bool(content), "reply": content[:50] or "(空回复)"}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:120]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}


@app.get("/api/models")
async def list_models(user=Depends(current_user)):
    return {"models": config.MODEL_CANDIDATES, "current": agent.effective_llm(user["id"])["model"]}


# ---------- 知识库(辅导员/管理员可写,按角色可见) ----------

@app.post("/api/kb/upload")
async def kb_upload(
    file: UploadFile = File(...),
    role_min: str = Form("student"),
    category: str = Form("其他"),
    user=Depends(require_role("counselor")),
):
    if role_min not in ROLE_RANK:
        raise HTTPException(400, f"role_min 必须是 {list(ROLE_RANK)}")
    category = (category or "其他").strip()[:20] or "其他"
    raw = await file.read()
    name = file.filename or "untitled"
    suffix = Path(name).suffix.lower()
    if suffix in (".txt", ".md"):
        text = raw.decode("utf-8", errors="replace")
    elif suffix == ".pdf":
        from pypdf import PdfReader

        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
    elif suffix == ".docx":
        import docx

        text = "\n".join(p.text for p in docx.Document(io.BytesIO(raw)).paragraphs)
    else:
        raise HTTPException(400, "仅支持 .txt / .md / .pdf / .docx")
    if not text.strip():
        raise HTTPException(400, "未能从文件中提取到文本")
    chunks = rag.chunk_text(text)
    if not chunks:
        raise HTTPException(400, "切分结果为空")
    vectors = await rag.embed_texts(chunks)
    doc_id = db.insert_document(title=Path(name).stem, filename=name, role_min=role_min,
                                uploaded_by=user["username"], category=category)
    db.insert_chunks(doc_id, list(zip(range(len(chunks)), chunks, vectors)))
    eff = agent.effective_llm(user["id"])
    summary = await agent.summarize_document(Path(name).stem, chunks, eff["model"], eff["base_url"], eff["api_key"])
    db.update_document_summary(doc_id, summary)
    logger.info("ingested doc=%s chunks=%d role_min=%s category=%s by %s",
                name, len(chunks), role_min, category, user["username"])
    return {"doc_id": doc_id, "chunks": len(chunks), "role_min": role_min,
            "category": category, "summary": summary}


@app.post("/api/kb/import_url")
async def kb_import_url(body: dict, user=Depends(require_role("counselor"))):
    """导入网页:抓取 URL → 提取正文文本 → 与文件上传同一入库管线"""
    url = (body.get("url") or "").strip()
    role_min = body.get("role_min", "student")
    category = (body.get("category") or "其他").strip()[:20] or "其他"
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL 必须以 http(s):// 开头")
    async with httpx.AsyncClient(timeout=25, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 (NovaAgent/0.4; campus KB importer)"}) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(502, f"网页返回错误: HTTP {e.response.status_code}")
        except httpx.HTTPError as e:
            raise HTTPException(502, f"网页抓取失败: {str(e)[:120]}")
    ctype = resp.headers.get("content-type", "")
    if "html" not in ctype and "text" not in ctype and ctype:
        raise HTTPException(400, f"不支持的网页类型: {ctype.split(';')[0]}")
    if len(resp.content) > 3 * 1024 * 1024:
        raise HTTPException(400, "网页过大(>3MB)")
    text, title = extract_html(resp.text)
    if not text:
        raise HTTPException(400, "未能从网页中提取到文本")
    chunks = rag.chunk_text(text)
    if not chunks:
        raise HTTPException(400, "切分结果为空")
    vectors = await rag.embed_texts(chunks)
    doc_id = db.insert_document(title=title[:80], filename=url, role_min=role_min,
                                uploaded_by=user["username"], category=category)
    db.insert_chunks(doc_id, list(zip(range(len(chunks)), chunks, vectors)))
    eff = agent.effective_llm(user["id"])
    summary = await agent.summarize_document(title[:80], chunks, eff["model"], eff["base_url"], eff["api_key"])
    db.update_document_summary(doc_id, summary)
    logger.info("imported url=%s chunks=%d by %s", url, len(chunks), user["username"])
    return {"doc_id": doc_id, "title": title[:80], "chunks": len(chunks),
            "role_min": role_min, "category": category, "summary": summary}


def extract_html(html: str) -> tuple[str, str]:
    """stdlib HTMLParser 提取正文文本与 <title>(无第三方依赖)"""
    from html.parser import HTMLParser

    class _Extractor(HTMLParser):
        SKIP = {"script", "style", "noscript", "svg", "head"}

        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
            self.title = ""
            self._skip_depth = 0
            self._in_title = False

        def handle_starttag(self, tag, attrs):
            if tag in self.SKIP:
                self._skip_depth += 1
            if tag == "title":
                self._in_title = True
            if tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"):
                self.parts.append("\n")

        def handle_endtag(self, tag):
            if tag in self.SKIP and self._skip_depth:
                self._skip_depth -= 1
            if tag == "title":
                self._in_title = False

        def handle_data(self, data):
            if self._in_title:
                self.title += data
            elif not self._skip_depth and data.strip():
                self.parts.append(data)

    ex = _Extractor()
    ex.feed(html)
    lines = [ln.strip() for ln in "".join(ex.parts).split("\n")]
    text = "\n".join(ln for ln in lines if ln)
    return text, (ex.title.strip() or "未命名网页")


@app.get("/api/kb/documents")
async def kb_documents(category: str = "", user=Depends(current_user)):
    rank = ROLE_RANK[user["role"]]
    return {"documents": db.list_documents(rank, category), "categories": db.list_categories(rank)}


@app.get("/api/kb/documents/{doc_id}/chunks")
async def kb_chunks(doc_id: int, user=Depends(current_user)):
    doc = db.get_document(doc_id, ROLE_RANK[user["role"]])
    if doc is None:
        raise HTTPException(404, "文档不存在或无权查看")
    return {"document": doc, "chunks": db.get_chunks(doc_id)}


@app.delete("/api/kb/documents/{doc_id}")
async def kb_delete(doc_id: int, user=Depends(require_role("counselor"))):
    if db.get_document(doc_id, ROLE_RANK[user["role"]]) is None:
        raise HTTPException(404, "文档不存在或无权删除")
    db.delete_document(doc_id)
    return {"deleted": True}


# ---------- 对话 ----------

@app.post("/api/chat")
async def chat(body: dict, user=Depends(current_user)):
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "question 不能为空")
    d = await agent.chat_for(user["id"], user["username"], user["role"], question)
    db.add_message(user["id"], "user", question)
    db.add_message(user["id"], "assistant", d.get("answer", ""))
    return d


@app.post("/api/chat/stream")
async def chat_stream(body: dict, user=Depends(current_user)):
    """T8: 流式对话(SSE)。事件序列: sources → delta* → tools? → done → [DONE]。"""
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "question 不能为空")

    async def gen():
        answer_parts: list[str] = []
        try:
            async for ev in agent.chat_stream_for(user["id"], user["username"], user["role"], question):
                if ev["type"] == "delta":
                    answer_parts.append(ev["content"])
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            db.add_message(user["id"], "user", question)
            db.add_message(user["id"], "assistant", "".join(answer_parts))
        except Exception as e:  # 流中途异常:通知前端(已渲染增量保留,不落库)
            logger.exception("stream error")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)[:200]}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/conversations")
async def conversations(limit: int = 50, user=Depends(current_user)):
    """T9: 当前用户会话历史(按用户隔离,时间正序)。"""
    return {"messages": db.get_messages(user["id"], limit)}


# ---------- 周报(辅导员/管理员) ----------

@app.post("/api/weekly/expand")
async def weekly_expand(body: dict, user=Depends(require_role("counselor"))):
    """AI 扩充:简短笔记 → 规范工作记录草稿(不落库,人工确认后保存)"""
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(400, "content 不能为空")
    eff = agent.effective_llm(user["id"])
    expanded = await agent.expand_fragment(content, body.get("category", "其他"),
                                           eff["model"], eff["base_url"], eff["api_key"])
    if not expanded:
        raise HTTPException(502, "扩充结果为空,请重试或直接保存原文")
    return {"expanded": expanded, "original": content}

@app.post("/api/weekly/fragments")
async def weekly_add(body: dict, user=Depends(require_role("counselor"))):
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(400, "content 不能为空")
    return await agent.weekly_add(content, body.get("category", "其他"), body.get("occurred_at", ""))


@app.get("/api/weekly/fragments")
async def weekly_list(
    category: str = "", start_date: str = "", end_date: str = "",
    user=Depends(require_role("counselor")),
):
    from collections import Counter

    d = await agent.weekly_list(start_date, end_date)
    if not d.get("ok"):
        raise HTTPException(502, d.get("error", "周报服务不可用"))
    all_frags = d.get("fragments", [])
    frags = [f for f in all_frags if not category or f["category"] == category]
    return {"fragments": frags, "stats": dict(Counter(f["category"] for f in all_frags))}


@app.delete("/api/weekly/fragments/{fragment_id}")
async def weekly_delete(fragment_id: int, user=Depends(require_role("counselor"))):
    d = await agent.weekly_delete(fragment_id)
    if not d.get("ok"):
        raise HTTPException(404, d.get("error", "删除失败"))
    return d


@app.get("/api/weekly/reports")
async def weekly_reports(user=Depends(require_role("counselor"))):
    d = await agent.weekly_reports()
    if not d.get("ok"):
        raise HTTPException(502, d.get("error", "周报服务不可用"))
    return d


@app.get("/api/weekly/reports/{report_id}")
async def weekly_report_detail(report_id: int, user=Depends(require_role("counselor"))):
    d = await agent.weekly_report_detail(report_id)
    if not d.get("ok"):
        raise HTTPException(404, d.get("error", "周报不存在"))
    return d


@app.post("/api/weekly/report")
async def weekly_report(body: dict, user=Depends(require_role("counselor"))):
    return await agent.weekly_render(body.get("start_date", ""), body.get("end_date", ""))


@app.post("/api/weekly/archive")
async def weekly_archive(body: dict, user=Depends(require_role("counselor"))):
    for k in ("title", "start_date", "end_date", "content_md"):
        if not body.get(k):
            raise HTTPException(400, f"{k} 不能为空")
    return await agent.weekly_archive(body["title"], body["start_date"], body["end_date"], body["content_md"])


# ---------- 其他 ----------

@app.get("/api/health")
async def health():
    return {"status": "ok", "weekly_mcp": agent.weekly.session is not None}


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")
