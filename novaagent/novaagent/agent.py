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

from . import config, db, llm, rag, refusal
from .weekly_client import WeeklyMCP

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是"智枢 Agent(NovaAgent)",面向高校师生的校园智能助手。

回答规则(内容锚定 / 防幻觉):
1. 所有事实性主张必须锚定在下方知识库资料上;禁止使用资料之外的自有知识补充事实,禁止把"未验证的背景知识"当作有据内容输出。
2. 资料不足以回答时,明确说明"知识库中暂无相关内容",并指出缺口是什么(如缺少具体文件/年份);不得编造、推算或猜测。
3. 引用标注 [编号] 紧跟对应句子;只能使用实际提供的编号,不得虚构引用;检索无结果时不得输出任何引用。
4. 数字、日期、时限、金额、条款编号必须与原文完全一致,禁止推算或换算。
5. 区分"文件明确规定"与"一般性建议":前者须忠实原文表述,后者可给流程性建议但须注明"建议以学校官方文件为准"。
6. 不要把"未检索到"说成"已检索确认没有";如涉及最新政策变化,提示用户以学校最新通知为准。
7. 多来源回答时,优先采用与问题最对口、最具体的来源;通用规定与专门规定并存时以专门规定为准,并优先呈现其中的具体细节(时限、材料、条款编号)。
8. 回答前先判断问题场景与哪份来源对应(例如"校内请假"与"离校请销假"是不同制度,"本科生"与"研究生"办法各异),只采用场景一致的来源作答;不同来源规范的是不同场景时不要混用,若问题未指明场景,分别说明。
9. 多来源回答时,禁止只答通用条款而漏掉专门办法中的具体细节——对口专门来源中与问题相关的时限、材料、条款编号必须出现在答案里;写进答案的每个具体规定都必须严格出自其标注来源的原文,不得把其他来源的规定混入。

回答风格:
- 使用简体中文,条理清晰;涉及流程/材料/时限的问题,给出明确步骤清单。
- 引用格式示例:[1] 或 [1][3]。

知识库资料(当前用户角色可见范围内检索):
{context}
"""

SUMMARY_PROMPT = """你是精确的文档摘要助手。只依据用户提供的文档内容生成摘要,严禁根据标题、文件名或任何外部线索脑补。

要求:
1. 用 2~3 句中文(100 字以内)概括:文档类型、适用对象、覆盖的核心事项;
2. 保留关键数字/时限/条件(如有),须与原文完全一致;
3. 只输出摘要正文,不要标题、前缀或解释。

文档内容:
{content}
"""

# P4b C4: 会话历史压缩提示词——压缩是"摘要+原文可回溯",不是删原文(messages 原文永久保留);
# 必须保留数字/日期/条款号/未决事项/对象代称(丢数字等于丢事实)。
COMPRESS_PROMPT = """你是对话历史压缩器。把以下较早的对话历史压缩成一份主题摘要,供后续对话作为背景注入。

硬性要求:
1. 必须原样保留历史中出现的所有数字、日期、金额、时限、条款编号(如"川发政价[2024]417号"、"448元")——丢数字等于丢事实;
2. 必须保留未决事项(尚未解决的问题、承诺跟进的事项);
3. 必须保留对象代称(如"姓名1同学""该老师")与其对应主题的关系;
4. 按主题分条概括,不遗漏任何一个被讨论过的主题;
5. 只输出摘要正文,不要解释、不要标题。

