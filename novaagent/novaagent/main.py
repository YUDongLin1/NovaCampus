"""NovaAgent FastAPI 入口:认证 / 知识库管理 / 检索增强对话 / 周报"""
from __future__ import annotations

import csv
import io
import json
import os
import logging
import re
from urllib.parse import quote, urlsplit
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config, db, llm, rag
from . import asr as asr_mod
from . import minutes as minutes_lib
from . import talk_summary
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

def _web_search_override(body: dict):
    """P4e M-B:单次请求覆盖。**键不存在 → None**(交回用户级/全局默认),显式 false 才强制关。"""
    v = body.get("web_search")
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _web_on(s: dict) -> bool:
    """用户设置 → 布尔(未设置过回落全局默认,默认关)。"""
    from . import config
    v = str(s.get("web_search_enabled") or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return config.WEB_SEARCH_ENABLED


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
        # P4e M-B: 当前联网开关状态(UI 要能看见当前是开还是关)
        "web_search_enabled": _web_on(s),
    }


@app.put("/api/me/settings")
async def put_settings(body: dict, user=Depends(current_user)):
    # P4e M-B: 用户级默认开关(与 custom/model 互斥无关,独立处理)
    if body.get("web_search") is not None:
        db.set_web_search_enabled(user["id"], body["web_search"])
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


def _rollback_ingest(doc_id: int | None, label: str, exc: BaseException) -> None:
    """P4f ⑩ / F3: 入库后处理(摘要)失败 → 删掉刚插入的 document 与 chunks。

    ⚠ 两条纪律:
      1. **回滚本身不得抛异常** —— 回滚失败只能记 error,绝不能把上游 LLM 的错误
         换成"回滚失败"的错,那会让排障时看不到真正的根因(429/400/超时);
      2. **doc_id 为 None 时不算失败** —— 那是"还没落库就炸了",本来就没脏。
    """
    if doc_id is None:
        return
    try:
        db.delete_document(doc_id)
    except Exception as de:  # noqa: BLE001
        logger.error("ingest rollback FAILED doc=%s label=%s err=%s: %s",
                     doc_id, label, type(de).__name__, de)
        return
    logger.warning("ingest rolled back doc=%s label=%s reason=%s: %s",
                   doc_id, label, type(exc).__name__, exc)


# ---------- 知识库(辅导员/管理员可写,按角色可见) ----------

@app.post("/api/kb/upload")
async def kb_upload(
    file: UploadFile = File(...),
    role_min: str = Form("student"),
    category: str = Form("其他"),
    folder_id: str = Form(""),
    audience: str = Form("common"),
    user=Depends(require_role("counselor")),
):
    if role_min not in ROLE_RANK:
        raise HTTPException(400, f"role_min 必须是 {list(ROLE_RANK)}")
    category = (category or "其他").strip()[:20] or "其他"
    # P4c C5: 上传即可标注文件夹与学段
    fid: int | None = None
    if str(folder_id).strip():
        try:
            fid = int(folder_id)
        except ValueError:
            raise HTTPException(400, "folder_id 必须是整数")
        _folder_visible_or_404(fid, user)  # 不可见 = 不存在(硬约束 1)
    if audience not in AUDIENCE_VALUES:
        raise HTTPException(400, f"audience 必须是 {list(AUDIENCE_VALUES)}")
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
    _gate_or_400("", Path(name).stem, text)  # P4a C4: 上传同走质量门(URL 类检查跳过)
    chunks = rag.chunk_text(text)
    if not chunks:
        raise HTTPException(400, "切分结果为空")
    vectors = await rag.embed_texts(chunks)
    doc_id = db.insert_document(title=Path(name).stem, filename=name, role_min=role_min,
                                uploaded_by=user["username"], category=category,
                                folder_id=fid, audience=audience)
    db.insert_chunks(doc_id, list(zip(range(len(chunks)), chunks, vectors)))
    eff = agent.effective_llm(user["id"])
    # P4f ⑩ / F3: 摘要失败 → **整条写入回滚**(旧行为:文档与分块已落库却返回 500)。
    # 实测代价(Qoder 第 5 回):三次失败的冒烟各往 KB 里留 3 篇孤儿文档(65/487 → 68/490),
    # 手工清了三轮 —— 「失败的上传」不该在知识库里留下任何痕迹。
    try:
        summary = await agent.summarize_document(
            Path(name).stem, chunks, eff["model"], eff["base_url"], eff["api_key"])
    except Exception as e:  # noqa: BLE001  上游 429/400/超时一律回滚,不静默留脏
        _rollback_ingest(doc_id, name, e)
        raise HTTPException(502, detail={"code": "summary_failed",
                                         "reason": "文档摘要生成失败,本次上传已整条回滚(未入库)",
                                         "hint": f"上游 LLM 返回错误: {str(e)[:160]}"})
    db.update_document_summary(doc_id, summary)
    logger.info("ingested doc=%s chunks=%d role_min=%s category=%s folder=%s audience=%s by %s",
                name, len(chunks), role_min, category, fid, audience, user["username"])
    return {"doc_id": doc_id, "chunks": len(chunks), "role_min": role_min,
            "category": category, "summary": summary, "folder_id": fid, "audience": audience}


@app.post("/api/kb/import_url")
async def kb_import_url(body: dict, request: Request, user=Depends(require_role("counselor"))):
    """导入网页:抓取 URL → 提取正文文本 → 与文件上传同一入库管线"""
    url = (body.get("url") or "").strip()
    role_min = body.get("role_min", "student")
    category = (body.get("category") or "其他").strip()[:20] or "其他"
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL 必须以 http(s):// 开头")
    # P4e M5 ②: 把**本次请求的 origin** 纳入禁抓判定 —— 「自家前端一律禁抓」
    # 不再依赖硬编码端口 8900(服务跑在 :8905 时同样禁抓自家前端)。
    _rt_origins = _runtime_deny_origins(request)
    # P4a C4: 抓取前先拦禁抓清单(名单/登录页/自家前端)——禁抓页不发起网络请求;
    # 其余质量项在抓取+提取后对真实正文执行
    if _deny_url_hit(url, _rt_origins):
        logger.warning("导入被质量门拦截: code=deny_url url=%s", url)
        raise HTTPException(400, detail={"code": "deny_url",
                                         "reason": "URL 命中禁抓清单(含学生姓名的名单页/登录页首页/自家前端)",
                                         "hint": "请粘贴具体文章页 URL;含学生姓名的公示/名单页一律禁止入库"})
    dup = db.find_document_by_url(url)
    if dup:
        raise HTTPException(400, detail={"code": "duplicate_url",
                                         "reason": f"该 URL 已入库(doc_id={dup['id']}《{dup['title']}》)",
                                         "hint": "同 URL 不重复入库;如需更新内容请先删除旧文档"})
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
    text, _stats = clean_body(text)  # P4a C6: 导航/页脚裁剪(fetch_public_pages 原型移植)
    _gate_or_400(url, title, text, _rt_origins)   # P4a C4: 质量门(登录页/短正文/口令/敏感/名单)
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


# ---------- P4a C4:导入质量门(kb_upload / kb_import_url 共用) ----------
# 原型:corpus/fetch_public_pages.py 的 gate()/DENY_URLS/clean_body()(C6 移植)。
# 口令检测必须覆盖多种措辞(P3b Review 实测教训):前端首页曾以 v0.3「密码均为 xxx123」
# 与 v0.5「admin/admin123 · counselor/…」两种措辞两度入库,只匹配单一措辞会漏。

DENY_URLS = [
    "https://hospital.swjtu.edu.cn/info/1013/5558.htm",  # 2025年度城乡居民医保已缴费人员名单公示(含学生姓名)
    "https://hospital.swjtu.edu.cn/info/1013/3988.htm",  # 2023级新生参保失败名单及处理方法(含学生姓名)
    "https://cwc.swjtu.edu.cn/",                          # 计财处首页=登录框(脏数据 id=109 来源)
    "http://127.0.0.1:8900/",                             # 自家前端(曾把演示口令写进库 id=22/120)
]

