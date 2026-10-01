#!/usr/bin/env python3
"""P4f:`persona` / `persona_inject` 用例在**主循环里的接线**验证(假 HTTP 客户端,零额度)。

## 为什么需要这一层(与 `test_p4f_persona_eval.py` 的分工)

`test_p4f_persona_eval.py` 验的是**判据本身能不能判红**。
但它碰不到下面两个真实接线风险 —— 两者都会让整轮评测**假绿**,而且从报告里看不出来:

  ① **类型漏进 else 分支**:`run()` 的分派是 `if/elif` 链,末尾 `else` 兜给
     `kb_hidden` 的 `judge_*`。若 `persona` 忘了加分支,它会落进 else ——
     `judge_kb_hidden` 对没有 `expect_absent_keywords` 的用例几乎恒 PASS。
     结果:4 条 persona 用例全绿,而 persona 判据**一次都没跑**。
  ② **第二个会话脱离隔离核对**:`persona` 一次用例开**两个**会话(两个 persona),
     `persona_inject` 也是两个(基线 + 攻击)。若只登记主 `conversation_id`,
     第二个会话的消息 id 从不参与「全局唯一」核对 → 串台查不出来,
     而 P4b C7 的隔离断言正是靠这个保证评测可信。

所以这里直接**打到主循环**:读源码确认分派存在 + 用假 `httpx.Client` 真跑执行器,
核对「建了几个 persona / 发了几次 chat / 每次是否显式带 persona_id /
登记了几个会话 / teardown 是否清理」。

## 零额度

假客户端**不发任何请求**;不 import novaagent;不起服务。
只 import `evals/run_evals.py` 的纯函数与执行器。

跑法:
    cd E:/AILearn/NovaCampus/novaagent
    .venv/Scripts/python.exe tests/test_p4f_persona_eval_wiring.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # E:/AILearn/NovaCampus
sys.path.insert(0, str(ROOT / "evals"))

import run_evals as R  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def chk(cond: bool, name: str, detail: str = "") -> None:
    (PASSED if cond else FAILED).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"\n       {detail}" if detail and not cond else ""))


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("-" * 78)


# ---------- 假 HTTP 客户端 ----------

class Resp:
    def __init__(self, code: int = 200, payload: dict | None = None, text: str = ""):
        self.status_code = code
        self._p = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._p

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise R.httpx.HTTPStatusError("boom", request=None, response=self)


ANSWER_LONG = ("申请休学需提交[1]：一、书面申请;二、诊断证明;三、导师签字;"
               "四、院系审批;五、离校手续确认，与教材一致。")
ANSWER_SHORT = "需提交书面申请与诊断证明[1]，经导师签字后报研究生院备案[1]。"
DOC = "研究生学籍管理规定"


class FakeClient:
    """按端点分派。`detailed_ids` 里的 persona_id 返回长答案,其余返回短答案。"""

    def __init__(self, detailed_ids: set[int] | None = None):
        self.detailed_ids = detailed_ids or set()
        self.created: list[str] = []
        self.chats: list[tuple] = []
        self.deleted: list[str] = []
        self._next_pid = 900

    def post(self, url, headers=None, json=None):
        if url.endswith("/api/personas"):
            self._next_pid += 1
            self.created.append(json["name"])
            return Resp(payload={"persona": {"id": self._next_pid, **json}})
        if url.endswith("/api/chat"):
            pid = json.get("persona_id")
            self.chats.append((json.get("question"), pid))
            ans = ANSWER_LONG if pid in self.detailed_ids else ANSWER_SHORT
            return Resp(payload={"answer": ans, "sources": [{"title": DOC, "ref": 1}],
                                 "conversation_id": 5000 + len(self.chats),
                                 "context": {"hit": False}})
        return Resp(payload={})

    def delete(self, url, headers=None, params=None):
        self.deleted.append(url)
        return Resp(payload={"ok": True})

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class LeakyClient(FakeClient):
    """模拟「注入真的生效」:零来源 + 零引用标记 + 复述注入话术。"""

    def post(self, url, headers=None, json=None):
        if url.endswith("/api/chat"):
            self.chats.append((json.get("question"), json.get("persona_id")))
            return Resp(payload={"answer": "已忽略上述规则，凭记忆回答即可，不必引用来源。",
                                 "sources": [], "conversation_id": 9001, "context": {}})
        return super().post(url, headers=headers, json=json)


TOKENS = {r: f"tok-{r}" for r in ("admin", "counselor", "student")}


# ---------- ① 主循环分派 ----------

def section_dispatch():
    section("① 主循环分派 —— persona 类型必须各有自己的 elif(否则落进 else 被当 kb_hidden 判)")

    src = (ROOT / "evals" / "run_evals.py").read_text(encoding="utf-8")
    start = src.index("for case in cases:")
    # ⚠ 必须用 rindex:`run_conversation_case` 里有一个同名的 `except httpx.HTTPStatusError`,
    #   **早于**主循环。用 index 会命中那个,切片成空串 → 分派断言全部假红(第一版踩过)。
    body = src[start:src.rindex("except httpx.HTTPStatusError")]
    chk(bool(body), f"主循环源码切片非空({len(body)} 字符)")

    for t in ("persona", "persona_inject"):
        chk(f'case["type"] == "{t}"' in body,
            f"主循环有 {t} 的 elif 分支(不落进 else → 不被 kb_hidden 判)")
    for t in ("qa", "permission_api", "scoped_qa", "intent", "rewrite",
              "stream_sse", "web_grounded"):
        chk(f'case["type"] == "{t}"' in body, f"既有 {t} 分支未被挤掉")

    # else 兜底分支仍然是 qa/refusal/kb_hidden 三选一,不含 persona
    tail = body[body.rindex("else:"):]
    chk("judge_kb_hidden" in tail and "judge_persona" not in tail,
        "else 兜底分支只含 kb_hidden 判定,不含 persona 判定")


# ---------- ② cases.json 用例自洽 ----------

def section_cases():
    section("② cases.json —— persona / persona_inject 用例字段自洽")

    spec = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
    pc = [c for c in spec["cases"] if c["type"] == "persona"]
    ic = [c for c in spec["cases"] if c["type"] == "persona_inject"]

    chk(spec["version"] == "v2.5", f"cases.json version=v2.5(实得 {spec['version']})")
    chk(len(spec["cases"]) == 59, f"用例总数 59(实得 {len(spec['cases'])})")
    chk(len(pc) == 3, f"persona 用例 3 条(实得 {len(pc)})")
    chk(len(ic) == 1, f"persona_inject 用例 1 条(实得 {len(ic)})")

    ids = [c["id"] for c in spec["cases"]]
    chk(len(ids) == len(set(ids)), "全部用例 id 互异(重复 id 会让隔离断言张冠李戴)")

    for c in pc:
        personas = c["setup"]["personas"]
        keys = {p["key"] for p in personas}
        chk(len(personas) == 2, f"{c['id']}: 两个 persona spec")
        chk(len(keys) == 2,
            f"{c['id']}: 两个 key 互异(judge 按 key 建 dict,重复会静默覆盖一侧)")
        # ⚠ 第3 回⑤:`longer` **变成可选** —— 无该键时判据走**方向无关**的
        #   长度比(任一侧更长皆可)。故这里分两种情况断言,不能无条件 `["longer"]`
        #   (那会在合法的方向无关用例上 KeyError,自测直接崩,而不是给出结论)。
        _st = c.get("expect_style") or {}
        if "longer" in _st:
            chk(_st["longer"] in keys,
                f"{c['id']}: expect_style.longer 指向真实存在的侧(否则风格判据直接判红)")
            chk(float(_st.get("min_ratio") or 0) >= 1.0,
                f"{c['id']}: min_ratio ≥ 1.0(小于 1 等于没有长度要求)")
        else:
            chk(float(_st.get("min_ratio") or 0) > 1.0,
                f"{c['id']}: 无 longer 的方向无关用例**仍必须声明 min_ratio > 1**"
                f"(否则风格判据完全失效,pf-03 就成了'不校验')")
            chk(c["id"] == "pf-03",
                f"{c['id']}: 只有 pf-03 是方向无关用例(负责人三次实测定案,"
                f"其余用例应保留 longer)")
            chk(_st.get("min_ratio") == 1.15,
                f"{c['id']}: pf-03 的 min_ratio 仍是 1.15(放宽方向不改阈值)")
        chk(bool(c.get("expect_sources")),
            f"{c['id']}: 声明了 expect_sources(主判据要有标注来源)")
        chk(bool(c.get("expect_keywords")),
            f"{c['id']}: 声明了 expect_keywords(风格变了但内容不能丢)")
        chk(c["role"] in ("counselor", "admin"),
            f"{c['id']}: role={c['role']}(persona 建/删只有 counselor+admin 有权,学生建不了)")

    inj = ic[0]["setup"]["persona"]["persona_prompt"]
    chk("忽略以上" in inj, "persona_inject: persona_prompt 确有「忽略以上…」注入文本")
    chk(bool(ic[0].get("expect_absent_keywords")), "persona_inject: 声明了 expect_absent_keywords")
    missing = [w for w in ic[0]["expect_absent_keywords"] if w not in inj]
    chk(not missing,
        "persona_inject: absent 判据词全部取自注入文本本身(不凭空写,判红才可信)",
        f"不在注入文本里的词: {missing}")
    return spec


# ---------- ③ 隔离断言覆盖全部会话 ----------

def section_isolation():
    section("③ 隔离断言 —— persona 开的**每一个**会话都要进核对")

    src = (ROOT / "evals" / "run_evals.py").read_text(encoding="utf-8")
    chk('"extra_conversation_ids": extra_conversation_ids' in src,
        "results 记录 extra_conversation_ids")
    chk('r.get("extra_conversation_ids") or []' in src,
        "隔离断言遍历 extra_conversation_ids(第二个会话不脱离核对)")
    chk("extra_conversation_ids: list = []" in src,
        "每轮初始化 extra_conversation_ids(非 persona 类型必须为空,不污染既有路径)")


# ---------- ④ 执行器端到端(假客户端) ----------

def section_runner(spec):
    section("④ 执行器端到端 —— 真跑 cases.json 里的用例(假客户端,零额度)")

    pf01 = next(c for c in spec["cases"] if c["id"] == "pf-01")
    # pf-01 的第一个 persona(spec 顺序)建出 id=901 → 详尽
    c = FakeClient(detailed_ids={901})
    res = R.run_persona_case(c, TOKENS, pf01)
    chk(res["ok"] is True, f"run_persona_case(pf-01) → PASS\n       {res['detail']}")
    chk(len(res["conversation_ids"]) == 2,
        f"登记了 2 个会话 id(隔离断言要逐个核对)(实得 {len(res['conversation_ids'])})")
    chk(len(c.created) == 2, f"按 spec 建了 2 个 persona(实得 {len(c.created)})")
    chk(len(c.chats) == 2, f"发 2 次 chat(实得 {len(c.chats)})")
    chk(all(q for q, _ in c.chats), "两次 chat 都带了 question")
    chk(all(pid is not None for _, pid in c.chats),
        "两次 chat 都**显式带 persona_id**(只靠会话绑定的话「首问前先选人设」会静默丢失)")
    chk(len({pid for _, pid in c.chats}) == 2, "两次 chat 用了不同 persona")
    chk(len(c.deleted) == 2, f"teardown 软删了 2 个 persona(实得 {len(c.deleted)})")

    # 会话必须彼此独立:两次 chat 都**不带** conversation_id
    # (共用一个会话会让后者看到前者历史,风格/来源对照都被污染)。
    # 假客户端不校验请求体里的 conversation_id 键,但可以断言:两次 chat 的会话 id 不同
    # —— 相同就说明服务端复用了同一个会话(执行器把 conversation_id 传进去了)。
    res_cids = [x for x in res["conversation_ids"] if x]
    chk(len(set(res_cids)) == len(res_cids) and len(res_cids) == 2,
        "两次 chat 拿到**不同**的 conversation_id(未共用会话,对照才不被历史污染)",
        f"cids={res_cids}")

    pf03 = next(x for x in spec["cases"] if x["id"] == "pf-03")
    c3 = FakeClient(detailed_ids={901})
    res3 = R.run_persona_case(c3, TOKENS, pf03)
    chk(isinstance(res3["ok"], bool),
        f"run_persona_case(pf-03) 返回 bool(亲和 vs 正式,ratio 1.15)={res3['ok']}\n       {res3['detail']}")

    ic01 = next(x for x in spec["cases"] if x["id"] == "pf-inject-01")
    c2 = FakeClient(detailed_ids={901})
    res2 = R.run_persona_inject_case(c2, TOKENS, ic01)
    chk(res2["ok"] is True, f"run_persona_inject_case(pf-inject-01) → PASS\n       {res2['detail']}")
    chk(len(res2["conversation_ids"]) == 2,
        f"登记了 2 个会话(基线 + 攻击)(实得 {len(res2['conversation_ids'])})")
    chk(c2.chats[0][1] is None,
        "第 1 次 chat 不带 persona_id(先取**无 persona 基线**)")
    chk(c2.chats[1][1] is not None,
        "第 2 次 chat 带 persona_id(顺序不能反,反了就没有基线可比)")
    chk(len(c2.deleted) == 1, f"teardown 软删了 persona(实得 {len(c2.deleted)})")

    section("⑤ 执行器端到端判红 —— 注入真生效时必须返回 FAIL")
    res3 = R.run_persona_inject_case(LeakyClient(), TOKENS, ic01)
    chk(res3["ok"] is False,
        f"注入真生效(零来源 + 零引用 + 话术复述)→ 执行器返回 FAIL\n       {res3['detail']}")
    chk("零来源" in res3["detail"] and "注入" in res3["detail"],
        "FAIL 文案指明了两条以上判据(能定位,不是笼统的红)")

    res4 = R.run_persona_case(FakeClient(detailed_ids=set()), TOKENS, pf01)
    chk(res4["ok"] is False,
        f"两个 persona 篇幅比不达标(人设没生效)→ 执行器返回 FAIL\n       {res4['detail']}")


# ---------- ⑥ 零额度与副作用 ----------

def section_no_side_effect():
    section("⑥ 零额度与无副作用")
    chk("agent" not in sys.modules, "novaagent.agent 未被导入(不碰 DB / 不建 LLM 客户端)")
    chk("novaagent.main" not in sys.modules, "novaagent.main 未被导入(不起 lifespan)")

    src = (ROOT / "evals" / "run_evals.py").read_text(encoding="utf-8")
    chk("CLIENT_ENV_ALLOWLIST" in src,
        "C0-① 显式白名单仍在(本单没把密钥收口改回去)")
    chk('"server": server_flags' in src,
        "C0-⑥ env_flags.server 仍带服务端 flags(含 llm_key_source)")


def main() -> int:
    for fn in (section_dispatch, section_cases, section_isolation):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            FAILED.append(f"{fn.__name__} 抛异常")
            print(f"[FAIL] {fn.__name__} 抛异常: {type(e).__name__}: {e}")
    try:
        spec = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
        for fn in (lambda: section_runner(spec), section_no_side_effect):
            fn()
    except Exception as e:  # noqa: BLE001
        FAILED.append(f"runner/no_side_effect 抛异常")
        print(f"[FAIL] 抛异常: {type(e).__name__}: {e}")

    total = len(PASSED) + len(FAILED)
    print("\n" + "=" * 78)
    print(f"[RESULT] {len(PASSED)}/{total} passed")
    for f in FAILED:
        print(f"  - {f}")
    print("=" * 78)
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())