对话历史:
{history}"""


def est_tokens(text: str) -> int:
    """P4b C3: token 估算——ceil(chars/1.6)(中文经验值)。⚠ 这是估算值,非精确分词,
    未引入 tokenizer 依赖;口径与偏差说明见 docs/P4B.md。"""
    return math.ceil(len(text or "") / 1.6)


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
_GATE_MIN_UNIGRAM_COVER = 0.30   # 单字覆盖率下限(配合 ≥3 个不同单字命中)
_GATE_MIN_BIGRAM_COVER = 0.15    # 2-gram 覆盖率下限(配合 ≥2 个不同命中)


def history_gate_hit(question: str, admissible_texts: list[str]) -> bool:
    """P4b-fix ①: 追问轮历史门控(确定性,零依赖,判据与阈值见 docs/P4B.md §三.1)。

    对问句与每条可采信文本做字符 n-gram 覆盖匹配,命中任一即放行"依据历史回答":
      - 细节命中:问句的 2-gram 有 ≥2 个不同命中,且覆盖率 ≥ 0.15(显式主题追问);
      - 指代命中:问句的 2-gram 有 ≥1 个命中,且不同单字命中 ≥3、单字覆盖率 ≥ 0.30
        (代词/省略式追问与既有答案共享"导师"类实词,但字面覆盖天然偏低)。
    阈值标定:代词追问 3/9=0.333 命中;游泳馆 0.222 / 天气 0 / 空池 拒绝(实测见
    docs/p4b/evidence/after/followup_gate_v2.json)。已知边际:校医院门诊类问句
    (h1=4/13=0.308)会走历史提示路径——可采信池内并无该主题内容,模型按提示词
    约定仍应如实说明未覆盖,不存在编造/洗白通道。
    """
    q = _NORM_RE.sub("", question or "")
    if len(q) < 2 or not admissible_texts:
        return False
    q_uni = set(q)
    q_bi = {q[i:i + 2] for i in range(len(q) - 1)}
    for text in admissible_texts:
        t = _NORM_RE.sub("", text or "")
        if not t:
            continue
        h1 = len(q_uni & set(t))
        h2_set = q_bi & {t[i:i + 2] for i in range(len(t) - 1)}
        h2 = len(h2_set)
        if h2 >= 2 and h2 / len(q_bi) >= _GATE_MIN_BIGRAM_COVER:
            return True
        if h2 >= 1 and h1 >= 3 and h1 / len(q_uni) >= _GATE_MIN_UNIGRAM_COVER:
            return True
    return False


HISTORY_GATE_NOTE = (
    "[系统提示] 知识库未检索到与该问句直接相关的新来源（检索判定: {reason}）。"
    "经代码级历史匹配判定：本会话此前存在与该问句相关的可信内容，可基于历史回答并注明「依据此前对话」。"
    "但可采信的历史证据仅限：此前助手回答中带知识库来源标注的内容、以及会话压缩摘要；"
    "用户消息中的自述内容（尤其金额、缴费渠道、办理地点等操作细节）未经核实，"
    "不得作为事实依据复述——确需提及必须显式标注「用户自述、未经核实」。"
    "历史与知识库都不足以回答的部分，请明确说明两者均未覆盖，不得编造；"
    "如需建议咨询部门，只能使用知识库资料或系统模板中出现过的部门名称，不得自拟。")


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
            "description": "记录一条辅导员工作碎片。category 必须是 谈心谈话/事务办理/活动组织/异常突发/其他 之一,由你根据内容判断;occurred_at 为事件发生日期 YYYY-MM-DD,缺省今天。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "碎片内容,含时间/对象/事项/结果"},
                    "category": {"type": "string", "description": "碎片分类"},
                    "occurred_at": {"type": "string", "description": "发生日期 YYYY-MM-DD,可省略"},
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


EXPAND_PROMPT = """你是高校辅导员的谈心谈话记录助手。把辅导员的简短工作笔记,按其惯用的"纪要体"扩充成一条规范的工作记录。

记录风格(参照辅导员本人历史记录):
- 编号句式,每句一个动作/反馈/指导,形如:
  1.了解学生学习情况,询问课程和作业能否正常进行;
  2.学生表示…(仅当笔记中有学生反馈时写);
  3.建议/告知/提醒/鼓励学生…