# P4e M5 ②:「自家前端禁抓」此前是**端口绑定**的 —— DENY_URLS 里写死了 8900,
# 服务一旦跑在别的端口(如冒烟常用的 :8905),`http://127.0.0.1:<port>/` 就不再命中
# 禁抓清单,会落到 index_page 判据被拒(code 由 deny_url 变 index_page)。
# **安全语义没破**(仍然被拒),但这条防线本意是"自家前端一律禁抓",不该依赖端口。
#
# 修法:**从请求自身的 origin 推导**运行时禁用 origin(而不是猜端口、也不是改测试)。
# 服务跑在哪个端口就禁哪个端口 —— 端口绑定问题从根上消失。
# 匹配范围只到 origin(协议+主机+端口)+ 路径根,不会误伤外部站点。
def _runtime_deny_origins(request) -> list[str]:
    """本次请求的 origin(如 http://127.0.0.1:8905/)——即"自家前端"可能出现的地址。

    ⚠ `request.url` 是 `starlette.datastructures.URL`,**不是 str**;
    直接 `u.scheme` 会抛 AttributeError。第一版我用 try/except 吞掉异常返回 [],
    结果**静默失效**(自己写的单测才发现:origins=[] → 判定不命中)。
    这正是「静默兜底」的反面教材:安全判定的兜底分支不能吞异常后照常放行。
    现显式转 str 并在失败时**记日志**。
    """
    try:
        u = str(request.url)          # URL 对象必须显式转字符串
        p = urlsplit(u)
        if not p.scheme or not p.netloc:
            logger.warning("运行时 origin 推导失败(url=%r),自家前端禁抓本次不生效", u)
            return []
        return [f"{p.scheme}://{p.netloc}/"]
    except Exception as e:            # 极端情况不因安全判定而 500,但必须留痕
        logger.warning("运行时 origin 推导异常(自家前端禁抓本次不生效): %s", e)
        return []


def _deny_url_hit(url: str, extra_origins: list[str] | None = None) -> bool:
    """URL 是否命中禁抓清单(静态清单 + 运行时 origin)。`main.py` 两处质量门共用,避免判据分叉。"""
    if url in DENY_URLS or any(u in url for u in DENY_URLS):
        return True
    return any(url.startswith(o) for o in (extra_origins or []))

LOGIN_FEATURES = ["浏览器版本过旧", "兼容性提示", "请输入验证码", "用户名", "登录密码", "忘记密码"]
MIN_EFFECTIVE_CHARS = 200

# 口令/演示凭据样式(每种措辞一条,均有单测)
PASSWORD_PATTERNS: list[tuple[str, str]] = [
    (r"(用户名|口令|密码|账号)\s*[/／]\s*(口令|密码|用户名|账号)", "用户名/口令斜杠式"),
    (r"演示账号|演示口令|默认口令", "演示账号/演示口令字样"),
    (r"(admin|counselor|student)123", "演示口令字面量(admin123/counselor123/student123)"),
    (r"密码(均为|都为|同为)", "「密码均为…」句式"),
]
RE_MOBILE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
# P4a-1 C2 实测修正:简版 \d{17}[\dXx] 会把 18 位业务编号(如保单号 PECD2016…)误判为
# 身份证,导致已入库语料 doc 115 无法通过重导;改为带出生日期合法性校验的版本
# (6 位地区+8 位合法出生日期+3 位顺序+校验位),与 evals/kb_doctor.py 保持一致。
RE_IDCARD = re.compile(
    r"(?<!\d)\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")

# P4a-1 C1:导航/索引页结构判据——长度门拦不住整站菜单(实测样本 1623 字全菜单)。
# 短行=≤12 字且不含句读与数字(纯菜单项);长行=>25 字且含句读(正文式句子)。
# 菜单短行占比 ≥50% 且正文长行 <15% 且总行数 ≥20(小样本防误伤)→ 判为索引页。
# 实测依据:docs/p4/evidence/sample_index_page.txt(81 行/短行 62%/长行 9 条)被拒;
# 6 篇已入库语料与 corpus/clean/policy+ops 全部放行(零误伤,报告见 docs/p4/evidence/)。
_INDEX_PUNCT = "、，。：；！？"
_INDEX_MIN_LINES = 20
_INDEX_SHORT_RATIO = 0.5
_INDEX_LONG_RATIO = 0.15


def index_page_stats(text: str) -> dict:
    """统计导航/索引页结构特征(纯函数,可单测)。"""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    short = long_ = 0
    for ln in lines:
        has_punct = any(ch in _INDEX_PUNCT for ch in ln)
        has_digit = any(ch.isdigit() for ch in ln)
        if len(ln) <= 12 and not has_punct and not has_digit:
            short += 1
        elif len(ln) > 25 and has_punct:
            long_ += 1
    total = len(lines)
    return {
        "total_lines": total,
        "short_lines": short,
        "long_lines": long_,
        "short_ratio": round(short / total, 4) if total else 0.0,
        "long_ratio": round(long_ / total, 4) if total else 0.0,
    }


def is_index_page(text: str) -> dict | None:
    """导航/索引页判定(纯函数)。命中返回统计 dict(供 reason 引用),否则 None。"""
    stats = index_page_stats(text)
    if (stats["total_lines"] >= _INDEX_MIN_LINES
            and stats["short_ratio"] >= _INDEX_SHORT_RATIO
            and stats["long_ratio"] < _INDEX_LONG_RATIO):
        return stats
    return None

# 正文起止与导航裁剪(fetch_public_pages.clean_body 移植;宁留噪声,不可丢正文)
_START_MARKS = [re.compile(r"^当前位置"), re.compile(r"^首页正文$"), re.compile(r"网站首页>")]
_END_MARKS = re.compile(r"^(地址：|通讯地址|Copyright|版权所有|蜀ICP|川公网安备|西南交通大学官方微信|西南交通大学官方微博)")
_NOISE_SUB = [(re.compile(r"admin点击：\[\]"), ""), (re.compile(r"^正文$"), ""), (re.compile(r"^首页$"), "")]
_NAV_WORDS = {
    "首页", "网站首页", "医院概况", "党的建设", "医院动态", "通知公告", "健康教育", "医疗保险",
    "健康管理", "红十字会", "联系我们", "学生医保", "教工医保", "报销须知", "机构设置", "部门概况",
    "现任领导", "工作人员", "工作动态", "办事指南", "户政业务", "车辆业务", "政审业务", "消防安全",
    "党建之家", "学习之家", "支部工作", "武装工作", "大学生征兵工作", "军训工作", "政策法规",
    "法律法规", "规章制度", "安全警示", "安全教育", "警示案例", "English", "公开制度", "公开年报",
    "公开事项", "公开目录", "公开指南", "监督投诉",
}


def clean_body(text: str) -> tuple[str, dict]:
    """裁掉整站导航/页脚,只留正文(fetch_public_pages 原型移植)。返回 (正文, 统计)。"""
    lines = text.split("\n")
    start = 0
    for i, ln in enumerate(lines):
        if any(m.search(ln) for m in _START_MARKS):
            start = i + 1
            break
    end = len(lines)
    for i in range(start, len(lines)):
        if _END_MARKS.search(lines[i]):
            end = i
            break
    kept, nav_drop = [], 0
    for ln in lines[start:end]:
        for pat, rep in _NOISE_SUB:
            ln = rep if pat.search(ln) else ln
        ln = ln.replace("\ufeff", "").strip()
        if not ln:
            continue
        if ln in _NAV_WORDS:
            nav_drop += 1
            continue
        kept.append(ln)
    return "\n".join(kept), {"dropped_nav": nav_drop, "cut_head": start, "cut_tail": len(lines) - end}


