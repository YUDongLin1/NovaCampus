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

现在极性写在下面两张表 `LLM_QUOTA_JUDGE` / `EMBEDDING_QUOTA_JUDGE` 里 —— 它们是
**唯一的权威定义**,`judge_flags()` / `judge_payload()` 与 `--selftest` 的极性断言
都从它们派生。要改极性只改这一处;改错会被自测当场抓住(见 `--selftest` 的 S6)。

## ⚠ LLM 与 embedding 分表(负责人2026-10-01 裁决)

OpenRouter **不提供 embedding**,所以只要用专用测试 key,就必然是
`llm=session_env + embedding=repo_dotenv` 的混合档。第一版的 J4「两项必须同档」
会把这种跑法判成「该轮不认」—— 而它是当前**唯一**可用的跑法,等于把事实堵死。
修正后:
  · **llm 不放宽**:`repo_dotenv` 照旧判红(硬约束第 7 条的本体);
  · **embedding 允许走仓库 .env,但强制披露**:判据层出`ok=None` 的披露项,
    输出层由 `render()` 强制打印(`ok=True` 的项也会带detail),`collect_disclosure()`
    再抽成机读 dict 供评测报告落盘;
  · **embedding=unset 仍判红** —— 没额度不是没问题;
  · 调用次数拿不到就写 `unknown`,**不许写 0**。

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
import re
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

KEYLIKE_PATTERNS = ("sk-", "Bearer ", 'api_key":"')

# ★ 额度档位的**极性单一权威定义**(硬约束第 7 条),**LLM 与 embedding 分表**。
#
# 【为什么分表 —— 负责人2026-10-01 裁决】
#   OpenRouter **不提供 embedding**。所以只要用专用测试 key,就必然是
#   `llm=session_env + embedding=repo_dotenv` 的**混合档**。第一版的 J4
#   「两项必须同档」会把这种跑法判成「该轮不认」—— 而它恰恰是当前**唯一**可用的跑法,
#   等于把事实堵死。修正:llm **不放宽**(硬约束第 7 条的本体),embedding 允许走
#   仓库 .env,但**必须强制披露**(见 EMBEDDING_DISCLOSURE)。
LLM_QUOTA_JUDGE: dict[str, tuple[bool, str]] = {
    "session_env": (True,
                    "调用方注入了会话环境变量(自带额度),全程不碰仓库 .env —— 合规,本轮结果可认"),
    "repo_dotenv": (False,
                    "读的是仓库 novaagent/.env = 用户的额度;按 C0-⑥ 该轮结果一律不认,证据链须重走"),
    "unset": (False,
              "既未注入也未配置,没有可用额度 —— 本轮无法在合规额度下取证"),
}

# embedding 侧:repo_dotenv **不再判红**,改判「披露」。unset 仍判红 ——
#   「没额度」不等于「没问题」(坑 45 同形:空值不得当成通过)。
EMBEDDING_QUOTA_JUDGE: dict[str, tuple[bool | None, str]] = {
    "session_env": (True, "embedding 亦为自带额度,全程零消耗"),
    "repo_dotenv": (None,
                    "embedding 走的是仓库 .env 的额度(OpenRouter 不提供 embedding,无法自带);"
                    "消耗次数见下方【披露】条,须在报告中披露"),
    "unset": (False, "embedding 无任何额度 —— 既不自带也未配置,检索无法进行"),
}

# 判红时的口径来源说明(供披露行与报告引用)
DISCLOSURE_SOURCE = "novaagent/.env的 EMBEDDING_API_KEY(用户额度)"

# J4 披露条的名字前缀。用它做**精确选择器**,不用「披露」子串 ——
#   J3b 的档位说明里也带「披露」二字,用子串会同时抓到两条,自测就会验错对象
#   (第一版就栽在这儿:S4 抓到的是 J3b,于是 6 条断言全红)。
DISCLOSURE_TAG = "【披露】"


@dataclass(frozen=True)
class Check:
    ok: bool
    name: str
    detail: str = ""


