"""NovaAgent FastAPI 入口:认证 / 知识库管理 / 检索增强对话 / 周报"""
from __future__ import annotations

import io
import json
import logging
import re
from urllib.parse import urlsplit
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
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
    summary = await agent.summarize_document(Path(name).stem, chunks, eff["model"], eff["base_url"], eff["api_key"])
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
        scope = _resolve_scope(body, user, question)
    except HTTPException:
        raise
    rank = ROLE_RANK[user["role"]]
    clarify = _audience_clarify(question, rank, scope)
    if clarify:
        return clarify
    empty = _scope_empty_response(scope, rank)
    if empty:
        return empty
    try:
        d = await agent.chat_for(user["id"], user["username"], user["role"], question, cid,
                                 scope=scope, web_search=_web_search_override(body))
    except LookupError as e:
        raise HTTPException(404, str(e))
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
    scope = _resolve_scope(body, user, question)
    rank = ROLE_RANK[user["role"]]
    pre = _audience_clarify(question, rank, scope) or _scope_empty_response(scope, rank)

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
                                                      web_search=_web_search_override(body)):
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


# ---------- P4b C6: 会话 CRUD ----------

@app.get("/api/conversations")
async def conversations(include_archived: bool = False, limit: int = 200, user=Depends(current_user)):
    """P4b: 当前用户的会话列表(默认只列未归档;按 archived,updated_at 排序)。
    ⚠ 语义变更(T9 的扁平消息流已迁往 GET /api/conversations/{id}/messages)——消费端
    chat.js/loadHistory 已同步改造(P4b C5),坑 30 说明见 docs/P4B.md。"""
    return {"conversations": db.list_conversations(user["id"], include_archived, limit)}


@app.post("/api/conversations")
async def conversations_create(body: dict, user=Depends(current_user)):
    cid = db.create_conversation(user["id"], (body.get("title") or "新会话"))
    conv = db.get_conversation(cid, user["id"])
    return {"id": cid, "title": conv["title"], "archived": conv["archived"],
            "updated_at": conv["updated_at"]}


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
    """重命名(title)与归档/恢复(archived)。"""
    ok = False
    if "title" in body:
        ok = db.rename_conversation(conversation_id, user["id"], str(body.get("title") or ""))
    if "archived" in body:
        ok = db.set_conversation_archived(conversation_id, user["id"], bool(body.get("archived"))) or ok
    if not ok:
        raise HTTPException(404, "会话不存在")
    conv = db.get_conversation(conversation_id, user["id"])
    return {"id": conversation_id, "title": conv["title"], "archived": conv["archived"]}


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


# ---------- P4b-0 前端拆分:静态资源挂载(本单对 main.py 的唯一改动) ----------
# 显式给 media_type:Windows 下 mimetypes 受注册表影响,若 .js 被判成 text/plain
# 浏览器会因严格 MIME 校验拒绝执行脚本 → 拆分后页面白屏。故不走 StaticFiles 猜测。
_WEB_MEDIA = {".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8"}


def _serve_web_asset(sub: str, name: str) -> FileResponse:
    root = (WEB_DIR / sub).resolve()
    target = (root / name).resolve()
    if not str(target).startswith(str(root)) or target.suffix != "." + sub or not target.is_file():
        raise HTTPException(404, "资源不存在")
    return FileResponse(target, media_type=_WEB_MEDIA[target.suffix])


@app.get("/css/{name}")
async def css_asset(name: str):
    return _serve_web_asset("css", name)


@app.get("/js/{name}")
async def js_asset(name: str):
    return _serve_web_asset("js", name)

