"""NovaAgent 冒烟测试:三角色权限边界 + RAG 引用 + 周报工具(直调 REST)

P4a 增补:导入质量门纯函数单测(口令三样式/登录页/敏感/名单/禁抓回归)+ KB 计数守恒 +
上传自清理(fixture 本地导入替代自家前端首页,根除 smoke 污染,坑 23/24)。

前置:weekly-mcp 容器已运行(18080),服务端已启动(uvicorn novaagent.main:app --port 8900)
用法:NO_PROXY="127.0.0.1,localhost" python tests/smoke_test.py [--cleanup] [--cleanup-only] [--base URL]
  --cleanup: 额外清理历史残留(旧版冒烟上传且未删的测试文档),跑完打印清理数。
  --cleanup-only: **只清理不跑完整套**(第 5 回⑩)。清完打印删掉的 id 与 documents/chunks
             计数即退出 0 —— 旧版只有「先清理再跑完整套」一种形态,于是「跑一次失败的
             冒烟」=「再污染一次语料」,复核方被迫手工清三轮。
验收口径:跑完 documents 计数必须与起始一致(守恒断言在本文件内);
  中途任何一步炸掉也要守恒 —— 自清理在 finally 里,不在正常路径末尾。
"""
import argparse
import http.server
import io
import os
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

import httpx

# P4e M5 ②:默认端口仍是 8900(保持既有调用方式不变),但**必须能用 --base 指到别处**——
# 此前 BASE 硬编码,服务跑在 :8905 时,「自家前端禁抓」断言会假红
# (期望 code=deny_url、实得 index_page),而质量门代码一行没变。
# 根因已在 main.py 修掉(禁抓判定纳入**运行时 origin**),本参数只是让冒烟能指向任意端口。
BASE = "http://127.0.0.1:8900"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from novaagent import refusal  # noqa: E402  纯函数单测(不依赖运行中的服务)
from novaagent.main import quality_gate_reject  # noqa: E402

SAMPLE_MD = """# 研究生学籍管理规定(测试样例)

第一条 为规范研究生学籍管理,制定本规定。
第二条 研究生最长学习年限为六年,超过者应予退学。
第三条 学生申请休学应提交书面申请、医院证明,经导师和培养单位同意后报研究生院审批。
第四条 休学以一学期为单位,期满前一周应当提交复学申请,经研究生院批准后复学。
第五条 研究生退学由培养单位提出意见,报研究生院审核批准后办理退学手续。
第六条 本规定仅限测试使用,不作为实际管理依据。

# 教师内部备忘(仅辅导员可见)

内部提示:退学预警名单每周一由研究生院下发,辅导员应在 3 个工作日内完成约谈。
"""
SUMMARY_MD = """# 请假办法测试

第一条 学生请假 3 天以内(含 3 天)由辅导员审批,请假单交学生工作办公室备案。
第二条 请假 3 天以上 7 天以内(含 7 天)由学院分管领导审批。
第三条 请假 7 天以上由学院审批后报教务处备案。
第四条 病假需附二级甲等以上医院开具的诊断证明。
第五条 未经批准擅自离校的,按旷课处理,累计达到规定学时的按学籍管理规定给予纪律处分。
第六条 本测试文件仅用于冒烟验证摘要链路,验证完成后应被删除,不作为实际管理依据。
"""
OPS_MD = """# 运维手册测试

第一章 服务巡检:每日 09:00 检查核心服务进程与磁盘水位,磁盘使用率超过 85% 时扩容;每周核对备份完整性。
第二章 故障处置:连接池耗尽时优先定位慢查询并重启应用池;数据库主从延迟超 5 分钟应上报值班组长并暂停批量任务。
第三章 变更管理:生产变更须双人在场,变更前备份,变更后 30 分钟内完成冒烟验证;回滚方案须提前写明。
第四章 值班与升级:夜间值班由工程师轮值,重大故障 15 分钟内升级至部门负责人,处置记录当日归档。
第五章 本文件仅用于冒烟测试分类功能,测试结束后应删除,不作为实际运维依据。
"""
FIXTURE_HTML = """<!DOCTYPE html>
<html><head><title>校园便民服务指南(测试夹具)</title></head><body>
<article><h1>校园便民服务指南</h1>
<p>一、校园卡服务:校园卡丢失后可在一卡通中心挂失与补办,工作日 08:30-17:00 受理,补办需携带学生证或身份证原件。</p>
<p>二、体育场馆:游泳馆开放时间为每日 06:30-21:30,深水区须持深水证入场;体育馆需提前一日线上预约。</p>
<p>三、校车安排:校区间通勤班车工作日每日六个班次,发车时刻以后勤服务网最新公告为准,节假日停运。</p>
<p>四、快递服务:各校区快递服务站位于生活区商业街,取件需凭取件码,大件物品可预约送货到楼。</p>
<p>五、报修服务:宿舍水电故障可在后勤服务平台提交报修工单,紧急情况可拨打楼宇值班电话。</p>
</article></body></html>"""

