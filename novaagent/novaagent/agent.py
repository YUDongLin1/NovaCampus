"""Agent 编排层:RAG 上下文注入 + 工具调用循环(周报 MCP 工具)

引用约定:检索结果编号 [1]..[n] 注入 system prompt,要求模型回答时标注引用,
来源列表随答案一并返回给前端渲染。
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from typing import Any

from . import asr, config, db, graph, llm, rag, refusal, websearch
from . import minutes as minutes_lib
from . import talk_summary
from .weekly_client import WeeklyMCP
from .prompts import (_BASE_IDENTITY, _BASE_STYLE, _HARD_RULES, _INJECTION_DEFENSE,
                        _PERSONA_INJECTION_MARK, _REGEN_HINT, _STYLE_HINTS, COMPRESS_PROMPT,
                        EXPAND_PROMPT, HISTORY_GATE_NOTE, SUMMARY_PROMPT, WEB_CONTEXT_BLOCK)

logger = logging.getLogger(__name__)








def build_system_prompt(persona: dict | None = None, ctx_local: str = "",
                        ctx_web: str = "") -> str:
    """组装 system prompt: **硬编码规则段 + persona 段 + 资料段**。

    结构(P4f C2 的核心):
        1. 基础身份
        2. **规则段 `_HARD_RULES`——模块级常量,无插值入口,persona 改不了**
        3. persona 段(人设提示词 + 风格),带注入防御标记
        4. 资料段(本地检索 + 联网分区)

    ⚠ 顺序不可调:规则段必须在 persona 段**之前**。放在之后等于让最后一句生效,
      那正是 prompt 注入最常见的利用方式(见 `novaagent/tests/test_p4f_persona.py`
      的顺序断言)。

    ⚠ **无 persona 时本函数与 P4e 的 SYSTEM_PROMPT 逐字等价**(有断言守着)。
      注入防御段只在**有 persona 时**才加——它是为了防 persona 段里的注入,
      没有 persona 就没有注入面,加了就是无谓的 prompt 噪声(还会让"零回归"
      变成一句无法验证的口头保证)。
    """
    if not persona:
        return legacy_system_prompt(ctx_local if ctx_local else "")

    parts: list[str] = [_BASE_IDENTITY, _HARD_RULES, _INJECTION_DEFENSE, _BASE_STYLE]

    seg: list[str] = []
    name = (persona.get("name") or "").strip()
    college = (persona.get("college") or "").strip()
    identity = "、".join(x for x in (name, college and f"{college}学院") if x) or "校园辅导员"
    seg.append(f"{_PERSONA_INJECTION_MARK}\n你现在担任「{identity}」,面向本校学生提供事务咨询与解答。")
    prompt = (persona.get("persona_prompt") or "").strip()
    if prompt:
        seg.append(f"人设补充(仅影响语气与侧重点):{prompt}")
    style = persona.get("style") or "balanced"
    seg.append(_STYLE_HINTS.get(style, _STYLE_HINTS["balanced"]))
    bound = persona.get("bound_folder_ids") or []
    cats = persona.get("bound_categories") or []
    if bound or cats:
        # 如实告诉模型范围,避免它以为能引用范围外的内容
        scope_desc = []
        if bound:
            scope_desc.append(f"指定文件夹 {len(bound)} 个")
        if cats:
            scope_desc.append("指定分类:" + "、".join(str(c) for c in cats))
        seg.append("检索范围提示:本次优先参考" + "、".join(scope_desc) +
                   "内的资料;范围外资料同样按第 1–9 条处理,不得越界引用。")
    parts.append("\n".join(seg))

    body: list[str] = []
    body.append("知识库资料(当前用户角色可见范围内检索):")
    body.append(ctx_local or "(本角色可见范围内未检索到相关资料)")
    if ctx_web:
        body.append(ctx_web)
    parts.append("\n".join(body))
    return "\n\n".join(parts) + "\n"


def legacy_system_prompt(context: str = "") -> str:
    """P4e 及之前的拼装口径(**无 persona 时与 build_system_prompt 逐字等价**)。

    保留它是为了给「零回归」提供一条可离线比对的基线:
    `build_system_prompt(None, ctx) == legacy_system_prompt(ctx)`。
    没有这条基线,任何 prompt 重组都只能靠"跑整轮评测看有没有变红"来判断,
    而那要烧额度(硬约束第 7 条)且不能定位到是哪一句变了。
    """
    return "\n\n".join([_BASE_IDENTITY, _HARD_RULES, _BASE_STYLE,
                        "知识库资料(当前用户角色可见范围内检索):\n" + (context or "")]) + "\n"


# 保留旧名以免既有引用 ImportError(P4b 起的两处调用点已改用 build_system_prompt)。
SYSTEM_PROMPT = legacy_system_prompt




def est_tokens(text: str) -> int:
    """P4b C3: token 估算——ceil(chars/1.6)(中文经验值)。⚠ 这是估算值,非精确分词,
    未引入 tokenizer 依赖;口径与偏差说明见 docs/P4B.md。"""
    return math.ceil(len(text or "") / 1.6)


# ---------- 成本可见性与工具结果护栏(T13 成本审计) ----------
#
# 【为什么护栏定在 12,000 tok 而不是 2,000】工具返回值会进 messages 并在**后续每一轮
#   工具调用**里重发(非流式 ≤3 轮 / 流式 ≤4 轮)。实测现库一次 `list_fragments` 全表
#   返回 ≈8.5k~9.9k tok(`data/weekly/weekly.db` 93 条 fragments),相当于 6 个典型请求
#   (输入 p50=1,580 tok)的量。把上限压到 2k 能省最多,但那会**改变模型可见内容**
#   (它看不到全部碎片),必须先有评测对比才能动 —— 见成本审计报告「待验证」。
#   12,000 高于现库实测最大值,因此**不改变现网任何一次输出**,只兜住未来的异常增长。
TOOL_RESULT_MAX_TOKENS = int(config.env("NOVA_TOOL_RESULT_MAX_TOKENS", "12000"))
TOOL_RESULT_MAX_CHARS = int(TOOL_RESULT_MAX_TOKENS * 1.6)


def cap_tool_result(payload: object) -> str:
    """序列化工具结果;超硬上限则截断并**留下可见标记**(坑 46:静默截断=丢内容没人知道)。"""
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) <= TOOL_RESULT_MAX_CHARS:
        return text
    logger.warning("工具结果被硬上限截断: %d 字 > %d 字(上限 %d tok)",
                   len(text), TOOL_RESULT_MAX_CHARS, TOOL_RESULT_MAX_TOKENS)
    return (text[:TOOL_RESULT_MAX_CHARS]
            + f"\n…[已截断:原结果 {len(text)} 字。需要完整内容请用 start_date/end_date "
              f"缩小日期范围后重新调用本工具]")


def request_token_profile(messages: list[dict]) -> dict:
    """按项目口径估一次请求的输入构成。**只读数,不改内容、不发请求。**
    存在的理由:此前全项目没有任何一处能看到"这一轮到底发了多少 token",
    成本只能靠事后估算(见 reports/ 与成本审计);有了它,trace 里就能直接读。"""
    by_role = {"system": 0, "user": 0, "assistant": 0, "tool": 0}
    total = 0
    for m in messages:
        t = est_tokens(str(m.get("content") or "")) + 4
        total += t
        role = m.get("role")
        if role in by_role:
            by_role[role] += t
    return {"est_input_tokens": total, "by_role": by_role, "messages": len(messages)}



# P4e M4:生成出口的**确定性闸门**——「有来源却零可核查事实」判为无效答案,触发**一次**重生。
#
# 【为什么放代码不放 prompt】本项目铁律「判定放代码,不放 prompt」(P4a C1 / 坑 21):
# prompt 只是"建议",模型可以不听;代码是判定。SYSTEM_PROMPT 第 1/3 条早已要求
# 「事实性主张必须锚定来源、引用标注 [编号] 紧跟对应句子」,但**没有强制力**——
# 实测 qa-17 会偶发输出「以下依据本科生办法,研究生相关规定未在知识库覆盖,请以…为准」(41 字),
# 零引用零数字,实质**没有回答用户问什么**。评测侧 P4d-fix ④ 的非答案检测能抓住它,
# 但那是**事后**判红;本闸门是**当场**拦住并重生一次。
#
# 【判据】sources 非空 且 答案既无 [n] 引用标记又无数字 → 无效。
#   - 复用评测侧同一把尺子(`_FACTUAL = r"\[\d+\]|\d"`),口径一致,不与评测打架。
#   - ⚠ 刻意**不判长度**:长度阈值会把"短真答案"误杀(P4d-fix ④ 已踩过,见 run_evals.py 注释)。
#   - ⚠ `sources` 为空时**不适用**——那是拒答路径,走 refusal 确定性模板,不经 LLM。
# 【失败后不许静默兜底】重生仍不合格 → **保留答案**、写 trace flag + 记 badcase,
#   评测照旧判红。静默兜底会把缺陷藏起来(坑 46/47),宁可让闸门显式地失败。
_FACTUAL_RE = re.compile(r"\[\d+\]|\d")

# P4e M-A:正文里**逐句绑定**的联网角标 `[W<n>]` —— 上游无「句子 ↔ URL」映射,写了就是假精确。
# 实测 wg-01 首轮模型即写出 `[W3]`(尽管 WEB_CONTEXT_BLOCK 明令禁止)→ 与 P4a 同源:
# **prompt 挡不住,必须落代码**。剥离时记 warning,不是静默兜底。
_WEB_CITATION_RE = re.compile(r"\[W\d{1,2}\]")


def strip_web_citations(answer: str) -> tuple[str, int]:
    """剥离答案正文里的 `[W<n>]` 角标,返回 (清理后答案, 剥离处数)。纯函数,可单测。

    ⚠ 只处理 `[W<n>]` 这一种;本地 `[1..n]` 归 P4a C2 的 `strip_invalid_refs` 管,互不越界。
    """
    hits = _WEB_CITATION_RE.findall(answer or "")
    if not hits:
        return answer, 0
    logger.warning("答案正文出现逐句绑定的 [W<n>] 角标 %d 处,已代码剥离"
                   "(上游只给 {type,url},无句子↔来源映射)", len(hits))
    return _WEB_CITATION_RE.sub("", answer or ""), len(hits)


def answer_is_grounded(answer: str, sources: list) -> bool:
    """答案是否「有据」:有来源 且 含 [n] 引用标记或具体数字。纯函数,可单测。"""
    if not sources:
        return True   # 无来源 = 拒答路径,不走本闸门
    return bool(_FACTUAL_RE.search(answer or ""))


# ---------- P4f C0-③: 轮次类型判定(闸门作用域) ----------
# 背景:闸门判据「有来源 却 零 [n] 零数字」不问**这一轮是否期待事实回答**,
# 于是被套到「往会话里塞背景资料」的种植轮上——P4e S2 实测命中 12~16 次、
# 重生失败 11~14 次**全在种植轮**,`final` 轮一次未命中(坑 64)。
#
# 【为什么判据必须是语义级,不能用「长度 < 30 字」】
#   长度既不是轮次类型的证据,也会随问句改写漂移:一句「好的」是 3 字但**期待事实**
#   (「好的,那学费是多少?」的后续),而 42 轮的种植文本每轮都 >300 字却是**纯陈述**。
#   换句话说长度与「是否期待事实回答」**不单调**,按它分档必然错一批(坑 63 的同族)。
#   正确做法是问「**用户这一轮在要什么**」,那是句子的语义属性,不是长度属性。
#
# 【判据:两类信号,任一命中即视为「本轮不期待事实回答」】
#   A. 抑制型元指令(suppressive meta-instruction)——用户**明确要求不要展开作答**:
#      「已阅/知悉/仅供知悉/无需回复/简短回复/不必回答/请勿调用工具/不要记录」等。
#      判据是**出现了要求抑制作答的祈使语**,不是「答案短」。
#   B. 纯陈述轮(non-interrogative)——整句**没有任何疑问/请求标记**:
#      疑问词(吗/呢/什么/哪些/怎么/如何/为什么/多少/几/是否/能否/可否)、
#      请求动词(查/找/问/列/说/解释/介绍/告诉/算/填/写/改/查一下…)+ 问号/冒号请求式。
#      纯背景陈述(「本条为背景资料:…」)落在这一类。
#
# 【为什么要 A 与 B 分开而不是合成一条】
#   A 是**用户显式收回提问权**(他说了"只需回已阅"),优先级高于任何疑问句——
#   哪怕句尾带问号,只要同句出现抑制语,本轮也不该被要求给事实。
#   B 是**句式本身没有请求**。分开写的好处:两类的可观测后果不同
#   (A 会有"简短回复"字样,B 完全没有请求词),复核方能按类核对,不会混成一句口径。
#
# ⚠ 边界(必须诚实标出,不要假装判据完美):
#   · 判据是**词法级**的,不是语义理解。极端构造的句子仍可能判错
#     (例:「请勿回答,顺便告诉我学费多少」——A 命中 → 判为非事实轮)。
#     本单**接受**这个边界:宁可漏判一轮(闸门少拦一次,答案原样返回、评测照常判红),
#     不可错判(闸门逼模型在纯陈述轮上编造引用,那才是真的伤害)。
#     方向性不对称是刻意的,与 P4a「宁多拒答不可无据作答」一致。
#   · 不改 `refusal.py`、不引入新模型调用(判据是纯字符串函数,零额度)。
_SUPPRESSIVE_MARKERS = (
    "已阅", "知悉", "仅供知悉", "仅供参考", "无需回复", "不用回复", "不必回复", "无需回答",
    "不用回答", "不必回答", "简短回复", "简要回复", "简短回答", "回复即可", "回答即可",
    "不用展开", "无需展开", "不必展开", "请勿调用", "不要调用", "无需调用", "不用调用",
    "不要记录", "无需记录", "不必记录", "不要生成", "无需生成", "仅作存档", "存档即可",
    "不用作答", "无需作答", "不作答", "不要作答", "别回答", "不用回答",
    # 「请勿回答」类:祈使 + 否定动词,单列是因为它是评测/教学场景最常见的抑制措辞,
    # 而「不用回答/无需回答」是同义变体,三者都要拦住(漏一个就等于闸门可被绕过)。
    "请勿回答", "请勿作答", "请勿展开", "无需再答", "不用再答", "不必再答",
)
_QUESTION_MARKERS = (
    "吗", "呢", "什么", "哪些", "哪个", "怎么", "怎样", "如何", "为什么", "为何", "多少",
    "几", "是否", "能否", "可否", "能不能", "可不可以", "多久", "何时", "什么时候", "在哪",
    "是谁", "哪些个", "几岁", "要不要", "行不行", "好不好", "可以吗",
)
_REQUEST_VERBS = (
    "查", "找", "问", "列", "说出", "解释", "介绍", "告诉", "算", "填写", "写", "改",
    "看一下", "查一下", "看一下", "确认", "核实", "对比", "比较", "申请", "办理", "报名",
)


def turn_expects_factual_answer(question: str) -> tuple[bool, str]:
    """本轮是否**期待事实回答**。返回 (bool, 判定依据标签)。纯函数,可单测。

    标签取值(供 `ctx_info["grounding_gate"]["scope"]` 落进评测报告,让"这轮为什么
    没被闸门管"在报告里**可自证**,而不是靠事后猜——坑 64 的教训是评测侧不留痕
    就只能靠"最可疑是 cc-01"这种猜测):
      · ``suppressed``  A 类命中:用户显式要求抑制作答(种植轮)
      · ``non_interrogative`` B 类命中:句式无任何疑问/请求标记(纯陈述轮)
      · ``factual``     两者都没命中 → 本轮期待事实回答 → 闸门应当生效
    """
    q = (question or "").strip()
    if not q:
        # 空问题:无内容可答,判为非事实轮(闸门不该逼模型为一个空问句编引用)
        return False, "non_interrogative"
    for m in _SUPPRESSIVE_MARKERS:
        if m in q:
            return False, "suppressed"
    has_q = any(m in q for m in _QUESTION_MARKERS) or "?" in q or "？" in q
    has_req = any(m in q for m in _REQUEST_VERBS)
    if not has_q and not has_req:
        return False, "non_interrogative"
    return True, "factual"


def grounding_gate_applies(question: str) -> tuple[bool, str]:
    """闸门是否作用于本轮 = 闸门开关开 且 本轮期待事实回答。

    `GROUNDING_GATE_SCOPE_MODE`:
      · ``factual_turns``(本单默认)→ 只对期待事实回答的轮次生效
      · ``all_turns``               → 退回 P4e 行为(全轮次都管),仅供 A/B 对照
    """
    if config.GROUNDING_GATE_SCOPE_MODE == "all_turns":
        return True, "all_turns"
    ok, label = turn_expects_factual_answer(question)
    return ok, label


def regen_messages(messages: list[dict], bad_answer: str) -> list[dict]:
    """构造重生的 messages:保留原上下文,追加上一版答案 + 强制要求(**只带问题,不外泄库内文本**)。"""
    return messages + [
        {"role": "assistant", "content": bad_answer},
        {"role": "user", "content": _REGEN_HINT.strip()},
    ]


def record_ungrounded(question: str, answer: str, n_sources: int, stage: str) -> None:
    """P4e M4:把一次「重生后仍零可核查事实」记入 evals/badcases.json(ungrounded 案)。

    与 `refusal.record_fabricated_ref` 同机制(同一文件、同 50 条滚动上限、同一主键合并口径),
    但**独立开一个 case id** —— 两者是不同缺陷,混在一个 case 里会让排障分不清是越界引用还是无据答案。

    ⚠ 尽力而为:任何失败只记日志,**绝不影响对话主流程**(与既有实现一致)。
    ⚠ 合规:只落**问题文本**与答案长度等元信息,不落库内内容;问题本身已是用户输入。
    """
    import json as _json
    import time as _time
    from pathlib import Path as _Path

    if not (question or "").strip():
        return
    path = _Path(config.DATA_DIR).parent.parent / "evals" / "badcases.json"
    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
        cases = data.get("cases", [])
        case = next((c for c in cases if c.get("id") == "ungrounded"), None)
        if case is None:
            case = {"id": "ungrounded", "type": "ungrounded", "status": "open",
                    "note": ("P4e M4:有来源但答案零 [n] 引用且零数字(无实质内容),"
                             "触发一次重生后仍不合格的现场记录"),
                    "first_seen": _time.strftime("%Y%m%d_%H%M%S"), "history": []}
            cases.append(case)
            data["cases"] = cases
        case["status"] = "open"
        case["last_seen"] = _time.strftime("%Y%m%d_%H%M%S")
        case.setdefault("history", []).append({
            "at": case["last_seen"], "question": (question or "")[:80],
            "answer_len": len(answer or ""), "sources_count": n_sources, "stage": stage,
        })
        case["history"] = case["history"][-50:]
        data["updated_at"] = case["last_seen"]
        path.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.warning("ungrounded 记录(重生后仍不合格): stage=%s sources=%d len=%d",
                       stage, n_sources, len(answer or ""))
    except Exception as e:  # badcase 记录失败不影响回答
        logger.warning("ungrounded 记录失败(不影响对话): %s", e)



class _StreamGate:
    """P4e S1-①:流式 grounding 闸门的**早窗提交**控制器(纯逻辑,无 IO,可单测)。

    【为什么改】M4 为了「先发一段再撤回是撤不回的」把 delta 全量缓冲,判完闸门再一次性
    下发 —— 判据对了,但**代价没有量化**:复核实测 TTFB 2365ms / E2E 2401ms、
    12 个 delta 挤在最后 36ms,渐进显示归零(HANDOFF 坑 60)。本类把两件事解耦:
      · **下发**:delta 默认立即放行;仅在「早窗」内 —— 即尚未出现可核查事实 **且**
        累计生成不足 `window_chars` 字 —— 暂缓,窗口一过(出现事实 或 满 N 字)立刻补发;
      · **判定**:始终对**整段**文本判,整段生成完仍零可核查事实才重生**一次**。

    【闸门语义完全不变】重生仍最多一次、仍写 `ctx_info["grounding_gate"]`、
    仍不许静默兜底(重生后仍不合格 → 保留答案 + flag + badcase,评测照旧判红)。
    变的只是「首字什么时候到」:从「整段生成完」回到「检索完成 + 首个事实出现」。

    【已下发的文字不假装没发生】若终究要重生,调用方先发一条显式事件
    `{"type":"grounding_retry","released_chars":N}`,由前端渲染成「已重新组织答案」状态,
    而不是把已展示内容偷偷删掉再当没发生过。
    """

    def __init__(self, n_sources: int, gate_on: bool = True, scope: str = "factual"):
        self.n_sources = n_sources
        self.enabled = config.GROUNDING_GATE_ENABLED
        # P4f C0-③: 本轮闸门是否生效(轮次类型判定结果,由调用方传入)。
        #   gate_on=False → **既不重生、也不缓冲**:delta 立刻原样下发。
        #   早窗机制是为"要在出现首个事实前暂缓一下"设计的,当本轮压根不期待事实时
        #   继续憋字既没意义(不会重生)、又白白让用户多等一个窗口(坑 60 的延迟代价)。
        self.gate_on = gate_on
        self.scope = scope
        self.window_chars = config.GROUNDING_EARLY_WINDOW_CHARS
        self.force = config.GROUNDING_STREAM_FORCE_UNGROUNDED
        self.pending: list = []
        self.text = ""            # 已生成全文(含尚未放行的部分)
        self.released_chars = 0   # 已下发给前端的字符数
        self.window_closed = False  # 早窗已过 → 之后一律直接放行

    def feed(self, chunk: str) -> list:
        """喂入一段 delta,返回**本次应当下发**的片段列表(可能为空=暂缓)。"""
        self.text += chunk or ""
        if not self.enabled or not self.gate_on or self.window_closed:
            self.released_chars += len(chunk or "")
            return [chunk] if chunk else []
        self.pending.append(chunk)
        # ⚠ N<=0 的完整语义 = **退回 M4 全量缓冲**(整段生成完才判定、才下发),
        #   不能只关掉"满 N 字"这一条——否则 N=0 档会在首个事实处放行,与早窗档同值,
        #   对照档失效(自检实测:未修时 N=0 档 span 518ms ≈ 早窗档 492ms)。
        if self.window_chars <= 0:
            return []
        # ① 出现首个可核查事实([n] 引用或数字) → 这一版算有据,立即放行
        if (not self.force) and bool(_FACTUAL_RE.search(self.text)):
            return self._release()
        # ② 早窗用尽(满 N 字) → 照常放行,不再继续憋着
        if len(self.text) >= self.window_chars:
            return self._release()
        return []

    def _release(self) -> list:
        out = [s for s in self.pending if s]
        self.pending = []
        self.released_chars += sum(len(s) for s in out)
        self.window_closed = True
        return out

    def flush(self) -> list:
        """生成结束:放行所有暂缓内容。"""
        return self._release() if self.pending else []

    @property
    def grounded(self) -> bool:
        """整段是否已「有据」(与 chat_for 的 `answer_is_grounded` 同一判据)。"""
        # ⚠ 顺序要紧:`gate_on` 必须**先于** `force` 判。
        #   否则测试钩子(force 首版判无据)会作用到不期待事实回答的轮次上,
        #   让「作用域收窄」在带钩子的 canonical 档里被旁路——那正是 C0-③ 要修的
        #   同一类错(P4e 上一轮就因为报告不记 env 标志,把依赖钩子的 55/55
        #   当成可复现结果,坑 63)。scope 收窄对钩子档同样生效。
        if not self.gate_on:
            return True      # 本轮不期待事实回答 → 判据不适用,视为通过(C0-③)
        if self.force:      # 测试钩子:强制首版走重生通道
            return False
        if not self.n_sources:
            return True     # 无来源 = 拒答路径,不走本闸门
        return bool(_FACTUAL_RE.search(self.text))

    def need_regen(self) -> bool:
        return self.enabled and self.gate_on and not self.grounded


def model_ctx(model: str) -> int:
    """模型上下文窗口(来自 MODEL_CANDIDATES.ctx;未知模型给保守值)。"""
    return next((m["ctx"] for m in config.MODEL_CANDIDATES if m["id"] == model), 32000)


# P4b-fix ①(决策 1 裁决落地): 追问轮"能否基于历史作答"由代码判定,不再是一句 prompt 豁免。
# 可采信历史证据(admissible)只有两类:
#   a) 此前 assistant 且带有效 sources 的回答(db.add_message 落库的 sources_json 快照);
#   b) 会话压缩摘要(assistant 生成的聚合产物,见 conversation_summary)。
# user 消息与拒答模板(无 sources)一律不进池——用户自述内容(金额/渠道/地点)没有任何
# 通道被当作事实依据复述;池为空或未命中 → 走 refusal.build_refusal 确定性模板。
_NORM_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")
_GATE_MIN_UNIGRAM_COVER = 0.30   # 主题命中:单字覆盖率下限(配合 ≥3 个不同单字 + ≥1 个 2-gram)
_GATE_MIN_BIGRAM_COVER = 0.15    # 细节命中:2-gram 覆盖率下限(配合 ≥2 个不同命中)
# 回指/承接语标记:出现即说明问句离开上下文便语义不完整(代词、指代词),此时只要与
# 可采信文本有任一实词重叠(≥1 个 2-gram 或 ≥2 个单字)就放行历史回答——回指问句的
# 字面覆盖天然偏低且随答案措辞波动(实测"需提交/应当提交"两版答案使单字命中在 2~3
# 之间跳动),纯覆盖率阈值无法同时稳住"代词指代命中"与"游泳馆类搭车问句拒绝"。
_ANAPHORA_MARKERS = ("它", "它们", "他", "她", "该", "上述", "此", "前面", "刚才", "上面",
                     "这个", "那个", "这些", "那些", "其")


def _has_anaphora(question: str) -> bool:
    return any(m in question for m in _ANAPHORA_MARKERS)


def history_gate_hit(question: str, admissible_texts: list[str]) -> bool:
    """P4b-fix ①: 追问轮历史门控(确定性,零依赖,判据与阈值见 docs/P4B.md §三.1)。

    对问句与每条可采信文本做字符 n-gram 覆盖匹配,命中任一即放行"依据历史回答":
      - 细节命中:问句 2-gram 有 ≥2 个不同命中且覆盖率 ≥0.15(显式主题追问);
      - 回指命中:问句含回指/承接标记(它/该/上述/此…)且 **2-gram ≥1 且单字 ≥2**
        (P4d 收紧:原为"或",偏宽——改写上线后问句本身应能命中知识库,不再靠更宽的回指档放行);
        ——代词问句离开上下文即语义不完整,须有先行语才可答;
      - 主题命中:2-gram ≥1 且单字 ≥3 且单字覆盖率 ≥0.30(显式主题、无回指标记)。
    未命中(含池为空)→ 调用方走 refusal.build_refusal 确定性模板。
    标定:代词追问两版答案措辞(需提交/应当提交)均命中;游泳馆 0.222/天气 0/空池
    拒绝;摘要数字追问按细节命中(实测见 docs/p4b/evidence/after/followup_gate_v2.json
    与评测 mt-01/rfol-01/hfp-01/cc-01)。已知边际:校医院门诊类问句(单字覆盖 0.308)
    走主题命中→历史提示路径,池内无该主题内容,模型按注入约定仍应如实说明未覆盖,
    无编造/洗白通道。
    """
    q = _NORM_RE.sub("", question or "")
    if len(q) < 2 or not admissible_texts:
        return False
    anaphora = _has_anaphora(question or "")
    q_uni = set(q)
    q_bi = {q[i:i + 2] for i in range(len(q) - 1)}
    for text in admissible_texts:
        t = _NORM_RE.sub("", text or "")
        if not t:
            continue
        h1 = len(q_uni & set(t))
        h2 = len(q_bi & {t[i:i + 2] for i in range(len(t) - 1)})
        if h2 >= 2 and h2 / len(q_bi) >= _GATE_MIN_BIGRAM_COVER:
            return True
        # P4d C7②: 回指档由"或"收紧为"且"(2-gram ≥1 且单字 ≥2)——改写上线后减少对历史通道的依赖
        if anaphora and h2 >= 1 and h1 >= 2:
            return True
        if h2 >= 1 and h1 >= 3 and h1 / len(q_uni) >= _GATE_MIN_UNIGRAM_COVER:
            return True
    return False




async def build_conversation_context(conversation_id: int, model: str) -> tuple[list[dict], dict]:
    """P4b C2/C3/C4: 组装历史注入消息与上下文预算信息。

    返回 (history_messages, ctx_info)。预算口径:budget = ctx*0.65(注入预算,system 与
    当前问题不计入——system 固定且短,当前问题必带);used = 实际注入的历史部分估算 token。
    未超预算 → 完整保留(时间正序);超预算 → 较早消息经 COMPRESS_PROMPT 压缩(摘要注入 +
    最近 ≤40% 预算的原文),压缩结果落 conversation_summary(原文永久保留);压缩失败 →
    降级为截断最早消息(truncated=True,前端标注已截断),绝不静默丢内容。
    """
    hist = db.get_conversation_history(conversation_id)
    budget = int(model_ctx(model) * 0.65)
    ctx_info: dict[str, Any] = {"budget": budget, "compressed": False, "truncated": False,
                                "history_count": len(hist)}
    if not hist:
        ctx_info["used"] = 0
        return [], ctx_info

    def used_of(msgs: list[dict]) -> int:
        return sum(est_tokens(m["content"]) + 4 for m in msgs)

    used = used_of(hist)
    if used <= budget:
        ctx_info["used"] = used
        ctx_info["history_msg_ids"] = [m["id"] for m in hist]
        return [{"role": m["role"], "content": m["content"]} for m in hist], ctx_info

    # 超预算:最近消息保留 ≤40% 预算,较早部分压缩。
    # P4b C4 实测修正:单次压缩 1000+ 条会按主题归并、丢掉具体数字(实测摘要 1.3k 字,
    # 埋点的 448/95585/417号 全部丢失)→ 改为分块压缩(每 40 条一块,并发调用,逐块保数),
    # 各块摘要拼接后注入并整体落 conversation_summary(原文永久保留)。
    recent: list[dict] = []
    kept = 0
    for m in reversed(hist):
        t = est_tokens(m["content"]) + 4
        if kept + t > int(budget * 0.4):
            break
        recent.insert(0, m)
        kept += t
    older = hist[: len(hist) - len(recent)]
    older_text = "\n".join(f"[msg {m['id']}] {m['role']}: {m['content']}" for m in older)
    try:
        cached = db.get_conversation_summary(conversation_id)
        if cached and cached["covered_until_message_id"] >= older[-1]["id"] and cached["summary_text"]:
            summary = cached["summary_text"]  # 摘要已覆盖到同一点,复用(避免每轮重复压缩)
        else:
            t0 = time.perf_counter()
            chunks = [older[i:i + 40] for i in range(0, len(older), 40)]

            async def _compress_chunk(ch: list[dict]) -> str:
                text = "\n".join(f"[msg {m['id']}] {m['role']}: {m['content']}" for m in ch)
                msg = await llm.chat(
                    [{"role": "user", "content": COMPRESS_PROMPT.format(history=text[:20000])}],
                    max_tokens=800, temperature=0,
                )
                return (msg.get("content") or "").strip()

            parts = await asyncio.gather(*(_compress_chunk(ch) for ch in chunks))
            summary = "\n".join(p for p in parts if p)
            if not summary:
                raise ValueError("压缩结果为空")
            db.upsert_conversation_summary(conversation_id, summary, older[-1]["id"])
            # P4b 决策 2 补充要求:首次超预算轮的压缩实测毫秒数(块数与调用数关系式见 docs/P4B.md §三.2)
            ctx_info["compress_ms"] = round((time.perf_counter() - t0) * 1000)
            ctx_info["compress_blocks"] = len(chunks)
        ctx_info["compressed"] = True
        ctx_info["summary_covered_until"] = older[-1]["id"]
        ctx_info["compressed_from_count"] = len(older)
        head = [{"role": "system",
                 "content": "以下是本会话较早内容的压缩摘要(原文保留在数据库,可回溯):\n" + summary}]
        used = est_tokens(summary) + 4 + kept
        ctx_info["history_msg_ids"] = [m["id"] for m in older] + [m["id"] for m in recent]
    except Exception as e:  # 压缩失败 → 降级截断(前端标注"已截断"),不静默丢内容
        logger.warning("会话压缩失败,降级为截断最早消息: %s", e)
        recent, kept = [], 0
        for m in reversed(hist):
            t = est_tokens(m["content"]) + 4
            if kept + t > budget:
                break
            recent.insert(0, m)
            kept += t
        older = hist[: len(hist) - len(recent)]
        ctx_info["truncated"] = True
        ctx_info["truncated_count"] = len(older)
        ctx_info["history_msg_ids"] = [m["id"] for m in recent]
        head = []
        used = kept
    ctx_info["used"] = used
    return head + [{"role": m["role"], "content": m["content"]} for m in recent], ctx_info


WEEKLY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_fragment",
            "description": "记录一条辅导员工作碎片。category 必须是 谈心谈话/事务办理/活动组织/异常突发/其他 之一,由你根据内容判断;occurred_at 为事件发生日期 YYYY-MM-DD,缺省今天。分类为谈心谈话时,把用户提到的学生姓名原样传 student_name,并把摘要传 summary(形如「就该学生职业规划情况进行谈心谈话」,只依据用户原话,不确定就留空)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "碎片内容,含时间/对象/事项/结果"},
                    "category": {"type": "string", "description": "碎片分类"},
                    "occurred_at": {"type": "string", "description": "发生日期 YYYY-MM-DD,可省略"},
                    "student_name": {"type": "string", "description": "谈心谈话对象(学生)姓名,可省略"},
                    "summary": {"type": "string", "description": "一句话规范摘要,可省略"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_weekly_report",
            "description": "聚合指定日期范围内的碎片,生成结构化周报 Markdown 草稿。用户要写周报时调用,拿到草稿后润色输出给用户。",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "起始日期 YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD,可省略(默认同周周日)"},
                },
                "required": ["start_date"],
            },
        },
    },
]




class _StreamRefFilter:
    """P4a C2:流式路径的引用越界过滤。

    逐段喂入 delta 文本,缓冲疑似 "[12" 的未完片段;补全为 "[n]" 后按 n_sources
    判定保留或丢弃;无法构成引用的方括号原样放行。flush 处理流末尾残片。
    """

    _MAX_PENDING = 8  # "[12]" 全长 4;超出即判非引用

    def __init__(self, n_sources: int, drop_web: bool = False):
        self.n_sources = n_sources
        # P4e M-A: 联网模式下还要流内剥离逐句绑定的 [W<n>](同 P4a C2 的"越界即剥离")
        self.drop_web = drop_web
        self.pending = ""
        self.stripped: list[int] = []
        self.web_stripped = 0

    def _decide(self, token: str) -> str:
        if self.drop_web and _WEB_CITATION_RE.fullmatch(token):
            self.web_stripped += 1
            return ""
        m = re.fullmatch(r"\[(\d{1,2})\]", token)
        if not m:
            return token
        n = int(m.group(1))
        if 1 <= n <= self.n_sources:
            return token
        self.stripped.append(n)
        return ""

    def feed(self, chunk: str) -> str:
        self.pending += chunk
        out: list[str] = []
        while self.pending:
            i = self.pending.find("[")
            if i < 0:
                # 无 "[":除末尾可能截断的 "[" 外全部放行
                keep = 1 if self.pending.endswith("[") else 0
                out.append(self.pending[: len(self.pending) - keep] if keep else self.pending)
                self.pending = self.pending[len(self.pending) - keep:] if keep else ""
                break
            out.append(self.pending[:i])
            self.pending = self.pending[i:]
            j = self.pending.find("]")
            if j < 0:
                if len(self.pending) <= self._MAX_PENDING:
                    break  # 可能是未完的引用片段,等下一个 delta
                out.append(self.pending[0])  # "["
                self.pending = self.pending[1:]
                continue
            token, rest = self.pending[: j + 1], self.pending[j + 1:]
            is_web_cite = bool(self.drop_web and _WEB_CITATION_RE.fullmatch(token))
            if is_web_cite or re.fullmatch(r"\[\d{1,2}\]", token):
                out.append(self._decide(token))
                self.pending = rest
            else:  # 形如 "[abc]" 不是引用标注,放行首个字符防止死循环
                out.append(self.pending[0])
                self.pending = self.pending[1:]
        return "".join(out)

    def flush(self) -> str:
        rest, self.pending = self.pending, ""
        return rest


# ---------- P4e M-A / M-C:联网来源的分区上下文与整段级声明 ----------
#
# 【引用语义为什么是「分区 + 整段级标注」而不是 `[W1]` 角标】
# 上游 Responses API 每条来源**只有 `{type, url}`**(四入口全矩阵实测,
# 见 docs/p4e/evidence/WEBSEARCH_PROTOCOL_HARDSTOP.md):
#   · 无 `index` → 没有上游编号;
#   · 正文**零 `[n]` 角标、零内联 URL、`annotations` 为空** → **不存在「哪句出自哪条 URL」的映射**。
# 若由我方自建「第 k 句 ↔ 第 k 条 URL」的对应关系,那是**用假精确换好看**——
# 面试与审计都答不出"凭什么说这句出自这条",属于不可辩护的引用。故:
#   · 联网来源**单独分区**列出真实 URL(可点、可核);
#   · `site_name` 由 `urlparse().netloc` 推导并在 UI 明确标注「由 URL 推导」;
#   · `index` 由我方按 `action.sources` 原序分配,**仅作列表编号**;
#   · 答案里**禁止**出现逐句绑定的 `[W<n>]`(评测有反向断言,见 run_evals._W_CITATION_RE);
#   · 改为**整段级**声明,由**代码注入**(不靠模型自觉,与 P4a C8 学段声明同一手法)。
WEB_DECLARE = ("⚠ 本节含公网检索内容，未经本校核实；"
               "涉及本校具体政策、流程与办理口径的，请以学校官方文件为准。")


# M-C 降级提示:联网不可用必须让用户看见(坑 46/47:静默兜底等于把缺陷藏起来)
WEB_UNAVAILABLE_NOTE = ("\n\n（已尝试联网检索，但本次联网搜索不可用或未返回结果；"
                        "以上仍为知识库范围的判定。）")


def _web_enabled(user_id: int, override: bool | None) -> bool:
    """P4e M-B 开关优先级:**单次请求覆盖 > 用户级默认 > 全局默认(默认关闭)**。"""
    if override is not None:
        return bool(override)
    v = str(db.get_user_settings(user_id).get("web_search_enabled") or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return config.WEB_SEARCH_ENABLED   # 未设置过的用户 → 全局默认(False)


class AgentService:
    """持有周报 MCP 长连接,提供检索增强对话与周报工具直调。"""

    def __init__(self) -> None:
        self.weekly = WeeklyMCP(config.WEEKLY_MCP_URL)

    async def start(self) -> None:
        await self.weekly.start()

    async def stop(self) -> None:
        await self.weekly.stop()

    async def expand_fragment(self, content: str, category: str, model: str,
                              base_url: str = "", api_key: str = "") -> str:
        """把简短笔记扩充为规范工作记录草稿(不落库,人工确认后保存)。"""
        msg = await llm.chat(
            [{"role": "user", "content": EXPAND_PROMPT.format(category=category, content=content)}],
            model=model,
            max_tokens=800,
            temperature=0.4,
            base_url=base_url,
            api_key=api_key,
        )
        return (msg.get("content") or "").strip()

    async def summarize_talk(self, content: str, model: str,
                             base_url: str = "", api_key: str = "") -> str:
        """谈心谈话自动摘要:模型**只选主题**,整句由 `talk_summary` 拼装。

        失败(调用异常 / 返回不在枚举内 / 返回空)一律返回空串,**绝不抛错**:
        摘要只是锦上添花,不能因为它把"保存一条记录"这个主动作打断;
        前端拿到空摘要就显示占位串,辅导员可手填。
        """
        try:
            msg = await llm.chat(
                [{"role": "user",
                  "content": talk_summary.TOPIC_PROMPT.format(content=content[:3000])}],
                model=model,
                max_tokens=16,
                temperature=0.1,
                base_url=base_url,
                api_key=api_key,
            )
        except Exception as e:  # noqa: BLE001 — 摘要失败不阻断保存(见 docstring)
            logger.warning("谈心谈话摘要失败(留空): %s", e)
            return ""
        topic = talk_summary.normalize_topic((msg.get("content") or "").strip())
        if not topic:
            logger.info("谈心谈话摘要:模型返回无法归一到枚举,留空")
            return ""
        return talk_summary.build_summary(topic)

    async def organize_minutes(self, raw_text: str, model: str,
                               base_url: str = "", api_key: str = "") -> tuple[dict, list[str]]:
        """零散会议内容 → (结构化纪要, untraced 说明)。

        与 `summarize_talk` 相反,这里**失败即抛**:整理整段纪要就是这一轮的主动作,
        静默返回空纪要比报错更坏(用户会以为"这份会议没内容")。
        """
        msg = await llm.chat(
            [{"role": "user",
              "content": minutes_lib.MINUTES_PROMPT.format(raw=raw_text[:12000])}],
            model=model,
            max_tokens=2500,
            temperature=0.2,
            base_url=base_url,
            api_key=api_key,
        )
        text = (msg.get("content") or "").strip()
        if not text:
            raise RuntimeError("整理结果为空,请重试或手动编辑")
        try:
            parsed = minutes_lib.parse_minutes_output(text)
        except ValueError as e:
            raise RuntimeError(f"整理结果解析失败:{e}") from e
        # 防虚构守卫:责任人与截止时间须能在原文中溯源,溯不到回落占位
        return minutes_lib.guard(parsed, raw_text)

    async def transcribe_audio(self, filename: str, data: bytes,
                               api_key: str = "") -> str:
        """录音 → 转写文本(会出网,调用方须已获用户确认)。"""
        return await asr.transcribe(filename, data, api_key=api_key)

    async def summarize_document(self, title: str, chunks: list[str], model: str = "",
                                 base_url: str = "", api_key: str = "") -> str:
        """文档入库摘要(WeKnora 式 doc profile):只依据原文,防脑补。"""
        joined = "\n".join(chunks)[:6000]
        msg = await llm.chat(
            [{"role": "user", "content": SUMMARY_PROMPT.format(content=f"《{title}》\n{joined}")}],
            model=model,
            max_tokens=300,
            temperature=0.2,
            base_url=base_url,
            api_key=api_key,
        )
        return (msg.get("content") or "").strip()

    def effective_llm(self, user_id: int) -> dict[str, str]:
        """解析用户生效 LLM 配置:自定义 API 优先,其次所选候选,最后全局默认。"""
        s = db.get_user_settings(user_id)
        if s["custom_model"] and s["llm_base_url"] and s["llm_api_key"]:
            return {"model": s["custom_model"], "base_url": s["llm_base_url"], "api_key": s["llm_api_key"]}
        return {"model": s["model"] or config.LLM_MODEL, "base_url": "", "api_key": ""}

    async def chat_for(self, user_id: int, username: str, role: str, question: str,
                       conversation_id: int | None = None,
                       scope: dict | None = None,
                       web_search: bool | None = None,
                       persona: dict | None = None) -> dict[str, Any]:
        # P4c C4: scope 为 main.resolve_scope 解析后的生效范围(folder_ids/categories/audience),
        # 本函数只把它透传给 rag.search_with_quality,并把生效 scope 原样带回响应(P4c 白名单边界)。
        if conversation_id:
            if not db.get_conversation(conversation_id, user_id):
                raise LookupError("会话不存在")
        else:
            conversation_id = db.create_conversation(user_id, title=question[:20])
        eff = self.effective_llm(user_id)
        min_rank = db.config.ROLE_RANK[role]
        # P4b: 历史注入(过去轮次)先于检索与当前问题落库——本问不计入自身历史
        hist_msgs, ctx_info = await build_conversation_context(conversation_id, eff["model"])
        # P4d: 检索编排走 LangGraph(graph 内检索复用 main 层解析出的 scope,不自行构造);
        # P4a 硬门控仍在下方 should_refuse 调用,未被削弱;P4b 追问门控逻辑一行未动。
        g_out: dict | None = None
        if config.GRAPH_ENABLED:
            g_out = await graph.run_pipeline(question=question, min_rank=min_rank, scope=scope,
                                             model=eff["model"], base_url=eff["base_url"],
                                             api_key=eff["api_key"])
            sources, quality = g_out["sources"], g_out["quality"]
            ctx_info["retrieval_trace"] = g_out.get("trace") or []
            ctx_info["intent"] = g_out.get("intent")
            ctx_info["attempts"] = g_out.get("attempts")
            ctx_info["rewritten"] = bool(g_out.get("rewritten"))
            # C3 断言锚点: direct(闲聊/时间)路径检索被跳过,评测据此断言 retrieval_skipped=true
            ctx_info["retrieval_skipped"] = bool(g_out.get("retrieval_skipped"))
        else:
            sources, quality = await rag.search_with_quality(question, min_rank, scope=scope)
        if scope:
            ctx_info["scope"] = scope
        if g_out and g_out.get("mode") == "direct":
            # 闲聊/问时间:确定性直答(时间类不调 LLM),不占检索与生成。
            # 落库口径与常规轮一致(user + assistant 各一条)——保证会话历史连续,
            # 也满足评测隔离断言「user 条数 == 应发轮数」(P4d 实测:不落库会让 intent 用例判红)。
            db.add_message(user_id, "user", question, conversation_id)
            db.add_message(user_id, "assistant", g_out["answer"], conversation_id)
            db.update_conversation_trace(conversation_id, g_out.get("trace"))
            return {"answer": g_out["answer"], "sources": [], "tool_trace": [],
                    "conversation_id": conversation_id, "context": ctx_info,
                    "retrieval_trace": g_out.get("trace") or []}
        db.update_conversation_trace(conversation_id, g_out.get("trace") if g_out else None)
        # P4a C1 拒答硬门控:无来源/相关度不足 → 确定性模板(代码拼装,不经 LLM)。
        # P4b C2/C4 多轮分支:追问轮的证据不只来自知识库——本会话历史(含压缩摘要)已注入
        # 上下文。首问(无历史)维持硬拒答不变(refusal_indomain 评测即此路径);追问轮检索
        # 不达标时不再硬拒,改为注入代码拼装的「依据历史回答/如实说明未覆盖」指令,
        # 由模型按已注入的证据回答——refusal.py 未改动,门控判定结果仍透传给模型。
        do_refuse, reason = refusal.should_refuse(sources, quality)
        followup_note = ""
        if do_refuse and hist_msgs:
            # P4b-fix ①(决策 1 裁决): 追问轮是否放行"依据历史回答"由代码门控判定。
            # 可采信证据=此前 assistant 且带有效 sources 的回答 + 压缩摘要;
            # 未命中(含池为空)→ 维持 do_refuse,走 build_refusal 确定性模板(contacts 出口)。
            admissible = [m["content"] for m in db.get_conversation_history(conversation_id)
                          if m["role"] == "assistant" and m.get("sources_json")]
            cached = db.get_conversation_summary(conversation_id)
            if cached and cached.get("summary_text"):
                admissible.append(cached["summary_text"])
            if history_gate_hit(question, admissible):
                do_refuse = False
                ctx_info["followup_no_new_sources"] = True
                ctx_info["history_gate"] = "hit"
                followup_note = HISTORY_GATE_NOTE.format(reason=reason)
            else:
                ctx_info["history_gate"] = "miss"
        # P4e M-B/M-C:联网是「本地拒答后的**补充通道**」——本地有据就**不出网**
        # (既省一次外网调用,也更合规:库内内容、会话历史一律不离开本机)。
        # 超时/失败/零来源 → 维持 do_refuse,并在拒答模板后追加明确提示,**不静默兜底**。
        web_on = _web_enabled(user_id, web_search)
        web_sources: list[dict] = []
        ctx_info["web_enabled"] = web_on
        if web_on and do_refuse:
            res = await websearch.search(question, model=eff["model"],
                                         base_url=eff["base_url"], api_key=eff["api_key"])
            web_sources = websearch.build_web_sources(res["urls"])
            ctx_info["web_called"] = True
            ctx_info["web_ms"] = res["ms"]
            ctx_info["web_n_sources"] = len(web_sources)
            ctx_info["web_error"] = res["error"]
            if web_sources:
                do_refuse = False
                ctx_info["web_fallback"] = True
            else:
                ctx_info["web_unavailable"] = True
        else:
            ctx_info["web_called"] = False
            ctx_info["web_ms"] = 0
            ctx_info["web_n_sources"] = 0
            ctx_info["web_error"] = ""
        # P4f: 人设信息写进 context,让评测/排障能自证「这一轮是谁在答」(零额度可复核)
        ctx_info["persona_id"] = (persona or {}).get("id")
        ctx_info["persona_name"] = (persona or {}).get("name") or ""
        user_msg_id = db.add_message(user_id, "user", question, conversation_id)
        assistant_saved = False
        try:
            if do_refuse:
                answer = refusal.build_refusal(question, reason)
                if web_on and ctx_info.get("web_unavailable"):
                    answer += WEB_UNAVAILABLE_NOTE
                db.add_message(user_id, "assistant", answer, conversation_id)
                assistant_saved = True
                return {"answer": answer, "sources": [], "tool_trace": [],
                        "conversation_id": conversation_id, "context": ctx_info,
                        "web_sources": []}
            stage_note = refusal.learn_stage_note(question, sources)  # P4a C8 学段声明注入
            context = "\n\n".join(
                f"[{s['ref']}] 《{s['title']}》({s['role_min']}可读)\n{s['content']}" for s in sources
            ) or "(本角色可见范围内未检索到相关资料)"
            if web_sources:   # P4e M-A:联网资料**另起一区**,与本地 [1..n] 不混编号
                context += WEB_CONTEXT_BLOCK.format(
                    urls="\n".join(f"- {w['url']}" for w in web_sources))
            if followup_note:
                context = f"{followup_note}\n\n{context}"
            if stage_note:
                context = f"{stage_note}\n\n{context}"
            # P4f C2: persona 只影响 prompt 组装; ctx_web 恒为空(联网资料已并入 context,
            #   保持与 P4e 逐字一致,避免"无 persona 路径"出现第二种拼装口径)。
            messages = [{"role": "system",
                         "content": build_system_prompt(persona, context)}]
            messages += hist_msgs
            messages.append({"role": "user", "content": question})
            # 成本可见:把这一轮实际要发的输入量记进 trace(纯读数,不影响任何内容)
            ctx_info["request_tokens"] = request_token_profile(messages)
            tool_trace: list[dict] = []
            answer = ""
            for _ in range(3):  # 最多 3 轮工具调用
                msg = await llm.chat(messages, tools=WEEKLY_TOOLS, model=eff["model"],
                                     base_url=eff["base_url"], api_key=eff["api_key"])
                if not msg.get("tool_calls"):
                    answer = msg.get("content") or ""
                    break
                messages.append(msg)
                for tc in msg["tool_calls"]:
                    name = tc["function"]["name"]
                    args = json.loads(tc["function"]["arguments"] or "{}")
                    logger.info("tool call: %s(%s) by %s", name, args, username)
                    result = await self.weekly.call(name, args)
                    tool_trace.append({"tool": name, "args": args, "result": result})
                    messages.append(
                        {"role": "tool", "tool_call_id": tc["id"], "content": cap_tool_result(result)}
                    )
            else:
                answer = "抱歉,这个问题处理超时了,请换个问法或稍后再试。"
            # P4e M-A:先剥逐句绑定的 [W<n>](联网模式),再走 P4a C2 的越界 [n] 剥离
            if web_sources:
                answer, _nw = strip_web_citations(answer)
                if _nw:
                    ctx_info["web_citations_stripped"] = _nw
            # P4a C2 引用硬校验:越界 [n] 代码剥离并记 fabricated_ref badcase
            answer, stripped = refusal.strip_invalid_refs(answer, len(sources))
            if stripped:
                refusal.record_fabricated_ref(question, stripped, len(sources))
            # P4e M4 生成出口确定性闸门:有来源却零 [n] 零数字 → 判无效,重生**一次**。
            # 重生仍不合格 → 保留答案 + 写 trace flag + 记 badcase,**不静默兜底**(坑 46/47)。
            # P4f C0-③: 闸门前先判**轮次类型**——只对本轮**确实期待事实回答**的轮次生效。
            # 纯陈述/抑制轮(种植轮塞背景、用户说"简短回复已阅即可")本就不该给引用,
            # 之前被套上闸门导致每轮白烧 11~14 次重生且零救回(坑 64)。
            _gate_on, _gate_scope = grounding_gate_applies(question)
            ctx_info["grounding_gate_scope"] = _gate_scope
            if not _gate_on:
                logger.info("grounding gate skipped: 本轮不期待事实回答(scope=%s)", _gate_scope)
            elif not answer_is_grounded(answer, sources):
                logger.info("grounding gate hit (len=%d, sources=%d), regenerating once",
                            len(answer), len(sources))
                regen = await llm.chat(regen_messages(messages, answer), tools=None,
                                       model=eff["model"], base_url=eff["base_url"],
                                       api_key=eff["api_key"])
                new_answer = (regen.get("content") or "").strip()
                if new_answer:
                    new_answer, stripped2 = refusal.strip_invalid_refs(new_answer, len(sources))
                    if stripped2:
                        refusal.record_fabricated_ref(question, stripped2, len(sources))
                    answer = new_answer
                ok2 = answer_is_grounded(answer, sources)
                ctx_info["grounding_gate"] = {
                    "hit": True, "regenerated": True, "ok_after_regen": ok2,
                    "n_sources": len(sources), "scope": _gate_scope,
                }
                if not ok2:
                    # 不静默:留 flag 让评测/排障看得见,答案照旧返回(评测会照常判红)
                    logger.warning("grounding gate still failed after regen; keeping answer")
                    ctx_info["grounding_gate"]["flag"] = "ungrounded_after_regen"
                    record_ungrounded(question, answer, len(sources), "after_regen")
            if web_sources:   # P4e M-A:整段级声明由**代码注入**,不靠模型自觉
                answer = (answer or "").rstrip() + "\n\n" + WEB_DECLARE
            db.add_message(user_id, "assistant", answer, conversation_id, sources=sources)
            assistant_saved = True
            return {"answer": answer, "sources": sources, "tool_trace": tool_trace,
                    "conversation_id": conversation_id, "context": ctx_info,
                    "web_sources": web_sources}
        except (asyncio.CancelledError, GeneratorExit):
            # P4b-fix ⑤: 客户端断开/任务取消 → 回滚本轮 user 消息,维持"中止=该轮未发生"口径。
            # assistant 已落库则视为完整轮次不回滚;db 调用为同步 sqlite,取消点内安全。
            if not assistant_saved:
                try:
                    db.delete_message(user_msg_id, conversation_id)
                except Exception as de:  # 回滚失败只记日志,不吞取消
                    logger.warning("中止回滚 user 消息失败(会话 %s): %s", conversation_id, de)
            raise

    async def chat_stream_for(self, user_id: int, username: str, role: str, question: str,
                              conversation_id: int | None = None,
                              scope: dict | None = None,
                              web_search: bool | None = None,
                              persona: dict | None = None):
        """T8: 流式对话路径——工具循环(非流式判定工具调用)后流式输出最终答案。
        异步生成器逐段 yield 事件:
          {"type": "sources", "sources": [...]}          检索来源(一次性,最先)
          {"type": "context", used, budget, compressed, truncated}  P4b C5: 上下文占用
          {"type": "delta", "content": str}              正文增量(逐 token)
          {"type": "tools", "trace": [...]}              工具执行记录
          {"type": "done", "answer", "sources", "tool_trace", "conversation_id", "context"}
        P4a: 拒答硬门控(无来源/相关度不足→确定性模板,不经 LLM)+ 流式引用越界过滤 + 学段声明注入。
        P4b: 会话解析(缺省自动新建)+ 历史注入与压缩 + 本问/答案落库到会话。
        """
        if conversation_id:
            if not db.get_conversation(conversation_id, user_id):
                raise LookupError("会话不存在")
        else:
            conversation_id = db.create_conversation(user_id, title=question[:20])
        eff = self.effective_llm(user_id)
        min_rank = db.config.ROLE_RANK[role]
        hist_msgs, ctx_info = await build_conversation_context(conversation_id, eff["model"])
        # P4d: 与 chat_for 同款编排(graph 内检索复用传入 scope);direct 分支在下方处理
        g_out: dict | None = None
        if config.GRAPH_ENABLED:
            g_out = await graph.run_pipeline(question=question, min_rank=min_rank, scope=scope,
                                             model=eff["model"], base_url=eff["base_url"],
                                             api_key=eff["api_key"])
            sources, quality = g_out["sources"], g_out["quality"]
            ctx_info["retrieval_trace"] = g_out.get("trace") or []
            ctx_info["intent"] = g_out.get("intent")
            ctx_info["attempts"] = g_out.get("attempts")
            ctx_info["rewritten"] = bool(g_out.get("rewritten"))
            # C3 断言锚点: direct(闲聊/时间)路径检索被跳过,评测据此断言 retrieval_skipped=true
            ctx_info["retrieval_skipped"] = bool(g_out.get("retrieval_skipped"))
        else:
            sources, quality = await rag.search_with_quality(question, min_rank, scope=scope)
        if scope:
            ctx_info["scope"] = scope  # P4c C4: 生效 scope 原样回传(纯 echo)
        db.update_conversation_trace(conversation_id, g_out.get("trace") if g_out else None)
        if g_out and g_out.get("mode") == "direct":
            text = g_out["answer"]
            db.add_message(user_id, "user", question, conversation_id)
            db.add_message(user_id, "assistant", text, conversation_id)
            yield {"type": "sources", "sources": []}
            yield {"type": "context", **ctx_info}
            yield {"type": "delta", "content": text}
            yield {"type": "done", "answer": text, "sources": [], "tool_trace": [],
                   "conversation_id": conversation_id, "context": ctx_info,
                   "retrieval_trace": g_out.get("trace") or []}
            return
        # P4b-fix ①(与 chat_for 同款代码门控):命中才注入历史依据指令;未命中维持硬拒。
        do_refuse, reason = refusal.should_refuse(sources, quality)
        followup_note = ""
        if do_refuse and hist_msgs:
            admissible = [m["content"] for m in db.get_conversation_history(conversation_id)
                          if m["role"] == "assistant" and m.get("sources_json")]
            cached = db.get_conversation_summary(conversation_id)
            if cached and cached.get("summary_text"):
                admissible.append(cached["summary_text"])
            if history_gate_hit(question, admissible):
                do_refuse = False
                ctx_info["followup_no_new_sources"] = True
                ctx_info["history_gate"] = "hit"
                followup_note = HISTORY_GATE_NOTE.format(reason=reason)
            else:
                ctx_info["history_gate"] = "miss"
        # P4e M-B/M-C:联网是「本地拒答后的**补充通道**」——本地有据就**不出网**
        # (既省一次外网调用,也更合规:库内内容、会话历史一律不离开本机)。
        # 超时/失败/零来源 → 维持 do_refuse,并在拒答模板后追加明确提示,**不静默兜底**。
        web_on = _web_enabled(user_id, web_search)
        web_sources: list[dict] = []
        ctx_info["web_enabled"] = web_on
        if web_on and do_refuse:
            res = await websearch.search(question, model=eff["model"],
                                         base_url=eff["base_url"], api_key=eff["api_key"])
            web_sources = websearch.build_web_sources(res["urls"])
            ctx_info["web_called"] = True
            ctx_info["web_ms"] = res["ms"]
            ctx_info["web_n_sources"] = len(web_sources)
            ctx_info["web_error"] = res["error"]
            if web_sources:
                do_refuse = False
                ctx_info["web_fallback"] = True
            else:
                ctx_info["web_unavailable"] = True
        else:
            ctx_info["web_called"] = False
            ctx_info["web_ms"] = 0
            ctx_info["web_n_sources"] = 0
            ctx_info["web_error"] = ""
        # P4f: 人设信息写进 context,让评测/排障能自证「这一轮是谁在答」(零额度可复核)
        ctx_info["persona_id"] = (persona or {}).get("id")
        ctx_info["persona_name"] = (persona or {}).get("name") or ""
        user_msg_id = db.add_message(user_id, "user", question, conversation_id)
        assistant_saved = False
        try:
            if do_refuse:  # P4a C1: 确定性拒答模板直接作为流式输出
                text = refusal.build_refusal(question, reason)
                if web_on and ctx_info.get("web_unavailable"):
                    text += WEB_UNAVAILABLE_NOTE
                db.add_message(user_id, "assistant", text, conversation_id)
                assistant_saved = True
                yield {"type": "sources", "sources": [], "web_sources": []}
                yield {"type": "context", **ctx_info}
                yield {"type": "delta", "content": text}
                yield {"type": "done", "answer": text, "sources": [], "tool_trace": [],
                       "conversation_id": conversation_id, "context": ctx_info,
                       "web_sources": []}
                return
            yield {"type": "sources", "sources": sources, "web_sources": web_sources}
            yield {"type": "context", **ctx_info}
            stage_note = refusal.learn_stage_note(question, sources)  # P4a C8 学段声明注入
            context = "\n\n".join(
                f"[{s['ref']}] 《{s['title']}》({s['role_min']}可读)\n{s['content']}" for s in sources
            ) or "(本角色可见范围内未检索到相关资料)"
            if web_sources:   # P4e M-A:联网资料**另起一区**,与本地 [1..n] 不混编号
                context += WEB_CONTEXT_BLOCK.format(
                    urls="\n".join(f"- {w['url']}" for w in web_sources))
            if followup_note:
                context = f"{followup_note}\n\n{context}"
            if stage_note:
                context = f"{stage_note}\n\n{context}"
            # P4f C2: persona 只影响 prompt 组装; ctx_web 恒为空(联网资料已并入 context,
            #   保持与 P4e 逐字一致,避免"无 persona 路径"出现第二种拼装口径)。
            messages = [{"role": "system",
                         "content": build_system_prompt(persona, context)}]
            messages += hist_msgs
            messages.append({"role": "user", "content": question})
            # 成本可见:把这一轮实际要发的输入量记进 trace(纯读数,不影响任何内容)
            ctx_info["request_tokens"] = request_token_profile(messages)
            tool_trace: list[dict] = []
            answer_parts: list[str] = []
            # P4e S1-①:早窗提交——delta 默认直接放行(gate.feed 返回本次应下发的片段),
            # 只在早窗内(未出现可核查事实且累计不足 N 字)暂缓。整段生成完仍零事实才重生一次。
            # 对比 M4 的全量缓冲:首字不再等整段生成完,但闸门判据一条都没放宽。
            # P4f C0-③: 先判轮次类型——不期待事实回答的轮次 gate_on=False,
            # 既不重生也不缓冲(delta 立即原样下发),并把判定标签写进 trace 供评测自证。
            _gate_on, _gate_scope = grounding_gate_applies(question)
            ctx_info["grounding_gate_scope"] = _gate_scope
            gate = _StreamGate(len(sources), gate_on=_gate_on, scope=_gate_scope)
            ref_filter = _StreamRefFilter(len(sources), drop_web=bool(web_sources))  # P4a C2 越界过滤 + P4e M-A 逐句 [W<n>] 剥离
            for _ in range(4):  # 工具轮 + 最终流式轮
                round_text: list[str] = []
                calls: dict[int, dict] = {}
                async for ev in llm.chat_stream(messages, tools=WEEKLY_TOOLS,
                                                model=eff["model"], base_url=eff["base_url"],
                                                api_key=eff["api_key"]):
                    if ev["type"] == "delta":
                        safe = ref_filter.feed(ev["content"])
                        if safe:
                            round_text.append(safe)
                            answer_parts.append(safe)
                            for seg in gate.feed(safe):
                                if seg:
                                    yield {"type": "delta", "content": seg}
                    elif ev["type"] == "tool_delta":
                        slot = calls.setdefault(ev["index"], {"id": "", "name": "", "args": ""})
                        if ev["id"]:
                            slot["id"] = ev["id"]
                        if ev["name"]:
                            slot["name"] = ev["name"]
                        slot["args"] += ev["args"]
                if not calls:  # 无工具调用 → 本次流式即最终答案
                    break
                ordered = [calls[i] for i in sorted(calls)]
                messages.append({
                    "role": "assistant",
                    "content": "".join(round_text) or None,
                    "tool_calls": [
                        {"id": c["id"], "type": "function",
                         "function": {"name": c["name"], "arguments": c["args"]}}
                        for c in ordered
                    ],
                })
                for c in ordered:
                    logger.info("tool call: %s(%s) by %s", c["name"], c["args"][:80], username)
                    result = await self.weekly.call(c["name"], json.loads(c["args"] or "{}"))
                    tool_trace.append({"tool": c["name"], "args": json.loads(c["args"] or "{}"), "result": result})
                    yield {"type": "tools", "trace": tool_trace}
                    messages.append({"role": "tool", "tool_call_id": c["id"],
                                     "content": cap_tool_result(result)})
            else:
                timeout_msg = "抱歉,这个问题处理超时了,请换个问法或稍后再试。"
                answer_parts.append(timeout_msg)
                for seg in gate.feed(timeout_msg):
                    if seg:
                        yield {"type": "delta", "content": seg}
            tail = ref_filter.flush()
            if tail:
                answer_parts.append(tail)
                for seg in gate.feed(tail):
                    if seg:
                        yield {"type": "delta", "content": seg}
            if ref_filter.stripped:  # P4a C2: 流中剥离的越界引用记 badcase
                refusal.record_fabricated_ref(question, ref_filter.stripped, len(sources))
            if ref_filter.web_stripped:   # P4e M-A: 流中剥掉多少处逐句 [W<n>],写进 trace(可观测)
                ctx_info["web_citations_stripped"] = ref_filter.web_stripped
            # P4e M4 / S1-①:整段生成完**仍零可核查事实** → 重生**一次**(判据与 chat_for 同一纯函数)
            if gate.need_regen():
                logger.info("grounding gate hit (stream, len=%d, sources=%d, released=%d), "
                            "regenerating once", len(gate.text), len(sources), gate.released_chars)
                # 已下发的文字不撤回、不假装没发生:显式告知前端"重新组织答案"
                yield {"type": "grounding_retry", "released_chars": gate.released_chars,
                       "n_sources": len(sources)}
                regen_parts: list[str] = []
                async for ev in llm.chat_stream(regen_messages(messages, gate.text), tools=None,
                                                model=eff["model"], base_url=eff["base_url"],
                                                api_key=eff["api_key"]):
                    if ev["type"] == "delta":
                        safe = ref_filter.feed(ev["content"])
                        if safe:
                            regen_parts.append(safe)
                            yield {"type": "delta", "content": safe}
                rtail = ref_filter.flush()
                if rtail:
                    regen_parts.append(rtail)
                    yield {"type": "delta", "content": rtail}
                new_answer = "".join(regen_parts).strip()
                if new_answer:
                    new_answer, stripped2 = refusal.strip_invalid_refs(new_answer, len(sources))
                    if stripped2:
                        refusal.record_fabricated_ref(question, stripped2, len(sources))
                    answer_parts = [new_answer]   # 落库/返回的是**重生后的版本**
                    gate.text = new_answer        # 重生结果即为最终文本(不再二次重生)
                ok2 = answer_is_grounded("".join(answer_parts), sources)
                ctx_info["grounding_gate"] = {
                    "hit": True, "regenerated": True, "ok_after_regen": ok2,
                    "n_sources": len(sources), "stream": True,
                    "early_window_chars": gate.window_chars,
                    "released_chars": gate.released_chars,
                    "scope": gate.scope,
                }
                if not ok2:
                    # 不静默:留 flag 让评测/排障看得见,答案照旧返回(评测会照常判红)
                    logger.warning("grounding gate still failed after regen (stream); keeping answer")
                    ctx_info["grounding_gate"]["flag"] = "ungrounded_after_regen"
                    record_ungrounded(question, "".join(answer_parts), len(sources),
                                      "after_regen_stream")
            # 早窗内暂缓的内容在此补发(正常路径上 feed 已逐段放行,这里只兜底)
            for seg in gate.flush():
                if seg:
                    yield {"type": "delta", "content": seg}
            if web_sources:   # P4e M-A:整段级声明由**代码注入**;同时作为 delta 下发
                decl = "\n\n" + WEB_DECLARE
                answer_parts.append(decl)
                yield {"type": "delta", "content": decl}
            db.add_message(user_id, "assistant", "".join(answer_parts), conversation_id,
                           sources=sources)  # P4b: 答案落库;P4b-fix ①: 带来源快照
            assistant_saved = True
            yield {"type": "done", "answer": "".join(answer_parts), "sources": sources,
                   "tool_trace": tool_trace, "conversation_id": conversation_id,
                   "context": ctx_info, "web_sources": web_sources}
        except (asyncio.CancelledError, GeneratorExit):
            # P4b-fix ⑤: 真 token 流阶段中止也维持"该轮未发生"——回滚本轮 user 消息。
            # (此前口径只覆盖构建/压缩先于落库的一半;实测中止于流中会残留 1 条无回复 user 消息。)
            if not assistant_saved:
                try:
                    db.delete_message(user_msg_id, conversation_id)
                except Exception as de:
                    logger.warning("中止回滚 user 消息失败(会话 %s): %s", conversation_id, de)
            raise

    # 周报 REST 直调(供前端周报页与评测脚本确定性使用,不依赖 LLM 决策)
    async def weekly_add(self, content: str, category: str, occurred_at: str,
                         student_name: str = "", summary: str = "") -> dict:
        args = {"content": content, "category": category, "occurred_at": occurred_at}
        # 只在非空时传:空串交给 MCP 层默认值,避免"传了空串"与"没传"在两端语义分叉
        if student_name:
            args["student_name"] = student_name
        if summary:
            args["summary"] = summary
        return await self.weekly.call("add_fragment", args)

    async def weekly_update(self, fragment_id: int, student_name: str = "",
                            summary: str = "") -> dict:
        return await self.weekly.call("update_fragment", {
            "fragment_id": fragment_id, "student_name": student_name, "summary": summary,
        })

    async def weekly_list(self, start_date: str = "", end_date: str = "") -> dict:
        return await self.weekly.call("list_fragments", {"start_date": start_date, "end_date": end_date})

    async def weekly_export_talk(self, month: str) -> dict:
        return await self.weekly.call("export_talk_records", {"month": month})

    async def weekly_delete(self, fragment_id: int) -> dict:
        return await self.weekly.call("delete_fragment", {"fragment_id": fragment_id})

    async def weekly_render(self, start_date: str, end_date: str = "") -> dict:
        return await self.weekly.call("render_weekly_report", {
            "start_date": start_date, "end_date": end_date,
        })

    async def weekly_archive(self, title: str, start_date: str, end_date: str, content_md: str) -> dict:
        return await self.weekly.call("archive_report", {
            "title": title, "start_date": start_date, "end_date": end_date, "content_md": content_md,
        })

    async def weekly_reports(self, start_date: str = "", end_date: str = "") -> dict:
        return await self.weekly.call("list_reports", {"start_date": start_date, "end_date": end_date})

    async def weekly_report_detail(self, report_id: int) -> dict:
        return await self.weekly.call("read_report", {"report_id": report_id})

    # ---------- 会议纪要存取(同库:周报 MCP 的 minutes 表) ----------

    async def minutes_add(self, fields: dict) -> dict:
        return await self.weekly.call("add_minutes", fields)

    async def minutes_list(self, start_date: str = "", end_date: str = "") -> dict:
        return await self.weekly.call("list_minutes",
                                      {"start_date": start_date, "end_date": end_date})

    async def minutes_get(self, minutes_id: int) -> dict:
        return await self.weekly.call("get_minutes", {"minutes_id": minutes_id})

    async def minutes_update(self, minutes_id: int, fields: dict) -> dict:
        return await self.weekly.call("update_minutes", {"minutes_id": minutes_id, **fields})

    async def minutes_delete(self, minutes_id: int) -> dict:
        return await self.weekly.call("delete_minutes", {"minutes_id": minutes_id})