def quality_gate_reject(url: str, title: str, text: str,
                        runtime_origins: list[str] | None = None) -> dict | None:
    """导入质量门(纯函数,可单测)。返回 None=放行;{code, reason, hint}=拒绝原因。

    检查项(P4a C4):禁抓 URL → 登录类标题 → 正文过短 → 登录页特征 →
    口令/演示凭据(四种措辞样式) → 手机号/身份证 → 名单特征(人名+名单)。

    ⚠ P4e M5 ②:`runtime_origins` 是**本次请求的 origin**(自家前端地址),由路由层从
    `request.url` 推导后传入 —— 让"自家前端一律禁抓"不再依赖硬编码端口 8900。
    保持**纯函数**(默认 None 时行为与从前逐字一致),单测仍可直接调用。
    """
    if url:
        if _deny_url_hit(url, runtime_origins):
            return {"code": "deny_url",
                    "reason": "URL 命中禁抓清单(含学生姓名的名单页/登录页首页/自家前端)",
                    "hint": "请粘贴具体文章页 URL;含学生姓名的公示/名单页一律禁止入库"}
    if title in ("登录", "未命名网页", ""):
        return {"code": "login_title",
                "reason": f"标题为登录/未命名类({title!r}),疑似非内容页",
                "hint": "请从具体文章页导入,而非站点首页或登录跳转页"}
    if len(text) < MIN_EFFECTIVE_CHARS:
        return {"code": "too_short",
                "reason": f"正文有效长度 {len(text)} < {MIN_EFFECTIVE_CHARS} 字,低信息量",
                "hint": "首页/导航页通常没有正文,请粘贴具体文章页 URL"}
    hits = [f for f in LOGIN_FEATURES if f in text[:600]]
    if len(hits) >= 2:
        return {"code": "login_page",
                "reason": f"命中登录页特征 {hits}",
                "hint": "疑似登录框/兼容性提示页,请粘贴正文文章页 URL"}
    idx = is_index_page(text)
    if idx:
        return {"code": "index_page",
                "reason": (f"导航/索引型页面:菜单式短行占比 {idx['short_ratio']:.0%}"
                           f"({idx['short_lines']}/{idx['total_lines']} 行),"
                           f"正文式长行仅 {idx['long_ratio']:.0%}"),
                "hint": "请粘贴具体文章页 URL（含发布日期/正文的页面），导航页无法入库"}
    for pat, label in PASSWORD_PATTERNS:
        if re.search(pat, text):
            return {"code": "credential",
                    "reason": f"命中口令/演示凭据样式:{label}",
                    "hint": "演示口令与凭据信息禁止入库(安全边界);请移除相关段落后重试"}
    if RE_MOBILE.search(text) or RE_IDCARD.search(text):
        return {"code": "personal_info",
                "reason": "正文疑似含手机号或身份证号(个人信息)",
                "hint": "个人信息禁止入库;如为公开业务电话请人工确认后联系管理员处理"}
    if ("名单" in title or "名单" in text[:400]) and ("姓名" in text or "学号" in text):
        return {"code": "name_list",
                "reason": "名单特征(标题/正文含「名单」且正文含姓名/学号)",
                "hint": "含学生姓名的公示/名单页禁止入库(P4 红线)"}
    return None


def _gate_or_400(url: str, title: str, text: str,
                 runtime_origins: list[str] | None = None) -> None:
    reject = quality_gate_reject(url, title, text, runtime_origins)
    if reject:
        logger.warning("导入被质量门拦截: code=%s url=%s title=%s", reject["code"], url, title[:60])
        raise HTTPException(400, detail=reject)


@app.get("/api/kb/documents")
async def kb_documents(category: str = "", folder_id: str = "", audience: str = "",
                       user=Depends(current_user)):
    """P4c C6: 列表增加 folder_id('root'=根目录/整数=指定夹)与 audience 筛选。"""
    rank = ROLE_RANK[user["role"]]
    fid: int | str | None = None
    if folder_id == "root":
        fid = "root"
    elif folder_id:
        try:
            fid = int(folder_id)
        except ValueError:
            raise HTTPException(400, "folder_id 必须是整数或 root")
        _folder_visible_or_404(fid, user)  # 不可见 = 不存在(硬约束 1)
    if audience and audience not in AUDIENCE_VALUES:
        raise HTTPException(400, f"audience 必须是 {list(AUDIENCE_VALUES)}")
    docs = db.list_documents(rank, category, folder_id=fid, audience=audience or "")
    return {"documents": docs, "categories": db.list_categories(rank),
            "audience_values": list(AUDIENCE_VALUES)}


@app.get("/api/kb/documents/{doc_id}/chunks")
async def kb_chunks(doc_id: int, user=Depends(current_user)):
    doc = db.get_document(doc_id, ROLE_RANK[user["role"]])
    if doc is None:
        raise HTTPException(404, "文档不存在或无权查看")
    return {"document": doc, "chunks": db.get_chunks(doc_id)}


@app.patch("/api/kb/documents/{doc_id}")
async def kb_document_patch(doc_id: int, body: dict, user=Depends(require_role("counselor"))):
    """P4c C2/C5: 单条移动(folder_id, null=移回根)与学段标注(audience)。"""
    rank = ROLE_RANK[user["role"]]
    doc = db.get_document(doc_id, rank)
    if doc is None:
        raise HTTPException(404, "文档不存在或无权修改")
    has_folder = "folder_id" in body
    fid = body.get("folder_id")
    if has_folder and fid is not None and not isinstance(fid, bool):
        if not isinstance(fid, int):
            raise HTTPException(400, "folder_id 必须是整数或 null")
        _folder_visible_or_404(fid, user)
    aud = body.get("audience")
    if aud is not None and aud not in AUDIENCE_VALUES:
        raise HTTPException(400, f"audience 必须是 {list(AUDIENCE_VALUES)}")
    db.update_document_meta(doc_id,
                            folder_id=fid if has_folder else db._UNSET,
                            audience=aud)
    return {"updated": True, "folder_id": fid if has_folder else doc["folder_id"],
            "audience": aud or doc["audience"]}


@app.post("/api/kb/documents/move")
async def kb_documents_move(body: dict, user=Depends(require_role("counselor"))):
    """P4c C2: 批量移动。只移动请求者可见的文档(不可见 = 不存在,跳过不泄露)。"""
    rank = ROLE_RANK[user["role"]]
    doc_ids = body.get("doc_ids") or []
    if not isinstance(doc_ids, list) or not doc_ids:
        raise HTTPException(400, "doc_ids 不能为空")
    doc_ids = [int(d) for d in doc_ids if str(d).strip().lstrip("-").isdigit()][:100]
    fid = body.get("folder_id", None)
    if fid is not None:
        if not isinstance(fid, int):
            raise HTTPException(400, "folder_id 必须是整数或 null")
        _folder_visible_or_404(fid, user)
    visible_docs = {d["id"] for d in db.list_documents(rank) }
    targets = [d for d in doc_ids if d in visible_docs]
    moved = db.move_documents(targets, fid)
    return {"moved": moved, "skipped": len(doc_ids) - moved, "folder_id": fid}


@app.delete("/api/kb/documents/{doc_id}")
async def kb_delete(doc_id: int, user=Depends(require_role("counselor"))):
    if db.get_document(doc_id, ROLE_RANK[user["role"]]) is None:
        raise HTTPException(404, "文档不存在或无权删除")
    db.delete_document(doc_id)
    return {"deleted": True}


# ---------- P4c C2: 文件夹 CRUD ----------

def _folder_visible_or_404(folder_id: int, user) -> dict:
    """「不可见 = 不存在」:越权与不存在同表现 404,不泄露文件夹是否存在(硬约束 1)。"""
    f = db.get_folder(folder_id)
    if f is None or folder_id not in db.visible_folder_ids(user["id"], user["role"]):
        raise HTTPException(404, "文件夹不存在或无权访问")
    return f


def _folder_owned_or_404(folder_id: int, user) -> dict:
    f = _folder_visible_or_404(folder_id, user)
    if user["role"] != "admin" and f["owner_id"] != user["id"]:
        raise HTTPException(404, "文件夹不存在或无权访问")  # 只读可见 ≠ 可管理,同样不泄露
    return f


def _folder_cycle_check(folder_id: int, new_parent_id: int | None) -> None:
    """重挂父级不得落入自己的子树(成环会让子树列表/删除死循环)。"""
    if new_parent_id is None:
        return
    if new_parent_id == folder_id or new_parent_id in set(db.folder_descendant_ids(folder_id)):
        raise HTTPException(400, "parent_id 不能是自身或自己的子孙文件夹")


@app.get("/api/kb/folders")
async def kb_folders(user=Depends(current_user)):
    """文件夹树(仅可见项,admin 管全部)+ 每夹可见文档数;@ 选择器与 KB 页共用。"""
    return {"folders": db.list_folders_with_counts(user["id"], user["role"])}


