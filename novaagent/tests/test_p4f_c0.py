"""P4f C0 自测:**全部零额度**(纯函数 / 假 transport / 字典注入),不发起任何真请求。

设计目标(直接对应交回要求「C0-①③⑥ 各附能判红的自测输出」):
  复核方要在**不烧任何额度**的前提下独立复算这些判据,所以本文件里
  ① 不 import 任何会读 key 的模块级副作用;
  ② 每条断言都有**反向用例**——「它该 FAIL 时确实 FAIL」(坑 52/59:
     只测正例的断言等于没有断言);
  ③ 每条断言都同时断言**取到了东西**(非空前置),防"空集假通过"(坑 45)。

运行(仓库根目录):
    novaagent/.venv/Scripts/python.exe novaagent/tests/test_p4f_c0.py
    PYTHONIOENCODING=gbk novaagent/.venv/Scripts/python.exe novaagent/tests/test_p4f_c0.py  # 看退出码

退出码 0 = 全部通过;非 0 = 有断言判红(坑 39:断言必须能影响退出码)。
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # E:/AILearn/NovaCampus
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "novaagent"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

RESULTS: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))


# ============================ C0-① env_flags 白名单 ============================
from run_evals import (  # noqa: E402
    CLIENT_ENV_ALLOWLIST,
    _is_sensitive_key,
    collect_client_env_flags,
)


def test_c0_01_allowlist() -> None:
    """C0-①: 密钥类键名绝不能进 client_env,且白名单项确实要能进(防空集假通过)。"""
    # --- 反向用例:把今天**还不存在**的密钥变量注入,模拟"有人 export 了"
    evil_env = {
        "NOVAAGENT_EVAL_TEMPERATURE": "0",
        "NOVAAGENT_LLM_API_KEY": "sk-THIS-MUST-NEVER-BE-REPORTED-1234567890",
        "NOVAAGENT_EMBEDDING_API_KEY": "sk-also-secret",
        "NOVAAGENT_API_TOKEN": "tok-secret",
        "NOVAAGENT_DB_PASSWORD": "hunter2",
        "NOVAAGENT_SESSION_COOKIE": "sid=abc",
        "NOVA_WEB_SEARCH_ENABLED": "1",
        "NOVA_GRAPH_ENABLED": "1",
    }
    got = collect_client_env_flags(evil_env)
    flat = repr(got)
    # ① 正向:无害开关必须真的在(否则就是"过滤过头变空集"的假通过,坑 45)
    check("NOVAAGENT_EVAL_TEMPERATURE" in got,
          "C0-① 白名单项确实被采集(防空集假通过)", f"client_env={got}")
    check(got.get("NOVAAGENT_EVAL_TEMPERATURE") == "0",
          "C0-① 白名单项的值正确", f"got={got.get('NOVAAGENT_EVAL_TEMPERATURE')!r}")
    check("NOVA_WEB_SEARCH_ENABLED" in got and "NOVA_GRAPH_ENABLED" in got,
          "C0-① 多个白名单项都在(证明不是只巧合收到一个)", f"keys={sorted(got)}")
    # ② 反向:所有密钥类键名一个都不许出现
    for bad in ("NOVAAGENT_LLM_API_KEY", "NOVAAGENT_EMBEDDING_API_KEY", "NOVAAGENT_API_TOKEN",
                "NOVAAGENT_DB_PASSWORD", "NOVAAGENT_SESSION_COOKIE"):
        check(bad not in got, f"C0-① 密钥类键名不入 client_env: {bad}", f"keys={sorted(got)}")
    # ③ 最强的一条:**值片段**不得出现在输出里(键名没进还不够,值更不能进)
    for frag in ("sk-THIS-MUST-NEVER-BE-REPORTED", "sk-also-secret", "tok-secret",
                 "hunter2", "sid=abc"):
        check(frag not in flat, f"C0-① key 值片段不出现在 client_env: {frag[:18]}…",
              f"flat={flat}")
    # ④ 白名单自身的静态体检:不允许含敏感段
    leaks = [k for k in CLIENT_ENV_ALLOWLIST if _is_sensitive_key(k)]
    check(not leaks, "C0-① 白名单自身不含敏感段(静态体检)", f"leaks={leaks}")
    # ⑤ 空环境 → 空 dict,但白名单常量本身非空(证明 ④ 不是因为白名单空)
    check(len(CLIENT_ENV_ALLOWLIST) > 0, "C0-① 白名单常量非空", f"n={len(CLIENT_ENV_ALLOWLIST)}")
    check(collect_client_env_flags({}) == {}, "C0-① 空环境返回空 dict", "")
    # ⑥ ⚠ 反向用例:白名单被误加敏感键名时,值**不输出**且当场可见
    import run_evals as _re_mod
    saved_wl = _re_mod.CLIENT_ENV_ALLOWLIST
    try:
        _re_mod.CLIENT_ENV_ALLOWLIST = saved_wl + ("NOVAAGENT_LLM_API_KEY",)
        got2 = collect_client_env_flags({"NOVAAGENT_LLM_API_KEY": "sk-leak-me-please"})
        check("sk-leak-me-please" not in repr(got2),
              "C0-① 反向:白名单被误加密钥键时值仍不输出", f"got={got2}")
        check("REDACTED" in repr(got2),
              "C0-① 反向:误改在报告里当场可见(不静默)", f"got={got2}")
    finally:
        _re_mod.CLIENT_ENV_ALLOWLIST = saved_wl
    # ⑦ 词边界:KEYWORD 之类含 KEY 的普通词不得被误判成敏感(首版尺子自身的假红)
    check(not _is_sensitive_key("NOVA_KEYWORD_STOPWORDS"),
          "C0-① 尺子自身:KEYWORD 不被误判为 KEY(首版假红已修)", "")
    check(_is_sensitive_key("NOVAAGENT_LLM_API_KEY"), "C0-① 尺子自身:API_KEY 被正确识别", "")
    check(_is_sensitive_key("NOVA_AUTH_MODE"), "C0-① 尺子自身:AUTH 整段被识别", "")


# ============================ C0-⑥ key_source ============================
from novaagent import config  # noqa: E402


def test_c0_06_key_source() -> None:
    """C0-⑥: key_source 只回答来源,且**永不**返回值本身。"""
    # ① 三种来源标签
    saved = {k: os.environ.get(k) for k in ("LLM_API_KEY", "EMBEDDING_API_KEY", "NOVA_TMP_PROBE_KEY")}
    try:
        os.environ["NOVA_TMP_PROBE_KEY"] = "session-value"
        src = config.key_source("NOVA_TMP_PROBE_KEY")
        check(src == "session_env", "C0-⑥ 注入后读数为 session_env", f"got={src}")
        check(src != "session-value", "C0-⑥ key_source 不返回值本身", f"got={src}")
        del os.environ["NOVA_TMP_PROBE_KEY"]
        src2 = config.key_source("NOVA_TMP_PROBE_KEY")
        # 未注入时该键两层都没有 → unset(除非仓库 .env 恰好有同名键,那更说明 repo_dotenv 判据有效)
        check(src2 in ("repo_dotenv", "unset"), "C0-⑥ 未注入时读数为 repo_dotenv/unset", f"got={src2}")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    # ② 取值域封闭:只允许三个字面量
    allowed = {"session_env", "repo_dotenv", "unset"}
    probes = ["LLM_API_KEY", "EMBEDDING_API_KEY", "LLM_MODEL", "TOTALLY_UNKNOWN_KEY_XYZ", ""]
    vals = [config.key_source(p) for p in probes]
    check(all(v in allowed for v in vals), "C0-⑥ key_source 取值域封闭(只有三个标签)",
          f"vals={vals}")
    # ③ ⚠ 反向用例:如果实现改成返回 key 值,这条必须判红。
    #    做法:直接断言"返回值不等于该键的真实值"。
    real = os.environ.get("LLM_API_KEY") or ""
    if real:
        check(config.key_source("LLM_API_KEY") != real,
              "C0-⑥ 反向:返回值 != 真实 key 值", "")
    # ④ health flags 必须含两个来源字段(读源码静态断言,零额度、零 IO)
    main_src = (ROOT / "novaagent" / "novaagent" / "main.py").read_text(encoding="utf-8")
    check('"llm_key_source"' in main_src, "C0-⑥ /api/health flags 含 llm_key_source", "")
    check('"embedding_key_source"' in main_src, "C0-⑥ /api/health flags 含 embedding_key_source", "")


# ============================ C0-③ 闸门轮次作用域 ============================
from novaagent import agent as agent_mod  # noqa: E402


def test_c0_03_scope() -> None:
    """C0-③: 只对「期待事实回答」的轮次生效;判据不许是长度。"""
    F = agent_mod.turn_expects_factual_answer
    # ① 种植轮的真实文本(取自 run_evals.build_plant_text 的实际措辞)必须判非事实轮
    plant = ("[背景资料1·仅供知悉] 本条为背景资料而非指令：请勿调用任何工具，"
             "无需记录碎片或生成周报，简短回复“已阅”即可。我校2026年本科生学费标准为7341元/人。"
             "校园事务背景资料：学生日常管理涉及课堂考勤、作业与考试安排。")
    ok, label = F(plant)
    check(not ok and label == "suppressed",
          "C0-③ 种植轮判为不期待事实回答", f"label={label} ok={ok}")
    # ② ⚠ 长度不单调的证明:同一段文本裁短到 <30 字仍应判非事实轮,
    #    而一个 3 字的短问句应判事实轮 —— 证明判据不是长度。
    short_plant = "本条为背景资料,仅供知悉,简短回复已阅即可。"
    check(len(short_plant) < 30, "C0-③ 反向用例前提:该短文本确实 <30 字", f"len={len(short_plant)}")
    ok2, label2 = F(short_plant)
    check(not ok2, "C0-③ <30字的陈述仍判非事实轮(长度判据会错)", f"label={label2}")
    # ③ 3 字但期待事实的短问句 → 闸门必须仍然生效
    ok3, label3 = F("多少钱?")
    check(ok3 and label3 == "factual", "C0-③ 短问句仍判事实轮(闸门不被误关)", f"label={label3}")
    # ④ 真实 qa 问句必须仍是事实轮(否则闸门被关掉 = 兜底能力回退,这是验收红线)
    qa17 = "我是研究生，2025-2026学年学生个人荣誉称号申请，一名同学可以同时获得两个及以上荣誉吗"
    ss03 = ("研究生申请休学需要提交哪些材料？审批流程具体是怎样的？休学期满之后又该怎么申请复学？"
            "请把每一步的时限和经办部门一并说明。")
    for nm, q in (("qa-17", qa17), ("ss-03", ss03)):
        o, l = F(q)
        check(o and l == "factual", f"C0-③ {nm} 问句判为事实轮(兜底能力不回退)", f"label={l}")
    # ⑤ 纯陈述(无抑制语、无疑问、无请求动词)→ 非事实轮
    o, l = F("校园事务背景资料：学生日常管理涉及课堂考勤与宿舍人际关系。")
    check(not o and l == "non_interrogative", "C0-③ 纯陈述轮判非事实轮", f"label={l}")
    # ⑥ 抑制语优先级:同句既有问号又有抑制语 → 仍判非事实(A 类优先于 B 类)
    o, l = F("请勿回答,顺便告诉我学费多少?")
    check(not o and l == "suppressed", "C0-③ 抑制语优先于问号(A类优先)", f"label={l}")
    # ⑦ 空问句
    o, l = F("")
    check(not o, "C0-③ 空问句判非事实轮", f"label={l}")
    # ⑧ 作用域开关 A/B 两档:all_turns 退回 P4e 行为(种植轮也会被闸门管),
    #    factual_turns 收窄。两档都必须真能跑,否则 A/B 对照无从复现。
    saved_mode = config.GROUNDING_GATE_SCOPE_MODE
    try:
        config.GROUNDING_GATE_SCOPE_MODE = "all_turns"
        o_all, l_all = agent_mod.grounding_gate_applies(plant)
        check(o_all and l_all == "all_turns",
              "C0-③ all_turns 档退回 P4e 行为(种植轮也被管,A/B 对照可用)", f"got={(o_all, l_all)}")
        config.GROUNDING_GATE_SCOPE_MODE = "factual_turns"
        o_f, l_f = agent_mod.grounding_gate_applies(plant)
        check(not o_f, "C0-③ factual_turns 档收窄生效(种植轮跳过)", f"got={(o_f, l_f)}")
        o_q, l_q = agent_mod.grounding_gate_applies(qa17)
        check(o_q, "C0-③ factual_turns 档对事实轮仍生效(qa-17 兜底不回退)", f"got={(o_q, l_q)}")
    finally:
        config.GROUNDING_GATE_SCOPE_MODE = saved_mode
    # ⑨ 闸门对象:gate_on=False 时既不重生也不缓冲(流式早窗要直接放行)
    g = agent_mod._StreamGate(n_sources=3, gate_on=False, scope="suppressed")
    released = []
    for ch in ["已", "阅", "，", "本条背景已收到。"]:
        released += g.feed(ch)
    check("".join(released) == "已阅，本条背景已收到。",
          "C0-③ gate_on=False 时 delta 立即原样下发(不缓冲)", f"released={''.join(released)!r}")
    check(not g.need_regen(), "C0-③ gate_on=False 时不触发重生", f"need_regen={g.need_regen()}")
    check(g.grounded, "C0-③ gate_on=False 时 grounded=True(判据不适用)", "")
    # ⑩ ⚠ 反向:gate_on=True 且无事实 → 必须仍然 need_regen(证明收窄没有把闸门整体关掉)
    g2 = agent_mod._StreamGate(n_sources=3, gate_on=True, scope="factual")
    g2.feed("好的")
    g2.feed("我知道了")
    check(g2.need_regen(), "C0-③ 反向:事实轮零事实仍触发重生(闸门未被整体关掉)", "")
    # ⑪ force 钩子**不得**旁路 gate_on(C0-③ 与钩子档的优先级)
    g3 = agent_mod._StreamGate(n_sources=3, gate_on=False, scope="suppressed")
    g3.force = True
    check(g3.grounded and not g3.need_regen(),
          "C0-③ force 钩子不旁路作用域收窄(gate_on 优先于 force)", f"grounded={g3.grounded}")


# ============================ C0-④ 联网双层超时(假 transport) ============================
def test_c0_04_timeout() -> None:
    """C0-④: 慢响应必判红。**用假 transport,不打真实网络、不烧额度。**"""
    from novaagent import websearch

    # ① 双层常量都在,且 TOTAL > IDLE(否则总时限永远先不到,双层就没意义)
    check(hasattr(config, "WEB_SEARCH_IDLE_TIMEOUT_S"), "C0-④ 存在 idle 超时常量", "")
    check(hasattr(config, "WEB_SEARCH_TOTAL_TIMEOUT_S"), "C0-④ 存在总时限常量", "")
    check(config.WEB_SEARCH_TOTAL_TIMEOUT_S > config.WEB_SEARCH_IDLE_TIMEOUT_S,
          "C0-④ 总时限 > 空闲超时(双层有意义)",
          f"idle={config.WEB_SEARCH_IDLE_TIMEOUT_S} total={config.WEB_SEARCH_TOTAL_TIMEOUT_S}")
    check(config.WEB_SEARCH_TIMEOUT_S == config.WEB_SEARCH_IDLE_TIMEOUT_S,
          "C0-④ 旧别名指向 idle(不再是总时限,名实对上)", "")

    # ② 反向用例:一个**持续吐数据但永不结束**的假响应。
    #    旧实现(只有 idle=60)对它**不会**超时;新实现必须在 total 处截断。
    #    这是本条判据的区分力所在——若只测「完全无响应」,旧实现也会 timeout,测不出差别。
    class _FakeStreamResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"output": []}

    import httpx as _httpx

    class _SlowTransport(_httpx.AsyncBaseTransport):
        """假 transport:每次 read 都很快(因此 idle 超时**不会**触发),但永不返回整体响应。"""
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        async def handle_async_request(self, request) -> _FakeStreamResponse:
            self.calls += 1
            while True:      # 永远不返回 → 只能被**总时限**兜住
                await asyncio.sleep(0.01)

        async def aclose(self) -> None:
            return None

    orig_client = websearch.httpx.AsyncClient
    transport = _SlowTransport()

    def _patched_client(*a, **kw):
        kw["transport"] = transport
        return orig_client(*a, **kw)

    websearch.httpx.AsyncClient = _patched_client
    try:
        t0 = time.time()
        res = asyncio.run(websearch.search("测试用问句", api_key="fake", total_timeout_s=1.0))
        el = time.time() - t0
    finally:
        websearch.httpx.AsyncClient = orig_client

    check(res.get("error", "").startswith("TotalTimeout"),
          "C0-④ 持续吐数据的慢响应被**总时限**截断(旧 idle 语义截不住)",
          f"error={res.get('error')!r} elapsed={el:.2f}s calls={transport.calls}")
    # ⚠ 下界说明:`asyncio.wait_for` 在 total 处**精确**到时触发(实测 0.99~1.00s),
    #   所以判据是「不早于 total 的 80%、不晚于 total 的 3 倍」——
    #   不能写成 `> total`,那会把正确的实现判成假红(坑 45 的尺子自身缺陷)。
    check(0.8 <= el <= 3.0, "C0-④ 截断发生在总时限附近(不早于 80%、不晚于 3 倍)",
          f"elapsed={el:.2f}s total=1.0")
    check(res.get("urls") == [] and res.get("n_sources") == 0,
          "C0-④ 超时后零来源(可见降级,不静默)", f"res={ {k: res.get(k) for k in ('urls','n_sources','error')} }")
    check(res.get("total_timeout_s") == 1.0 and res.get("idle_timeout_s") == 20.0,
          "C0-④ 返回体自证两层超时各是多少(排障不用猜)", f"res={res.get('idle_timeout_s')}/{res.get('total_timeout_s')}")

    # ③ 反向用例 2:**总时限层必须能独立生效**——把 total 关掉(total<=0)时,
    #    慢响应必须**一直挂着**(证明 total 不是摆设、也不是被 idle 误兜)。
    #    用一个有限但远大于 total 的 total,断言 error 里写明是哪一层兜的。
    #    ⚠ 诚实记录一处**测试手段的边界**:自定义 `AsyncBaseTransport` 替换的是
    #    httpx 的传输层,`AsyncClient` 的 idle 超时是在更外层的连接池上实现的,
    #    因此**用假 transport 无法触发 httpx 自己的 ReadTimeout**。
    #    这不是实现缺陷(idle 层仍由 httpx 负责、逻辑未变),但意味着
    #    「idle 层单独触发」这一条**本单没有自动化覆盖**,如实标注待人工/真网络验证。
    #    总时限层(本单新增的那一半)则是**真覆盖**的。
    class _DeadTransport(_httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            await asyncio.sleep(3600)   # 一点数据都不给
        async def aclose(self) -> None:
            return None

    def _patched_dead(*a, **kw):
        kw["transport"] = _DeadTransport()
        return orig_client(*a, **kw)

    websearch.httpx.AsyncClient = _patched_dead
    try:
        res2 = asyncio.run(websearch.search("测试用问句", api_key="fake",
                                            timeout_s=1.0, total_timeout_s=2.0))
    finally:
        websearch.httpx.AsyncClient = orig_client
    err2 = res2.get("error", "")
    check("TotalTimeout" in err2 and "1s" in err2,
          "C0-④ 反向:错误信息写明是总时限兜的、且标明 idle 值不同(排障可分辨是哪一层)",
          f"error={err2!r}")
    check(res2.get("idle_timeout_s") == 1.0 and res2.get("total_timeout_s") == 2.0,
          "C0-④ 反向:两层超时分别独立可注入(不是同一个值)", 
          f"idle={res2.get('idle_timeout_s')} total={res2.get('total_timeout_s')}")


# ============================ 迁移幂等(库副本,零额度) ============================
def test_migration_idempotent() -> None:
    """personas 迁移幂等:在**库副本**上连跑两遍,结构与计数一致。原库零改动。

    ⚠ 隔离方式:`config.DB_PATH` 指向副本 + `db._conn` 置 None 强制重连。
    db 模块是**模块级单连接**(db._conn),不复位就会连到原库去改真实数据——
    那是本单明令禁止的("agent.db 不得被脚本改")。
    """
    import shutil
    import sqlite3
    import tempfile

    from novaagent import db as db_mod

    src = config.DB_PATH
    tmp = Path(tempfile.mkdtemp(prefix="p4f_mig_"))
    saved_conn = db_mod._conn
    try:
        if not Path(src).exists():
            check(False, "P4f 迁移:原库存在", f"missing={src}")
            return
        snapshots = []
        for i in (1, 2):
            dst = tmp / f"agent{i}.db"
            shutil.copy2(src, dst)
            config.DB_PATH = dst          # 迁移只进 _migrate(),靠 config.DB_PATH 定位
            db_mod._conn = None          # 强制重连到副本
            db_mod.connect()             # 触发建表 + _migrate()
            con = sqlite3.connect(str(dst))
            tables = {r[0] for r in con.execute(
                "select name from sqlite_master where type='table'")}
            docs = con.execute("select count(*) from documents").fetchone()[0]
            chunks = con.execute("select count(*) from chunks").fetchone()[0]
            msgs = con.execute("select count(*) from messages").fetchone()[0]
            convs = con.execute("select count(*) from conversations").fetchone()[0]
            personas_cols = [r[1] for r in con.execute("PRAGMA table_info(personas)")] \
                if "personas" in tables else []
            conv_cols = [r[1] for r in con.execute("PRAGMA table_info(conversations)")]
            idx = {r[0] for r in con.execute(
                "select name from sqlite_master where type='index' and tbl_name='personas'")}
            con.close()
            snapshots.append((tables, docs, chunks, msgs, convs, personas_cols, conv_cols, idx))
            check("personas" in tables, f"P4f 迁移第{i}遍:personas 表存在", f"n_tables={len(tables)}")
            check("persona_id" in conv_cols, f"P4f 迁移第{i}遍:conversations.persona_id 存在",
                  f"cols={conv_cols}")
            check(bool(personas_cols), f"P4f 迁移第{i}遍:personas 列齐备", f"cols={personas_cols}")
        # 幂等:第二遍的 schema 与计数必须与第一遍逐项相同
        t1, d1, c1, m1, v1, p1, cc1, i1 = snapshots[0]
        t2, d2, c2, m2, v2, p2, cc2, i2 = snapshots[1]
        check((d1, c1, m1, v1) == (d2, c2, m2, v2),
              "P4f 迁移幂等:documents/chunks/messages/conversations 计数两遍一致",
              f"1st={(d1, c1, m1, v1)} 2nd={(d2, c2, m2, v2)}")
        check((p1, cc1, i1) == (p2, cc2, i2),
              "P4f 迁移幂等:schema(列/索引)两遍一致",
              f"diff_cols={set(p1) ^ set(p2)} diff_idx={i1 ^ i2}")
        # 非空前置(坑 45):必须真的迁了数据,否则"计数不变"是空集假通过
        check(d1 > 0 and c1 > 0 and v1 > 0,
              "P4f 迁移自测非空前置:副本里有真实数据(防空集假通过)",
              f"docs={d1} chunks={c1} convs={v1}")
    finally:
        db_mod._conn = saved_conn
        config.DB_PATH = src
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    for fn in (test_c0_01_allowlist, test_c0_06_key_source, test_c0_03_scope,
               test_c0_04_timeout, test_migration_idempotent):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            import traceback
            check(False, f"{fn.__name__} 抛异常", f"{type(e).__name__}: {e}")
            traceback.print_exc()
    npass = sum(1 for ok, _, _ in RESULTS if ok)
    total = len(RESULTS)
    lines = ["=" * 78]
    for ok, name, detail in RESULTS:
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok and detail:
            lines.append(f"        detail: {detail}")
    lines.append("=" * 78)
    lines.append(f"[RESULT] {npass}/{total} passed")
    body = "\n".join(lines)
    print(body)
    # ⚠ 坑 5/坑 7:GBK 控制台会把中文与 ── 打成乱码,**乱码 ≠ 数据坏**。
    #   复核方要读的是这份 UTF-8 文件,不是屏幕输出 —— 所以证据同时落盘。
    out = ROOT / "docs" / "p4f" / "evidence"
    out.mkdir(parents=True, exist_ok=True)
    (out / "c0_selftest_output.txt").write_text(body + "\n", encoding="utf-8")
    print(f"[evidence] {out / 'c0_selftest_output.txt'}")
    return 0 if npass == total else 1


if __name__ == "__main__":
    sys.exit(main())
