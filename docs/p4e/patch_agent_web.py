#!/usr/bin/env python3
"""P4e 主体 M-A/M-B/M-C:agent.py 接入联网检索(分区上下文 + 开关 + 降级可观测)。

改写点(全部 count 断言):
  1. import 加 websearch
  2. class AgentService 之前插入联网常量与 `_web_enabled`
  3. chat_for / chat_stream_for 签名加 `web_search` 参数(各 1 处)
  4. 两处 history-gate 之后插入「联网补充通道」(相同文本,count=2)
  5. 两处 context 组装追加联网区块(相同文本,count=2)
  6. chat_for 拒答分支:不可用提示 + web_sources 字段
  7. chat_for 落库前:整段级声明注入 + 响应带 web_sources
  8. chat_stream_for:sources/done 事件带 web_sources;拒答分支提示;落库前声明与下发

用法: novaagent/.venv/Scripts/python.exe docs/p4e/patch_agent_web.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "novaagent" / "novaagent" / "agent.py"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

# ---------- 1 ----------
A1_OLD = "from . import config, db, graph, llm, rag, refusal\n"
A1_NEW = "from . import config, db, graph, llm, rag, refusal, websearch\n"

# ---------- 2 ----------
A2_OLD = 'class AgentService:\n    """持有周报 MCP 长连接,提供检索增强对话与周报工具直调。"""\n'
A2_NEW = '''# ---------- P4e M-A / M-C:联网来源的分区上下文与整段级声明 ----------
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

WEB_CONTEXT_BLOCK = """

联网检索资料（公网检索，未经本校核实，仅作参考）:
{urls}

联网资料使用规则:
1. 只在上列联网资料能支撑时才作答，不得用自有知识补充联网资料里没有的事实；
2. **禁止**在正文里写 [W1]、[W2] 之类的角标——上游不提供「哪句出自哪条来源」的映射，
   写了就是假精确；需要指代来源时直接说站点名（如"据国家统计局网站"）；
3. 联网资料不能替代本校规定；涉及本校具体政策/流程/时限的，如实说明公网查不到本校口径。
"""

# M-C 降级提示:联网不可用必须让用户看见(坑 46/47:静默兜底等于把缺陷藏起来)
WEB_UNAVAILABLE_NOTE = ("\\n\\n（已尝试联网检索，但本次联网搜索不可用或未返回结果；"
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


''' + A2_OLD

# ---------- 3 ----------
A3_OLD = """    async def chat_for(self, user_id: int, username: str, role: str, question: str,
                       conversation_id: int | None = None,
                       scope: dict | None = None) -> dict[str, Any]:"""
A3_NEW = """    async def chat_for(self, user_id: int, username: str, role: str, question: str,
                       conversation_id: int | None = None,
                       scope: dict | None = None,
                       web_search: bool | None = None) -> dict[str, Any]:"""

A3B_OLD = """    async def chat_stream_for(self, user_id: int, username: str, role: str, question: str,
                              conversation_id: int | None = None,
                              scope: dict | None = None):"""
A3B_NEW = """    async def chat_stream_for(self, user_id: int, username: str, role: str, question: str,
                              conversation_id: int | None = None,
                              scope: dict | None = None,
                              web_search: bool | None = None):"""

# ---------- 4（两处相同） ----------
A4_OLD = """            else:
                ctx_info["history_gate"] = "miss"
        user_msg_id = db.add_message(user_id, "user", question, conversation_id)
"""
A4_NEW = """            else:
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
        user_msg_id = db.add_message(user_id, "user", question, conversation_id)
"""

# ---------- 5（两处相同） ----------
A5_OLD = """            context = "\\n\\n".join(
                f"[{s['ref']}] 《{s['title']}》({s['role_min']}可读)\\n{s['content']}" for s in sources
            ) or "(本角色可见范围内未检索到相关资料)"
"""
A5_NEW = """            context = "\\n\\n".join(
                f"[{s['ref']}] 《{s['title']}》({s['role_min']}可读)\\n{s['content']}" for s in sources
            ) or "(本角色可见范围内未检索到相关资料)"
            if web_sources:   # P4e M-A:联网资料**另起一区**,与本地 [1..n] 不混编号
                context += WEB_CONTEXT_BLOCK.format(
                    urls="\\n".join(f"- {w['url']}" for w in web_sources))
"""

# ---------- 6 ----------
A6_OLD = """            if do_refuse:
                answer = refusal.build_refusal(question, reason)
                db.add_message(user_id, "assistant", answer, conversation_id)
                assistant_saved = True
                return {"answer": answer, "sources": [], "tool_trace": [],
                        "conversation_id": conversation_id, "context": ctx_info}