@app.post("/api/kb/folders")
async def kb_folder_create(body: dict, user=Depends(require_role("counselor"))):
    name = (body.get("name") or "").strip()
    if not name or len(name) > 50:
        raise HTTPException(400, "name 必填且不超过 50 字")
    visibility = body.get("visibility") or "private"
    if visibility not in FOLDER_VISIBILITY:
        raise HTTPException(400, f"visibility 必须是 {list(FOLDER_VISIBILITY)}")
    parent_id = body.get("parent_id")
    if parent_id is not None:
        if not isinstance(parent_id, int):
            raise HTTPException(400, "parent_id 必须是整数或 null")
        _folder_visible_or_404(parent_id, user)
    visible = db.visible_folder_ids(user["id"], user["role"])
    if db.folder_name_exists(name, parent_id, requester_visible=visible):
        raise HTTPException(409, "同级已存在同名文件夹")
    fid = db.create_folder(name, parent_id, user["id"], visibility)
    return {"folder_id": fid, "name": name, "parent_id": parent_id, "visibility": visibility}


@app.patch("/api/kb/folders/{folder_id}")
async def kb_folder_patch(folder_id: int, body: dict, user=Depends(require_role("counselor"))):
    f = _folder_owned_or_404(folder_id, user)
    fields: dict = {}
    if "name" in body:
        name = (body.get("name") or "").strip()
        if not name or len(name) > 50:
            raise HTTPException(400, "name 必填且不超过 50 字")
        visible = db.visible_folder_ids(user["id"], user["role"])
        if db.folder_name_exists(name, body.get("parent_id", f["parent_id"]),
                                 exclude_id=folder_id, requester_visible=visible):
            raise HTTPException(409, "同级已存在同名文件夹")
        fields["name"] = name
    if "parent_id" in body:
        pid = body.get("parent_id")
        if pid is not None:
            if not isinstance(pid, int):
                raise HTTPException(400, "parent_id 必须是整数或 null")
            _folder_visible_or_404(pid, user)
        _folder_cycle_check(folder_id, pid)
        fields["parent_id"] = pid
    if "visibility" in body:
        v = body.get("visibility")
        if v not in FOLDER_VISIBILITY:
            raise HTTPException(400, f"visibility 必须是 {list(FOLDER_VISIBILITY)}")
        fields["visibility"] = v
    if fields:
        db.update_folder(folder_id, **fields)
    return {"updated": True, **db.get_folder(folder_id)}


@app.delete("/api/kb/folders/{folder_id}")
async def kb_folder_delete(folder_id: int, cascade: bool = False,
                           user=Depends(require_role("counselor"))):
    """删除文件夹。**非空默认拒绝**(C2/边界):提示先移动;级联需显式 cascade=true,
    且级联只是删除文件夹壳、其下文档移回根目录(不删文档,KB 守恒)。"""
    f = _folder_owned_or_404(folder_id, user)
    subtree = [folder_id] + db.folder_descendant_ids(folder_id)
    rank = ROLE_RANK[user["role"]]
    docs_inside = db.folder_visible_doc_count(subtree, rank)
    children = len(subtree) - 1
    if (docs_inside or children) and not cascade:
        raise HTTPException(409, {
            "code": "folder_not_empty",
            "reason": "文件夹非空",
            "hint": f"该文件夹含 {docs_inside} 篇可见文档、{children} 个子文件夹;"
                    "请先移动，或确认级联删除(cascade=true，文档将移回根目录、不会被删除)",
        })
    moved_docs = db.delete_folders(subtree)
    return {"deleted": True, "folders_removed": len(subtree), "docs_moved_to_root": moved_docs}


# ---------- 对话 ----------

def _resolve_conversation(body: dict, user_id: int) -> int:
    """P4b: 解析请求里的会话——传了 conversation_id 必须属主(不存在/越权同表现 404),
    缺省返回 0(由 agent 层自动新建,标题=首问前 20 字)。"""
    cid = body.get("conversation_id")
    if cid:
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            raise HTTPException(400, "conversation_id 必须是整数")
        if not db.get_conversation(cid, user_id):
            raise HTTPException(404, "会话不存在")
        return cid
    return 0


# ---------- P4c: scope 解析 / F3 学段追问 / 空库提示 ----------

FOLDER_VISIBILITY = ("private", "student", "counselor", "admin")
AUDIENCE_VALUES = ("undergrad", "postgrad", "common")
# F3 学段敏感主题清单(P4.md M5):命中且问句未自带学段、且库内确有本/研两段标注材料时才追问
_AUDIENCE_SENSITIVE = ("荣誉称号", "奖学金", "评优", "学籍", "请假", "休学", "复学", "助学金")
_STAGE_WORDS = (("本科生", "undergrad"), ("本科", "undergrad"), ("专科", "undergrad"),
                ("大一", "undergrad"), ("大二", "undergrad"), ("大三", "undergrad"),
                ("大四", "undergrad"), ("研究生", "postgrad"), ("硕士", "postgrad"),
                ("博士", "postgrad"), ("研一", "postgrad"), ("研二", "postgrad"),
                ("研三", "postgrad"))

_AUDIENCE_CLARIFY_TEXT = ("您的问题涉及本科生与研究生的不同规定，为避免答错学段，请先告诉我："
                          "您想咨询的是本科生还是研究生的相关规定？")
_SCOPE_EMPTY_TEXT = ("您指定的知识库范围下没有可检索的文档，本次回答**未做全库检索**。"
                     "请确认所选文件夹/学段是否有内容，或去掉 @ 范围后重新提问。")
_SCOPE_MISSING_TEXT = "指定的知识库不存在或无权访问"


def _resolve_scope(body: dict, user, question_text: str = "") -> dict | None:
    """P4c C3/C4: 解析请求里的 scope(前端已把 @ 与问句分离,这里做服务端解析与 RBAC 交集)。

    硬约束 1(RBAC 优先): 请求的 folder_ids 与该用户可见集合取交集,**越权/不存在的
    folder 静默忽略**;全部不可见 → 404,文案与"不存在"一致,不泄露存在性。
    """
    raw = body.get("scope") or {}
    if not isinstance(raw, dict):
        raise HTTPException(400, "scope 必须是对象")
    folder_ids = raw.get("folder_ids") or []
    categories = raw.get("categories") or []
    audience = (raw.get("audience") or body.get("audience_hint") or "").strip() or None
    if audience and audience not in AUDIENCE_VALUES:
        raise HTTPException(400, f"audience 必须是 {list(AUDIENCE_VALUES)}")
    if not isinstance(folder_ids, list) or not isinstance(categories, list):
        raise HTTPException(400, "scope.folder_ids / scope.categories 必须是数组")
    folder_ids = [int(f) for f in folder_ids if str(f).strip().lstrip("-").isdigit()]
    categories = [str(c).strip() for c in categories if str(c).strip()][:5]
    if not audience:
        # P4c C5: 问句自带学段词(本科生/研究生/硕士…) → 自动映射 audience(未标注文档恒 common,零回归)
        audience = _audience_stage_of(question_text) or None
    if not folder_ids and not categories and not audience:
        return None
    resolved: list[int] | None = None
    if folder_ids:
        visible = db.visible_folder_ids(user["id"], user["role"])
        resolved = [f for f in folder_ids if f in visible]
        if not resolved:  # 全部不可见 → 与"不存在"同表现(硬约束 1)
            raise HTTPException(404, _SCOPE_MISSING_TEXT)
    scope = {"folder_ids": resolved, "categories": categories or None, "audience": audience}
    return scope if any(scope.values()) else None


_PERSONA_MISSING_TEXT = "指定的人设不存在或无权使用"