# ============================ 纯函数判据层 ============================
# 下面三个函数只吃 dict、不联网、不读文件 —— 复核方可离线重放。
def judge_flags(flags: dict,
                llm_table: dict[str, tuple[bool, str]] | None = None,
                emb_table: dict[str, tuple[bool | None, str]] | None = None,
                embedding_calls: int | None = None) -> list[Check]:
    """判据本体。两个 `*_table` 参数只为自测能注入「反表」验证极性断言会红。

    `embedding_calls` = 本轮 embedding 调用次数(由调用方/日志提供)。
    **拿不到就传 None,输出 `unknown`,不许假装是 0**(坑 45:空值不得当成通过)。
    """
    lt = LLM_QUOTA_JUDGE if llm_table is None else llm_table
    et = EMBEDDING_QUOTA_JUDGE if emb_table is None else emb_table
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

    # J3a LLM 档位 —— **不放宽**,极性取自 LLM_QUOTA_JUDGE(硬约束第 7 条的本体)
    lv = flags.get("llm_key_source")
    if lv not in lt:
        out.append(Check(False, "llm_key_source 额度档位无法判定", f"got={lv!r}"))
    else:
        ok, why = lt[lv]
        out.append(Check(ok, f"llm_key_source 额度档位[{lv}] → {'合规' if ok else '该轮不认'}",
                         why))

    # J3b embedding 档位 —— repo_dotenv 判**披露**(ok=None),unset 仍判红
    ev = flags.get("embedding_key_source")
    if ev not in et:
        out.append(Check(False, "embedding_key_source 额度档位无法判定", f"got={ev!r}"))
    else:
        ok, why = et[ev]
        if ok is None:
            out.append(Check(True, f"embedding_key_source 额度档位[{ev}] → 披露(不判红)",
                             why))
        else:
            out.append(Check(ok, f"embedding_key_source 额度档位[{ev}] → "
                                 f"{'合规' if ok else '该轮不认'}", why))

    # J4 ★ 披露(负责人裁决:OpenRouter 不提供 embedding,混合档是唯一可用跑法)
    #   **不是**「同档才算过」,而是「用了用户额度就必须显式说出来」。
    #   这一条永远存在(即使档位合规也打印「无需披露」),这样报告里总有一行,
    #   后人不用去猜「这轮到底有没有碰用户额度」。
    if ev == "repo_dotenv":
        n = "unknown" if embedding_calls is None else str(embedding_calls)
        out.append(Check(
            True, f"{DISCLOSURE_TAG}embedding 走仓库 .env 额度,须计入报告",
            f"embedding_key_source=repo_dotenv({DISCLOSURE_SOURCE});"
            f"本轮 embedding 调用次数={n}"
            + ("← 拿不到次数,如实记 unknown,**不写 0**" if embedding_calls is None else "")))
    else:
        out.append(Check(True, f"{DISCLOSURE_TAG}embedding 无需披露(非 repo_dotenv)",
                         f"embedding_key_source={ev!r}"))

    return out


def _disclosure(checks: list[Check]) -> list[Check]:
    """精确取出 J4 的披露条(用 DISCLOSURE_TAG 前缀,不用「披露」子串)。

    子串会同时命中 J3b 的档位说明 —— 第一版自测就因此抓到错对象、
    6 条断言全红。这里做成**单一权威选择器**,自测、render、collect_disclosure
    三处都用它,免得再各写一份字符串匹配又漂移(坑 45:同一件事只应有一份实现)。
    """
    return [c for c in checks if c.name.startswith(DISCLOSURE_TAG)]


def judge_key_leak(payload: dict) -> Check:
    """J5:health 响应不得含任何 key 形态串 —— 只允许来源标签与模型名。"""
    blob = json.dumps(payload, ensure_ascii=False)
    hits = [p for p in KEYLIKE_PATTERNS if p in blob]
    return Check(not hits, "health 响应不含疑似 key 形态串",
                 f"命中: {hits}" if hits else f"已查 {len(KEYLIKE_PATTERNS)} 种形态")


