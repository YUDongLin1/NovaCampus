#!/usr/bin/env python3
"""P4e S1-② ⑤ 的**确定性**证据:进程内驱动 `chat_stream_for`,桩掉 LLM 与检索。

为什么不用 HTTP 用例单独证明:闸门自然命中率约 20%(qa-17 实测 2/10),
靠真实模型命中来断言「重生通道」会**空跑**(坑 39/45)。本探针把首版答案固定成
「零 [n] 零数字」的空话,于是闸门**必然**命中,断言必然被执行。

DB:用 agent.db 的**副本**(NOVA_DATA_DIR 指到临时目录),生产库零改动(HANDOFF 纪律)。

断言:
  U1 空话首版 → 出现 grounding_retry,且 released_chars 与早窗语义一致
  U2 retry 之后**逐段**下发重生结果(delta 数 > 1)
  U3 done.answer / 落库答案 == 重生后版本(不含被作废的首版)
  U4 ctx_info["grounding_gate"] 写在 done 事件里(hit/regenerated/ok_after_regen)
  U5 N=0(全缓冲)时首版在生成结束前**一个 delta 都不发**(回归闸)
  U6 有据首版([1] 出现)→ 不重生、无 retry 事件
  U7 闸门关闭档(NOVA_GROUNDING_GATE=0)→ 无 retry、无 grounding_gate
退出码:0 = 全过;1 = 有 FAIL。
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

# ⚠ 必须在 import novaagent.* 之前把 DATA_DIR 指到库副本(config 在 import 期读 env)
_TMP = Path(tempfile.mkdtemp(prefix="nova_gate_unit_"))
_SRC_DB = ROOT / "novaagent" / "data" / "agent.db"
_DATA = _TMP / "novaagent" / "data"
_DATA.mkdir(parents=True, exist_ok=True)
if _SRC_DB.exists():
    shutil.copy2(_SRC_DB, _DATA / "agent.db")
os.environ["NOVA_DATA_DIR"] = str(_DATA)   # 深一层:record_ungrounded 的落盘也留在临时目录
os.environ["NOVA_GRAPH_ENABLED"] = "0"          # 跳过 LangGraph,检索走桩
os.environ["NOVAAGENT_EVAL_TEMPERATURE"] = "0"
sys.path.insert(0, str(ROOT / "novaagent"))

from novaagent import agent, config, db, llm, rag  # noqa: E402


# ---- 演示口令:一律从环境变量读,源码内不落明文(开源前脱敏要求) ----
def _demo_pw(role: str) -> str:
    r = role.upper()
    pwd = os.environ.get(f"NOVA_SEED_{r}_PASSWORD") or os.environ.get("NOVA_DEMO_PASSWORD", "")
    if not pwd:
        raise RuntimeError(
            f"未设置演示口令:请在 novaagent/.env 中写入 NOVA_DEMO_PASSWORD"
            f"(或 NOVA_SEED_{r}_PASSWORD)。")
    return pwd


ADMIN_PW = _demo_pw("admin")
COUNSELOR_PW = _demo_pw("counselor")
STUDENT_PW = _demo_pw("student")


FAILS: list = []


def ck(cond: bool, name: str, detail: str = "") -> None:
    print(f"{'[PASS]' if cond else '[FAIL]'} {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        FAILS.append(name)


FAKE_SOURCES = [
    {"ref": 1, "title": "研究生学籍管理规定", "content": "最长学习年限为 5 年。", "score": 0.98,
     "role_min": "student", "doc_id": 1, "chunk_id": 1},
    {"ref": 2, "title": "研究生学籍管理规定", "content": "休学一般一次一年。", "score": 0.91,
     "role_min": "student", "doc_id": 1, "chunk_id": 2},
]

BAD_ANSWER = "这个我这边暂时没法确认，建议你再问问别的地方。"      # 零 [n] 零数字
GOOD_ANSWER = "根据规定，研究生最长学习年限为 5 年[1]，休学一般一次一年[2]。"


def _mk_stream(text: str, chunk: int = 6, then: str | None = None):
    """按顺序返回:第 1 次流式=text,其后=then(text)。

    ⚠ S1-① 后**重生也走 llm.chat_stream**(重生结果同样逐段下发),所以桩必须能区分第几次调用。
    """
    state = {"n": 0}

    async def _stream(messages, tools=None, model="", base_url="", api_key="",
                      max_tokens=2048, temperature=0.3):
        state["n"] += 1
        body = text if state["n"] == 1 else (then if then is not None else text)
        for i in range(0, len(body), chunk):
            yield {"type": "delta", "content": body[i:i + chunk]}
        yield {"type": "finish", "reason": "stop"}
    return _stream


def _mk_chat(text: str):
    async def _chat(messages, tools=None, max_tokens=2048, temperature=0.3,
                    model="", base_url="", api_key=""):
        return {"role": "assistant", "content": text}
    return _chat


async def _run(first_pass: str, regen: str) -> tuple:
    """每次调用都装**全新**的桩(桩内部有调用计数,复用会让第 2 次跑拿到重生版作首版)。"""
    llm.chat_stream = _mk_stream(first_pass, then=regen)   # type: ignore[assignment]
    llm.chat = _mk_chat(regen)                             # type: ignore[assignment]
    events: list = []
    try:
        async for ev in agent.AgentService().chat_stream_for(1, "student", "student",
                                                          "研究生最长学习年限是几年？"):
            events.append(ev)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        events.append({"type": "error", "error": f"{type(e).__name__}: {e}"})
    return events


def _parts(events: list) -> tuple:
    kinds = [e.get("type") for e in events]
    deltas = [e.get("content") or "" for e in events if e.get("type") == "delta"]
    retry = next((e for e in events if e.get("type") == "grounding_retry"), None)
    done = next((e for e in events if e.get("type") == "done"), None)
    return kinds, deltas, retry, done


async def main() -> int:
    db.connect()  # 库副本上跑,生产 agent.db 零改动
    async def _fake_search(q, mr, scope=None):   # 必须是协程:agent 里是 await 调用
        return FAKE_SOURCES, {"top_score": 0.98, "n_above_threshold": 2,
                              "rerank_available": True}
    rag.search_with_quality = _fake_search       # type: ignore[assignment]
    user = db.verify_user("student", STUDENT_PW)
    print(f"[env] DATA_DIR={config.DATA_DIR}(库副本) user={user and user['username']}")

    # ---- U1~U4:空话首版 → 必然重生 ----
    config.GROUNDING_EARLY_WINDOW_CHARS = 80
    config.GROUNDING_GATE_ENABLED = True
    config.GROUNDING_STREAM_FORCE_UNGROUNDED = False
    kinds, deltas, retry, done = _parts(await _run(BAD_ANSWER, GOOD_ANSWER))
    ck(retry is not None, "U1 空话首版触发 grounding_retry",
       f"kinds={kinds[:8]}")
    ck(retry is not None and retry.get("released_chars") == 0,
       "U1b 首版不足 80 字 → 一个字都没下发就判废(released_chars=0)",
       f"released={retry and retry.get('released_chars')}")
    after = kinds[kinds.index("grounding_retry") + 1:] if retry else []
    ck(after.count("delta") > 1, "U2 重生结果**逐段**下发(delta>1)",
       f"retry 后 delta 数={after.count('delta')}")
    final = (done or {}).get("answer") or ""
    ck(GOOD_ANSWER in final and BAD_ANSWER not in final,
       "U3 done.answer == 重生后版本(不含被作废首版)", f"final={final[:40]!r}")
    gate = ((done or {}).get("context") or {}).get("grounding_gate") or {}
    ck(gate.get("hit") and gate.get("regenerated") and gate.get("ok_after_regen"),
       "U4 ctx_info.grounding_gate 三字段齐全", f"gate={gate}")
    conv = (done or {}).get("conversation_id")
    msgs = db.conversation_messages(conv, 50)[0] if conv else []
    asst = [m for m in msgs if m["role"] == "assistant"]
    ck(bool(asst) and asst[-1]["content"] == final,
       "U3b 落库答案 == done.answer(重生后版本)",
       f"len={len(asst[-1]['content']) if asst else 0} vs {len(final)}")

    # ---- U5:N=0 全缓冲 → 生成结束前一个 delta 都不发 ----
    config.GROUNDING_EARLY_WINDOW_CHARS = 0
    kinds0, deltas0, retry0, _ = _parts(await _run(BAD_ANSWER, GOOD_ANSWER))
    ck(retry0 is not None and retry0.get("released_chars") == 0,
       "U5 N=0 档:首版在重生判定前零下发(全缓冲语义)", f"released={retry0 and retry0.get('released_chars')}")
    config.GROUNDING_EARLY_WINDOW_CHARS = 80

    # ---- U6:首版有据 → 不重生 ----
    kinds1, deltas1, retry1, done1 = _parts(await _run(GOOD_ANSWER, GOOD_ANSWER))
    ck(retry1 is None, "U6 首版含 [1] → 不重生、无 grounding_retry", f"kinds={kinds1[:6]}")
    ck(len(deltas1) > 1, "U6b 有据首版也是逐段下发", f"deltas={len(deltas1)}")
    g1 = ((done1 or {}).get("context") or {}).get("grounding_gate")
    ck(g1 is None, "U6c 未命中闸门时不写 grounding_gate", f"gate={g1}")

    # ---- U7:闸门关闭档 ----
    config.GROUNDING_GATE_ENABLED = False
    kinds2, deltas2, retry2, done2 = _parts(await _run(BAD_ANSWER, GOOD_ANSWER))
    ck(retry2 is None and ((done2 or {}).get("context") or {}).get("grounding_gate") is None,
       "U7 GATE=0 档:无 retry、无 grounding_gate", f"kinds={kinds2[:6]}")
    ck("".join(deltas2) == BAD_ANSWER, "U7b GATE=0 档原样下发首版(闸门真的关了)",
       f"len={len(''.join(deltas2))}")
    config.GROUNDING_GATE_ENABLED = True

    shutil.rmtree(_TMP, ignore_errors=True)
    print(f"\n[unit] {'ALL PASS' if not FAILS else 'FAIL: ' + ', '.join(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
