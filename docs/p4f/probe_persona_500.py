#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断 pf-* 四条 HTTP 500 的真因：把 `llm.chat` 的 400 响应体打出来。

最小档集中验证里 `pf-01/02/03/pf-inject-01` 全报 HTTP 500，服务端 traceback 停在
`llm.py:50 raise_for_status()` → **上游 OpenRouter 返回 400**，但 httpx 的异常文本不带响应体，
光看日志判不了是「上下文超长」「参数不被接受」还是「persona 路径自己造出了畸形请求」。

做法：TestClient（不进 `with` → 不触发 lifespan，避开 weekly MCP 外部依赖）+ 把 `llm.chat`
包一层，捕获 HTTPStatusError 并**原样打印响应体**，然后按评测的调用形态发一次带 persona 的
`/api/chat`。零产品代码改动，只用测试态包装。

跑法：cd novaagent && set -a && . ./.env.test && set +a && \\
      PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe ../docs/p4f/probe_persona_500.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(r"E:/AILearn/NovaCampus")
sys.path.insert(0, str(ROOT / "novaagent"))

from novaagent import agent as AG, db, llm, main  # noqa: E402

OUT = ROOT / "docs" / "p4f" / "evidence" / "review" / "persona_500_probe.txt"
lines = []


def log(s):
    print(s)
    lines.append(str(s))


# ---------- 把 400 的响应体捞出来 ----------
_orig_chat = llm.chat
CAUGHT = []


async def chat_probe(messages, tools=None, **kw):
    import httpx
    try:
        return await _orig_chat(messages, tools=tools, **kw)
    except httpx.HTTPStatusError as e:
        body = e.response.text
        CAUGHT.append({"status": e.response.status_code, "n_msg": len(messages),
                       "prompt_chars": sum(len(m.get("content") or "") for m in messages),
                       "body": body[:1500]})
        log("[llm.chat] 上游 %s；消息 %d 条 / 总 %d 字" % (
            e.response.status_code, len(messages),
            sum(len(m.get("content") or "") for m in messages)))
        log("[llm.chat] 响应体 = %s" % body[:900])
        raise


llm.chat = chat_probe
AG.llm.chat = chat_probe


def main_():
    db.connect()          # TestClient 不走 lifespan，模块级单连接要自己拉起来
    spec = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
    case = next(c for c in spec["cases"] if c["id"] == "pf-01")
    from fastapi.testclient import TestClient
    client = TestClient(main.app)
    r = client.post("/api/login", json={"username": "counselor", "password": "counselor123"})
    tok = r.json()["token"]
    H = {"Authorization": "Bearer " + tok}

    spec_a = case["setup"]["personas"][0]
    rc = client.post("/api/personas", headers=H, json={
        "name": spec_a["name"], "college": spec_a.get("college") or "学工部",
        "style": spec_a.get("style") or "balanced",
        "persona_prompt": spec_a.get("persona_prompt") or "",
        "visibility": spec_a.get("visibility") or "private"})
    log("[probe] 建 persona → %s" % rc.status_code)
    pid = rc.json()["persona"]["id"]
    try:
        # ① 带 persona（评测失败的那条路径）
        rq = client.post("/api/chat", headers=H,
                         json={"question": case["question"], "persona_id": pid})
        log("[probe] 带 persona /api/chat → %s" % rq.status_code)
        # ② 同一问句不带 persona（对照：证明差异是否真来自 persona 段）
        rq2 = client.post("/api/chat", headers=H, json={"question": case["question"]})
        log("[probe] 无 persona /api/chat → %s" % rq2.status_code)
    finally:
        client.delete(f"/api/personas/{pid}", headers=H)   # 走公开 API 软删，不直写 DB

    # ③ 纯离线：把两种 system prompt 的规模与差异量化出来
    persona = {"name": spec_a["name"], "college": spec_a.get("college") or "",
               "style": spec_a.get("style"), "persona_prompt": spec_a["persona_prompt"],
               "bound_folder_ids": [], "bound_categories": []}
    ctx = "[1] 《示例制度》(student可读)\n" + ("休学须提交书面申请。" * 60)
    p_with = AG.build_system_prompt(persona, ctx)
    p_without = AG.build_system_prompt(None, ctx)
    log("[probe] system prompt 字数：带 persona=%d 无 persona=%d 差=%d"
        % (len(p_with), len(p_without), len(p_with) - len(p_without)))
    log("[probe] 捕获到的上游错误 %d 次" % len(CAUGHT))
    for i, c in enumerate(CAUGHT):
        log("  #%d status=%s n_msg=%d prompt_chars=%d" % (i + 1, c["status"], c["n_msg"], c["prompt_chars"]))
        log("      body=%s" % c["body"][:600].replace("\n", " "))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log("[probe] 落盘 %s" % OUT)


main_()