def _resolve_persona(body: dict, user, conversation_id: int | None) -> tuple:
    """P4f C3: 解析本轮使用的 persona,并把它的绑定范围与请求 scope 求交。

    返回 `(persona, effective_body)`:后者是**并入了 persona 范围**的请求体,调用方拿它
    去走 P4c 的 `_resolve_scope` —— **唯一解析入口,不在 persona 层另写一套**
    (另写一套就是绕过;坑 45:同一件事只应有一个权威实现)。

    优先级:**请求里显式传的 persona_id > 会话上绑定的 persona**(对话中可切换人设)。

    ## 硬约束:persona **不得提权**(逐条对应 P4c 的同类约束)
    1. **不可见 = 不存在**:`db.get_persona` 对不可见 persona 返回 None,这里抛 404,
       文案与「不存在」完全一致 → 不泄露存在性(同 P4c 硬约束 1)。
    2. **绑定范围必须与调用者 RBAC 可见范围求交**:`db.visible_folder_ids` 过滤一遍,
       越权夹**静默丢弃**(同 P4c);全部不可见 → 404,同样不区分。
    3. **空 scope 不回落**:persona 范围与请求范围交集为空时,给 effective_body 打
       `__persona_scope_empty` 标记,调用方走既有「未做全库检索」提示路径
       (同 P4c 硬约束 3),**绝**不把范围悄悄放大成全库。
    """
    eff = dict(body)
    pid = body.get("persona_id")
    if pid is None and conversation_id:
        conv = db.get_conversation(conversation_id, user["id"])
        if conv:
            pid = conv.get("persona_id")
    if pid in (None, "", 0, "0"):
        return None, eff
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        raise HTTPException(404, _PERSONA_MISSING_TEXT)
    persona = db.get_persona(pid_int, user["id"], user["role"])
    if not persona:
        raise HTTPException(404, _PERSONA_MISSING_TEXT)
    # ---- 硬约束 2:绑定范围 ∩ RBAC 可见范围(越权静默丢弃) ----
    bound = list(persona.get("bound_folder_ids") or [])
    if bound:
        visible = set(db.visible_folder_ids(user["id"], user["role"]))
        kept = [f for f in bound if int(f) in visible]
        if not kept:
            # 与「不存在」同表现,不区分「夹存在但无权限」与「夹不存在」
            raise HTTPException(404, _SCOPE_MISSING_TEXT)
        persona = dict(persona, bound_folder_ids=kept)
    # ---- 把 persona 范围并入请求 scope,交由 _resolve_scope 统一解析 ----
    merged = dict(body.get("scope") or {}) if isinstance(body.get("scope"), dict) else {}
    if persona.get("bound_folder_ids"):
        req_folders = [f for f in (merged.get("folder_ids") or [])]
        if req_folders:
            inter = [f for f in req_folders if f in persona["bound_folder_ids"]]
            if not inter:
                eff["__persona_scope_empty"] = True   # 硬约束 3
            merged["folder_ids"] = inter or req_folders
        else:
            merged["folder_ids"] = list(persona["bound_folder_ids"])
    if persona.get("bound_categories") and not merged.get("categories"):
        merged["categories"] = list(persona["bound_categories"])
    eff["scope"] = merged
    return persona, eff


def _persona_scope_empty_response() -> dict:
    """硬约束 3 的确定性响应:**明确提示未做全库检索**,与 P4c 空 scope 同一语义。"""
    return {"answer": _SCOPE_EMPTY_TEXT + "（该范围来自您选择的辅导星人设绑定）",
            "sources": [], "tool_trace": [],
            "context": {"scope_empty": True, "persona_scope_empty": True}}


def _audience_stage_of(question: str) -> str | None:
    for word, aud in _STAGE_WORDS:
        if word in question:
            return aud
    return None


def _audience_clarify(question: str, min_rank: int, scope: dict | None) -> dict | None:
    """P4c C5/F3: 学段敏感 + 未自带学段 + 无 hint + 库内确有本/研两段标注材料 → 追问学段(不猜)。

    库内没有成对标注时恒不触发(当前全为 common → 零回归);编排式多轮留给 P4d。
    """
    if scope and scope.get("audience"):
        return None
    if _audience_stage_of(question):
        return None
    hits = [k for k in _AUDIENCE_SENSITIVE if k in question]
    if not hits or not db.audience_conflict(hits, min_rank):
        return None
    return {
        "answer": _AUDIENCE_CLARIFY_TEXT,
        "sources": [], "tool_trace": [],
        "clarify": {"type": "audience", "options": ["本科生", "研究生"],
                    "hint_param": "audience_hint"},
        "context": {"audience_clarify": True},
    }


def _scope_empty_response(scope: dict, min_rank: int) -> dict | None:
    """P4c 硬约束 3: scope 指定范围内没有可见文档 → 明确提示,**绝不回落全库**。"""
    if not scope:
        return None
    if db.count_visible_documents(min_rank, scope.get("folder_ids"),
                                  scope.get("categories"), scope.get("audience")) > 0:
        return None
    return {"answer": _SCOPE_EMPTY_TEXT, "sources": [], "tool_trace": [],
            "context": {"scope_empty": True, "scope": scope}}


@app.post("/api/chat")
async def chat(body: dict, user=Depends(current_user)):
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "question 不能为空")
    if question.startswith("@"):
        # P4c 硬约束 2 的服务端兜底: @ 语法由前端解析成 scope,@xxx 残留进问句会污染 embedding/FTS
        raise HTTPException(400, "问题文本不能以 @ 开头：请用 @ 选择器指定知识库（scope 参数）")
    cid = _resolve_conversation(body, user["id"]) or None
    try:
        persona, eff_body = _resolve_persona(body, user, cid)
        scope = _resolve_scope(eff_body, user, question)
    except HTTPException:
        raise
    if eff_body.get("__persona_scope_empty"):
        return _persona_scope_empty_response()
    rank = ROLE_RANK[user["role"]]
    clarify = _audience_clarify(question, rank, scope)
    if clarify:
        return clarify
    empty = _scope_empty_response(scope, rank)
    if empty:
        return empty
    try:
        d = await agent.chat_for(user["id"], user["username"], user["role"], question, cid,
                                 scope=scope, web_search=_web_search_override(eff_body),
                                 persona=persona)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except httpx.HTTPStatusError as e:
        # P4f 第3 回⑧(可选一条):上游 429 限流 → **503 + 明确文案**,
        #   而不是让 `raise_for_status()` 冒成 500 白屏。
        #   归因要可读:复核方看到 500 时分不清「模型答错」与「额度受限/被限流」——
        #   而它们的处置完全不同(后者加节流即可)。
        #   ⚠ **只加异常映射**:不碰任何拒答门控/grounding 闸门/检索编排。
        if e.response.status_code == 429:
            raise HTTPException(503, "模型额度受限，请稍后再试（上游 429 限流）")
        raise
    return d


@app.post("/api/chat/stream")
async def chat_stream(body: dict, user=Depends(current_user)):
    """T8: 流式对话(SSE)。事件序列: sources → context → delta* → tools? → done → [DONE]。"""
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "question 不能为空")
    if question.startswith("@"):
        raise HTTPException(400, "问题文本不能以 @ 开头：请用 @ 选择器指定知识库（scope 参数）")
    cid = _resolve_conversation(body, user["id"]) or None
    # P4f: persona 与 chat 路径**同一套解析**(不另写一份,坑 45)
    persona, eff_body = _resolve_persona(body, user, cid)
    scope = _resolve_scope(eff_body, user, question)
    rank = ROLE_RANK[user["role"]]
    pre = (_persona_scope_empty_response() if eff_body.get("__persona_scope_empty")
           else None) or _audience_clarify(question, rank, scope) \
        or _scope_empty_response(scope, rank)

    async def gen():
        answer_parts: list[str] = []
        try:
            if pre:  # P4c: 学段追问 / 空库提示——确定性响应,不经 LLM
                ctx = pre.get("context") or {}
                yield f"data: {json.dumps({'type': 'sources', 'sources': []}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'context', **ctx}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'delta', 'content': pre['answer']}, ensure_ascii=False)}\n\n"
                answer_parts.append(pre["answer"])
                done_ev = {"type": "done", "answer": pre["answer"], "sources": [],
                           "tool_trace": [], "conversation_id": None, "context": ctx}
                yield f"data: {json.dumps(done_ev, ensure_ascii=False)}\n\n"
            else:
                async for ev in agent.chat_stream_for(user["id"], user["username"], user["role"],
                                                      question, cid, scope=scope,
                                                      web_search=_web_search_override(eff_body),
                                                      persona=persona):
                    if ev["type"] == "delta":
                        answer_parts.append(ev["content"])
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except LookupError as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"
        except Exception as e:  # 流中途异常:通知前端(已渲染增量保留,不落库)
            logger.exception("stream error")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)[:200]}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- P4f C1: persona(AI 辅导员人设)API ----------
# 权限(硬约束): 辅导员只管自己的;学生**只能列/用** visibility='public' 的(不能建改删);
# admin 管全部。不可见 → 404 且与「不存在」同文案(不泄露存在性)。
# ⚠ personas.visibility 的 CHECK **只有 ('private','public')** 两档 ——
#   写 'student'/'counselor' 会被 CHECK 当场拦下(复核方造 'counselor' 时实测到)。
#   那三档是 **kb_folders.visibility** 的档位,两张表各有一套,别混用(坑 69)。