def judge_payload(payload: dict,
                  llm_table: dict[str, tuple[bool, str]] | None = None,
                  emb_table: dict[str, tuple[bool | None, str]] | None = None,
                  embedding_calls: int | None = None) -> list[Check]:
    """把 /api/health 的整个响应 dict 判一遍。纯函数,离线可重放。"""
    flags = payload.get("flags") or {}
    return judge_flags(flags, llm_table, emb_table, embedding_calls) + [judge_key_leak(payload)]


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

    # ---- S4 组:负责人2026-10-01 裁决后的新口径 --------------------------------
    # 背景:OpenRouter 不提供 embedding → 混合档(session_env + repo_dotenv)
    #   是当前**唯一**可用跑法,判红它等于把事实堵死。所以 S4 从
    #   「配一半判红」改成「配一半 → **额度判绿 + 披露项出现**」。
    c4 = judge_payload(_fake_payload(llm="session_env", embedding="repo_dotenv"))
    chk(not _failed(c4),
        "S4 混合档(session_env+repo_dotenv)额度判绿 —— 唯一可用跑法不再被堵死",
        f"红项={[c.name for c in _failed(c4)]}")
    d4 = _disclosure(c4)
    chk(len(d4) == 1 and d4[0].ok,
        "S4 混合档必须出现且仅出现一条披露项(不能靠红项暗示)",
        f"披露项={[(c.name, c.ok) for c in _disclosure(c4)]}")
    chk(bool(d4) and "须计入报告" in d4[0].name,
        "S4 披露项的名字就写明「须计入报告」,不能只藏在 detail 里",
        f"name={d4[0].name if d4 else ''}")
    chk(bool(d4) and DISCLOSURE_SOURCE in d4[0].detail,
        "S4 披露项点明消耗的是哪一份额度(EMBEDDING_API_KEY)",
        f"detail={d4[0].detail if d4 else ''}")

    # S4b ★ 反向:放宽 embedding 之后,**llm 侧不许被一起放水**
    c4b = judge_payload(_fake_payload(llm="repo_dotenv", embedding="repo_dotenv"))
    f4b = _failed(c4b)
    chk(any("llm_key_source" in c.name for c in f4b),
        "S4b llm=repo_dotenv 仍判红(放宽 embedding 不能把 llm 一起放过)",
        f"红项={[c.name for c in f4b]}")
    chk(any("该轮不认" in c.name for c in f4b),
        "S4b 红项落在「该轮不认」上 —— 证据链仍须重走",
        f"红项={[c.name for c in f4b]}")

    # S4c ★ 反向:embedding=unset 仍判红(没额度不等于没问题,坑 45 同形)
    c4c = judge_payload(_fake_payload(llm="session_env", embedding="unset"))
    chk(any("embedding_key_source" in c.name and not c.ok for c in c4c),
        "S4c embedding=unset 仍判红(披露放宽只对 repo_dotenv 生效,不含 unset)",
        f"红项={[c.name for c in _failed(c4c)]}")

    # S4d 披露次数:拿得到就写数,拿不到如实写 unknown,**不许写 0**
    d4n = _disclosure(judge_payload(_fake_payload(llm="session_env", embedding="repo_dotenv"),
                                embedding_calls=None))
    d4v = _disclosure(judge_payload(_fake_payload(llm="session_env", embedding="repo_dotenv"),
                                embedding_calls=137))
    chk(bool(d4n) and "unknown" in d4n[0].detail,
        "S4d 拿不到调用次数时披露写 unknown",
        f"detail={d4n[0].detail if d4n else ''}")
    chk(bool(d4n) and "=0" not in d4n[0].detail,
        "S4d 拿不到次数**不许写 0**(0 会被读成「一次都没调」)",
        f"detail={d4n[0].detail if d4n else ''}")
    chk(bool(d4v) and "137" in d4v[0].detail,
        "S4d 调用方给了次数就如实写进去",
        f"detail={d4v[0].detail if d4v else ''}")

    # S4e ★ 披露必须**看得见**:render 对 ok=True 的披露行也要打 detail,
    #    否则「显式打印一行」只是判据层存在、输出层看不见(坑 71 同形:
    #    「恰好没走到」≠ 有拦截力,反过来「恰好没显示」≠ 已披露)。
    d4only = _disclosure(c4)
    line = "\n".join(render(d4only).splitlines())
    chk(bool(d4only) and "embedding 调用次数" in line and "PASS" in line,
        "S4e 披露行在渲染输出里可见(不只是判据层存在)",
        f"rendered={line!r}")
    # 反向:普通绿项的 detail 仍**不该**被刷出来,否则输出会被 detail 淹没
    plain_ok = Check(True, "普通绿项(无披露标记)", "不该被打印的 detail")
    chk("不该被打印的 detail" not in render([plain_ok]),
        "S4e 反向:非披露的绿项不打印 detail(披露可见 ≠ 全部都打印)",
        f"rendered={render([plain_ok])!r}")

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

    # S6 ★★ 极性自检:把两张极性表各自反过来,断言自测会红。
    #    没有这一条,S1/S2 全绿也可能只是因为断言写得宽松(坑 52)。
    inv_llm = {"session_env": (False, "反表:故意判红"),
               "repo_dotenv": (True, "反表:故意判绿"),
               "unset": (False, "反表:故意判红")}
    inv_emb = {"session_env": (False, "反表:故意判红"),
               "repo_dotenv": (False, "反表:把披露也判红(错:披露项不是红项)"),
               "unset": (True, "反表:故意判绿")}
    # 6a llm 极性写反:repo_dotenv 不再判红
    ci = judge_payload(base, llm_table=inv_llm)
    chk(not _named(_failed(ci), "llm_key_source"),
        "S6a llm 极性写反时 repo_dotenv 不再判红 → 证明 S1/S4b 真的在守极性",
        f"红项={[c.name for c in _failed(ci)]}")
    # 6b llm 极性写反:session_env 改判红
    ci2 = judge_payload(_fake_payload(llm="session_env", embedding="session_env"),
                        llm_table=inv_llm)
    chk(bool(_named(_failed(ci2), "llm_key_source")),
        "S6b llm 极性写反时 session_env 改判红 → 证明 S2 真的在守极性",
        f"红项={[c.name for c in _failed(ci2)]}")
    # 6c ★ embedding 极性写反:把「披露」误升成红项 → 混合档又被打死,
    #    S4 的判绿必须当场翻脸,否则「放宽」可能悄悄变成「另一种堵死」。
    ci3 = judge_payload(_fake_payload(llm="session_env", embedding="repo_dotenv"),
                        emb_table=inv_emb)
    chk(any("embedding_key_source" in c.name for c in _failed(ci3)),
        "S6c embedding 极性写反时混合档被判红 → 证明 S4 的判绿依赖极性本身",
        f"红项={[c.name for c in _failed(ci3)]}")
    # 6d embedding 极性写反:unset 被判绿 → 红项必须**消失**。
    #    这一条断言的是「反表下不再红」,与 6c 的断言方向相反 ——
    #    两边合起来才证明 embedding 极性表的两个端点各自被守着。
    ci4 = judge_payload(_fake_payload(llm="session_env", embedding="unset"),
                        emb_table=inv_emb)
    chk(not _named(_failed(ci4), "embedding_key_source"),
        "S6d embedding 极性写反时 unset 不再判红 → 证明 S4c 真的在守极性",
        f"红项={[c.name for c in _failed(ci4)]}")
    # 6e ★ 反向:反表把 unset 判绿时,S4c 用的那条判据必须真的翻脸
    #    (直接验「同一输入换表后红项有差异」,避免断言只靠名字匹配蒙对)
    f_real = _named(_failed(judge_payload(
        _fake_payload(llm="session_env", embedding="unset"))), "embedding_key_source")
    f_inv = _named(_failed(ci4), "embedding_key_source")
    chk(bool(f_real) and not f_inv,
        "S6e 同一输入(embedding=unset)在正表判红、反表判绿 → 极性被真实读取",
        f"正表红项={[c.name for c in f_real]} 反表红项={[c.name for c in f_inv]}")

    # S7 判据是纯函数:同一输入两次结果一致,且离线可算(此处没碰过网络/文件)
    chk(judge_payload(base) == c1, "S7 判据是纯函数(同输入两次同结论,可离线重放)")

    # S8 collect_disclosure —— 披露进评测报告的**唯一出口**,必须自己验一遍。
    #    判据绿了但这里抽不出数字,报告里就还是空的(订单第1 条第 2 点)。
    mix_v = judge_payload(_fake_payload(llm="session_env", embedding="repo_dotenv"),
                          embedding_calls=42)
    dv = collect_disclosure(mix_v)
    chk(isinstance(dv, dict) and dv.get("embedding_calls") == 42,
        "S8 collect_disclosure 抽出调用次数(42)", f"got={dv}")
    chk(isinstance(dv, dict) and dv.get("embedding_key_source") == "repo_dotenv"
        and dv.get("quota_source") == DISCLOSURE_SOURCE,
        "S8 披露 dict 点明档位与额度来源(报告要靠这两个字段归因)",
        f"got={dv}")
    du = collect_disclosure(judge_payload(
        _fake_payload(llm="session_env", embedding="repo_dotenv"), embedding_calls=None))
    chk(isinstance(du, dict) and du.get("embedding_calls") is None
        and du.get("embedding_calls_raw") == "unknown",
        "S8 拿不到次数时 dict 里是 None/unknown,**不是 0**", f"got={du}")
    dc = collect_disclosure(judge_payload(
        _fake_payload(llm="session_env", embedding="session_env")))
    chk(dc is None, "S8 embedding 也在自带额度时返回 None(无需披露)", f"got={dc}")
    # 反向:llm 侧违规时**不能**因为 embedding 披露而把违规吞掉
    dl = collect_disclosure(judge_payload(
        _fake_payload(llm="repo_dotenv", embedding="repo_dotenv"), embedding_calls=7))
    chk(isinstance(dl, dict) and dl.get("embedding_calls") == 7
        and bool(_named(_failed(judge_payload(
            _fake_payload(llm="repo_dotenv", embedding="repo_dotenv"),
            embedding_calls=7)), "该轮不认")),
        "S8 反向:llm=repo_dotenv 仍判红,披露不吞掉违规",
        f"disclosure={dl}红项={[c.name for c in _failed(judge_payload(_fake_payload(llm='repo_dotenv', embedding='repo_dotenv'), embedding_calls=7))]}")

    return out