"""
A6_NEW = """            if do_refuse:
                answer = refusal.build_refusal(question, reason)
                if web_on and ctx_info.get("web_unavailable"):
                    answer += WEB_UNAVAILABLE_NOTE
                db.add_message(user_id, "assistant", answer, conversation_id)
                assistant_saved = True
                return {"answer": answer, "sources": [], "tool_trace": [],
                        "conversation_id": conversation_id, "context": ctx_info,
                        "web_sources": []}
"""

# ---------- 7 ----------
A7_OLD = """            db.add_message(user_id, "assistant", answer, conversation_id, sources=sources)
            assistant_saved = True
            return {"answer": answer, "sources": sources, "tool_trace": tool_trace,
                    "conversation_id": conversation_id, "context": ctx_info}
"""
A7_NEW = """            if web_sources:   # P4e M-A:整段级声明由**代码注入**,不靠模型自觉
                answer = (answer or "").rstrip() + "\\n\\n" + WEB_DECLARE
            db.add_message(user_id, "assistant", answer, conversation_id, sources=sources)
            assistant_saved = True
            return {"answer": answer, "sources": sources, "tool_trace": tool_trace,
                    "conversation_id": conversation_id, "context": ctx_info,
                    "web_sources": web_sources}
"""

# ---------- 8a: 流式拒答分支 ----------
A8A_OLD = """            if do_refuse:  # P4a C1: 确定性拒答模板直接作为流式输出
                text = refusal.build_refusal(question, reason)
                db.add_message(user_id, "assistant", text, conversation_id)
                assistant_saved = True
                yield {"type": "sources", "sources": []}
                yield {"type": "context", **ctx_info}
                yield {"type": "delta", "content": text}
                yield {"type": "done", "answer": text, "sources": [], "tool_trace": [],
                       "conversation_id": conversation_id, "context": ctx_info}
                return
"""
A8A_NEW = """            if do_refuse:  # P4a C1: 确定性拒答模板直接作为流式输出
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
"""

# ---------- 8b: 流式正常路径 sources 事件 ----------
A8B_OLD = '            yield {"type": "sources", "sources": sources}\n'
A8B_NEW = '            yield {"type": "sources", "sources": sources, "web_sources": web_sources}\n'

# ---------- 8c: 流式落库前 ----------
A8C_OLD = """            db.add_message(user_id, "assistant", "".join(answer_parts), conversation_id,
                           sources=sources)  # P4b: 答案落库;P4b-fix ①: 带来源快照
            assistant_saved = True
            yield {"type": "done", "answer": "".join(answer_parts), "sources": sources,
                   "tool_trace": tool_trace, "conversation_id": conversation_id, "context": ctx_info}
"""
A8C_NEW = """            if web_sources:   # P4e M-A:整段级声明由**代码注入**;同时作为 delta 下发
                decl = "\\n\\n" + WEB_DECLARE
                answer_parts.append(decl)
                yield {"type": "delta", "content": decl}
            db.add_message(user_id, "assistant", "".join(answer_parts), conversation_id,
                           sources=sources)  # P4b: 答案落库;P4b-fix ①: 带来源快照
            assistant_saved = True
            yield {"type": "done", "answer": "".join(answer_parts), "sources": sources,
                   "tool_trace": tool_trace, "conversation_id": conversation_id,
                   "context": ctx_info, "web_sources": web_sources}
"""

PAIRS = [
    ("A1", A1_OLD, A1_NEW, 1), ("A2", A2_OLD, A2_NEW, 1),
    ("A3", A3_OLD, A3_NEW, 1), ("A3B", A3B_OLD, A3B_NEW, 1),
    ("A4", A4_OLD, A4_NEW, 2), ("A5", A5_OLD, A5_NEW, 2),
    ("A6", A6_OLD, A6_NEW, 1), ("A7", A7_OLD, A7_NEW, 1),
    ("A8A", A8A_OLD, A8A_NEW, 1), ("A8B", A8B_OLD, A8B_NEW, 1), ("A8C", A8C_OLD, A8C_NEW, 1),
]


def main() -> int:
    src = AGENT.read_text(encoding="utf-8")
    for name, old, new, cnt in PAIRS:
        n = src.count(old)
        if n != cnt:
            print(f"[FAIL] {name} 命中 {n} 次(期望 {cnt})")
            return 1
        src = src.replace(old, new)
    AGENT.write_text(src, encoding="utf-8")
    print("[OK] agent.py 已接入联网检索(分区上下文 / 开关 / 降级可观测)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