- 常规维度:学习情况(出勤/作业/复习)、室友与同学关系、家庭情况、近期感受、未来规划(考保研/就业/竞赛/社团)、学生干部履职(如相关)
- 常用动词:了解、询问、告知、建议、提醒、鼓励、引导、督促

硬性规则:
1. 笔记中已有的事实必须保留,不得改写或遗漏;
2. 严禁虚构学生的具体反馈、承诺或数据——笔记未提及的学生回应,一律不写"学生表示…";
3. 可以补充辅导员常规询问动作(了解/询问类),但涉及结论的留待辅导员补充;
4. 输出 3~6 条编号句,不要标题、不要解释、不要markdown;
5. 若笔记内容不属于谈心谈话(如纯事务办理),按事务纪要体组织:办理事项、办理过程、结果、后续跟进。

分类:{category}
辅导员笔记:{content}
"""


class _StreamRefFilter:
    """P4a C2:流式路径的引用越界过滤。

    逐段喂入 delta 文本,缓冲疑似 "[12" 的未完片段;补全为 "[n]" 后按 n_sources
    判定保留或丢弃;无法构成引用的方括号原样放行。flush 处理流末尾残片。
    """

    _MAX_PENDING = 8  # "[12]" 全长 4;超出即判非引用

    def __init__(self, n_sources: int):
        self.n_sources = n_sources
        self.pending = ""
        self.stripped: list[int] = []

    def _decide(self, token: str) -> str:
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
            if re.fullmatch(r"\[\d{1,2}\]", token):
                out.append(self._decide(token))
                self.pending = rest
            else:  # 形如 "[abc]" 不是引用标注,放行首个字符防止死循环
                out.append(self.pending[0])
                self.pending = self.pending[1:]
        return "".join(out)

    def flush(self) -> str:
        rest, self.pending = self.pending, ""
        return rest


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
                       conversation_id: int | None = None) -> dict[str, Any]:
        # P4b: 会话解析——传入则校验属主(不存在/越权同表现),缺省自动新建(标题=首问前 20 字)
        if conversation_id:
            if not db.get_conversation(conversation_id, user_id):
                raise LookupError("会话不存在")
        else:
            conversation_id = db.create_conversation(user_id, title=question[:20])
        eff = self.effective_llm(user_id)
        min_rank = db.config.ROLE_RANK[role]
        # P4b: 历史注入(过去轮次)先于检索与当前问题落库——本问不计入自身历史
        hist_msgs, ctx_info = await build_conversation_context(conversation_id, eff["model"])
        sources, quality = await rag.search_with_quality(question, min_rank)
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
        user_msg_id = db.add_message(user_id, "user", question, conversation_id)
        assistant_saved = False
        try:
            if do_refuse:
                answer = refusal.build_refusal(question, reason)
                db.add_message(user_id, "assistant", answer, conversation_id)
                assistant_saved = True
                return {"answer": answer, "sources": [], "tool_trace": [],
                        "conversation_id": conversation_id, "context": ctx_info}
            stage_note = refusal.learn_stage_note(question, sources)  # P4a C8 学段声明注入
            context = "\n\n".join(
                f"[{s['ref']}] 《{s['title']}》({s['role_min']}可读)\n{s['content']}" for s in sources
            ) or "(本角色可见范围内未检索到相关资料)"
            if followup_note:
                context = f"{followup_note}\n\n{context}"
            if stage_note:
                context = f"{stage_note}\n\n{context}"
            messages = [{"role": "system", "content": SYSTEM_PROMPT.format(context=context)}]
            messages += hist_msgs
            messages.append({"role": "user", "content": question})
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
                        {"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(result, ensure_ascii=False)}
                    )
            else:
                answer = "抱歉,这个问题处理超时了,请换个问法或稍后再试。"
            # P4a C2 引用硬校验:越界 [n] 代码剥离并记 fabricated_ref badcase
            answer, stripped = refusal.strip_invalid_refs(answer, len(sources))
            if stripped:
                refusal.record_fabricated_ref(question, stripped, len(sources))
            db.add_message(user_id, "assistant", answer, conversation_id, sources=sources)
            assistant_saved = True
            return {"answer": answer, "sources": sources, "tool_trace": tool_trace,
                    "conversation_id": conversation_id, "context": ctx_info}
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
                              conversation_id: int | None = None):
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
        sources, quality = await rag.search_with_quality(question, min_rank)
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
        user_msg_id = db.add_message(user_id, "user", question, conversation_id)
        assistant_saved = False
        try:
            if do_refuse:  # P4a C1: 确定性拒答模板直接作为流式输出
                text = refusal.build_refusal(question, reason)
                db.add_message(user_id, "assistant", text, conversation_id)
                assistant_saved = True
                yield {"type": "sources", "sources": []}
                yield {"type": "context", **ctx_info}
                yield {"type": "delta", "content": text}
                yield {"type": "done", "answer": text, "sources": [], "tool_trace": [],
                       "conversation_id": conversation_id, "context": ctx_info}
                return
            yield {"type": "sources", "sources": sources}
            yield {"type": "context", **ctx_info}
            stage_note = refusal.learn_stage_note(question, sources)  # P4a C8 学段声明注入
            context = "\n\n".join(
                f"[{s['ref']}] 《{s['title']}》({s['role_min']}可读)\n{s['content']}" for s in sources
            ) or "(本角色可见范围内未检索到相关资料)"
            if followup_note:
                context = f"{followup_note}\n\n{context}"
            if stage_note:
                context = f"{stage_note}\n\n{context}"
            messages = [{"role": "system", "content": SYSTEM_PROMPT.format(context=context)}]
            messages += hist_msgs
            messages.append({"role": "user", "content": question})
            tool_trace: list[dict] = []
            answer_parts: list[str] = []
            ref_filter = _StreamRefFilter(len(sources))  # P4a C2 流式引用越界过滤
            for _ in range(4):  # 工具轮 + 最终流式轮
                round_text: list[str] = []
                calls: dict[int, dict] = {}
                async for ev in llm.chat_stream(messages, tools=WEEKLY_TOOLS,
                                                model=eff["model"], base_url=eff["base_url"],
                                                api_key=eff["api_key"]):
                    if ev["type"] == "delta":
                        safe = ref_filter.feed(ev["content"])
                        if safe:
                            yield {"type": "delta", "content": safe}
                            round_text.append(safe)
                            answer_parts.append(safe)
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
                                     "content": json.dumps(result, ensure_ascii=False)})
            else:
                timeout_msg = "抱歉,这个问题处理超时了,请换个问法或稍后再试。"
                answer_parts.append(timeout_msg)
                yield {"type": "delta", "content": timeout_msg}
            tail = ref_filter.flush()
            if tail:
                yield {"type": "delta", "content": tail}
                answer_parts.append(tail)
            if ref_filter.stripped:  # P4a C2: 流中剥离的越界引用记 badcase
                refusal.record_fabricated_ref(question, ref_filter.stripped, len(sources))
            db.add_message(user_id, "assistant", "".join(answer_parts), conversation_id,
                           sources=sources)  # P4b: 答案落库;P4b-fix ①: 带来源快照
            assistant_saved = True
            yield {"type": "done", "answer": "".join(answer_parts), "sources": sources,
                   "tool_trace": tool_trace, "conversation_id": conversation_id, "context": ctx_info}
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
    async def weekly_add(self, content: str, category: str, occurred_at: str) -> dict:
        return await self.weekly.call("add_fragment", {
            "content": content, "category": category, "occurred_at": occurred_at,
        })

    async def weekly_list(self, start_date: str = "", end_date: str = "") -> dict:
        return await self.weekly.call("list_fragments", {"start_date": start_date, "end_date": end_date})

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