# 冒烟会产生(并在失败时残留)的文档标题。[0] 清理与 --cleanup-only 都按这份清单删。
# 第 5 回补上「校园便民服务指南(测试夹具)」:它是 [16b] 本地夹具导入的那篇,
# 中途炸掉时同样会残留,而旧清单只覆盖了 4 篇上传文档。
LEGACY_TITLES = ["学籍管理规定-测试", "学籍管理规定-学生版", "分类测试-运维手册",
                 "摘要测试-请假办法", "校园便民服务指南(测试夹具)"]


# ---------- ⑨ 通道判据(纯函数,离线可断言) ----------
# 第 5 回的背景:第 3 回 ③ 加的守卫是 `assert smoke_model in _cands`,而 _cands 是
# **内置 DashScope 候选清单**。于是「换通道」(额度纪律要求的能力)与「冒烟」互斥 ——
# 只要 config.LLM_BASE_URL 指向非 DashScope,第 13 步必炸(Qoder 实测 :8973/:8974 两次)。
# 判据因此从「模型名在候选里」改成「**当前通道是不是内置通道**」:后者才是
# 「要不要验内置模型切换」的正确前置条件。
BUILTIN_LLM_HOST = "dashscope.aliyuncs.com"


def is_builtin_llm_channel(base_url: str = "") -> bool:
    """base_url 是否指向**内置** DashScope 通道(只回答通道,不回答模型名合不合法)。

    · 空串 = 未显式配置 = 回落 config 默认(DashScope 兼容模式)→ 内置;
    · 解析不出 host 的畸形值一律**判非内置** —— 安全方向是走 skip(不 assert 炸),
      而不是在信息不足时把冒烟判红;
    · 端口与 userinfo 不参与判定(`https://user:pw@host:443/v1` 仍按 host 判)。
    """
    bu = (base_url or "").strip()
    if not bu:
        return True
    netloc = urlsplit(bu if "://" in bu else "https://" + bu).netloc.lower()
    host = netloc.rpartition("@")[2].split(":")[0]
    if not host:
        return False
    return host == BUILTIN_LLM_HOST or host.endswith("." + BUILTIN_LLM_HOST)


def plan_step13(base_url: str = "", custom_enabled: bool = False,
                smoke_model: str = "", candidates: list[str] | None = None) -> dict:
    """[13] 该做什么 —— **纯函数**,不联网、不依赖服务,自测可直接断言(第 5 回 ⑨)。

    返回 {"action": "switch"|"skip", "reason": str, "model": str, "valid": bool}。
    ⚠ 判据顺序即优先级:自定义通道 > 非内置通道 > 候选清单为空。
    """
    cands = list(candidates or [])
    if custom_enabled:
        return {"action": "skip", "model": smoke_model, "valid": None,
                "reason": "自定义通道(custom API 已启用),内置模型切换不适用"}
    if not is_builtin_llm_channel(base_url):
        return {"action": "skip", "model": smoke_model, "valid": None,
                "reason": f"内置模型切换不适用于自定义通道(base_url={base_url or '(空)'})"}
    if not cands:
        return {"action": "skip", "model": smoke_model, "valid": None,
                "reason": "MODEL_CANDIDATES 为空,无从切换(防'空集假通过')"}
    model = smoke_model or cands[0]
    return {"action": "switch", "model": model, "valid": model in cands,
            "reason": f"内置通道(base_url={base_url or '(默认 DashScope)'})"}


