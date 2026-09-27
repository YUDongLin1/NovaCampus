"""NovaAgent 冒烟测试:三角色权限边界 + RAG 引用 + 周报工具(直调 REST)

前置:weekly-mcp 容器已运行(18080),服务端已启动(uvicorn novaagent.main:app --port 8900)
用法:NO_PROXY="127.0.0.1,localhost" python tests/smoke_test.py
"""
import io
import sys

import httpx

BASE = "http://127.0.0.1:8900"
SAMPLE_MD = """# 研究生学籍管理规定(测试样例)

第一条 为规范研究生学籍管理,制定本规定。
第二条 研究生最长学习年限为六年,超过者应予退学。
第三条 学生申请休学应提交书面申请、医院证明,经导师和培养单位同意后报研究生院审批。
第四条 本规定仅限测试使用。

# 教师内部备忘(仅辅导员可见)

内部提示:退学预警名单每周一由研究生院下发,辅导员应在 3 个工作日内完成约谈。
"""


def login(client: httpx.Client, username: str, password: str) -> dict:
    r = client.post(f"{BASE}/api/login", json={"username": username, "password": password})
    r.raise_for_status()
    return r.json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def main() -> int:
    with httpx.Client(timeout=180) as c:
        admin = login(c, "admin", "admin123")
        counselor = login(c, "counselor", "counselor123")
        student = login(c, "student", "student123")
        print(f"[1] 三角色登录 OK: {admin['role']}/{counselor['role']}/{student['role']}")

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
        c.post(f"{BASE}/api/kb/upload", headers=auth(counselor["token"]),
               files=files2, data={"role_min": "student"}).raise_for_status()
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
                   files={"file": ("分类测试-运维手册.md", io.BytesIO("# 运维手册测试\n连接池耗尽时重启服务。".encode()), "text/markdown")},
                   data={"role_min": "admin", "category": "运维手册"})
        r.raise_for_status()
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
        sample_txt = "# 请假办法测试\n第一条 学生请假3天以内由辅导员审批。\n第二条 病假需附医院证明。"
        r = c.post(f"{BASE}/api/kb/upload", headers=auth(counselor["token"]),
                   files={"file": ("摘要测试-请假办法.md",
                                   io.BytesIO(sample_txt.encode()),
                                   "text/markdown")},
                   data={"role_min": "student", "category": "学生事务"})
        r.raise_for_status()
        d = r.json()
        assert d.get("summary"), "上传应返回 AI 摘要"
        doc_id = d["doc_id"]
        r = c.get(f"{BASE}/api/kb/documents/{doc_id}/chunks", headers=auth(student["token"]))
        assert r.json()["document"]["summary"] == d["summary"]
        print(f"[15] 文档摘要 OK: {d['summary'][:40]}...")

        # 网页导入:导入 NovaAgent 自身页面(本地可达、script 已被提取器跳过)
        r = c.post(f"{BASE}/api/kb/import_url", headers=auth(counselor["token"]),
                   json={"url": f"{BASE}/", "role_min": "counselor", "category": "工作制度"})
        r.raise_for_status()
        d = r.json()
        assert d["chunks"] >= 1 and d["summary"]
        print(f"[16] 网页导入 OK:《{d['title']}》{d['chunks']} 块")

        # 辅导员删除(可见文档) + 自定义 API 设置往返
        r = c.delete(f"{BASE}/api/kb/documents/{doc_id}", headers=auth(counselor["token"]))
        r.raise_for_status()
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

    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
