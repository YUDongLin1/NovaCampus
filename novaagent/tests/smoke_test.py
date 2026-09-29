"""NovaAgent 冒烟测试:三角色权限边界 + RAG 引用 + 周报工具(直调 REST)

P4a 增补:导入质量门纯函数单测(口令三样式/登录页/敏感/名单/禁抓回归)+ KB 计数守恒 +
上传自清理(fixture 本地导入替代自家前端首页,根除 smoke 污染,坑 23/24)。

前置:weekly-mcp 容器已运行(18080),服务端已启动(uvicorn novaagent.main:app --port 8900)
用法:NO_PROXY="127.0.0.1,localhost" python tests/smoke_test.py [--cleanup]
  --cleanup: 额外清理历史残留(旧版冒烟上传且未删的测试文档),跑完打印清理数。
验收口径:跑完 documents 计数必须与起始一致(守恒断言在本文件内)。
"""
import argparse
import http.server
import io
import sys
import threading
from pathlib import Path

import httpx

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

LEGACY_TITLES = ["学籍管理规定-测试", "学籍管理规定-学生版", "分类测试-运维手册", "摘要测试-请假办法"]


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cleanup", action="store_true", help="清理历史残留的冒烟测试文档后继续")
    args = ap.parse_args()

    with httpx.Client(timeout=180) as c:
        admin = login(c, "admin", "admin123")
        counselor = login(c, "counselor", "counselor123")
        student = login(c, "student", "student123")
        print(f"[1] 三角色登录 OK: {admin['role']}/{counselor['role']}/{student['role']}")

        def doc_count() -> int:
            r = c.get(f"{BASE}/api/kb/documents", headers=auth(admin["token"]))
            r.raise_for_status()
            return len(r.json()["documents"])

        if args.cleanup:
            docs = c.get(f"{BASE}/api/kb/documents", headers=auth(admin["token"])).json()["documents"]
            legacy = [d["id"] for d in docs if d["title"] in LEGACY_TITLES]
            for did in legacy:
                r = c.delete(f"{BASE}/api/kb/documents/{did}", headers=auth(admin["token"]))
                r.raise_for_status()
            print(f"[0] --cleanup 清理历史残留 {len(legacy)} 篇: {legacy}")

        count_before = doc_count()
        uploaded_ids: list[int] = []  # P4a C5: 本次冒烟产生的 doc_id 全量登记,结束时删除
        print(f"[KB 守恒] 起始 documents={count_before}")

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
        r = c.post(f"{BASE}/api/weekly/fragments", headers=auth(counselor["token"]),
                   json={"content": "与姓名1同学谈话,反馈补考压力,已转介心理中心",
                         "category": "谈心谈话", "occurred_at": "2026-09-25"})
        r.raise_for_status()
        assert r.json()["ok"]
        r = c.post(f"{BASE}/api/weekly/report", headers=auth(counselor["token"]),
                   json={"start_date": "2026-09-21", "end_date": "2026-09-27"})
        r.raise_for_status()
        assert r.json()["ok"] and "谈心谈话" in r.json()["report_markdown"]
        print("[6] 周报记录+生成 OK(经 MCP)")

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
        r = c.get(f"{BASE}/api/me/settings", headers=auth(counselor["token"]))
        r.raise_for_status()
        models = [m["id"] for m in r.json()["candidates"]]
        assert "qwen-flash" in models
        r = c.put(f"{BASE}/api/me/settings", headers=auth(counselor["token"]), json={"model": "qwen-flash"})
        r.raise_for_status()
        r = c.put(f"{BASE}/api/me/settings", headers=auth(counselor["token"]), json={"model": "bad-model"})
        assert r.status_code == 400, "非法模型应 400"
        print("[13] 模型设置 OK(合法切换/非法拒绝)")

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
        assert r.json()["effective_model"] == "qwen-flash"
        r = c.put(f"{BASE}/api/me/settings", headers=auth(counselor["token"]),
                  json={"custom": {"model": "m", "base_url": "https://x/v1", "api_key": ""}})
        assert r.status_code == 400, "缺 Key 的自定义配置应 400"
        print("[17] 自定义 API 设置 OK(启用/关闭/校验)")

        # P4a C5: 自清理 + KB 计数守恒断言
        removed = []
        for did in uploaded_ids:
            r = c.delete(f"{BASE}/api/kb/documents/{did}", headers=auth(admin["token"]))
            if r.status_code == 200:
                removed.append(did)
        count_after = doc_count()
        assert count_after == count_before, \
            f"KB 计数不守恒: 起始 {count_before} → 结束 {count_after}(残留 {uploaded_ids})"
        print(f"[18] 自清理 OK(删除 {len(removed)} 篇冒烟文档),KB 计数守恒: {count_before} → {count_after}")

    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    unit_tests()
    sys.exit(main())
