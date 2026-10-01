#!/usr/bin/env python3
"""C0-⑤ 端口复查验证用的**零额度**探针(只打 /api/health)。

## 为什么需要它

`docs/p4d/run_with_server.sh` 改完后会打印 `[port-check] :<port> closed=True/False`。
要验证这一行,得真起一次服务 —— 但**不能**用 `run_evals.py` / `smoke_test.py` 验:
那两个都会发真实 LLM 请求,落在 `novaagent/.env` 的用户额度上(硬约束第 7 条)。

本探针只做一次 `GET /api/health`:
  · 不带任何 question → 不进 agent.chat_for / chat_stream_for → **不调 LLM、不调 embedding**;
  · 顺便把 C0-③/④/⑥ 的 flags 读数打出来,验证 health 真的带了这些字段。

## ⚠ 额度档位的极性(Qoder 第 1 回 Review 打回的第 1 条)

**第一版把极性写反了**:它在 `src == "session_env"` 时判失败,也就是
「注入了会话环境变量(自带额度,不碰用户 .env)」的**合规**跑法被判红,
而「直接读仓库 .env(用用户额度)」的违规跑法判绿 —— 与硬约束第 7 条正好相反。
Qoder 的实测:`evidence/review/run_c0_05_with_session_keys.txt` 注入会话 key 跑 :8947,
health 五项齐全、`closed=True`,却被这一行打成 `[RESULT] 4/5` + 退出码 1。

现在极性写在下面这张表 `QUOTA_JUDGE` 里 —— 它是**唯一的权威定义**,
`judge_payload()` 与 `--selftest` 的极性断言都从它派生。
要改极性只改这一处;改错会被自测当场抓住(见 `--selftest` 的 S6)。

## 为什么判据要抽成纯函数

`judge_payload(payload: dict) -> list[Check]` **只吃 dict 出结论**,不联网、不读文件。
这样复核方可以**离线重放**判据(喂构造出来的假 health 响应),既不必真起服务,
也不必烧任何额度 —— 而「判据能不能判红」这件事,恰恰是零额度自测唯一该证明的东西。

## 跑法

在线(由 run_with_server.sh 拉起,或手工):
    bash docs/p4d/run_with_server.sh 8941 tests/probe_port_check.py --base http://127.0.0.1:8941

离线(纯判据自测,零额度零依赖,不需要服务):
    novaagent/.venv/Scripts/python.exe novaagent/tests/probe_port_check.py --selftest

退出码:0 = 通过;1 = 有判据不成立;2 = 参数错误;3 = **漏了 --base**(坑 57:不留默认端口,
        否则会去审别人的进程 —— :8900 上就有别人的常驻实例)。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

REQUIRED_FLAGS = ("llm_key_source", "embedding_key_source",
                  "grounding_gate_scope_mode", "web_search_idle_timeout_s",
                  "web_search_total_timeout_s")

KEY_SOURCE_VALUES = ("session_env", "repo_dotenv", "unset")

# ★ 额度档位的**极性单一权威定义**(硬约束第 7 条)。
#   True  = 合规,这一轮的结果**可以**计入证据链
#   False = 该轮结果**不认**,证据链须重走
#   注意 `session_env` 在左边:注入会话环境变量 = 自带额度 = 不碰用户 .env = **合规**。
#   (第一版把它写成失败,是本单唯一一条「断言极性反了」的缺陷,已修。)
QUOTA_JUDGE: dict[str, tuple[bool, str]] = {
    "session_env": (True,
                    "调用方注入了会话环境变量(自带额度),全程不碰仓库 .env —— 合规,本轮结果可认"),
    "repo_dotenv": (False,
                    "读的是仓库 novaagent/.env = 用户的额度;按 C0-⑥ 该轮结果一律不认,证据链须重走"),
    "unset": (False,
              "既未注入也未配置,没有可用额度 —— 本轮无法在合规额度下取证"),
}

KEYLIKE_PATTERNS = ("sk-", "Bearer ", 'api_key":"')


@dataclass(frozen=True)
class Check:
    ok: bool
    name: str
    detail: str = ""


# ============================ 纯函数判据层 ============================
# 下面三个函数只吃 dict、不联网、不读文件 —— 复核方可离线重放。
def judge_flags(flags: dict,
                quota_table: dict[str, tuple[bool, str]] | None = None) -> list[Check]:
    """判据本体。`quota_table` 只为自测能注入一张「反表」来验证极性断言会红。"""
    qt = QUOTA_JUDGE if quota_table is None else quota_table
    out: list[Check] = []

    # J1 五项字段齐全
    missing = [k for k in REQUIRED_FLAGS if k not in flags]
    out.append(Check(not missing,
                     "/api/health 可读,且 flags 含 C0-③/④/⑥ 的全部字段",
                     f"缺字段: {missing}" if missing else f"keys={sorted(flags)}"))

    # J2 取值域封闭:不在域内的读数一律判红(防止将来加档位时静默漏判)
    for field_name in ("llm_key_source", "embedding_key_source"):
        v = flags.get(field_name)
        out.append(Check(v in KEY_SOURCE_VALUES,
                         f"{field_name} 取值域封闭({'/'.join(KEY_SOURCE_VALUES)})",
                         f"got={v!r}"))

    # J3 额度档位 —— 极性取自 QUOTA_JUDGE
    for field_name in ("llm_key_source", "embedding_key_source"):
        v = flags.get(field_name)
        if v not in qt:
            # 已在 J2 判红;这里补一条可读的,避免"因为什么红"要回上一条找
            out.append(Check(False, f"{field_name} 额度档位无法判定", f"got={v!r}"))
            continue
        ok, why = qt[v]
        out.append(Check(ok, f"{field_name} 额度档位[{v}] → {'合规' if ok else '该轮不认'}",
                         why))

    # J4 两项必须同档:配一半是最容易漏的坑(embedding 悄悄用了用户额度)
    a, b = flags.get("llm_key_source"), flags.get("embedding_key_source")
    out.append(Check(a == b, "两项额度档位同档(llm 与 embedding 不能配一半)",
                     f"llm={a!r} embedding={b!r}"))

    return out


def judge_key_leak(payload: dict) -> Check:
    """J5:health 响应不得含任何 key 形态串 —— 只允许来源标签与模型名。"""
    blob = json.dumps(payload, ensure_ascii=False)
    hits = [p for p in KEYLIKE_PATTERNS if p in blob]
    return Check(not hits, "health 响应不含疑似 key 形态串",
                 f"命中: {hits}" if hits else f"已查 {len(KEYLIKE_PATTERNS)} 种形态")


def judge_payload(payload: dict,
                  quota_table: dict[str, tuple[bool, str]] | None = None) -> list[Check]:
    """把 /api/health 的整个响应 dict 判一遍。纯函数,离线可重放。"""
    flags = payload.get("flags") or {}
    return judge_flags(flags, quota_table) + [judge_key_leak(payload)]


# ============================ 离线判据自测 ============================
def _fake_payload(llm: str | None = "repo_dotenv",
                  embedding: str | None = "repo_dotenv",
                  *, drop: tuple[str, ...] = (),
                  inject_keylike: str | None = None) -> dict:
    """构造一份假的 /api/health 响应。自测**不联网**,这些 dict 就是全部输入。"""
    flags = {
        "llm_key_source": llm,
        "embedding_key_source": embedding,
        "grounding_gate_scope_mode": "factual_turns",
        "web_search_idle_timeout_s": 20.0,
        "web_search_total_timeout_s": 45.0,
    }
    for k in drop:
        flags.pop(k, None)
    payload = {"status": "ok", "weekly_mcp": True, "flags": flags}
    if inject_keylike:
        payload["_leak"] = inject_keylike
    return payload


def _failed(checks: list[Check]) -> list[Check]:
    return [c for c in checks if not c.ok]


def _named(checks: list[Check], needle: str) -> list[Check]:
    return [c for c in checks if needle in c.name]


def selftest() -> tuple[list[Check], str]:
    """判据的能判红/能判绿自测。零额度、零依赖、可离线复算。

    S6 是这一节存在的理由:它把 QUOTA_JUDGE 的极性**故意反过来**再跑一遍,
    断言自测确实会红 —— 否则「全绿」可能只是因为断言写得太宽松。
    """
    out: list[Check] = []

    def chk(ok, name, detail=""):
        out.append(Check(bool(ok), name, detail))

    base = _fake_payload()

    # S0 基线:构造出来的合规态本身判绿(否则下面所有"判红"都没有对照)
    c0 = judge_payload(_fake_payload(llm="session_env", embedding="session_env"))
    chk(not _failed(c0), "S0 合规态(session_env)整体判绿", f"红项={[c.name for c in _failed(c0)]}")

    # S1 ★ 反向:repo_dotenv(用用户额度)必须被判红,且红在「该轮不认」上
    c1 = judge_payload(base)
    f1 = _failed(c1)
    chk(bool(f1), "S1 repo_dotenv 判红(该轮不认)",
        f"意外全绿: {[c.name for c in c1]}")
    quota_red = _named(f1, "该轮不认")
    chk(bool(quota_red), "S1 红项确实是额度档位那条(不是别的判据误报)",
        f"红项={[c.name for c in f1]}")
    chk("该轮结果一律不认" in (quota_red[0].detail if quota_red else ""),
        "S1 红项的理由写明「该轮结果一律不认」",
        f"detail={quota_red[0].detail if quota_red else ''}")

    # S2 ★ session_env(合规跑法)必须**不**判红 —— 这条正是第一版写反的地方
    c2 = judge_payload(_fake_payload(llm="session_env", embedding="session_env"))
    chk(not _named(_failed(c2), "额度档位"),
        "S2 session_env 不因额度档位判红(合规跑法被当红=极性反了)",
        f"红项={[c.name for c in _failed(c2)]}")
    chk(bool(_named(c2, "额度档位") ) and all(c.ok for c in _named(c2, "额度档位")),
        "S2 session_env 的额度判据明确判绿",
        f"{[(c.name, c.ok) for c in _named(c2, '额度档位')]}")

    # S3 unset:没额度也要判红(否则"没 key"会被当成"没问题"放过)
    c3 = judge_payload(_fake_payload(llm="unset", embedding="unset"))
    chk(bool(_named(_failed(c3), "该轮不认")),
        "S3 unset 判红(没有可用额度不是'没问题')",
        f"红项={[c.name for c in _failed(c3)]}")

    # S4 两项配一半 → 判红(最容易漏的坑:embedding 悄悄用了用户额度)
    c4 = judge_payload(_fake_payload(llm="session_env", embedding="repo_dotenv"))
    chk(any("同档" in c.name for c in _failed(c4)),
        "S4 llm/embedding 配一半判红", f"红项={[c.name for c in _failed(c4)]}")

    # S5 缺字段 / key 形态串 → 判红
    c5 = judge_payload(_fake_payload(drop=("web_search_total_timeout_s",)))
    j1 = [c for c in c5 if "全部字段" in c.name]
    chk(bool(j1) and not j1[0].ok,
        "S5 缺 flags 字段判红", f"{[(c.name, c.ok) for c in j1]}")
    chk(bool(j1) and "web_search_total_timeout_s" in j1[0].detail,
        "S5 红项点名缺了哪个字段(不能只说'缺字段')",
        f"detail={j1[0].detail if j1 else ''}")
    c6 = judge_payload(_fake_payload(inject_keylike="sk-should-never-appear"))
    chk(bool(_named(_failed(c6), "key 形态串")),
        "S5 响应含 key 形态串判红", f"红项={[c.name for c in _failed(c6)]}")

    # S6 ★★ 极性自检:把 QUOTA_JUDGE 反过来,断言自测会红。
    #    没有这一条,S1/S2 全绿也可能只是因为断言写得宽松(坑 52)。
    inverted = {"session_env": (False, "反表:故意判红"),
                "repo_dotenv": (True, "反表:故意判绿"),
                "unset": (False, "反表:故意判红")}
    ci = judge_payload(base, quota_table=inverted)
    chk(not _named(_failed(ci), "该轮不认"),
        "S6 极性写反时 repo_dotenv 不再判红 → 证明 S1 真的在守极性",
        f"红项={[c.name for c in _failed(ci)]}")
    ci2 = judge_payload(_fake_payload(llm="session_env", embedding="session_env"),
                        quota_table=inverted)
    chk(bool(_named(_failed(ci2), "该轮不认")),
        "S6 极性写反时 session_env 改判红 → 证明 S2 真的在守极性",
        f"红项={[c.name for c in _failed(ci2)]}")

    # S7 判据是纯函数:同一输入两次结果一致,且离线可算(此处没碰过网络/文件)
    chk(judge_payload(base) == c1, "S7 判据是纯函数(同输入两次同结论,可离线重放)")

    return out


# ============================ 在线探针 ============================
def run_online(base: str) -> list[Check]:
    import httpx  # 只在在线模式导入:离线自测连 httpx 都不需要

    try:
        with httpx.Client(timeout=15) as c:
            r = c.get(f"{base}/api/health")
    except Exception as e:  # noqa: BLE001
        return [Check(False, "GET /api/health 连不上", f"{type(e).__name__}: {e}")]

    print(f"[probe] base={base}")
    if r.status_code != 200:
        return [Check(False, f"GET /api/health → {r.status_code}", r.text[:200])]

    payload = r.json() or {}
    flags = payload.get("flags") or {}
    print(f"[probe] status={payload.get('status')} weekly_mcp={payload.get('weekly_mcp')}")

    checks = judge_payload(payload)
    for k in REQUIRED_FLAGS:
        print(f"[probe]   {k} = {flags.get(k)!r}")
    return checks


def render(checks: list[Check]) -> str:
    lines = ["=" * 78]
    for c in checks:
        lines.append(f"[{'PASS' if c.ok else 'FAIL'}] {c.name}")
        if not c.ok and c.detail:
            lines.append(f"        detail: {c.detail}")
    npass = sum(1 for c in checks if c.ok)
    lines.append("=" * 78)
    lines.append(f"[RESULT] {npass}/{len(checks)} passed")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="C0-⑤ 端口复查零额度探针")
    ap.add_argument("--base", help="被审服务的 base URL,如 http://127.0.0.1:8941(必填)")
    ap.add_argument("--selftest", action="store_true",
                    help="只跑判据的离线自测:不起服务、不联网、零额度")
    args = ap.parse_args()

    if args.selftest:
        checks = selftest()
        body = ("[selftest] 判据离线自测(纯函数,不联网、不起服务)\n"
                + render(checks))
        print(body)
        out_dir = ROOT / "docs" / "p4f" / "evidence"
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "port_probe_selftest_output.txt"
        p.write_text(body + "\n", encoding="utf-8")
        print(f"[evidence] {p}")
        return 0 if all(c.ok for c in checks) else 1

    # 坑 57:不留默认端口。不传 --base 就去审别人的进程 —— :8900 上就有常驻实例。
    if not args.base:
        print("[FATAL] 必须显式 --base http://127.0.0.1:<port>。", file=sys.stderr)
        print("        不留默认端口是为了不去审别人的进程(坑 57):", file=sys.stderr)
        print("        正确用法: bash docs/p4d/run_with_server.sh <port> "
              "tests/probe_port_check.py --base http://127.0.0.1:<port>", file=sys.stderr)
        return 3

    checks = run_online(args.base.rstrip("/"))
    print(render(checks))
    return 0 if all(c.ok for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())