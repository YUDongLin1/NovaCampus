"""P4d: LangGraph 检索编排(只做状态机编排,不接管模型/向量)。

边界(与 Qoder 约定):
  - LLM 仍走 `llm.py`(httpx,OpenAI 兼容模式);向量仍走 numpy 内存余弦(`rag.py`);
    **不引入 langchain 的模型/向量/retriever 封装**;
  - P4a 硬门控只调用、不削弱:`refusal.should_refuse / build_refusal` 仍在 agent 层;
    graph 只决定"要不要再改写一次"以及"最终交给 agent 的 sources/quality";
  - P4c 的 scope 是**入口唯一性**:graph 内任何检索都使用 main 层 `_resolve_scope`
    解析出来的 scope(由 agent 传入),**不自行构造 scope、不绕过解析**。

图:
  intent ─┬─(chitchat) → direct
          ├─(time)     → direct(正则 + datetime,不调 LLM)
          └─(retrieval/降级) → retrieve → grade ┬─达标 → done(交回 agent 生成)
                                                ├─可改写 → rewrite → retrieve(≤MAX_REWRITE)
                                                └─否则 → refuse(交回 agent 走 P4a 硬门控)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from . import config, llm, rag


class GraphState(TypedDict, total=False):
    """编排状态(**必须显式声明通道**)。

    踩坑记录:用裸 `dict` 作 StateGraph 的 schema 时,LangGraph 无法推导通道,
    `ainvoke` 的返回值只保留**最后一个节点**返回的键(实测 `{'y': 2}`,先前的键全部丢失),
    表现为节点里 `s['question']` 抛 KeyError('question')。必须用 TypedDict + total=False
    让每个键成为一个可选通道,节点即可安全地只返回增量。
    """
    question: str
    min_rank: int
    scope: dict | None
    model: str
    base_url: str
    api_key: str
    query: str
    plan: list
    trace: list
    attempts: int
    sources: list
    quality: dict
    rewritten: bool
    last_query: str
    intent: str
    audience_hint: str
    mode: str
    answer: str
    do_refuse: bool
    reason: str
    retrieval_skipped: bool

# ---- 时间与闲聊(不调 LLM) ----
_TIME_RE = re.compile(r"(几点|什么时间|现在时间|当前时间|今天几号|几月几号|星期几|周几|哪天|今天.*日期|今天是什么日子)")
_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
# 与 agent.history_gate_hit 同口径的归一化正则(去标点/空白,只留中英数字符)
_NORM_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")


def time_direct_answer(question: str) -> str | None:
    """问时间/日期类:正则 + datetime 直答,**不调 LLM**。命中返回答案,否则 None。"""
    if not _TIME_RE.search(question or ""):
        return None
    now = datetime.now()
    return (f"现在是 {now.strftime('%Y年%m月%d日')} {_WEEKDAYS[now.weekday()]} "
            f"{now.strftime('%H:%M')}。如果您要问的是学校的办事时间或截止日期，"
            "请告诉我具体事项，我在知识库里查。")


INTENT_PROMPT = """你是意图分类器。判断用户这句话是否需要检索学校知识库来回答。

只输出严格 JSON,不要解释(**下面 JSON 示例中的花括号是字面量,已按 str.format 规则写成双花括号**):
{{"intent":"chitchat|time|retrieval","need_retrieval":true|false,
 "audience_hint":"undergrad|postgrad|common|","normalized_query":"..."}}

规则:
1. 打招呼、闲聊、问你是谁、问能力 → intent="chitchat", need_retrieval=false;
2. 问当前时间/日期/星期 → intent="time", need_retrieval=false;
3. 需要学校政策/流程/材料/金额/时限/条款等事实 → intent="retrieval", need_retrieval=true;
4. normalized_query:把口语问法改写成**材料里会出现的规范表述**——
   - 展开同义术语(学平险→学生平安保险/大学生意外伤害保险,医保→大学生医疗保险);
   - 去掉称呼与情境噪声("老师我想问下""我看计财处只有医保这项"这类铺垫);
   - 保留学段限定(本科生/研究生)与核心意图词(办理/投保/理赔/材料/时限);
   - 只输出一条检索式短句,**不要回答用户的问题**。

用户原话:{q}"""

REWRITE_PROMPT = """你是高校知识库的检索式改写器。上一次检索没召回到达标材料。