@app.get("/api/personas")
async def personas_list(user=Depends(current_user)):
    """列出可见人设。

    ⚠ P4f 第3回②:**对外投影** —— 非作者拿到的 `persona_prompt` 是空串。
      public 人设的正文是辅导员的内部表述,学生能读到就能反推 system prompt 的
      组装方式(提示词面泄露),而public 人设的**使用**根本不依赖这段正文
      (它只在服务端组装时被读)。判据按**作者**:`owner_id == 请求者` 或
      `role=='admin'` 给全文,其余置 `""`(不删键 —— 前端契约依赖键存在)。

    ★ 投影**只作用于本响应**:`_resolve_persona` 走 `db.get_persona` 拿的是
      内部完整读数,不受影响 —— 学生**选用**该人设提问时,服务端照样带上
      persona 段(坑 46:别把展示脱敏做成功能阉割)。
    """
    rows = db.list_personas(user["id"], user["role"])
    return {"personas": db.project_personas_for_response(rows, user["id"], user["role"])}


@app.post("/api/personas")
async def personas_create(body: dict, user=Depends(require_role("counselor"))):
    """学生不得创建人设(require_role 拦截)。演示口令等敏感内容不落 KB,人设文本只进本表。"""
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name 不能为空")
    style = body.get("style") or "balanced"
    if style not in db._STYLE_VALUES:
        raise HTTPException(400, f"style 必须是 {list(db._STYLE_VALUES)}")
    visibility = body.get("visibility") or "private"
    if visibility not in db._PERSONA_VISIBILITY_VALUES:
        raise HTTPException(400, f"visibility 必须是 {list(db._PERSONA_VISIBILITY_VALUES)}")
    # 绑定夹必须是自己可见的(与检索时的 RBAC 交集同源;越权夹此刻就拒,不留到运行时)
    fids = [int(f) for f in (body.get("bound_folder_ids") or []) if str(f).strip().lstrip("-").isdigit()]
    if fids:
        visible = set(db.visible_folder_ids(user["id"], user["role"]))
        bad = [f for f in fids if f not in visible]
        if bad:
            # 与「不存在」同表现(P4c 硬约束 1)
            raise HTTPException(404, "指定的知识库不存在或无权访问")
    # P5-2: avatar = 内置头像库的**逻辑 id**(由 db.normalize_avatar 清洗,未知 id 也放行)
    pid = db.create_persona(user["id"], name, body.get("college") or "",
                            body.get("persona_prompt") or "", style, fids,
                            list(body.get("bound_categories") or []), visibility,
                            bool(body.get("is_default")), body.get("avatar") or "")
    # 出口统一过投影(与 GET /api/personas 同一个出口函数,坑 45:同一件事一处实现)。
    # 自建人设按作者判据 → 全文照returned,行为与改前一致。
    p = db.get_persona(pid, user["id"], user["role"])
    return {"persona": db.project_persona_for_response(p, user["id"], user["role"])}


@app.patch("/api/personas/{persona_id}")
async def personas_patch(persona_id: int, body: dict, user=Depends(require_role("counselor"))):
    # P5-2: `avatar` 与其它字段走同一个 patch 通道(清洗在 db.update_persona 里)。
    # 学生进不来 —— require_role 已在入口拦掉(403),不靠前端不渲染。
    p = db.update_persona(persona_id, user["id"], user["role"], body)
    if not p:
        raise HTTPException(404, _PERSONA_MISSING_TEXT)
    # 同 POST:出口统一过投影(admin 改别人的时候也不该顺手把正文带出去)
    return {"persona": db.project_persona_for_response(p, user["id"], user["role"])}


@app.delete("/api/personas/{persona_id}")
async def personas_delete(persona_id: int, user=Depends(require_role("counselor"))):
    """**软删除**:历史会话保留并标记「人设已删除」(见 db.persona_display_name)。"""
    if not db.delete_persona(persona_id, user["id"], user["role"]):
        raise HTTPException(404, _PERSONA_MISSING_TEXT)
    return {"ok": True, "soft_deleted": True}


# ---------- P4b C6: 会话 CRUD ----------

@app.get("/api/conversations")
async def conversations(include_archived: bool = False, limit: int = 200, user=Depends(current_user)):
    """P4b: 当前用户的会话列表(默认只列未归档;按 archived,updated_at 排序)。
    ⚠ 语义变更(T9 的扁平消息流已迁往 GET /api/conversations/{id}/messages)——消费端
    chat.js/loadHistory 已同步改造(P4b C5),坑 30 说明见 docs/P4B.md。"""
    return {"conversations": db.list_conversations(user["id"], include_archived, limit)}


@app.post("/api/conversations")
async def conversations_create(body: dict, user=Depends(current_user)):
    # P4f: 新建会话时可指定 persona(对话中切换人设的落点)。可见性由 _resolve_persona 保证。
    persona_id = None
    if body.get("persona_id") not in (None, "", 0, "0"):
        _p, _eff = _resolve_persona({"persona_id": body.get("persona_id")}, user, None)
        persona_id = int(body["persona_id"])
    cid = db.create_conversation(user["id"], (body.get("title") or "新会话"), persona_id=persona_id)
    conv = db.get_conversation(cid, user["id"])
    return {"id": cid, "title": conv["title"], "archived": conv["archived"],
            "updated_at": conv["updated_at"], "persona_id": conv.get("persona_id"),
            "persona_name": db.persona_display_name(conv.get("persona_id"))}


@app.get("/api/conversations/{conversation_id}/messages")
async def conversation_messages(conversation_id: int, limit: int = 50, offset: int = 0,
                                user=Depends(current_user)):
    """P4b: 某会话的消息分页(时间正序);越权与不存在同表现(404)。"""
    if not db.get_conversation(conversation_id, user["id"]):
        raise HTTPException(404, "会话不存在")
    msgs, total = db.conversation_messages(conversation_id, limit, offset)
    return {"messages": msgs, "total": total}


@app.patch("/api/conversations/{conversation_id}")
async def conversation_patch(conversation_id: int, body: dict, user=Depends(current_user)):
    """重命名(title)与归档/恢复(archived);P4f 增加切换人设(persona_id)。"""
    ok = False
    if "title" in body:
        ok = db.rename_conversation(conversation_id, user["id"], str(body.get("title") or ""))
    if "archived" in body:
        ok = db.set_conversation_archived(conversation_id, user["id"], bool(body.get("archived"))) or ok
    if "persona_id" in body:
        # 切换人设:先过可见性(不可见 → 404,与不存在同表现),再落库
        raw = body.get("persona_id")
        if raw in (None, "", 0, "0"):
            ok = db.set_conversation_persona(conversation_id, user["id"], None) or ok
        else:
            _p, _eff = _resolve_persona({"persona_id": raw}, user, None)
            ok = db.set_conversation_persona(conversation_id, user["id"], int(raw)) or ok
    if not ok:
        raise HTTPException(404, "会话不存在")
    conv = db.get_conversation(conversation_id, user["id"])
    return {"id": conversation_id, "title": conv["title"], "archived": conv["archived"],
            "persona_id": conv.get("persona_id"),
            "persona_name": db.persona_display_name(conv.get("persona_id"))}


@app.delete("/api/conversations/{conversation_id}")
async def conversation_delete(conversation_id: int, user=Depends(current_user)):
    """级联删除:只删该会话的消息与摘要;越权与不存在同表现(404)。"""
    r = db.delete_conversation(conversation_id, user["id"])
    if r is None:
        raise HTTPException(404, "会话不存在")
    return {"ok": True, **r}


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


# ---------- 谈心谈话:姓名 / 自动摘要 / 按月导出 ----------

TALK_CATEGORY = "谈心谈话"


def _attachment_headers(filename: str) -> dict[str, str]:
    """下载文件名头。

    ⚠ 中文文件名必须走 RFC 5987 的 `filename*`,同时给一个纯 ASCII 的 `filename` 兜底
      —— HTTP 头是 latin-1,直接塞中文会 UnicodeEncodeError,而不是"某些浏览器显示乱码"。
    """
    fallback = re.sub(r"[^A-Za-z0-9._-]", "_", filename) or "download"
    return {"Content-Disposition":
            f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename)}'}


@app.post("/api/weekly/summarize")
async def weekly_summarize(body: dict, user=Depends(require_role("counselor"))):
    """按谈话内容生成规范摘要草稿(不落库,供表单在保存前预览与手改)。"""
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(400, "content 不能为空")
    eff = agent.effective_llm(user["id"])
    summary = await agent.summarize_talk(content, eff["model"], eff["base_url"], eff["api_key"])
    return {"summary": summary, "placeholder": talk_summary.PLACEHOLDER_SUMMARY}