# ============================ 在线探针 ============================
def collect_disclosure(checks: list[Check]) -> dict | None:
    """从判据结果里抽出**唯一的**披露记录,供调用方落进评测报告。

    订单第1 条要求「披露要能进评测报告,不能只在探针 stdout 一闪而过」。
    这就是那个出口:调用方拿本函数的返回值直接写进报告的 `env_flags.quota_disclosure`。
    返回 None = 本轮无需披露(embedding 也在自带额度上)。
    """
    for c in checks:
        if not c.name.startswith(DISCLOSURE_TAG):
            continue
        if "无需披露" in c.name:
            return None
        m = re.search(r"本轮 embedding 调用次数=(\d+|unknown)", c.detail)
        raw = m.group(1) if m else "unknown"
        return {
            "embedding_key_source": "repo_dotenv",
            "quota_source": DISCLOSURE_SOURCE,
            "embedding_calls": None if raw == "unknown" else int(raw),
            "embedding_calls_raw": raw,
            "note": "embedding 消耗了仓库 .env 的用户额度;llm 侧仍为自带额度",
        }
    return None


def run_online(base: str, embedding_calls: int | None = None) -> list[Check]:
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

    checks = judge_payload(payload, embedding_calls=embedding_calls)
    for k in REQUIRED_FLAGS:
        print(f"[probe]   {k} = {flags.get(k)!r}")
    disc = collect_disclosure(checks)
    if disc is not None:
        # 单独打一行机读摘要:即便 stdout 被刷走,这行也能被 grep 出来转进报告
        print(f"[DISCLOSURE] {json.dumps(disc, ensure_ascii=False)}")
    return checks


def render(checks: list[Check]) -> str:
    """渲染判据结果。

    ⚠ 披露项(`ok=True` 且名字带「披露」)的 detail **必须打出来**:
    披露的全部价值就是被人看见,只在判据层存在、输出层看不到等于没披露
    (坑71 同形:「恰好没走到」≠ 有拦截力,这里反过来:「恰好没显示」≠ 已披露)。
    """
    lines = ["=" * 78]
    for c in checks:
        lines.append(f"[{'PASS' if c.ok else 'FAIL'}] {c.name}")
        if (not c.ok or c.name.startswith(DISCLOSURE_TAG)) and c.detail:
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
    ap.add_argument("--embedding-calls", type=int, default=None,
                    help="本轮 embedding 调用次数(由调用方/日志提供)。"
                         "不传 = 披露里如实写 unknown,**不会被当成 0**")
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

    checks = run_online(args.base.rstrip("/"), embedding_calls=args.embedding_calls)
    print(render(checks))
    return 0 if all(c.ok for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())