把问句改写成**材料正文里更可能出现的规范表述**:
1. 同义术语展开(学平险 ↔ 学生平安保险 ↔ 大学生意外伤害保险;医保 ↔ 大学生医疗保险 ↔ 城乡居民基本医疗保险);
2. 意图归一("在哪里买/怎么办的/是否统一办理" → "办理 投保 参保";"怎么报/能报多少" → "理赔 报销");
3. 去掉情境噪声与称呼(老师/我想问下/我看计财处…这类与检索无关的表述);
4. 保留学段与对象限定(本科生/研究生/新生);
5. 只输出**一条**检索式短句(8~30 字,关键词式,不要问号,不要解释)。

原始问句:{q}
上一次改写(若无可忽略):{prev}"""


def _strip_noise(q: str) -> str:
    """确定性地去情境噪声(不依赖 LLM)。"""
    out = (q or "").strip()
    for pat in config.NOISE_PATTERNS:
        out = re.sub(pat, "", out).strip()
    return out or (q or "").strip()


def dict_core_terms(q: str) -> list[str]:
    """问句命中的**词典核心术语**(长词优先,避免"医保"吃掉"大学生医疗保险")。

    作用有二:① 归一式的锚点;② LLM 改写的**跑题护栏**——只有问到已知核心术语的问句
    才允许交给 LLM 改写,否则域外问句可能被改写成库内主题、把"该拒答"变成"答错题"。
    """
    base = _strip_noise(q)
    out: list[str] = []
    for k in sorted(config.TERM_EXPANSION, key=len, reverse=True):
        if k in base and not any(k in o for o in out):
            out.append(k)
    return out


def normalize_query(q: str) -> str:
    """C1 范式:去噪 + 词典核心术语 + 其全部同义词(**改写主力**,确定性、零 LLM 依赖)。

    实测依据(`docs/p4d/probe_normalize_variants.py`,同一 corpus):
      F2 崩塌的 6 条学平险问法(原句/术语+意图/书面正式名/口语称呼情境/背景前置倒装)
      在 C1 归一后 rerank 峰值 0.10~0.19 → **0.968~0.992**、n_above 0→3~4;
      无词典命中的域外问句(量子计算实验室开放日)**逐字不变**,零误伤。
    无核心术语时退化为"仅去噪";连去噪也无变化时返回空串(表示无可用的确定性改写)。
    """
    base = _strip_noise(q)
    core = dict_core_terms(q)
    if not core:
        return base if base != (q or "").strip() else ""
    parts: list[str] = list(core)
    for k in core:
        for a in config.TERM_EXPANSION[k]:
            if a not in parts:
                parts.append(a)
    return " ".join(dict.fromkeys(parts))


def expand_terms(q: str) -> str:
    """**追加式**术语展开(保留原句,仅在其后补同义词)。

    与 normalize_query 的区别:本函数保留整句噪声,实测在含长噪声的问句上 rerank 只有
    0.47~0.80 且 n_above=1(撞「单来源放行线 0.9」),故**降级为兜底**;
    主力是 normalize_query(关键词式)。保留此实现供 A/B 对照与异常回退。
    """
    base = _strip_noise(q)
    extra: list[str] = []
    for term, alts in config.TERM_EXPANSION.items():
        if term in base:
            for a in alts:
                if a not in base and a not in extra:
                    extra.append(a)
    return (base + " " + " ".join(extra)).strip() if extra else base


def build_rewrite_plan(q: str) -> list[tuple[str, str]]:
    """有序改写计划:第 1 档=确定性归一(主力),第 2 档=LLM 改写(辅助,带术语锚点护栏)。

    只收录"与原句不同"的档位;两者都不可用 → 空计划 → 直接走拒答(不浪费 LLM 往返,
    也避免把域外问题改写进库内主题)。档位上限由 config.MAX_REWRITE 截断。
    """
    plan: list[tuple[str, str]] = []
    norm = normalize_query(q)
    if norm and norm != (q or "").strip():
        plan.append(("normalize", norm))
    if dict_core_terms(q):  # 有术语锚点才允许 LLM 改写
        plan.append(("llm", ""))
    return plan[: max(0, config.MAX_REWRITE)]


async def _llm_json(prompt: str, model: str, timeout_s: float,
                    base_url: str = "", api_key: str = "") -> dict:
    """一次轻量 LLM 调用(temperature 0),带超时;失败抛异常由调用方降级。

    base_url/api_key 必须透传用户生效 LLM(自定义 API 接入),否则会静默走全局 key。
    """
    msg = await asyncio.wait_for(
        llm.chat([{"role": "user", "content": prompt}], model=model, max_tokens=200, temperature=0,
                 base_url=base_url, api_key=api_key),
        timeout=timeout_s,
    )
    txt = (msg.get("content") or "").strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```[a-zA-Z]*|```$", "", txt).strip()
    start, end = txt.find("{"), txt.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型未返回 JSON")
    return json.loads(txt[start:end + 1])


# ---------------- 节点 ----------------

async def node_intent(s: dict) -> dict:
    q = s["question"]
    t0 = time.time()
    trace = list(s.get("trace") or [])
    if time_direct_answer(q):
        trace.append({"node": "intent", "ms": round((time.time() - t0) * 1000),
                      "intent": "time", "llm_called": False})
        return {"intent": "time", "trace": trace}
    try:
        d = await _llm_json(INTENT_PROMPT.format(q=q), s.get("model") or config.LLM_MODEL,
                            config.INTENT_TIMEOUT_S, s.get("base_url") or "", s.get("api_key") or "")
        intent = d.get("intent") or ("retrieval" if d.get("need_retrieval") else "chitchat")
        if intent not in ("chitchat", "time", "retrieval"):
            intent = "retrieval"
        trace.append({"node": "intent", "ms": round((time.time() - t0) * 1000),
                      "intent": intent, "llm_called": True,
                      "normalized_query": d.get("normalized_query") or ""})
        # ⚠ 首轮检索**必须用原句**:P4d 的改写能力全部挂在"未达标 → rewrite"分支上,
        # 首轮保持原句可保证"本来能过的用例逐字不变"(零回归的第一道保险)。
        # intent 产出的 normalized_query 仅入 trace 供复盘,不参与首轮检索。
        return {"intent": intent, "audience_hint": d.get("audience_hint") or "", "trace": trace}
    except Exception:  # 路由挂了不能不答 → 降级为默认走检索
        trace.append({"node": "intent", "ms": round((time.time() - t0) * 1000),
                      "intent": "retrieval(fallback)", "llm_called": True, "error": True})
        return {"intent": "retrieval", "query": q, "trace": trace}


async def node_direct(s: dict) -> dict:
    q = s["question"]
    trace = list(s.get("trace") or [])
    # C3 断言锚点:direct 路径必须留下"检索被跳过"的显式标记(评测断言 retrieval_skipped=true)
    trace.append({"node": "retrieve", "skipped": True, "reason": f"intent={s.get('intent')}",
                  "n_sources": 0})
    if s.get("intent") == "time":
        return {"mode": "direct", "answer": time_direct_answer(q) or "", "sources": [],
                "quality": {"top_score": None, "n_above_threshold": 0, "rerank_available": False,
                            "fused_candidates": 0},
                "do_refuse": False, "reason": "", "retrieval_skipped": True, "trace": trace}
    return {"mode": "direct",
            "answer": ("我是校园智能助手，可以查学校的政策流程、奖助学金、学籍与保险等材料，"
                       "也可以帮你整理周报。直接把问题发给我就行。"),
            "sources": [],
            "quality": {"top_score": None, "n_above_threshold": 0, "rerank_available": False,
                        "fused_candidates": 0},
            "do_refuse": False, "reason": "", "retrieval_skipped": True, "trace": trace}


async def node_retrieve(s: dict) -> dict:
    t0 = time.time()
    q = s.get("query") or s["question"]
    # P4c 硬约束:scope 只能来自 main 层 _resolve_scope 的解析结果(由 agent 透传)
    sources, quality = await rag.search_with_quality(q, s["min_rank"], scope=s.get("scope"))
    trace = list(s.get("trace") or [])
    trace.append({"node": "retrieve", "ms": round((time.time() - t0) * 1000), "query": q,
                  "n_sources": len(sources), "top_score": quality.get("top_score"),
                  "n_above_threshold": quality.get("n_above_threshold"),
                  "fused_candidates": quality.get("fused_candidates")})
    attempts = int(s.get("attempts") or 0) + 1
    out = {"sources": sources, "quality": quality, "trace": trace, "attempts": attempts,
           "last_query": q}
    if attempts == 1:  # 首轮算出改写计划(固定下来,后续档位按序取用)
        out["plan"] = build_rewrite_plan(s["question"])
    return out


def _worth_rewriting(s: dict) -> bool:
    """是否还有可用的改写档位。

    P4d 修正(T10/T13 的"分数地板"教训):**不再**用 rerank 绝对值判断"库里有没有这个主题"
    ——实测 rerank 在本 corpus 上会把正确候选整体压到 0.03~0.19,绝对值不可作主题判据
    (`docs/p4d/probe_rerank_dist.py`:目标材料常在融合第 1 位却只得 0.10)。
    改为:有候选可谈 + 改写计划里还有未用档位。
    """
    plan = s.get("plan") or []
    idx = int(s.get("attempts") or 0) - 1
    if idx < 0 or idx >= len(plan):
        return False
    if not (s.get("quality") or {}).get("fused_candidates"):
        return False
    return True


def grade_ok(q: dict) -> bool:
    return (q or {}).get("top_score") is not None and (q.get("top_score") or 0) >= config.GRADE_MIN_SCORE \
        and (q.get("n_above_threshold") or 0) >= config.GRADE_MIN_ABOVE


def route_after_grade(s: dict) -> str:
    if grade_ok(s.get("quality")):
        return "done"
    if _worth_rewriting(s):
        return "rewrite"
    return "refuse"


async def node_rewrite(s: dict) -> dict:
    """按计划逐档改写:第 1 档=确定性归一(主力),第 2 档=LLM 改写(辅助,带护栏)。"""
    t0 = time.time()
    q0 = s["question"]
    prev = s.get("last_query") or q0
    plan = s.get("plan") or []
    idx = int(s.get("attempts") or 0) - 1
    kind = plan[idx][0] if 0 <= idx < len(plan) else "normalize"
    if kind == "normalize":
        cand = plan[idx][1]
    else:
        cand = ""
        try:
            msg = await asyncio.wait_for(
                llm.chat([{"role": "user", "content": REWRITE_PROMPT.format(q=q0, prev=prev)}],
                         model=s.get("model") or config.LLM_MODEL, max_tokens=64, temperature=0,
                         base_url=s.get("base_url") or "", api_key=s.get("api_key") or ""),
                timeout=config.REWRITE_TIMEOUT_S)
            cand = (msg.get("content") or "").strip().strip("。.\n").replace("\n", " ")
            cand = re.sub(r"^[\"'「『].*?[\"'」』]", "", cand).strip()
        except Exception:  # 改写失败 → 退回确定性归一(仍是一次有效尝试)
            cand = ""
        if not (4 <= len(cand) <= 60):
            cand = ""
        if cand and not _topic_kept(q0, cand):  # 跑题护栏:LLM 输出必须与问句同主题
            cand = ""
        if not cand:
            cand = normalize_query(q0) or expand_terms(q0)
    trace = list(s.get("trace") or [])
    trace.append({"node": "rewrite", "ms": round((time.time() - t0) * 1000), "strategy": kind,
                  "from": prev, "to": cand, "attempt": int(s.get("attempts") or 0)})
    return {"query": cand, "trace": trace, "rewritten": True}


def _topic_kept(original: str, candidate: str) -> bool:
    """LLM 改写跑题护栏(代码级,不信任模型自述)。

    判定:候选式必须与问句共享 **≥2 个非停用字符 2-gram**,或共享一个词典核心术语
    ——否则视为跑题(例:把"量子计算实验室开放日预约"改写成"学生平安保险"))
    ,该档作废退回确定性归一。
    """
    a = _NORM_RE.sub("", original or "")
    b = _NORM_RE.sub("", candidate or "")
    if not a or len(b) < 3:
        return False
    for k in dict_core_terms(original):
        if k in b:
            return True
    stop = config.KEYWORD_STOPWORDS
    ga = {a[i:i + 2] for i in range(len(a) - 1)} - stop
    gb = {b[i:i + 2] for i in range(len(b) - 1)} - stop
    return len(ga & gb) >= 2


async def node_refuse(s: dict) -> dict:
    return {"mode": "refuse", "do_refuse": True, "reason": "graph_not_graded"}


async def node_done(s: dict) -> dict:
    return {"mode": "generate", "do_refuse": False, "reason": ""}


# ---------------- 对外入口 ----------------

def _build_graph():
    g = StateGraph(GraphState)
    g.add_node("intent", node_intent)
    g.add_node("direct", node_direct)
    g.add_node("retrieve", node_retrieve)
    g.add_node("rewrite", node_rewrite)
    g.add_node("refuse", node_refuse)
    g.add_node("done", node_done)
    g.set_entry_point("intent")
    g.add_conditional_edges("intent", lambda s: "direct" if s.get("intent") in ("chitchat", "time") else "retrieve",
                            {"direct": "direct", "retrieve": "retrieve"})
    g.add_edge("direct", END)
    g.add_conditional_edges("retrieve", route_after_grade,
                            {"done": "done", "rewrite": "rewrite", "refuse": "refuse"})
    g.add_edge("rewrite", "retrieve")
    g.add_edge("refuse", END)
    g.add_edge("done", END)
    return g.compile()


_GRAPH = None


def _graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = _build_graph()
    return _GRAPH


async def run_pipeline(question: str, min_rank: int, scope: dict | None = None,
                       model: str = "", base_url: str = "", api_key: str = "") -> dict:
    """完整编排入口(供 agent 调用)。

    返回 dict:
      mode      'direct'(闲聊/时间直答) | 'generate'(交回 agent 生成) | 'refuse'(交回 agent 走 P4a 硬门控)
      answer    mode=direct 时的确定性文案
      sources / quality  检索结果(未达标时为空/低分)
      trace     检索轨迹(落 conversations.retrieval_trace,评测断言 skipped/rewrite 用)
      do_refuse / reason / intent / attempts / rewritten / audience_hint
    """
    t0 = time.time()
    state: dict[str, Any] = {"question": question, "min_rank": min_rank, "scope": scope,
                             "model": model, "base_url": base_url, "api_key": api_key,
                             "query": question, "trace": [], "attempts": 0, "plan": [],
                             "sources": [], "quality": {}, "rewritten": False}
    try:
        out = await _graph().ainvoke(state)
    except Exception as e:  # 编排整体失败 → 降级为"普通检索一次",绝不阻断回答
        logging.getLogger("novaagent.graph").exception("graph 编排异常,降级为单遍检索")
        sources, quality = await rag.search_with_quality(question, min_rank, scope=scope)
        return {"mode": "generate" if grade_ok(quality) else "refuse", "answer": "",
                "sources": sources, "quality": quality, "do_refuse": not grade_ok(quality),
                "reason": "graph_fallback", "intent": "retrieval(fallback)", "attempts": 1,
                "rewritten": False, "trace": [{"node": "pipeline", "error": str(e)[:120]}],
                "ms": round((time.time() - t0) * 1000)}
    out["ms"] = round((time.time() - t0) * 1000)
    out.setdefault("retrieval_skipped", False)
    return out


async def retrieve_with_retry(question: str, min_rank: int, scope: dict | None = None,
                              model: str = "", max_rewrite: int | None = None,
                              base_url: str = "", api_key: str = "") -> dict:
    """只跑 retrieve → grade → rewrite 循环(不含意图判定),供评测矩阵与诊断脚本使用。

    返回 {sources, quality, trace, attempts, rewritten, final_query}。
    """
    max_rewrite = config.MAX_REWRITE if max_rewrite is None else max_rewrite
    state: dict[str, Any] = {"question": question, "query": question, "min_rank": min_rank,
                             "scope": scope, "model": model, "base_url": base_url,
                             "api_key": api_key, "trace": [], "attempts": 0, "plan": [],
                             "sources": [], "quality": {}, "rewritten": False}
    for _ in range(max_rewrite + 2):
        st = await node_retrieve(state)
        state.update(st)
        if max_rewrite != config.MAX_REWRITE:  # 消融对照:截断改写档位(0 = 退化为单遍)
            state["plan"] = (state.get("plan") or [])[:max_rewrite]
        if grade_ok(state["quality"]):
            break
        if not _worth_rewriting(state):
            break
        state.update(await node_rewrite(state))
    return {"sources": state["sources"], "quality": state["quality"], "trace": state["trace"],
            "attempts": state["attempts"], "rewritten": state.get("rewritten", False),
            "final_query": state.get("last_query") or question}
