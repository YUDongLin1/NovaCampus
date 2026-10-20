#!/usr/bin/env python3
"""P4e S1-①:早窗提交——把「闸门判定」与「delta 下发」解耦,恢复真流式。

三处精确改写(每处 count/切片断言,失败即报错):
  1. `config.py` 追加 S1 三个开关 + P4e 联网配置
  2. `agent.py` 在 `record_ungrounded` 之后插入 `_StreamGate`
  3. `agent.py` 的 `chat_stream_for` 缓冲块整体替换为早窗版

用法: novaagent/.venv/Scripts/python.exe docs/p4e/patch_s1_early_window.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONF = ROOT / "novaagent" / "novaagent" / "config.py"
AGENT = ROOT / "novaagent" / "novaagent" / "agent.py"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

# ---------------- 1. config.py ----------------
CONF_ANCHOR = "\n\ndef configured() -> list[str]:\n"
CONF_NEW = '''
# ---------- P4e S1: 流式 grounding 闸门的「早窗提交」 ----------
# 背景(HANDOFF 坑 60 / TASKS P4e S1):P4e M4 为拦「有来源却零 [n] 零数字」的空话答案,
# 把 /api/chat/stream 改成 delta **全量缓冲**、判完闸门再下发。复核方实测
# **TTFB 2365ms / E2E 2401ms、12 个 delta 挤在最后 36ms** → 渐进显示归零,真流式被关掉。
# S1 的解法:判定与下发解耦——delta 默认直接放行,只在「早窗」内(还没出现可核查事实
# **且**累计生成不足 N 字)暂缓;窗口一过立刻补发。**整段生成完仍零可核查事实**才重生一次。
#
# 【N 为什么取 80】
#   · 可核查事实(首个 `[n]` 引用或第一个数字)在据实作答时**几乎总在首句内**出现,
#     实测本项目 qa 用例答案首句 40~120 字 → 80 字能让「首个事实」大概率落在窗口内,
#     命中即放行,缓冲量通常只有十几字;
#   · 最坏情况(整段无事实)也只憋住 80 字 ≈ 1~2 句,而不是整段 200~400 字;
#   · 太小(如 20)会让短免责话术被提前放行、削弱闸门的"不发空话"初衷;
#     太大(如 300)则退回近似全缓冲。故取 60~120 区间的中位。
GROUNDING_EARLY_WINDOW_CHARS = int(env("NOVA_GROUNDING_EARLY_WINDOW_CHARS", "80"))
# 闸门总开关:0 = 关闭(P4e M4 之前的行为),供三档延迟对照取"关闭"档
GROUNDING_GATE_ENABLED = env("NOVA_GROUNDING_GATE", "1") not in ("0", "false", "False")
# ⚠ 测试钩子(默认关):强制流式首版被判为「无据」,使 stream_sse 的重生通道断言
#   **必然**被执行(否则该通道只有约 20% 概率自然命中,断言会空跑——坑 39/45)。
#   只作用于 /api/chat/stream 的首版判定,不影响 /api/chat,重生仍走真实 LLM。
GROUNDING_STREAM_FORCE_UNGROUNDED = env("NOVA_GROUNDING_STREAM_FORCE_UNGROUNDED", "0") == "1"

# ---------- P4e M7: 联网搜索(默认关闭) ----------
WEB_SEARCH_ENABLED = env("NOVA_WEB_SEARCH_ENABLED", "0") not in ("0", "false", "False")
WEB_SEARCH_TIMEOUT_S = float(env("NOVA_WEB_SEARCH_TIMEOUT_S", "20"))
WEB_SEARCH_MAX_SOURCES = int(env("NOVA_WEB_SEARCH_MAX_SOURCES", "8"))

''' + CONF_ANCHOR

# ---------------- 2. agent.py: _StreamGate ----------------
GATE_ANCHOR = '        logger.warning("ungrounded 记录失败(不影响对话): %s", e)\n'
GATE_NEW = GATE_ANCHOR + '''


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

    def __init__(self, n_sources: int):
        self.n_sources = n_sources
        self.enabled = config.GROUNDING_GATE_ENABLED
        self.window_chars = config.GROUNDING_EARLY_WINDOW_CHARS
        self.force = config.GROUNDING_STREAM_FORCE_UNGROUNDED
        self.pending: list = []
        self.text = ""            # 已生成全文(含尚未放行的部分)
        self.released_chars = 0   # 已下发给前端的字符数
        self.window_closed = False  # 早窗已过 → 之后一律直接放行

    def feed(self, chunk: str) -> list:
        """喂入一段 delta,返回**本次应当下发**的片段列表(可能为空=暂缓)。"""
        self.text += chunk or ""
        if not self.enabled or self.window_closed:
            self.released_chars += len(chunk or "")
            return [chunk] if chunk else []
        self.pending.append(chunk)
        # ① 出现首个可核查事实([n] 引用或数字) → 这一版算有据,立即放行
        if (not self.force) and bool(_FACTUAL_RE.search(self.text)):
            return self._release()
        # ② 早窗用尽(满 N 字) → 照常放行,不再继续憋着(N=0 表示退回全缓冲)
        if self.window_chars > 0 and len(self.text) >= self.window_chars:
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
        if self.force:      # 测试钩子:强制首版走重生通道
            return False
        if not self.n_sources:
            return True     # 无来源 = 拒答路径,不走本闸门
        return bool(_FACTUAL_RE.search(self.text))

    def need_regen(self) -> bool:
        return self.enabled and not self.grounded
'''

# ---------------- 3. agent.py: chat_stream_for 缓冲块 ----------------
OLD_START = ('            tool_trace: list[dict] = []\n'
             '            answer_parts: list[str] = []\n'
             '            # P4e M4:流式路径的 grounding 闸门靠**缓冲**实现')
OLD_END = ('            # 闸门判定通过后才真正下发内容(重生时只发重生结果,不补发被丢弃的首版)\n'
           '            for seg in buffered:\n'
           '                if seg:\n'
           '                    yield {"type": "delta", "content": seg}\n')

NEW_BLOCK = '''            tool_trace: list[dict] = []
            answer_parts: list[str] = []
            # P4e S1-①:早窗提交——delta 默认直接放行(gate.feed 返回本次应下发的片段),
            # 只在早窗内(未出现可核查事实且累计不足 N 字)暂缓。整段生成完仍零事实才重生一次。
            # 对比 M4 的全量缓冲:首字不再等整段生成完,但闸门判据一条都没放宽。
            gate = _StreamGate(len(sources))
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
                                     "content": json.dumps(result, ensure_ascii=False)})
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
'''


def main() -> int:
    # 1. config.py
    src = CONF.read_text(encoding="utf-8")
    if src.count(CONF_ANCHOR) != 1:
        print("[FAIL] config.py 锚点命中次数 != 1")
        return 1
    CONF.write_text(src.replace(CONF_ANCHOR, CONF_NEW, 1), encoding="utf-8")
    print("[OK] config.py 已追加 S1 / 联网配置")

    # 2+3. agent.py
    src = AGENT.read_text(encoding="utf-8")
    if src.count(GATE_ANCHOR) != 1:
        print("[FAIL] agent.py _StreamGate 锚点命中次数 != 1")
        return 1
    src = src.replace(GATE_ANCHOR, GATE_NEW, 1)
    i = src.find(OLD_START)
    j = src.find(OLD_END)
    if i < 0 or j < 0 or j <= i:
        print(f"[FAIL] 缓冲块切片失败: start={i} end={j}")
        return 1
    src = src[:i] + NEW_BLOCK + src[j + len(OLD_END):]
    AGENT.write_text(src, encoding="utf-8")
    print("[OK] agent.py 已替换为早窗提交")
    return 0


if __name__ == "__main__":
    sys.exit(main())