@app.post("/api/weekly/fragments")
async def weekly_add(body: dict, user=Depends(require_role("counselor"))):
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(400, "content 不能为空")
    category = body.get("category", "其他")
    student_name = (body.get("student_name") or "").strip()
    summary = (body.get("summary") or "").strip()
    # 姓名**只在谈心谈话这一类**必填:事务办理/活动组织没有"某个学生"这个对象,
    # 一刀切必填会逼着辅导员填无关内容。MCP 层保持宽松默认值(见 server.py 同处注释),
    # 严格的只有这条 UI 入口 —— 这是有意的不对称,不是漏判。
    if category == TALK_CATEGORY and not student_name:
        raise HTTPException(400, "谈心谈话记录必须填写学生姓名")
    if category == TALK_CATEGORY and not summary:
        eff = agent.effective_llm(user["id"])
        summary = await agent.summarize_talk(content, eff["model"], eff["base_url"], eff["api_key"])
    d = await agent.weekly_add(content, category, body.get("occurred_at", ""),
                               student_name, summary)
    if isinstance(d, dict):
        d["summary"] = summary
    return d


@app.patch("/api/weekly/fragments/{fragment_id}")
async def weekly_patch(fragment_id: int, body: dict, user=Depends(require_role("counselor"))):
    """详情页补录姓名 / 手改摘要。"""
    student_name = (body.get("student_name") or "").strip()
    summary = (body.get("summary") or "").strip()
    if not student_name and not summary:
        raise HTTPException(400, "student_name 与 summary 至少要提供一个")
    d = await agent.weekly_update(fragment_id, student_name, summary)
    if not d.get("ok"):
        raise HTTPException(404, d.get("error", "记录不存在"))
    return d


@app.get("/api/weekly/records/export")
async def weekly_records_export(month: str, user=Depends(require_role("counselor"))):
    """按月导出谈心谈话记录:每条一行台账整句,UTF-8 with BOM 的 CSV。

    BOM 不是可选修饰:Excel 双击打开无 BOM 的 UTF-8 CSV 会把中文显示成乱码,
    而这份文件的用途就是给辅导员在 Excel 里看和往上交。
    """
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month or ""):
        # 只写 \d{4}-\d{2} 会放过 `2026-13`:它到 MCP 层才被拒,返回的是 502 而不是 400
        # —— "用户输入不合法"必须是 4xx,否则客户端无法区分"我月份写错了"和"服务坏了"
        raise HTTPException(400, "month 必须是 YYYY-MM 格式(月份 01~12)")
    d = await agent.weekly_export_talk(month)
    if not d.get("ok"):
        raise HTTPException(502, d.get("error", "导出失败"))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["谈心谈话记录"])
    for row in d.get("rows", []):
        w.writerow([row])
    data = ("﻿" + buf.getvalue()).encode("utf-8")
    headers = _attachment_headers(f"谈心谈话记录_{month}.csv")
    headers["X-Export-Count"] = str(d.get("count", 0))
    return StreamingResponse(iter([data]), media_type="text/csv; charset=utf-8", headers=headers)


# ---------- 会议纪要(AI 整理) ----------
# ⚠ 出网告知:转写会把**会议音频**发往 DashScope,整理会把**会议原文**发往 LLM。
#   这与既有"联网检索只发问题文本"是两条不同通道,前端入口必须先勾选确认再调这些接口。

MINUTES_TEXT_EXTS = {".txt", ".md", ".markdown"}
MINUTES_MAX_BYTES = 8 * 1024 * 1024


def _minutes_payload(body: dict) -> dict:
    """把 HTTP 请求体(结构化数组)收成 MCP `add_minutes`/`update_minutes` 的参数。

    ⚠ 三个数组字段在这里**序列化成 JSON 文本**:MCP 工具参数声明为 `str`,
      直接传 list 会在协议层参数校验就被打回(实测报 `Input should be a valid string`),
      根本到不了函数体。读回时由 server 层解析成数组,前端看到的仍是数组。
    """
    def _lines(key: str) -> str:
        v = body.get(key)
        if isinstance(v, str):
            s = v.strip()
            # 容忍把数组发成 JSON 文本的调用方:不先 parse 就会把 `["a"]` 连中括号
            # 当成一条要点存进纪要(实测:前端正常路径不会踩到,手写脚本会)
            if s.startswith("[") and s.endswith("]"):
                try:
                    v = json.loads(s)
                except json.JSONDecodeError:
                    v = [s]
            else:
                v = [p.strip() for p in re.split(r"[\n;；]+", s) if p.strip()]
        return json.dumps([str(x).strip() for x in (v or []) if str(x).strip()][:200],
                          ensure_ascii=False)

    todos = body.get("todos") or []
    if isinstance(todos, str):
        try:
            todos = json.loads(todos or "[]")
        except json.JSONDecodeError:
            todos = []
    cleaned = [{"item": str(t.get("item") or "").strip(),
                "owner": str(t.get("owner") or "").strip(),
                "due": str(t.get("due") or "").strip()}
               for t in todos if isinstance(t, dict) and str(t.get("item") or "").strip()]
    return {
        "title": (body.get("title") or "").strip(),
        "meeting_time": (body.get("meeting_time") or "").strip(),
        "attendees": (body.get("attendees") or "").strip(),
        "discussion": _lines("discussion"),
        "resolutions": _lines("resolutions"),
        "todos": json.dumps(cleaned[:40], ensure_ascii=False),
    }


@app.post("/api/weekly/minutes/transcribe")
async def minutes_transcribe(file: UploadFile = File(...), user=Depends(require_role("counselor"))):
    """录音文件 → 转写文本(整理流程的第一步;转写完的文本再交给 /organize)。"""
    data = await file.read()
    if not data:
        raise HTTPException(400, "音频文件为空")
    if len(data) > config.ASR_MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"音频超过 {config.ASR_MAX_MB}MB 上限")
    try:
        text = await agent.transcribe_audio(file.filename or "audio.mp3", data,
                                            agent.effective_llm(user["id"])["api_key"])
    except asr_mod.AsrError as e:
        raise HTTPException(502, str(e))
    if not text:
        raise HTTPException(502, "转写结果为空,请检查音频是否包含语音")
    return {"ok": True, "text": text, "chars": len(text),
            "audio_name": file.filename or "", "source_type": "audio"}


@app.post("/api/weekly/minutes/organize")
async def minutes_organize(body: dict, user=Depends(require_role("counselor"))):
    """零散内容 → 结构化纪要草稿(不落库,前端编辑确认后再 POST /minutes 保存)。"""
    raw = (body.get("raw") or "").strip()
    if not raw:
        raise HTTPException(400, "raw 不能为空(请先粘贴会议内容、上传笔记或上传录音)")
    eff = agent.effective_llm(user["id"])
    try:
        minutes, untraced = await agent.organize_minutes(raw, eff["model"],
                                                         eff["base_url"], eff["api_key"])
    except (RuntimeError, ValueError) as e:
        raise HTTPException(502, f"整理失败:{e}")
    except Exception as e:  # noqa: BLE001 — LLM 通道异常给可读错误,不抛裸 500
        logger.exception("会议纪要整理失败")
        # 文案要点:异常类型名(如 KeyError)对用户没有可操作性,必须同时给出**下一步**
        raise HTTPException(502, f"整理失败（{type(e).__name__}）：请检查设置里的模型配置，"
                                f"或把原始内容拆短一些再试")
    return {"ok": True, "minutes": minutes, "untraced": untraced,
            "markdown": minutes_lib.render_markdown(minutes), "raw": raw}


@app.post("/api/weekly/minutes")
async def minutes_create(body: dict, user=Depends(require_role("counselor"))):
    d = await agent.minutes_add({
        **_minutes_payload(body),
        "raw_content": (body.get("raw_content") or body.get("raw") or "").strip(),
        "source_type": body.get("source_type") if body.get("source_type") in ("text", "file", "audio") else "text",
        "audio_name": (body.get("audio_name") or "").strip(),
    })
    if not d.get("ok"):
        raise HTTPException(502, d.get("error", "保存失败"))
    return d


@app.get("/api/weekly/minutes")
async def minutes_list(user=Depends(require_role("counselor"))):
    d = await agent.minutes_list()
    if not d.get("ok"):
        raise HTTPException(502, d.get("error", "纪要服务不可用"))
    return d