def login(client: httpx.Client, username: str, password: str) -> dict:
    r = client.post(f"{BASE}/api/login", json={"username": username, "password": password})
    r.raise_for_status()
    return r.json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def unit_tests() -> None:
    """P4a 纯函数单测(不依赖服务):引用剥离/口令三样式/敏感/门控/出口匹配/禁抓回归。"""
    # U1 引用硬校验:越界剥离,[1] 字样与条款编号〔2025〕、年份[2026] 不误伤
    a, s = refusal.strip_invalid_refs("依据〔2025〕13号文件 [1] 与 [3]，年份[2026]有效。", 2)
    assert s == [3] and "[1]" in a and "[3]" not in a and "〔2025〕" in a and "[2026]" in a, (a, s)
    a, s = refusal.strip_invalid_refs("无引用答案 [12]", 0)
    assert s == [12] and "[12]" not in a
    print("[U1] 引用剥离 OK(越界[3]/[12]剥除,[1]与〔2025〕/[2026]不误伤)")

    # U2 口令检测三样式(P3b Review 教训:只匹配单一措辞会漏)
    style_v03 = "演示账号：admin / counselor / student（密码均为 xxx123）" + "补" * 210
    style_v05 = "演示账号 admin/admin123 · counselor/counselor123 · student/student123" + "补" * 210
    style_slash = "登录用户名/口令请勿外传" + "补" * 210
    for label, text in [("v0.3 密码均为式", style_v03), ("v0.5 字面量式", style_v05),
                        ("用户名/口令斜杠式", style_slash)]:
        r = quality_gate_reject("", "测试页", text)
        assert r and r["code"] == "credential", (label, r)
    neg = ("如登录密码遗失，请携带学生证到信息中心重置。" + "正常正文。" * 40)
    assert quality_gate_reject("", "重置指引", neg) is None, "正常正文不应被口令规则误伤"
    print("[U2] 口令检测 OK(v0.3 密码均为/v0.5 字面量/用户名口令斜杠式 全命中,正常正文不误伤)")

    # U3 敏感与名单
    r = quality_gate_reject("", "通知", "联系电话 13812345678。" + "补" * 210)
    assert r and r["code"] == "personal_info", r
    r = quality_gate_reject("", "名单公示", "本次名单含姓名与学号两列。" + "张三，3120100000。" + "补" * 210)
    assert r and r["code"] == "name_list", r
    r = quality_gate_reject("", "登录", "请输入用户名与密码。" + "补" * 210)
    assert r and r["code"] == "login_title", r
    assert quality_gate_reject("", "正常页", "校园通知正文，用于验证长度下限与放行路径。" * 15) is None
    print("[U3] 敏感扫描 OK(手机号 personal_info/名单 name_list/登录标题 login_title/正常页放行)")

    # U4 门控判定(拒答硬门控;含实测修正:单来源高置信放行,单来源低分拒)
    G = lambda t, n: {"rerank_available": True, "top_score": t, "n_above_threshold": n}
    assert refusal.should_refuse([], G(0.9, 0))[0]
    assert refusal.should_refuse([{"t": 1}], G(0.5, 1))[0]        # 单来源低分→拒
    assert not refusal.should_refuse([{"t": 1}], G(0.9952, 1))[0]  # qa-01 实测:单块 0.9952→答
    assert not refusal.should_refuse([{"t": 1}, {"t": 2}], G(0.9, 2))[0]
    assert not refusal.should_refuse([{"t": 1}], {"rerank_available": False, "top_score": None, "n_above_threshold": 1})[0]
    short = quality_gate_reject("", "短文", "只有一句话。")
    assert short and short["code"] == "too_short", short
    print("[U4] 拒答门控判定 OK(空来源/单达标低分拒,单来源高置信与双达标答,降级路径答,短正文拒)")

    # U5 出口匹配(F2 → 保卫处;F1 短问 → 校医院医保办)
    f2 = [c["dept"] for c in refusal.match_contacts("我们学校有学平险吗，我看我们计财处只有医保这项")]
    assert f2 and "保卫处" in f2[0], f2
    f1s = [c["dept"] for c in refusal.match_contacts("我参保地还在某市，怎么转到学校这边")]
    assert f1s and "医保" in f1s[0], f1s
    print(f"[U5] 出口匹配 OK(F2→{f2[0]};F1短问→{f1s[0]})")

    # U6 禁抓回归(P3a/P4 历史脏数据源,必须被拦)
    for url in ("https://cwc.swjtu.edu.cn/", "http://127.0.0.1:8900/"):
        r = quality_gate_reject(url, "任意标题", "足够长的正文内容。" * 40)
        assert r and r["code"] == "deny_url", (url, r)
    print("[U6] 禁抓回归 OK(cwc 首页/自家前端 均命中 DENY_URLS)")

    # U7 导航/索引页判据(P4a-1):真实样本拒,正文页放行,6 篇已入库语料零误伤
    from novaagent.main import index_page_stats, is_index_page
    sample = Path(__file__).resolve().parent.parent.parent / "docs" / "p4" / "evidence" / "sample_index_page.txt"
    sample_text = sample.read_text(encoding="utf-8")
    st = index_page_stats(sample_text)
    assert st["short_ratio"] >= 0.5 and st["long_ratio"] < 0.15 and st["total_lines"] >= 20, st
    r = quality_gate_reject("", "收费项目", sample_text)
    assert r and r["code"] == "index_page", r
    article = ("一、校园卡服务:校园卡丢失后可在一卡通中心挂失与补办，工作日 08:30-17:00 受理，"
               "补办需携带学生证或身份证原件，挂失后 24 小时内生效。\n"
               "二、体育场馆:游泳馆开放时间为每日 06:30-21:30，深水区须持深水证入场；"
               "体育馆需提前一日线上预约，节假日开放时间以场馆公告为准。\n"
               "三、校车安排:校区间通勤班车工作日每日六个班次，发车时刻以后勤服务网最新公告为准，"
               "节假日停运；教师班车随原班次执行。\n"
               "四、报修服务:宿舍水电故障可在后勤服务平台提交报修工单，"
               "紧急情况可拨打楼宇值班电话，报修后 48 小时内须响应。\n"
               "五、快递服务:各校区快递服务站位于生活区商业街，取件需凭取件码，"
               "大件物品可预约送货到楼，贵重物品须本人签收。\n"
               "六、以上服务事项如有调整，以各主管部门最新通知为准。")
    assert quality_gate_reject("", "校园便民服务指南", article) is None, "正文页不应被 index_page 误伤"
    assert is_index_page(article) is None
    print(f"[U7] 导航/索引页判据 OK(真实样本 short={st['short_ratio']:.0%}/long={st['long_ratio']:.0%} 被拒;"
          f"正文页放行)")


class _FixtureHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = FIXTURE_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静默
        pass


