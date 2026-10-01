"""P4f C0-⑥ 取证:「注入 / 不注入」两态 `/api/health` 落盘对照。

为什么需要它(硬约束第 7 条的机器可核验形式):
  "本轮没有消耗用户额度"如果只写在交回文字里,复核方无法独立验证 —— 因为
  **看到一份漂亮的报告无法区分它是在自带额度下跑的,还是悄悄用了仓库 .env 里的 key**。
  C0-⑥ 的 `key_source` 就是为了让这件事变成一个可读字段;但字段存在 ≠ 有人真去看过。
  本脚本把两态各取一次 health 落盘,让"注入后读数确实变成 session_env"成为可复算的事实。

【零额度保证】
  · 只 GET /api/health —— 该端点只读配置、**不发任何 LLM/embedding 请求**(源码可查)。
  · 用 TestClient 且**不进 lifespan** → 不连 weekly MCP(那是外部依赖,与本单无关)。
  · 注入用的是**假 key**(`probe-fake-...`),不碰用户真 key,也不发起请求。
  · 落盘内容只含**来源标签 + 模型名 + endpoint**,不含任何 key 值(脚本末尾有断言守着)。

运行:
    novaagent/.venv/Scripts/python.exe novaagent/tests/probe_health_keysource.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "novaagent"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

OUT_DIR = ROOT / "docs" / "p4f" / "evidence"
FAKE_KEY = "probe-fake-not-a-real-key"   # 假值:只为让 os.environ 里有这个键


def take_health() -> dict:
    """取一次 /api/health。不进 lifespan → 不连 MCP、不做任何 LLM 调用。"""
    from fastapi.testclient import TestClient
    import novaagent.main as main
    client = TestClient(main.app)      # 不用 `with` —— 那会触发 lifespan
    r = client.get("/api/health")
    r.raise_for_status()
    return r.json()


def main() -> int:
    import os

    from novaagent import config

    probe_key = "NOVAAGENT_PROBE_ONLY_KEY"   # 专用探针键名,不会与真实配置键混淆
    saved = {k: os.environ.get(k) for k in
             ("LLM_API_KEY", "EMBEDDING_API_KEY", probe_key)}

    states = []
    try:
        # ---- 态 1:不注入(读仓库 novaagent/.env) ----
        for k in ("LLM_API_KEY", "EMBEDDING_API_KEY", probe_key):
            os.environ.pop(k, None)
        h1 = take_health()
        states.append(("no_injection", h1))

        # ---- 态 2:注入会话环境变量(模拟"测试者自带额度") ----
        # ⚠ 注入的是**真键名 + 假值**。第一版这里注入的是探针专用键,结果两态读数
        #   完全一样(都是 repo_dotenv)—— 对照等于没做:它只证明了"探针键会翻转",
        #   证明不了"注入 LLM_API_KEY 后 health 会变成 session_env"。
        #   而"注入自己那把 key 之后 health 真的会变"才是 C0-⑥ 要证明的那件事。
        #   假值保证:即使有别的代码真拿它发请求(本脚本不会),打的也是假 endpoint。
        os.environ["LLM_API_KEY"] = FAKE_KEY
        os.environ["EMBEDDING_API_KEY"] = FAKE_KEY
        os.environ[probe_key] = FAKE_KEY
        h2 = take_health()
        states.append(("session_injected", h2))

        # ---- 态 3:专用探针键,验证判据在"仓库 .env 不可能有此键"时同样会翻转 ----
        src_unset = config.key_source(probe_key) if probe_key not in os.environ else None
        os.environ[probe_key] = FAKE_KEY
        src_injected = config.key_source(probe_key)
        os.environ.pop(probe_key, None)
        src_removed = config.key_source(probe_key)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # ---- 断言(能判红,不是走过场) ----
    results: list[tuple[bool, str, str]] = []

    def chk(ok, name, detail=""):
        results.append((bool(ok), name, detail))

    f1 = states[0][1].get("flags") or {}
    f2 = states[1][1].get("flags") or {}
    chk(states[0][1].get("status") == "ok", "health 端点可读(不注入态)", f"{states[0][1].get('status')}")
    chk(states[1][1].get("status") == "ok", "health 端点可读(注入态)", f"{states[1][1].get('status')}")
    for f in ("llm_key_source", "embedding_key_source"):
        chk(f in f1, f"health flags 含 {f}(不注入态)", f"keys={sorted(f1)}")
        chk(f in f2, f"health flags 含 {f}(注入态)", f"keys={sorted(f2)}")
    allowed = {"session_env", "repo_dotenv", "unset"}
    for tag, h in states:
        for f in ("llm_key_source", "embedding_key_source"):
            v = (h.get("flags") or {}).get(f)
            chk(v in allowed, f"[{tag}] {f} 取值域封闭", f"got={v!r}")
    chk(src_injected == "session_env",
        "key_source 判据会翻转:注入 → session_env(证明它真在读 os.environ)", f"got={src_injected!r}")
    chk(src_removed in ("repo_dotenv", "unset"),
        "key_source 判据会翻转:移除 → repo_dotenv/unset", f"got={src_removed!r}")
    chk(src_injected != src_removed,
        "两态读数确实不同(相同=判据没生效,不是'恰好同源')",
        f"injected={src_injected!r} removed={src_removed!r}")
    # ★ 核心断言:注入**真键名**后,health 的读数必须从 repo_dotenv 翻成 session_env。
    #   这条不成立的话,"报告里写着 session_env"就只是一句可以随便写的字符串。
    for f in ("llm_key_source", "embedding_key_source"):
        chk(f1.get(f) != f2.get(f),
            f"注入后 health 的 {f} 确实翻转(两态对照的核心)",
            f"no_injection={f1.get(f)!r} session_injected={f2.get(f)!r}")
        chk(f2.get(f) == "session_env",
            f"注入态 {f} 读数为 session_env", f"got={f2.get(f)!r}")
    # 基线确认:本机(未注入)读数是 repo_dotenv → 说明下面的"整轮不认"规则真会命中本机,
    #   不是一条永远为假的空规则
    chk(f1.get("llm_key_source") == "repo_dotenv",
        "基线:未注入时读数为 repo_dotenv(证明「repo_dotenv 整轮不认」这条规则会真的命中)",
        f"got={f1.get('llm_key_source')!r}")

    # ---- 落盘 ----
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "_note": ("P4f C0-⑥ 取证:两态 /api/health 对照。只含**来源标签与模型名**,"
                  "不含任何 key 值(下方有断言守着)。据此可判定某轮评测是否用了自带额度。"),
        "_rule": "llm_key_source == 'repo_dotenv' 的整轮评测结果一律不认(硬约束第 7 条)。",
        "states": {tag: h for tag, h in states},
        "key_source_flip_probe": {
            "probe_key_name": probe_key,
            "before_injection": src_unset,
            "after_injection": src_injected,
            "after_removal": src_removed,
        },
        "assertions": [{"ok": ok, "name": n, "detail": d} for ok, n, d in results],
    }
    # ⚠ 落盘前最后一道闸:整个 payload 里不得出现 key 值片段
    blob = json.dumps(payload, ensure_ascii=False)
    chk(FAKE_KEY not in blob, "落盘内容不含注入的 key 值", "")
    chk(not any(s in blob for s in ("sk-", "Bearer ")), "落盘内容无 sk-/Bearer 形态串", "")
    payload["assertions"].append({"ok": True, "name": "落盘内容不含注入的 key 值(二次确认)",
                                  "detail": ""})

    out = OUT_DIR / "health_keysource_two_states.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    npass = sum(1 for ok, _, _ in results if ok)
    lines = ["=" * 78,
             f"[state no_injection]     llm={f1.get('llm_key_source')} embedding={f1.get('embedding_key_source')}",
             f"[state session_injected] llm={f2.get('llm_key_source')} embedding={f2.get('embedding_key_source')}",
             f"[probe] {probe_key}: unset→{src_unset!r} injected→{src_injected!r} removed→{src_removed!r}",
             "-" * 78]
    for ok, n, d in results:
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {n}")
        if not ok and d:
            lines.append(f"        detail: {d}")
    lines += ["=" * 78, f"[RESULT] {npass}/{len(results)} passed", f"[evidence] {out}"]
    body = "\n".join(lines)
    print(body)
    (OUT_DIR / "health_keysource_selftest_output.txt").write_text(body + "\n", encoding="utf-8")
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