@app.get("/api/weekly/minutes/{minutes_id}")
async def minutes_detail(minutes_id: int, user=Depends(require_role("counselor"))):
    d = await agent.minutes_get(minutes_id)
    if not d.get("ok"):
        raise HTTPException(404, d.get("error", "纪要不存在"))
    return d


@app.put("/api/weekly/minutes/{minutes_id}")
async def minutes_update(minutes_id: int, body: dict, user=Depends(require_role("counselor"))):
    """在线编辑保存(整条覆盖,见 server.py `update_minutes`)。"""
    d = await agent.minutes_update(minutes_id, _minutes_payload(body))
    if not d.get("ok"):
        raise HTTPException(404, d.get("error", "纪要不存在"))
    return d


@app.delete("/api/weekly/minutes/{minutes_id}")
async def minutes_delete(minutes_id: int, user=Depends(require_role("counselor"))):
    d = await agent.minutes_delete(minutes_id)
    if not d.get("ok"):
        raise HTTPException(404, d.get("error", "删除失败"))
    return d


@app.get("/api/weekly/minutes/{minutes_id}/export")
async def minutes_export_docx(minutes_id: int, user=Depends(require_role("counselor"))):
    d = await agent.minutes_get(minutes_id)
    if not d.get("ok"):
        raise HTTPException(404, d.get("error", "纪要不存在"))
    docx = minutes_lib.render_docx(minutes_lib.normalize_fields(d))
    title = (d.get("title") or "会议纪要").strip() or "会议纪要"
    headers = _attachment_headers(f"{title}.docx")
    return StreamingResponse(iter([docx]),
                             media_type="application/vnd.openxmlformats-officedocument"
                                        ".wordprocessingml.document",
                             headers=headers)



# ---------- 其他 ----------

@app.get("/api/health")
async def health():
    # P4e S2-②: 暴露**本进程生效**的关键配置,供评测/排障把"当时是什么配置"写进报告。
    # 只读、无敏感字段(不含 key/口令)。新增字段对既有消费端(冒烟连通性检查)无影响。
    try:
        flags = {
            "grounding_gate_enabled": config.GROUNDING_GATE_ENABLED,
            "grounding_early_window_chars": config.GROUNDING_EARLY_WINDOW_CHARS,
            "grounding_stream_force_ungrounded": config.GROUNDING_STREAM_FORCE_UNGROUNDED,
            # P4f C0-③: 闸门轮次作用域判定(见 config.GROUNDING_GATE_SCOPE_MODE)。
            # 暴露出来是为了让"某轮为什么没被闸门管"在报告里可自证,而不是靠猜。
            "grounding_gate_scope_mode": config.GROUNDING_GATE_SCOPE_MODE,
            "web_search_enabled_default": config.WEB_SEARCH_ENABLED,
            # P4f C0-④: 双层超时,两个字段都暴露,避免再出现"一个数字两种语义"。
            # 旧的 web_search_timeout_s 保留为 idle 的别名,让历史报告仍可读。
            "web_search_idle_timeout_s": config.WEB_SEARCH_IDLE_TIMEOUT_S,
            "web_search_total_timeout_s": config.WEB_SEARCH_TOTAL_TIMEOUT_S,
            "web_search_timeout_s": config.WEB_SEARCH_IDLE_TIMEOUT_S,
            "web_search_max_sources": config.WEB_SEARCH_MAX_SOURCES,
            "graph_enabled": config.GRAPH_ENABLED,
            "max_rewrite": config.MAX_REWRITE,
            "llm_model": config.LLM_MODEL,
            # ---------- P4f C0-⑥: 额度来源(硬约束第 7 条的机器可读形式) ----------
            # ⚠ 这两个字段**只回答"key 来自哪一层"**,绝不回答 key 是什么。
            #   session_env  = 会话注入(测试者自带额度,合规)
            #   repo_dotenv  = 仓库 novaagent/.env(用户本人额度;按硬约束第 7 条,
            #                  读数为它的整轮评测结果**一律不认**)
            #   unset        = 两层都没有
            # 有了它,"我没用用户那把 key"就不再是一句口头承诺,而是每份报告自带字段。
            "llm_key_source": config.key_source("LLM_API_KEY"),
            "embedding_key_source": config.key_source("EMBEDDING_API_KEY"),
            "eval_temperature": os.environ.get("NOVAAGENT_EVAL_TEMPERATURE", ""),
            # 纪要转写通道(同样只暴露来源标签,不暴露 key 值)
            **asr_mod.describe_config(),
        }
    except Exception as e:  # noqa: BLE001  — 自检字段不该让 health 挂掉
        logger.warning("health flags 组装失败: %s", e)
        flags = {}
    return {"status": "ok", "weekly_mcp": agent.weekly.session is not None, "flags": flags}


@app.get("/")
async def index(request: Request):
    return _web_file(WEB_DIR / "index.html", request, "text/html; charset=utf-8")


# ---------- P4b-0 前端拆分:静态资源挂载(本单对 main.py 的唯一改动) ----------
# 显式给 media_type:Windows 下 mimetypes 受注册表影响,若 .js 被判成 text/plain
# 浏览器会因严格 MIME 校验拒绝执行脚本 → 拆分后页面白屏。故不走 StaticFiles 猜测。
_WEB_MEDIA = {".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8"}

# 【为什么入口资源必须带 Cache-Control】不写这个头,浏览器就按「启发式缓存」自己决定
# 新鲜期(Chrome 约 (now − Last-Modified) / 10,本仓库实测约 2 小时),于是部署后出现
# **混版**:主文档 F5 一定重取,而 /js/weekly.js 仍在用改版前那一份。同一个根因结出两条
# 完全不同的症状 ——
#   · 旧 addFragment 不发 student_name → 新后端按契约回 400「必须填写学生姓名」,
#     姓名明明填了也存不进(看起来像校验逻辑坏了);
#   · 旧文件里根本没有 summarizeTalk → 内联 onclick 抛 ReferenceError,只写在 console,
#     「生成摘要」按钮点了没反应、不转圈、也不报错(看起来像事件没绑上)。
# `no-cache` 的语义是「可以缓存,但每次必须回源校验」,配合下面的 ETag:文件没变回 304
# (不重传正文),变了立刻拿新的 —— 这是唯一能让「HTML 新 + JS 旧」不再出现的开关。
_WEB_HEADERS = {"Cache-Control": "no-cache"}


def _norm_etag(value: str) -> str:
    """比较 ETag 时忽略弱校验前缀(`W/"…"` 与 `"…"` 指向同一份内容)。"""
    value = value.strip()
    return value[2:].strip() if value.startswith("W/") else value


def _web_file(target: Path, request: Request, media_type: str) -> Response:
    """带 ETag 回源校验的静态响应。
    ⚠ 本仓库 Starlette 版本的 `FileResponse` **不再处理条件请求**(304 逻辑只留在
      `StaticFiles` 里,而我们因为 MIME 坑不能用它),所以 `If-None-Match` 要自己接:
      否则 `no-cache` 会让每次刷新都全量重传所有 JS/CSS。
    """
    resp = FileResponse(target, media_type=media_type, headers=dict(_WEB_HEADERS),
                        stat_result=target.stat())
    sent = {_norm_etag(v) for v in (request.headers.get("if-none-match") or "").split(",") if v.strip()}
    etag = _norm_etag(resp.headers.get("etag") or "")
    if request.method == "GET" and etag and etag in sent:
        # 304 不能带 content-length / content-type,否则浏览器会等一个并不存在的正文
        return Response(status_code=304, headers={
            "etag": etag,
            "last-modified": resp.headers.get("last-modified", ""),
            **_WEB_HEADERS,
        })
    return resp


def _serve_web_asset(sub: str, name: str, request: Request) -> Response:
    root = (WEB_DIR / sub).resolve()
    target = (root / name).resolve()
    if not str(target).startswith(str(root)) or target.suffix != "." + sub or not target.is_file():
        raise HTTPException(404, "资源不存在")
    return _web_file(target, request, _WEB_MEDIA[target.suffix])


@app.get("/css/{name}")
async def css_asset(name: str, request: Request):
    return _serve_web_asset("css", name, request)


@app.get("/js/{name}")
async def js_asset(name: str, request: Request):
    return _serve_web_asset("js", name, request)