def _cleanup_smoke_docs(c: httpx.Client, token: str) -> list[int]:
    """按标题清单删除冒烟相关文档,返回**真正删掉**的 id 列表(删不掉的只告警)。

    第 5 回⑩:这份清理既服务 `--cleanup`,也服务 `--cleanup-only` 与 finally 收尾 ——
    旧版它是 `--cleanup` 分支里的一段内联代码,只有走正常路径才轮得到它。
    """
    docs = c.get(f"{BASE}/api/kb/documents", headers=auth(token)).json()["documents"]
    ids = [d["id"] for d in docs if d["title"] in LEGACY_TITLES]
    removed: list[int] = []
    for did in ids:
        r = c.delete(f"{BASE}/api/kb/documents/{did}", headers=auth(token))
        if r.status_code == 200:
            removed.append(did)
        else:
            print(f"[warn] 清理 doc_id={did} 失败: HTTP {r.status_code} {r.text[:80]}")
    return removed


def main() -> int:
    global BASE  # P4e M5 ②: --base 改写模块级 BASE(各检查函数共用)
    ap = argparse.ArgumentParser()
    ap.add_argument("--cleanup", action="store_true", help="清理历史残留的冒烟测试文档后继续")
    ap.add_argument("--cleanup-only", action="store_true",
                    help="**只清理不跑完整套**:清完打印删掉的 id 与语料计数即退出(第 5 回⑩)")
    ap.add_argument("--base", default=BASE,
                    help="被测服务地址(须与 run_with_server.sh 起的端口一致)")
    args = ap.parse_args()
    BASE = args.base.rstrip("/")

    with httpx.Client(timeout=180) as c:
        admin = login(c, "admin", "admin123")
        counselor = login(c, "counselor", "counselor123")
        student = login(c, "student", "student123")
        print(f"[1] 三角色登录 OK: {admin['role']}/{counselor['role']}/{student['role']}")

        def doc_count() -> int:
            r = c.get(f"{BASE}/api/kb/documents", headers=auth(admin["token"]))
            r.raise_for_status()
            return len(r.json()["documents"])

        if args.cleanup or args.cleanup_only:
            legacy = _cleanup_smoke_docs(c, admin["token"])
            print(f"[0] 清理历史残留 {len(legacy)} 篇: {legacy}")
            if args.cleanup_only:
                docs_now = c.get(f"{BASE}/api/kb/documents",
                                 headers=auth(admin["token"])).json()["documents"]
                chunks_now = sum(int(d.get("chunk_count") or 0) for d in docs_now)
                print(f"[0] --cleanup-only 只清理不跑完整套: "
                      f"documents={len(docs_now)} chunks={chunks_now}")
                return 0

        # ⚠ 这两个变量必须在 try **之前**定义:只要进了 try,finally 就一定会执行,
        #   而 finally 要读它们。若定义在 try 内且中途炸在更早的位置(例如第一个
        #   上传就 500),finally 引用未绑定的局部变量会抛 UnboundLocalError,
        #   **把真正的失败原因盖掉** —— 收尾逻辑绝不能掩盖根因(实测踩到过一次)。
        count_before = doc_count()
        uploaded_ids: list[int] = []  # P4a C5: 本次冒烟产生的 doc_id 全量登记,结束时删除
        print(f"[KB 守恒] 起始 documents={count_before}")
        try:
            # 权限边界:学生不能上传 / 不能看辅导员级文档
            r = c.post(f"{BASE}/api/kb/upload", headers=auth(student["token"]),
                       files={"file": ("x.md", io.BytesIO(b"test"), "text/markdown")})
            assert r.status_code == 403, f"学生上传应 403,得到 {r.status_code}"
            print("[2] 学生上传被拒(403)OK")

            files = {"file": ("学籍管理规定-测试.md", io.BytesIO(SAMPLE_MD.encode()), "text/markdown")}
            r = c.post(f"{BASE}/api/kb/upload", headers=auth(counselor["token"]),
                       files=files, data={"role_min": "counselor"})
            r.raise_for_status()
            chunks = r.json()["chunks"]
            uploaded_ids.append(r.json()["doc_id"])
            assert chunks >= 1
            print(f"[3] 辅导员上传 OK(切分 {chunks} 块,辅导员级可见)")

            r = c.get(f"{BASE}/api/kb/documents", headers=auth(student["token"]))
            titles = [d["title"] for d in r.json()["documents"]]
            assert all("学籍管理规定-测试" != t for t in titles), f"学生不应看到辅导员级文档: {titles}"
            r2 = c.get(f"{BASE}/api/kb/documents", headers=auth(counselor["token"]))
            assert any("学籍管理规定-测试" in t for t in [d["title"] for d in r2.json()["documents"]])
            print("[4] 文档可见性 OK(学生不可见,辅导员可见)")

            # RAG:学生问学籍问题(可见范围 student 级)——先传一份学生级文档
            files2 = {"file": ("学籍管理规定-学生版.md", io.BytesIO(SAMPLE_MD.encode()), "text/markdown")}
            r = c.post(f"{BASE}/api/kb/upload", headers=auth(counselor["token"]),
                       files=files2, data={"role_min": "student"})
            r.raise_for_status()
            uploaded_ids.append(r.json()["doc_id"])
            r = c.post(f"{BASE}/api/chat", headers=auth(student["token"]),
                       json={"question": "研究生申请休学需要哪些材料和审批步骤?"})
            r.raise_for_status()
            d = r.json()
            assert d["answer"] and d["sources"], f"应带引用回答: {d}"
            assert any("休学" in s["content"] or "申请" in s["content"] for s in d["sources"])
            print(f"[5] 学生 RAG 问答 OK(引用 {len(d['sources'])} 条,含 [n] 标注)")
            print(f"    答案节选: {d['answer'][:80]}...")

            # 周报:直调 REST → MCP
            # ⚠ 这里**显式传 summary**:谈心谈话保存时若摘要为空,服务端会自动调一次 LLM
            #   生成摘要 —— 冒烟不该为摘要这件事扣额度,所以把摘要给定住。
            r = c.post(f"{BASE}/api/weekly/fragments", headers=auth(counselor["token"]),
                       json={"content": "与姓名1同学谈话,反馈补考压力,已转介心理中心",
                             "category": "谈心谈话", "occurred_at": "2026-09-25",
                             "student_name": "姓名1",
                             "summary": "就该学生心理健康情况进行谈心谈话"})
            r.raise_for_status()
            assert r.json()["ok"]
            # 永久闸门:谈心谈话缺学生姓名必须被拒(400),而不是静默存一条没名字的台账
            r = c.post(f"{BASE}/api/weekly/fragments", headers=auth(counselor["token"]),
                       json={"content": "与某同学谈了职业规划", "category": "谈心谈话",
                             "occurred_at": "2026-09-25", "summary": "就该学生职业规划情况进行谈心谈话"})
            assert r.status_code == 400, f"谈心谈话缺姓名应 400,得到 {r.status_code}"
            # 对照:非谈心谈话分类不要求姓名(事务办理没有"某个学生"这个对象)
            r = c.post(f"{BASE}/api/weekly/fragments", headers=auth(counselor["token"]),
                       json={"content": "代办了休学手续", "category": "事务办理",
                             "occurred_at": "2026-09-25"})
            assert r.status_code == 200, f"事务办理不要求姓名,得到 {r.status_code}"
            assert r.json()["ok"]
            r = c.post(f"{BASE}/api/weekly/report", headers=auth(counselor["token"]),
                       json={"start_date": "2026-09-21", "end_date": "2026-09-27"})
            r.raise_for_status()
            assert r.json()["ok"] and "谈心谈话" in r.json()["report_markdown"]
            print("[6] 周报记录+生成 OK(经 MCP;姓名必填闸门与分类对照已验)")

            # 学生不应能访问周报
            r = c.post(f"{BASE}/api/weekly/report", headers=auth(student["token"]),
                       json={"start_date": "2026-09-21"})
            assert r.status_code == 403, f"学生访问周报应 403,得到 {r.status_code}"
            print("[7] 学生访问周报被拒(403)OK")

            # 知识库分块查看:学生可看学生级文档分块,不可看辅导员级文档
            docs = c.get(f"{BASE}/api/kb/documents", headers=auth(counselor["token"])).json()["documents"]
            student_doc = next(d for d in docs if d["title"] == "学籍管理规定-学生版")
            counselor_doc = next(d for d in docs if d["title"] == "学籍管理规定-测试")
            assert student_doc["chunk_count"] >= 1
            r = c.get(f"{BASE}/api/kb/documents/{student_doc['id']}/chunks", headers=auth(student["token"]))
            r.raise_for_status()
            assert r.json()["chunks"], "分块不应为空"
            r = c.get(f"{BASE}/api/kb/documents/{counselor_doc['id']}/chunks", headers=auth(student["token"]))
            assert r.status_code == 404, f"学生查看辅导员级文档分块应 404,得到 {r.status_code}"
            print("[8] 分块查看 OK(学生可看学生级;辅导员级 404 不可见)")

            # 工作记录:筛选 + 分类过滤 + 学生 403
            r = c.get(f"{BASE}/api/weekly/fragments?category=谈心谈话", headers=auth(counselor["token"]))
            r.raise_for_status()
            d = r.json()
            assert d["fragments"] and all(f["category"] == "谈心谈话" for f in d["fragments"])
            assert d["stats"].get("谈心谈话", 0) >= 1
            fid = d["fragments"][0]["id"]
            r = c.get(f"{BASE}/api/weekly/fragments", headers=auth(student["token"]))
            assert r.status_code == 403
            print(f"[9] 记录筛选 OK({d['stats']}),学生访问记录 403 OK")

            # 按月导出谈心谈话(CSV):不调 LLM,可放心在冒烟里跑
            r = c.get(f"{BASE}/api/weekly/records/export?month=2026-09",
                      headers=auth(counselor["token"]))
            assert r.status_code == 200, f"按月导出应 200,得到 {r.status_code}"
            assert r.content.startswith("﻿".encode("utf-8")), "CSV 必须带 UTF-8 BOM(否则 Excel 中文乱码)"
            cd = r.headers.get("content-disposition", "")
            assert "attachment" in cd and "filename*=UTF-8''" in cd, f"下载头不完整: {cd!r}"
            rows = r.content.decode("utf-8-sig").strip().splitlines()
            assert rows and "谈心谈话记录" in rows[0], f"表头缺失: {rows[:1]}"
            assert all("进行谈心谈话" in x or "未生成摘要" in x or "姓名" in x for x in rows[1:]), \
                f"导出行既不是台账整句也没有占位标记: {rows[1:3]}"
            n_export = len(rows) - 1
            r = c.get(f"{BASE}/api/weekly/records/export?month=2026-13",
                      headers=auth(counselor["token"]))
            assert r.status_code == 400, f"非法 month 应 400,得到 {r.status_code}"
            r = c.get(f"{BASE}/api/weekly/records/export?month=2026-09",
                      headers=auth(student["token"]))
            assert r.status_code == 403, f"学生导出工作记录应 403,得到 {r.status_code}"
            print(f"[9a] 按月导出 OK({n_export} 行 CSV 带 BOM;非法月份 400;学生 403)")

            # 会议纪要:列表/详情走 MCP 存取,不调 LLM(整理与转写要花钱,不在冒烟里跑)
            r = c.get(f"{BASE}/api/weekly/minutes", headers=auth(counselor["token"]))
            assert r.status_code == 200 and "minutes" in r.json(), \
                f"纪要列表应 200 且带 minutes,得到 {r.status_code}"
            r = c.get(f"{BASE}/api/weekly/minutes/999999", headers=auth(counselor["token"]))
            assert r.status_code == 404, f"不存在的纪要应 404,得到 {r.status_code}"
            r = c.get(f"{BASE}/api/weekly/minutes", headers=auth(student["token"]))
            assert r.status_code == 403, f"学生访问会议纪要应 403,得到 {r.status_code}"
            print("[9b] 会议纪要存取 OK(列表/404/学生 403;整理与转写不在冒烟内)")

            # 归档周报列表与详情
            r = c.get(f"{BASE}/api/weekly/reports", headers=auth(counselor["token"]))
            r.raise_for_status()
            reports = r.json()["reports"]
            assert reports, "应有归档周报"
            r = c.get(f"{BASE}/api/weekly/reports/{reports[0]['id']}", headers=auth(counselor["token"]))
            r.raise_for_status()
            assert r.json()["content_md"]
            print(f"[10] 归档周报列表/详情 OK({len(reports)} 篇)")

            # 删除测试记录
            r = c.delete(f"{BASE}/api/weekly/fragments/{fid}", headers=auth(counselor["token"]))
            r.raise_for_status()
            assert r.json()["ok"]
            print("[11] 记录删除 OK")

            # 知识库分类:上传带分类 → 筛选生效
            r = c.post(f"{BASE}/api/kb/upload", headers=auth(counselor["token"]),
                       files={"file": ("分类测试-运维手册.md", io.BytesIO(OPS_MD.encode()), "text/markdown")},
                       data={"role_min": "admin", "category": "运维手册"})
            r.raise_for_status()
            uploaded_ids.append(r.json()["doc_id"])
            assert r.json()["category"] == "运维手册"
            r = c.get(f"{BASE}/api/kb/documents?category=运维手册", headers=auth(admin["token"]))
            assert any(d["title"] == "分类测试-运维手册" for d in r.json()["documents"])
            assert "运维手册" in r.json()["categories"]
            print("[12] 知识库分类 OK(上传+筛选)")

            # 个人设置:模型列表 + 切换 + 对话使用设置模型(仅验证接口层)
            #
            # P4f 第3 回③:模型名**不得写死**。原实现硬编码 `qwen-flash`,而下一步的
            # `/api/weekly/expand` 会真的用这个模型名去生成 —— 于是「换通道」与「冒烟」
            # 互斥:走 OpenRouter 等非 DashScope 通道时上游 400,冒烟 exit 1
            # (Qoder 实测两次:清掉 user_settings 后崩在 /api/weekly/expand)。
            # 现在从**配置**取,并允许 NOVA_SMOKE_MODEL 覆盖;反向断言(bad-model → 400)保留。
            #
            # P4f 第 5 回⑨:**判据换掉了**。上一版在这里 `assert smoke_model in _cands`,
            # 而 `_cands` 是 MODEL_CANDIDATES —— **内置 DashScope 的候选清单**。
            # 于是只要换了通道(恰恰是额度纪律要求的能力),第 13 步必炸:
            # Qoder 实测 `NOVA_SMOKE_MODEL='qwen/qwen-plus'` 在 `:8973`/`:8974` 连炸两次。
            # 旧版那条「检测到 custom 就跳过」的分支覆盖不到「全局 config 指向非候选模型」,
            # 所以判据改成「**当前通道是不是内置通道**」(见 `plan_step13`,纯函数、可离线断言);
            # 非内置通道打印 `[13][skip]` 并跳过,**不 assert 炸**。
            from novaagent import config as _cfg
            _cands = [m["id"] for m in _cfg.MODEL_CANDIDATES]
            assert _cands, "C13 前置:MODEL_CANDIDATES 非空(否则下一步无从选模型)"
            # 覆盖优先级:环境变量 > 配置首个候选(= 默认档)
            smoke_model = os.environ.get("NOVA_SMOKE_MODEL") or _cfg.LLM_MODEL or _cands[0]
            _settings0 = c.get(f"{BASE}/api/me/settings", headers=auth(counselor["token"]))
            _settings0.raise_for_status()
            _sj = _settings0.json()
            _plan = plan_step13(base_url=_cfg.LLM_BASE_URL,
                                custom_enabled=bool((_sj.get("custom") or {}).get("enabled")),
                                smoke_model=smoke_model, candidates=_cands)
            if _plan["action"] == "switch":
                assert smoke_model in _cands, (
                    f"内置通道上 NOVA_SMOKE_MODEL={smoke_model!r} 不在候选 {_cands} 内 —— "
                    f"换模型请改它或清掉 NOVA_SMOKE_MODEL")
                r = c.put(f"{BASE}/api/me/settings", headers=auth(counselor["token"]),
                          json={"model": smoke_model})
                r.raise_for_status()
                r = c.get(f"{BASE}/api/me/settings", headers=auth(counselor["token"]))
                r.raise_for_status()
                models = [m["id"] for m in r.json()["candidates"]]
                assert models, "C13 前置:candidates 列表非空(防空集假通过)"
                # 反向断言必须保留:传一个不存在的模型名要被拒(非法模型不得静默落库)。
                # 它验的是 **API 校验**,不是通道 —— 故留在这条内置分支里。
                r = c.put(f"{BASE}/api/me/settings", headers=auth(counselor["token"]),
                          json={"model": "bad-model"})
                assert r.status_code == 400, f"非法模型应 400,得到 {r.status_code}"
                # 坑 66:这一步会把 user_settings.model 写下去,**必须还原** ——
                #   留着就等于「测试把环境状态改了」,下一次跑评测会带着上一次的模型,
                #   报告里 env_flags.server.llm_model 与实际请求模型不一致(坑 66)。
                _orig = _sj.get("model")
                _restore = {"model": _orig} if _orig else {"model": ""}
                r = c.put(f"{BASE}/api/me/settings", headers=auth(counselor["token"]),
                          json=_restore)
                r.raise_for_status()
                _now = c.get(f"{BASE}/api/me/settings", headers=auth(counselor["token"])).json()
                assert _now.get("model") == _orig, (
                    f"user_settings.model 未还原:期望 {_orig!r},实得 {_now.get('model')!r}")
                print(f"[13] 模型设置 OK(合法切换/非法拒绝;已还原 model={_orig!r},"
                      f"本轮切换用 {smoke_model!r})")
            else:
                print(f"[13][skip] {_plan['reason']} —— 内置模型切换断言不适用,整步跳过")

            # AI 扩充:LLM 生成草稿(容忍波动,只验非空与接口链路)
            r = c.post(f"{BASE}/api/weekly/expand", headers=auth(counselor["token"]),
                       json={"content": "和小王谈了补考压力,已转介心理中心", "category": "谈心谈话"})
            r.raise_for_status()
            exp = r.json()["expanded"]
            assert len(exp) > len("和小王谈了补考压力,已转介心理中心"), "扩充应长于原文"
            print(f"[14] AI 扩充 OK(草稿 {len(exp)} 字)")

            # 摘要:上传接口返回 summary 且写库(查 chunks 接口)
            r = c.post(f"{BASE}/api/kb/upload", headers=auth(counselor["token"]),
                       files={"file": ("摘要测试-请假办法.md",
                                       io.BytesIO(SUMMARY_MD.encode()),
                                       "text/markdown")},
                       data={"role_min": "student", "category": "学生事务"})
            r.raise_for_status()
            d = r.json()
            assert d.get("summary"), "上传应返回 AI 摘要"
            doc_id = d["doc_id"]
            uploaded_ids.append(doc_id)
            r = c.get(f"{BASE}/api/kb/documents/{doc_id}/chunks", headers=auth(student["token"]))
            assert r.json()["document"]["summary"] == d["summary"]
            print(f"[15] 文档摘要 OK: {d['summary'][:40]}...")

            # P4a: 网页导入质量门回归——自家前端/计财处首页必须被拦(禁抓页不发起抓取)
            # P4e M5 ②: `f"{BASE}/"` 跟随 --base,不再依赖硬编码 8900。此前服务跑在 :8905 时
            # 这条会落到 index_page 判据 → 期望 deny_url 实得 index_page(**假红**),
            # 而质量门代码一行没变——说明"自家前端禁抓"是**端口绑定**的。
            # 根因已在 main.py 修掉(禁抓判定纳入**运行时 origin**),故在任意端口上都应判 deny_url;
            # 本条因此同时充当该修复的回归闸门。
            for denied in ("https://cwc.swjtu.edu.cn/", f"{BASE}/"):
                r = c.post(f"{BASE}/api/kb/import_url", headers=auth(counselor["token"]),
                           json={"url": denied, "role_min": "counselor"})
                assert r.status_code == 400, f"{denied} 应被质量门拦截,得到 {r.status_code}"
                assert r.json()["detail"]["code"] == "deny_url", r.json()
            # P4a-1: 导航/索引页回归(真实站点,结构判据在抓取后生效)——须被拦且 code=index_page
            r = c.post(f"{BASE}/api/kb/import_url", headers=auth(counselor["token"]),
                       json={"url": "https://infpub.swjtu.edu.cn/gksx/cw_zcjsfxx/sfxm_sfyj_sfbzjtsfs.htm",
                             "role_min": "counselor"})
            assert r.status_code == 400, f"索引页应被质量门拦截,得到 {r.status_code}"
            assert r.json()["detail"]["code"] == "index_page", r.json()
            print("[16a] 导入质量门回归 OK(cwc 首页/自家前端 → deny_url;infpub 导航索引页 → index_page)")

            # P4a: 网页导入正路径——本地 fixture(不依赖运行中页面,根除 smoke 污染源)
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                fixture_url = f"http://127.0.0.1:{srv.server_address[1]}/guide.html"
                r = c.post(f"{BASE}/api/kb/import_url", headers=auth(counselor["token"]),
                           json={"url": fixture_url, "role_min": "counselor", "category": "工作制度"})
                r.raise_for_status()
                d = r.json()
                uploaded_ids.append(d["doc_id"])
                assert d["chunks"] >= 1 and d["summary"]
                print(f"[16b] 网页导入 OK(本地夹具):《{d['title']}》{d['chunks']} 块")
            finally:
                srv.shutdown()

            # 辅导员删除(可见文档) + 自定义 API 设置往返
            r = c.delete(f"{BASE}/api/kb/documents/{doc_id}", headers=auth(counselor["token"]))
            r.raise_for_status()
            uploaded_ids.remove(doc_id)  # 已删,不重复
            r = c.put(f"{BASE}/api/me/settings", headers=auth(counselor["token"]),
                      json={"custom": {"model": "test-model", "base_url": "https://example.com/v1", "api_key": "sk-test"}})
            r.raise_for_status()
            r = c.get(f"{BASE}/api/me/settings", headers=auth(counselor["token"]))
            assert r.json()["custom"]["enabled"] is True and r.json()["custom"]["api_key_set"] is True
            r = c.put(f"{BASE}/api/me/settings", headers=auth(counselor["token"]),
                      json={"custom": {"model": "", "base_url": "", "api_key": ""}})
            r.raise_for_status()
            # 关闭自定义后必须回落到**全局配置档**,不能写死 qwen-flash ——
            # 换通道(config.LLM_MODEL 被环境变量改成别的)时这行会假红(坑 66 同源:
            # 报告/断言自证的模型 ≠ 实际生效的模型)。
            assert r.json()["effective_model"] == _cfg.LLM_MODEL, (
                f"关闭自定义后 effective_model 应回落全局配置 {_cfg.LLM_MODEL!r},"
                f"实得 {r.json()['effective_model']!r}")
            r = c.put(f"{BASE}/api/me/settings", headers=auth(counselor["token"]),
                      json={"custom": {"model": "m", "base_url": "https://x/v1", "api_key": ""}})
            assert r.status_code == 400, "缺 Key 的自定义配置应 400"
            print("[17] 自定义 API 设置 OK(启用/关闭/校验)")
        # P4a C5 / 第 5 回⑩: 自清理 + KB 计数守恒断言 —— **放进 finally**。
        # 旧版 [18] 写在正常路径末尾,中途任何 assert/异常都不会执行到,于是
        # 「每跑一次失败的冒烟就往 KB 里留 3 篇脏文档」(Qoder 第 5 回实测
        # 65/487 → 68/490 连着三轮,每轮手工清)。失败路径才更需要自清理。
        finally:
            removed: list[int] = []
            for did in list(uploaded_ids):
                try:
                    r = c.delete(f"{BASE}/api/kb/documents/{did}", headers=auth(admin["token"]))
                    if r.status_code == 200:
                        removed.append(did)
                    else:
                        print(f"[warn] 收尾删除 doc_id={did} 失败: HTTP {r.status_code} {r.text[:80]}")
                except Exception as e:  # noqa: BLE001  收尾不得盖掉真正的失败原因
                    print(f"[warn] 收尾删除 doc_id={did} 抛异常: {type(e).__name__}: {e}")
            try:
                count_after = doc_count()
            except Exception as e:  # noqa: BLE001
                count_after = None
                print(f"[warn] 收尾读 documents 计数失败: {type(e).__name__}: {e}")
            leftover = [d for d in uploaded_ids if d not in removed]
            print(f"[18] 自清理(finally)删除 {len(removed)} 篇冒烟文档: {removed}"
                  + (f" **残留 {leftover}**" if leftover else "")
                  + f"; KB 计数 {count_before} → {count_after}")
        # ⚠ 守恒断言留在**正常路径**:能走到这一步说明整套步骤没炸,此时计数必须回到起点;
        #   失败时异常已在上抛(自清理已在 finally 里跑过),不需要它再判一次。
        assert count_after == count_before, \
            f"KB 计数不守恒: 起始 {count_before} → 结束 {count_after}(残留 {uploaded_ids})"
        print(f"[18] KB 计数守恒: {count_before} → {count_after}")

    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    unit_tests()
    sys.exit(main())
