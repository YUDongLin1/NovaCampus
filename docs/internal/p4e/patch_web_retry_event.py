#!/usr/bin/env python3
"""P4e S1-①:前端消费 `grounding_retry` 事件——已下发的文字**不撤回、不假装没发生**。

规格要求(TASKS P4e S1-①):「已下发给前端的文字不得被撤回后当作已展示内容重复;
若必须重生,走一条显式 SSE 事件通知前端『重新组织答案』,前端把它渲染成状态
而不是假装没发生过」。

实现:把已下发的初稿原样折进 `.gate-draft` 块(可见、弱化),插入一行状态说明,
重生结果另起一段继续流式。**不删除**初稿、**不把重生结果伪装成唯一版本**。

用法: novaagent/.venv/Scripts/python.exe docs/p4e/patch_web_retry_event.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHAT = ROOT / "novaagent" / "web" / "js" / "chat.js"
CSS = ROOT / "novaagent" / "web" / "css" / "theme.css"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

P1_OLD = "  let got = false, srcs = null, trace = null;\n"
P1_NEW = "  let got = false, srcs = null, trace = null, target = bot;\n"

P2_OLD = """        if (ev.type === 'delta') {
          if (!got) { bot.textContent = ''; got = true; }
          bot.textContent += ev.content;
          $('messages').scrollTop = $('messages').scrollHeight;
        } else if (ev.type === 'sources') {
"""
P2_NEW = """        if (ev.type === 'delta') {
          if (!got) { target.textContent = ''; got = true; }
          target.textContent += ev.content;
          $('messages').scrollTop = $('messages').scrollHeight;
        } else if (ev.type === 'grounding_retry') {
          /* P4e S1-①:初稿被判定「未给出可核查依据」(有来源却零引用零数字)。
             已下发的文字**不撤回、不假装没发生**:原样折进「初稿」块并显式标注,
             重生结果另起一段继续流式。 */
          const draft = document.createElement('div');
          draft.className = 'gate-draft';
          draft.textContent = target.textContent;
          const st = document.createElement('div');
          st.className = 'gate-status';
          st.textContent = '（初稿未给出可核查依据，已重新组织答案如下）';
          target.textContent = '';
          bot.appendChild(draft);
          bot.appendChild(st);
          const fresh = document.createElement('div');
          bot.appendChild(fresh);
          target = fresh; got = false;
          $('messages').scrollTop = $('messages').scrollHeight;
        } else if (ev.type === 'sources') {
"""

P3_OLD = "          if (ev.answer && !got) { bot.textContent = ev.answer; got = true; }\n"
P3_NEW = "          if (ev.answer && !got) { target.textContent = ev.answer; got = true; }\n"

CSS_NEW = """
/* P4e S1-①:grounding 闸门重生的「初稿」块与状态行——初稿保留可见,不假装没发生 */
.gate-draft { opacity: .55; border-left: 3px solid var(--ink-light, #c9c4bb);
  padding-left: 8px; margin: 4px 0; white-space: pre-wrap; font-size: .95em; }
.gate-status { color: #9a6a3a; font-size: .88em; margin: 4px 0 2px; }
"""


def main() -> int:
    s = CHAT.read_text(encoding="utf-8")
    for name, old, new in (("P1", P1_OLD, P1_NEW), ("P2", P2_OLD, P2_NEW), ("P3", P3_OLD, P3_NEW)):
        n = s.count(old)
        if n != 1:
            print(f"[FAIL] chat.js {name} 锚点命中 {n} 次")
            return 1
        s = s.replace(old, new, 1)
    CHAT.write_text(s, encoding="utf-8")
    print("[OK] chat.js 已消费 grounding_retry")

    c = CSS.read_text(encoding="utf-8")
    if ".gate-draft" not in c:
        CSS.write_text(c.rstrip("\n") + "\n" + CSS_NEW, encoding="utf-8")
        print("[OK] theme.css 已追加 .gate-draft / .gate-status")
    else:
        print("[skip] theme.css 已含 .gate-draft")
    return 0


if __name__ == "__main__":
    sys.exit(main())
