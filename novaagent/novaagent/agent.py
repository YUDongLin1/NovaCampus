"""Agent 编排层:RAG 上下文注入 + 工具调用循环(周报 MCP 工具)

引用约定:检索结果编号 [1]..[n] 注入 system prompt,要求模型回答时标注引用,
来源列表随答案一并返回给前端渲染。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from . import config, db, llm, rag
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

    async def chat_for(self, user_id: int, username: str, role: str, question: str) -> dict[str, Any]:
        eff = self.effective_llm(user_id)
        min_rank = db.config.ROLE_RANK[role]
        sources = await rag.search(question, min_rank)
        context = "\n\n".join(
            f"[{s['ref']}] 《{s['title']}》({s['role_min']}可读)\n{s['content']}" for s in sources
        ) or "(本角色可见范围内未检索到相关资料)"
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
            {"role": "user", "content": question},
        ]
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
        return {"answer": answer, "sources": sources, "tool_trace": tool_trace}

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
