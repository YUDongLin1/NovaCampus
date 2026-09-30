#!/usr/bin/env python3
"""NovaAgent 评测引擎 v1 — 对接 /api/* 执行评测集

用例类型:
  qa                    检索问答:回答须命中 expect_keywords 且有引用
  refusal               拒答:回答须明示"知识库未覆盖"或无引用
  permission_api        API 权限:期待指定 HTTP 状态码(403/404)
  kb_hidden             知识层权限:回答不得引用 hidden_marker 文档
  ---- P4b-fix ③ 新增(新代码路径覆盖,坑 22) ----
  multiturn             多轮:turns[].question 逐轮携带 conversation_id;末轮答案命中
                        expect_keywords,expect_context 断言 history_gate=hit 等门控标志
  context_compress      压缩:case.plant{turns,chars,facts} 经 API 种植超预算历史,
                        末轮断言 expect_context.compressed=true 且关键数字仍在答案
  refusal_followup      有历史+域内无据追问 → 必须走 build_refusal 确定性模板
                        (「系统模板生成」指纹 + expect_absent_keywords 禁自拟出口)
  history_false_premise 用户断言假事实 → 不得复述其金额/渠道/经办人(expect_absent_keywords)

用法:NO_PROXY="127.0.0.1,localhost" python run_evals.py [--base http://127.0.0.1:8900]
前置:NovaAgent 与 weekly-mcp 已启动。语料缺失时自动以 counselor 身份播种 seed_corpus/。
报告:reports/eval_report_<时间戳>.json;评测隔离断言(全量)失败 → 退出码非 0(P4b-fix ②)。
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

try:  # Windows GBK 控制台防 emoji 编码崩溃(T2 同款修复, 独立于 PYTHONIOENCODING)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

import faithfulness  # LLM-as-judge:复用 novaagent 模型配置(只读导入)

BASE = "http://127.0.0.1:8900"
HERE = Path(__file__).parent
SEED_ROLES = {
    "EVAL-研究生学籍管理规定.md": "student",
    "EVAL-研究生奖学金评定办法.md": "student",
    "EVAL-学生请假管理办法.md": "student",
    "EVAL-辅导员内部工作备忘.md": "counselor",
}
REFUSAL_MARKS = ("暂无", "没有找到", "未检索", "知识库中未", "无法回答", "不在知识库", "没有相关")

# P4d-fix ④（假阳性修复）：非答案检测用的免责措辞与阈值。
# NON_ANSWER_MARKS 与 REFUSAL_MARKS 有意重叠但更宽——它要抓的是"答案自认没答"
# （如「未在知识库覆盖」「请以…为准」），而 REFUSAL_MARKS 只服务于拒答判定。
NON_ANSWER_MARKS = (
    "未在知识库", "未检索到", "没有检索到", "未覆盖", "没有覆盖", "未收录", "未包含",
    "知识库中未", "暂无", "没有找到", "无法回答", "不在知识库", "没有相关",
    "请以", "建议咨询", "请咨询", "无法提供", "以学校现行", "以研究生主管部门", "以保卫处",
)
# 阈值依据实测（docs/p4d/evidence/after/answers_facts.json）：
#   真非答案 qa-12 → 全文 45 字 / 剥离免责后实质 0 / **零引用标记**
#   真答案   rind-02 → 全文 571 / 实质 505 / 有 [1][2][3] 引用标记 + 数字 448/2012/2016
#   真答案   qa-13  → 全文 702 / 实质 597 / 有 [1][3] 引用标记
# 单靠长度分不开「实质 28 字的短答案」与「实质 0 的非答案」，故用**双条件**：
#   命中免责措辞 **且** (实质内容 < 阈值 **或** 零可核查事实) → 判非答案。
# 「可核查事实」= 引用标记 [n] 或具体数字（金额/年限/电话/绩点）。
# 阈值 80：远高于实测非答案 0、远低于实测真答案 505/597，两侧留足余量。
NON_ANSWER_MIN_SUBSTANTIVE = 80
_FACTUAL = re.compile(r"\[\d+\]|\d")


def substantive_len(answer: str) -> int:
    """剥离免责措辞后的"实质内容"长度（字符数）。

    两级剥离，**顺序固定并由自测覆盖**（第一版只做整行剥离，实测误伤"实质内容与免责句
    同处一行"的正常答案——那种整行被当成免责行删掉，substantive_len 归 0 → 真答案被
    误判为非答案）：
      1. **句级**：按中英文标点切句，逐句丢弃"整句都是免责措辞且不含数字"的句子
        （含数字的免责句是事实，如「2026 年度缴费 448 元」）；
      2. **行级**：剩下的行若整行都是免责措辞且很短（<=120），再丢整行。
    """
    sents = re.split(r"(?<=[。；;\n])", answer)
    kept_sents = []
    for s in sents:
        t = s.strip().lstrip(">*-—·• ").strip()
        if not t:
            continue
        # 保留句：含数字 **或含引用标记 [n]**（两者都是"可核查事实"的载体；
        # 第一版没保留 [n]，实测把「…需出院证、诊断证明书等材料[1]」整句删掉 → 实质长度归零）
        if any(m in t for m in NON_ANSWER_MARKS) and not _FACTUAL.search(t) and len(t) <= 120:
            continue
        kept_sents.append(t)
    kept = 0
    for line in "\n".join(kept_sents).splitlines():
        s = line.strip().lstrip(">*-—·• ").strip()
        if not s:
            continue
        if any(m in s for m in NON_ANSWER_MARKS) and len(s) <= 120 and not _FACTUAL.search(s):
            continue
        kept += len(s)
    return kept


def login(c: httpx.Client, username: str, password: str) -> str:
    r = c.post(f"{BASE}/api/login", json={"username": username, "password": password})
    r.raise_for_status()
    return r.json()["token"]


def seed_corpus_if_needed(c: httpx.Client, counselor_token: str) -> int:
    """按标题前缀 EVAL- 检查是否已播种,缺哪个补哪个。返回本次上传数。"""
    docs = c.get(f"{BASE}/api/kb/documents", headers={"Authorization": f"Bearer {counselor_token}"}).json()
    existing = {d["title"] for d in docs["documents"]}
    uploaded = 0
    for fname, role_min in SEED_ROLES.items():
        title = fname.rsplit(".", 1)[0]
        if title in existing:
            continue
        path = HERE / "seed_corpus" / fname
        r = c.post(
            f"{BASE}/api/kb/upload",
            headers={"Authorization": f"Bearer {counselor_token}"},
            files={"file": (fname, io.BytesIO(path.read_bytes()), "text/markdown")},
            data={"role_min": role_min},
        )
        r.raise_for_status()
        uploaded += 1
        time.sleep(0.2)
    return uploaded


# P4e C0-②（M1②）：共现判据的**邻近**阈值。
# 原判据是「整篇答案两词都在」，实测会误杀据实引用的正常答案——复核方发现
# `录取通知书` 在 student 可见块有 **5 块**，《国家助学贷款实施办法》第十七条原文
# 「在线提交录取通知书、身份证等相关证明资料」里两词相隔 40+ 字、用于**完全不同**的
# 用途（继续贴息申请），却会被整篇共现判成「夹带无据断言」。
# 现改为邻近共现：**同句** 或 两词**首次出现位置**距离 ≤ COOCUR_WINDOW 字。
# 80 字的依据：足够容纳一个完整分句（「…须提交录取通知书，并提供相关证明资料」，
# 约 20~30 字），又不会跨越到另一个独立用途（实测误杀样本间隔 40+ 字但语义独立，
# 取 80 仍偏保守；若复核方认为该放宽，改这一个常量即可，判据逻辑不动）。
COOCUR_WINDOW = 80
_SENT_SPLIT = re.compile(r"(?<=[。；;!?！？\n])")


def _cooccur_near(answer: str, a: str, b: str) -> bool:
    """判断 a 与 b 在 answer 中是否**邻近共现**（同句，或首次出现位置距离 ≤ COOCUR_WINDOW）。

    ⚠ 与旧判据的关键差别：旧判据只问「两词是否都在这篇答案里」，不问是否相邻；
    这会把**分处不同用途**的据实引用判成违规（M1 修订的根因）。
    同句优先——中文答案里同一分句的两词几乎必然是同一件事的表述。
    """
    if a not in answer or b not in answer:
        return False
    # ① 同句共现（对中文更稳，优先判）
    for sent in _SENT_SPLIT.split(answer):
        if a in sent and b in sent:
            return True
    # ② 窗口邻近（兜底：跨句但紧邻的情形，如分号断开的并列成分）
    ia = answer.find(a)
    ib = answer.find(b)
    return abs(ia - ib) <= COOCUR_WINDOW


def _check_absent_keywords(case: dict, answer: str) -> list[str]:
    """P4e C0-②：「答案不得出现无据断言」的两段式检查（qa / refusal_indomain 共用同一判据）。

    原实现只有**无条件** `expect_absent_keywords` 一种判据，坑 54 指出它埋雷：
    rind-07 选的 `证明`(student 可见 **42 块**) / `录取`(14 块) 是**宽词**——
    《学生公寓管理办法》「应当妥善保管宿舍房门钥匙」、教育部令 41 号讲录取报到都是
    **正当出处**。C0-① 把检索补强之后，这类块会被召回并据实引用，届时该用例必然
    假红（"必然，不是偶发"）。

    改为两段：
      1. **无条件段** `expect_absent_keywords`：只放**库内零命中**的具体事项词
         （交回/退卡/提档/调档/饭卡/档案转递…实测 student 可见 323 块全为 0 块）。
         出现即夹带无据断言——这类处置动作全库无条款可答，是本用例的**主判据**。
      2. **共现段** `expect_absent_keywords_cooccur`：[[词, [共现词...]], ...]，
         只有该词**与共现词邻近共现**才算夹带（如答案里「证明」与「交回」出现在
         同一句或邻近处，才说明它在替用户"认定"这件事该开证明）。共现词**必须取
         库内零命中的处置动词**——见下方 M2 修订。

    ⚠ **M1 修订（2026-09-30 第二回打回）**：共现判据原为「**整篇答案**两词都在」，
    复核方实测 `录取通知书` 在 student 可见块 **5 块**，且《国家助学贷款实施办法》
    第十七条原文就是「在线提交录取通知书、身份证等相关**证明**资料」——
    于是一个**据实引用该条款的正常答案**（两词都在，但相隔 40+ 字、分处不同用途）
    会被整篇共现判红。**这正是 C0-② 要消除的「检索一增强就必然假红」在改进后的断言里复发。**
    两处修法（都做）：① `录取通知书` 从 `证明` 的共现词里删掉（复核方实测 5 块，非零命中）；
    ② 共现判据改为**窗口邻近**（`_cooccur_near`，默认同句或距离 ≤ `COOCUR_WINDOW` 字）。

    ⚠ **M2 修订**：注释原写「共现词一律取零命中的处置动词」而**未验证过共现词本身**，
    `录取通知书` 就是被漏掉的反例。现所有共现词都由 `docs/p4e/probe_rind07_kw.py`
    实测并落盘 `rind07_kw_probe.json` 的 `c0_2_cooccur_context_all_zero` 字段把关。
    实测结论（student 可见 323 块）：`交回/提档/调档/凭据/退还/退卡/借阅/回收` 全 0 块；
    ⚠ `录取通知书` **5 块**、`报到` 5 块、`注销` 6 块 → **均不得作共现词**。

    ⚠ **M3 修订**：原 `if not pair or len(pair) < 2: continue` 会让写成 `["证明"]`
    的畸形对**永久失效且不报错**（自测只校验每对的 `[0]`、从不校验 `[1]`，坑 45/52 同形状）。
    现改为结构不符即 `raise ValueError`——坏数据必须吵，不能静默失效。

    返回违规词列表（空 = 通过）。
    """
    bad = [k for k in case.get("expect_absent_keywords", []) if k and k in answer]
    for idx, pair in enumerate(case.get("expect_absent_keywords_cooccur", []) or []):
        # M3：结构不符即吵。静默 continue 会让断言**永久失效而不报错**（坑 45/52）。
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            raise ValueError(
                f"{case.get('id')} 的 expect_absent_keywords_cooccur[{idx}] 结构不符: "
                f"须为 [主词, [共现词...]]，实得 {pair!r}")
        word, ctxs = pair[0], pair[1]
        if not isinstance(ctxs, (list, tuple)):
            raise ValueError(
                f"{case.get('id')} 的 expect_absent_keywords_cooccur[{idx}][1] 须为 list，"
                f"实得 {type(ctxs).__name__}")
        if not word:
            raise ValueError(
                f"{case.get('id')} 的 expect_absent_keywords_cooccur[{idx}] 主词为空")
        if not ctxs or not all(isinstance(c, str) and c for c in ctxs):
            raise ValueError(
                f"{case.get('id')} 的 expect_absent_keywords_cooccur[{idx}] 共现词列表为空或有非法项")
        if word not in answer:
            continue
        # M1②：邻近共现，不再是"整篇两词都在"
        hit_ctx = [c for c in ctxs if _cooccur_near(answer, word, c)]
        if hit_ctx:
            bad.append(f"{word}(与 {'/'.join(hit_ctx)} 邻近共现)")
    return bad


def judge_qa(case: dict, answer: str, sources: list) -> tuple[bool, str]:
    if not sources:
        return False, "无引用来源"
    # T6 ⑥a 措辞加固:条目为 str(必含)或 list(any-of,任一同义词命中即可)
    missing = []
    for kw in case["expect_keywords"]:
        alts = kw if isinstance(kw, list) else [kw]
        if not any(a in answer for a in alts):
            missing.append("/".join(alts))
    if missing:
        return False, f"回答未命中关键词: {missing}(引用 {[s['title'] for s in sources]})"
    # P4d-fix ④（假阳性修复）：非答案检测。
    # 起因(qa-12 现场)：问「研究生奖助学金」，检索到 3 条**本科生**文档，答案如实说
    # 「研究生奖助学金相关规定未在知识库覆盖，请以研究生主管部门最新通知为准」——
    # 这**根本不是答案**，但因为关键词「奖助学金」出现在问题复述里，被 judge_qa 判 PASS。
    # 这条不是 P4d 引入的，是被忠实度调查(③)暴露出来的既有假阳性：非答案也能过。
    #
    # 判据（先量后判，依据 docs/p4d/evidence/after/answers_facts.json 实测三档）：
    #   qa-12  真非答案 → 全文 45  / 实质 0   / **零引用标记、零数字**
    #   rind-02 真答案 → 全文 571 / 实质 505 / 有 [1][2][3] 与 448、2012、2016
    #   qa-13  真答案 → 全文 702 / 实质 597 / 有 [1][3]（末行才声明研究生未覆盖）
    # 判据 = **零可核查事实**（无引用标记 [n] 且无数字）或 **实质内容完全为 0**。
    #
    # 为什么不用"实质长度 < 阈值"作主判据（第一版的错法，自测抓到）：
    #   「学平险理赔需出院证、诊断证明书[1]；现行投保方式请以最新通知为准」是**真答案**，
    #   剥离免责句后实质仅 27 字 → 被长度阈值误判为非答案。而本产品的答案只要有来源就**一定**
    #   带 [n] 引用标记（实测 18 条 qa 全部带），故"有无引用标记"比"长度"更本质、更稳。
    #   阈值只保留一条**兜底**：实质内容为 0 时无论有无数字都算非答案。
    #
    # 已知取舍（如实记录，不藏）：一个"没有任何引用标记、也没有任何数字"的**短真答案**
    # （如「学平险由学校统一组织投保。投保方式未在知识库覆盖，请以最新通知为准。」）
    # 会被判成非答案。这是**刻意偏向严**——宁可漏过这种边缘形态，也不放过 qa-12 那种
    # 整段免责的假答案；产品实际输出必带 [n]，故实测无影响（见 selftest 的 5 条回放断言）。
    marks = [m for m in NON_ANSWER_MARKS if m in answer]
    sub = substantive_len(answer)
    has_fact = bool(_FACTUAL.search(answer))
    if marks and (not has_fact or sub == 0):
        why = ("全文无任何引用标记 [n] 与具体数字(零可核查事实)" if not has_fact
               else "剥离免责措辞后实质内容为 0")
        return False, (f"非答案:命中免责措辞 {marks},但{why}——"
                       f"关键词命中来自问题复述,不是答案(引用 {[s['title'] for s in sources]})")
    # P4d-fix ① / P4e C0-②：qa 型也检查"不得夹带无据断言"（rind-02 迁移后要断言
    # 「95585 不得作现行」；rind-07 迁回 refusal 型后由 judge_refusal_indomain 共用同一判据）。
    # 此前只有 refusal 类判定检查该字段，qa 型忽略；迁移后必须真的检查，否则断言形同虚设。
    # （自测抓到过一次真实缺陷：这段曾被误放到 return 之后成为死代码，硬断言形同虚设。）
    absent = _check_absent_keywords(case, answer)
    if absent:
        return False, (f"夹带禁用内容(历史文件信息不得作现行/无据断言): {absent}"
                       f"(引用 {[s['title'] for s in sources]})")
    return True, f"命中 {case['expect_keywords']},引用 {len(sources)} 条"


def judge_refusal(case: dict, answer: str, sources: list) -> tuple[bool, str]:
    declined = (not sources) or any(m in answer for m in REFUSAL_MARKS)
    if declined:
        return True, "正确拒答" + ("(无引用)" if not sources else "(明示未覆盖)")
    return False, f"不应回答却给出了内容,引用: {[s['title'] for s in sources]}"


def judge_refusal_indomain(case: dict, answer: str, sources: list) -> tuple[bool, str]:
    """P4a C7:域内无据拒答判定——拒答 + 无越界 [n] + 出口信息 + 不夹带无据断言。"""
    declined = any(m in answer for m in REFUSAL_MARKS)
    if not declined:
        return False, f"域内无据问题未拒答反而作答,引用: {[s['title'] for s in sources]}"
    bad_refs = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer) if int(n) > len(sources)})
    if bad_refs:
        return False, f"越界引用未剥离: {bad_refs}(sources={len(sources)})"
    if len(sources) == 0 and re.search(r"\[\d+\]", answer):
        return False, "无来源却仍含 [n] 引用(虚构引用)"
    contact = case.get("expect_contact")
    if contact and contact not in answer:
        return False, f"拒答未含出口信息({contact})"
    absent = _check_absent_keywords(case, answer)
    if absent:
        return False, f"拒答/答案夹带无据断言: {absent}"
    return True, f"域内无据正确拒答(sources={len(sources)},出口与断言检查通过)"


def judge_kb_hidden(case: dict, answer: str, sources: list) -> tuple[bool, str]:
    cited = [s["title"] for s in sources if case["hidden_marker"] in s["title"]]
    if cited:
        return False, f"越权引用了受限文档: {cited}"
    declined = (not sources) or any(m in answer for m in REFUSAL_MARKS)
    return True, ("未泄露受限文档;" + ("正确拒答" if declined else "回答了但未引用受限内容"))


# P4d-fix ②（口径变更,坑 51）：标题归一。
# 起因：qa-09 的 expect_sources 写「离校请销假」(半角)，而 KB 标题是「离校请（销）假」(全角)，
# 朴素子串匹配永不相交 → R@k 恒 0.0，而该文档实际排在来源第 1、2 位(0.9722/0.9347)，
# 检索完全正确、用例本身还判 PASS。**我们从 v1.2 一路记录的 R@k 0.9412 因此长期被这个假象压低(16/17)。**
# 修法：两侧都归一后再比。**这会把全套 R@k 由 0.9412 → 1.0，属口径变更，已在
# docs/EVAL_BASELINE.md §十五记账；历史各版数值保留不抹并加注「含尺子缺陷(括号全半角)」。**
_TITLE_NORM_MAP = {
    # 全角 → 半角（只做确定性的成对映射，不做语义猜测）
    "（": "(", "）": ")", "［": "[", "］": "]", "【": "[", "】": "]",
    "〔": "[", "〕": "]",  # 文号用的六角括号
    "《": "", "》": "", "〈": "", "〉": "", "「": "", "」": "",
    "，": ",", "。": ".", "、": ",", "：": ":", "；": ";",
    "　": "", "\u3000": "",
}

# P4d-fix ② 的核心（第一版两次都没修好，自测逐次暴露）：
#   期望串「离校请销假」 vs KB 标题「离校请（销）假」——括号里的「销」是**内嵌的同义字**，
#   不是可删的插入语。所以：
#     只把括号换成半角        → 「离校请(销)假」 ✗ 仍不相交
#     只删括号连内容          → 「离校请假」     ✗ 仍不相交
#   正确做法是**两侧都生成多种形态，任意形态命中即算命中**：
#     形态 A：去括号符、**保留内容** → 「离校请销假」 ✓（对上期望串）
#     形态 B：**删除**括号连内容   → 「离校请假」   ✓（对上另一种写法）
#     形态 C：原样（全角已转半角）
#   这样既修好 qa-09，又不会把「大学生意外伤害保险理赔须知(学平险)」里的「学平险」
#   删掉（形态 A 保留了它 → qa-15 / rind-02 不再被误伤）。
_PAREN_ANY = re.compile(r"[（(［\[【〔][^（()）\[\]【〔〕]{0,20}[）)］\]】〕]")
_PAREN_OPEN = "（(［[【〔"
_PAREN_CLOSE = "）)］]】〕"


def _title_forms(s: str) -> list[str]:
    """生成标题/期望串的归一形态集合（任意一个命中即算命中）。

    形态 C（base）：全角→半角、去书名号、去空白；
    形态 A：去括号符、**保留内容** → 「离校请(销)假」→「离校请销假」；
    形态 B：**删除**括号连内容（循环到不动点，覆盖嵌套）→「离校请假」。
    """
    base = "".join(_TITLE_NORM_MAP.get(ch, ch) for ch in s)
    for ws in (" ", "\t", "\n", "\r", "\u3000"):
        base = base.replace(ws, "")
    a = _PAREN_ANY.sub(lambda m: m.group(0)[1:-1], base)
    b, prev = base, None
    while prev != b:
        prev = b
        b = _PAREN_ANY.sub("", b)
    return sorted({f for f in (base, a, b) if f})


def normalize_title(s: str) -> str:
    """形态 C（主形态）：全/半角统一 + 去书名号 + 去空白，括号内容保留。

    单独用它比较会漏（见 `_title_forms` 注释：期望「离校请销假」vs 标题「离校请（销）假」
    只转半角仍不相交），所以 `compute_recall` 一律用 `_title_forms` 多形态匹配。
    本函数用于"归一后长什么样"可直接观察与打印。
    """
    base = "".join(_TITLE_NORM_MAP.get(ch, ch) for ch in s)
    for ws in (" ", "\t", "\n", "\r", "\u3000"):
        base = base.replace(ws, "")
    return base


def compute_recall(case: dict, sources: list) -> float | None:
    """Recall@k:expect_sources(标题子串)在返回 sources 标题中的命中比例。

    P4d-fix ②：两侧先做**多形态归一**（`_title_forms`：全/半角统一、去书名号、去空白，
    并额外生成"去括号符保留内容"与"删括号连内容"两种形态），
    修掉「全角『离校请（销）假』vs 半角『离校请销假』子串永不相交」这个尺子缺陷（坑 51）。
    口径变更：R@k 0.9412 → 1.0，已记账（EVAL_BASELINE §十五），历史数值保留不抹并加注。
    """
    expect = case.get("expect_sources") or []
    if not expect:
        return None
    titles: list[str] = []
    for s in sources:
        titles.extend(_title_forms(s.get("title", "")))
    hit = 0
    for sub in expect:
        forms = _title_forms(sub)
        if any(f in t for f in forms for t in titles):
            hit += 1
    return round(hit / len(expect), 4)


# ---------- P4b-fix ③: 新代码路径用例的执行与判定 ----------

CHAT_TURN_TYPES = {"multiturn", "context_compress", "refusal_followup", "history_false_premise"}
_TEMPLATE_MARK = "系统模板生成"  # refusal.build_refusal 确定性模板指纹(模型自由发挥不会有)


def kw_missing(keywords: list, answer: str) -> list[str]:
    """与 judge_qa 同款 any-of 语义:条目为 str(必含)或 list(任一同义词命中)。"""
    missing = []
    for kw in keywords:
        alts = kw if isinstance(kw, list) else [kw]
        if not any(a in answer for a in alts):
            missing.append("/".join(alts))
    return missing


def ctx_mismatch(case: dict, ctx: dict) -> list[str]:
    """expect_context: 断言门控/压缩标志等上下文状态,证明新代码路径真的被执行。"""
    bad = []
    for k, v in (case.get("expect_context") or {}).items():
        if ctx.get(k) != v:
            bad.append(f"context.{k}={ctx.get(k)!r}(期待 {v!r})")
    return bad


def judge_history_answer(case: dict, answer: str, ctx: dict) -> tuple[bool, str]:
    """multiturn / context_compress: 末轮答案命中关键词 + 上下文标志断言。"""
    bad = ctx_mismatch(case, ctx)
    missing = kw_missing(case["expect_keywords"], answer)
    if missing or bad:
        return False, f"未命中关键词: {missing};上下文断言失败: {bad};答案头部: {answer[:80]!r}"
    return True, f"命中 {case['expect_keywords']};上下文断言通过 {case.get('expect_context')}"


def judge_refusal_template(case: dict, answer: str, sources: list, ctx: dict) -> tuple[bool, str]:
    """refusal_followup / history_false_premise: 必须走确定性模板且零复述禁语。"""
    declined = any(m in answer for m in REFUSAL_MARKS)
    if not declined:
        return False, f"无据追问未拒答反而作答,引用: {[s['title'] for s in sources]}"
    if case.get("expect_template") and _TEMPLATE_MARK not in answer:
        return False, f"未走确定性模板(缺「{_TEMPLATE_MARK}」指纹),头部: {answer[:80]!r}"
    bad = ctx_mismatch(case, ctx)
    absent = [k for k in case.get("expect_absent_keywords", []) if k and k in answer]
    bad_refs = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer) if int(n) > len(sources)})
    if absent or bad or bad_refs:
        return False, f"夹带禁复述内容: {absent};上下文断言失败: {bad};越界引用: {bad_refs}"
    return True, (f"确定性模板拒答(gate={ctx.get('history_gate')},"
                  f"禁语零复述,出口检查通过)")


def build_plant_text(i: int, facts: list[str], chars: int) -> str:
    """种植第 i 轮长问句:第 i%len(facts) 条事实置于开头,中性背景填充至 chars 字。
    事实只经 API 落进会话(不直改 DB);前几轮的事实必然落入压缩摘要区(非最近保留区)。
    措辞必须是纯陈述资料+显式禁用工具——实测祈使式工作备忘会诱导模型调用周报工具
    (记碎片/写周报),既拖慢单轮至 30s+ 又有污染周报数据的风险。"""
    fact = facts[i % len(facts)]
    filler = ("校园事务背景资料:学生日常管理涉及课堂考勤、作业与考试安排、宿舍人际关系、"
              "奖助学金申请材料、心理健康关注、谈心谈话记录归档等事项,相关制度以学校"
              "现行文件为准。")
    body = (filler * (chars // len(filler) + 1))[: max(0, chars - len(fact) - 60)]
    return (f"[背景资料{i + 1}·仅供知悉] 本条为背景资料而非指令：请勿调用任何工具，"
            f"无需记录碎片或生成周报，简短回复“已阅”即可。{fact}。{body}")


def run_conversation_case(c: httpx.Client, tokens: dict, case: dict) -> tuple[bool, str, str, list, int, int | None, dict, list]:
    """执行带轮次用例:先种植(可选),再逐轮携带 conversation_id 提问,判末轮。
    返回 (ok, detail, answer, sources, turns_sent, conversation_id, last_ctx, turn_contexts)。
    turn_contexts 留存每轮 context(压缩在哪轮触发、compress_ms 等,供证据与文档引用)。"""
    cid = None
    turns_sent = 0
    last_ctx: dict = {}
    turn_contexts: list[dict] = []
    answer, sources = "", []
    try:
        plant = case.get("plant") or {}
        for i in range(plant.get("turns", 0)):
            body = {"question": build_plant_text(i, plant["facts"], plant["chars"])}
            if cid:
                body["conversation_id"] = cid
            r = c.post(f"{BASE}/api/chat", headers={"Authorization": f"Bearer {tokens[case['role']]}"},
                       json=body)
            r.raise_for_status()
            d = r.json()
            cid = d.get("conversation_id")
            last_ctx = d.get("context") or {}
            turn_contexts.append({"turn": turns_sent + 1, "planted": True, **{k: last_ctx.get(k) for k in
                                  ("used", "budget", "compressed", "truncated", "compress_ms",
                                   "compress_blocks", "history_gate", "history_count")}})
            turns_sent += 1
        for i, t in enumerate(case["turns"]):
            body = {"question": t["question"]}
            if cid:
                body["conversation_id"] = cid
            r = c.post(f"{BASE}/api/chat", headers={"Authorization": f"Bearer {tokens[case['role']]}"},
                       json=body)
            r.raise_for_status()
            d = r.json()
            answer, sources = d.get("answer", ""), d.get("sources", [])
            cid = d.get("conversation_id")
            last_ctx = d.get("context") or {}
            turn_contexts.append({"turn": turns_sent + 1, "planted": False, "question": t["question"],
                                  **{k: last_ctx.get(k) for k in ("used", "budget", "compressed",
                                                                  "truncated", "compress_ms", "compress_blocks",
                                                                  "history_gate", "followup_no_new_sources",
                                                                  "history_count")}})
            turns_sent += 1
        if case["type"] in ("multiturn", "context_compress"):
            ok, detail = judge_history_answer(case, answer, last_ctx)
        else:
            ok, detail = judge_refusal_template(case, answer, sources, last_ctx)
        return ok, detail, answer, sources, turns_sent, cid, last_ctx, turn_contexts
    except httpx.HTTPStatusError as e:
        return False, f"HTTP {e.response.status_code}: {e.response.text[:120]}", "", [], turns_sent, cid, last_ctx, turn_contexts


def run_scoped_qa(c: httpx.Client, tokens: dict, case: dict) -> tuple[bool, str, str, list]:
    """P4c C7: @ 指定检索范围用例(自备夹 + 自清理,坑 23/39)。

    setup.folder            建夹参数(name/visibility);夹由 counselor 建
    setup.move_doc_title    可选:把标题前缀匹配的既有文档移入该夹(验证"来源全属该夹")
    断言(全部能失败且失败即 total_pass 不满):
      expect_status            期待 HTTP 状态(越权 folder 与不存在同表现 404)
      expect_sources_titles    来源标题前缀必须全落在集合内(scope 生效的直接证明)
      expect_no_sources        必须零来源(空库提示路径,防"回落全库"回归)
      expect_context           context 标志断言(scope_empty 等)
      expect_keywords          答案关键词(any-of 语义同 qa)
    teardown: 文档 folder_id 复位 + 级联删夹(只删壳,不删文档) → KB 元数据守恒。
    """
    co = {"Authorization": f"Bearer {tokens['counselor']}"}
    setup = case.get("setup") or {}
    fid = None
    moved_doc = None
    try:
        r = c.post(f"{BASE}/api/kb/folders", headers=co, json=setup["folder"])
        r.raise_for_status()
        fid = r.json()["folder_id"]
        moved_title = setup.get("move_doc_title")
        if moved_title:
            docs = c.get(f"{BASE}/api/kb/documents", headers=co).json()["documents"]
            moved_doc = next((d for d in docs if d["title"].startswith(moved_title)), None)
            assert moved_doc, f"setup 失败: 找不到待移入文档(前缀 {moved_title})"
            r = c.patch(f"{BASE}/api/kb/documents/{moved_doc['id']}", headers=co,
                        json={"folder_id": fid})
            r.raise_for_status()
        raw_scope = {"folder_ids": [fid],
                     "categories": setup.get("categories"),
                     "audience": setup.get("audience")}
        scope = {k: v for k, v in raw_scope.items() if v}
        r = c.post(f"{BASE}/api/chat", headers={"Authorization": f"Bearer {tokens[case['role']]}"},
                   json={"question": case["question"], "scope": scope})
        if case.get("expect_status"):
            ok = r.status_code == case["expect_status"]
            return ok, f"HTTP {r.status_code}(期待 {case['expect_status']}) body={r.text[:100]}", "", []
        r.raise_for_status()
        d = r.json()
        sources = d.get("sources") or []
        ctx = d.get("context") or {}
        answer = d.get("answer") or ""
        bad: list[str] = []
        for k, v in (case.get("expect_context") or {}).items():
            if ctx.get(k) != v:
                bad.append(f"context.{k}={ctx.get(k)!r}(期待 {v!r})")
        if case.get("expect_no_sources") and sources:
            bad.append(f"期待零来源却得 {len(sources)} 条(疑似回落全库): "
                       f"{[s['title'] for s in sources][:3]}")
        allow = tuple(case.get("expect_sources_titles") or ())
        if allow:
            if not sources:
                bad.append("期待有来源却为空")
            else:
                bad += [f"来源越界: {s['title']}" for s in sources
                        if not s["title"].startswith(allow)]
        if case.get("expect_keywords"):
            miss = kw_missing(case["expect_keywords"], answer)
            if miss:
                bad.append(f"答案未命中: {miss}; 头部: {answer[:80]!r}")
        detail = "; ".join(bad) if bad else f"sources={len(sources)}, scope 断言全过"
        return (not bad), detail, answer, sources
    finally:
        if moved_doc:
            try:
                c.patch(f"{BASE}/api/kb/documents/{moved_doc['id']}", headers=co,
                        json={"folder_id": None})
            except Exception:  # noqa: BLE001
                pass
        if fid:
            try:
                c.delete(f"{BASE}/api/kb/folders/{fid}", headers=co, params={"cascade": "true"})
            except Exception:  # noqa: BLE001
                pass


def _trace_has(trace: list, node: str) -> bool:
    return any(isinstance(t, dict) and t.get("node") == node for t in (trace or []))


def _trace_skipped(trace: list) -> bool:
    return any(isinstance(t, dict) and t.get("skipped") is True for t in (trace or []))


def run_intent_case(c: httpx.Client, tokens: dict, case: dict) -> tuple[bool, str, str, list, int | None, dict]:
    """P4d C3: 意图直答用例(闲聊/时间)——断言**检索被跳过**(不调 LLM 的问时间类还要断言零 LLM)。

    断言(每条都能失败,失败即计入 total_pass 不满;坑 39/45):
      expect_retrieval_skipped  context.retrieval_skipped 必须为 true;trace 内必须有 skipped 标记;
      expect_intent             context.intent 等于该值;
      expect_no_sources         必须零来源(直答不检索);
      expect_answer_any         答案包含任一关键词(any-of);
      expect_no_llm_intent      intent 阶段未调 LLM(问时间类:正则直答);
      expect_latency_lt_ms      端到端延迟上限(毫秒,证明快路径真的快)。
    反断言(坑 45): "零来源"必须与"检索确实被跳过"同时成立才算过——只断言空 sources 会把
    检索失败/空库误判为通过。
    """
    t0 = time.time()
    r = c.post(f"{BASE}/api/chat", headers={"Authorization": f"Bearer {tokens[case['role']]}"},
               json={"question": case["question"]})
    r.raise_for_status()
    elapsed_ms = round((time.time() - t0) * 1000)
    d = r.json()
    ctx = d.get("context") or {}
    trace = ctx.get("retrieval_trace") or []
    sources = d.get("sources") or []
    answer = d.get("answer") or ""
    bad: list[str] = []
    if case.get("expect_retrieval_skipped") and not ctx.get("retrieval_skipped"):
        bad.append(f"retrieval_skipped={ctx.get('retrieval_skipped')!r}(期待 True)")
    if case.get("expect_retrieval_skipped") and not _trace_skipped(trace):
        bad.append(f"trace 内无 skipped 标记: {[t.get('node') for t in trace]}")
    if case.get("expect_intent") and ctx.get("intent") != case["expect_intent"]:
        bad.append(f"intent={ctx.get('intent')!r}(期待 {case['expect_intent']!r})")
    if case.get("expect_no_sources") and sources:
        bad.append(f"期待零来源却得 {len(sources)} 条: {[s['title'] for s in sources][:2]}")
    if case.get("expect_answer_any") and not any(k in answer for k in case["expect_answer_any"]):
        bad.append(f"答案未含 {case['expect_answer_any']} 任一; 头部: {answer[:80]!r}")
    if case.get("expect_no_llm_intent"):
        it = next((t for t in trace if t.get("node") == "intent"), None)
        if not it or it.get("llm_called"):
            bad.append(f"intent 阶段调了 LLM(期待正则直答): {it}")
    lat = case.get("expect_latency_lt_ms")
    if lat and elapsed_ms >= lat:
        bad.append(f"延迟 {elapsed_ms}ms ≥ {lat}ms")
    detail = "; ".join(bad) if bad else (f"skipped={ctx.get('retrieval_skipped')}, "
                                         f"intent={ctx.get('intent')}, trace={[t.get('node') for t in trace]}"
                                         f", {elapsed_ms}ms")
    return (not bad), detail, answer, sources, d.get("conversation_id"), ctx


def run_rewrite_case(c: httpx.Client, tokens: dict, case: dict) -> tuple[bool, str, str, list, int | None, dict]:
    """P4d C3: 改写用例——口语化/噪声长问句必须**发生改写**且**最终召回到达标来源**。

    断言(每条都能失败;坑 39):
      expect_rewritten       trace 内必须出现 rewrite 节点(证明改写真的跑了,而非一次蒙对);
      expect_final_sources   最终必须有来源(改写后召回成功);
      expect_sources_titles  来源标题须命中任一前缀(证实召回到目标材料,不是别的块);
      expect_keywords        答案关键词(any-of);
      expect_min_attempts    最少检索轮数(≥2 证明经历了 retry)。
    反断言(坑 45): 若 expect_rewritten 为真却零来源 → 判红(改写没救回来等于没改)。
    """
    r = c.post(f"{BASE}/api/chat", headers={"Authorization": f"Bearer {tokens[case['role']]}"},
               json={"question": case["question"]})
    r.raise_for_status()
    d = r.json()
    ctx = d.get("context") or {}
    trace = ctx.get("retrieval_trace") or []
    sources = d.get("sources") or []
    answer = d.get("answer") or ""
    bad: list[str] = []
    attempts = ctx.get("attempts")
    rewrites = [t for t in trace if t.get("node") == "rewrite"]
    if case.get("expect_rewritten"):
        if not rewrites and not ctx.get("rewritten"):
            bad.append(f"未发生改写(attempts={attempts}, trace={[t.get('node') for t in trace]})")
    if case.get("expect_final_sources") and not sources:
        bad.append("改写后仍零来源(未救回)")
    allow = tuple(case.get("expect_sources_titles") or ())
    if allow and sources:
        bad += [f"来源非目标材料: {s['title']}" for s in sources
                if not any(s["title"].startswith(p) for p in allow)]
    if case.get("expect_min_attempts") and (attempts or 0) < case["expect_min_attempts"]:
        bad.append(f"检索轮数 {attempts} < {case['expect_min_attempts']}")
    if case.get("expect_keywords"):
        miss = kw_missing(case["expect_keywords"], answer)
        if miss:
            bad.append(f"答案未命中: {miss}; 头部: {answer[:80]!r}")
    qs = [t.get("to") for t in rewrites if t.get("to")]
    detail = "; ".join(bad) if bad else (f"改写 {qs[-1:] if qs else '(未触发)'} → "
                                         f"sources={len(sources)}, attempts={attempts}")
    return (not bad), detail, answer, sources, d.get("conversation_id"), ctx


def run() -> int:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()
    BASE = args.base.rstrip("/")

    spec = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    cases = spec["cases"]

    with httpx.Client(timeout=180) as c:
        admin = login(c, "admin", "admin123")
        counselor = login(c, "counselor", "counselor123")
        student = login(c, "student", "student123")
        tokens = {"admin": admin, "counselor": counselor, "student": student}
        n = seed_corpus_if_needed(c, counselor)
        if n:
            print(f"[seed] 播种评测语料 {n} 篇")
        print(f"[eval] 共 {len(cases)} 条用例\n")

        results = []
        for case in cases:
            t0 = time.time()
            conversation_id = None  # P4b C7: 每个用例独立会话(自动新建)
            first_question = case.get("question", "")
            turns_sent = 1
            last_ctx: dict = {}
            turn_ctxs: list = []
            try:
                if case["type"] == "permission_api":
                    method = case["method"]
                    body = {"question": "x"} if method == "POST" and "chat" in case["path"] else None
                    r = c.request(method, BASE + case["path"], headers={"Authorization": f"Bearer {tokens[case['role']]}"},
                                  json=body)
                    ok, detail = (r.status_code == case["expect_status"],
                                  f"{method} {case['path']} → {r.status_code}(期待 {case['expect_status']})")
                    answer, sources = "", []
                elif case["type"] in CHAT_TURN_TYPES:
                    # P4b-fix ③: 多轮/压缩/追问门控/假前提用例——逐轮携带 conversation_id
                    ok, detail, answer, sources, turns_sent, conversation_id, last_ctx, turn_ctxs = \
                        run_conversation_case(c, tokens, case)
                    first_question = case["turns"][0]["question"]
                    if (case.get("plant") or {}).get("turns"):
                        first_question = build_plant_text(0, case["plant"]["facts"], case["plant"]["chars"])
                elif case["type"] == "scoped_qa":
                    # P4c C7: @ 指定检索范围——setup 自备夹(必要时移入既有文档),带 scope 提问,
                    # 断言来源全属该夹 / 空库提示不回落 / 越权 404 同表现;teardown 恢复 KB 元数据。
                    ok, detail, answer, sources = run_scoped_qa(c, tokens, case)
                    turns_sent = 1
                    first_question = case["question"]
                elif case["type"] == "intent":
                    # P4d C3: 闲聊/时间直答——断言检索被跳过(不调 LLM 的问时间类另断言零 LLM)
                    ok, detail, answer, sources, conversation_id, last_ctx = \
                        run_intent_case(c, tokens, case)
                    turns_sent = 1
                elif case["type"] == "rewrite":
                    # P4d C3: 口语化/噪声问句必须发生改写且最终召回达标来源
                    ok, detail, answer, sources, conversation_id, last_ctx = \
                        run_rewrite_case(c, tokens, case)
                    turns_sent = 1
                else:
                    r = c.post(f"{BASE}/api/chat", headers={"Authorization": f"Bearer {tokens[case['role']]}"},
                               json={"question": case["question"]})
                    r.raise_for_status()
                    d = r.json()
                    answer, sources = d.get("answer", ""), d.get("sources", [])
                    conversation_id = d.get("conversation_id")
                    last_ctx = d.get("context") or {}
                    if case["type"] == "qa":
                        ok, detail = judge_qa(case, answer, sources)
                    elif case["type"] == "refusal":
                        ok, detail = judge_refusal(case, answer, sources)
                    elif case["type"] == "refusal_indomain":
                        ok, detail = judge_refusal_indomain(case, answer, sources)
                    else:
                        ok, detail = judge_kb_hidden(case, answer, sources)
            except httpx.HTTPStatusError as e:
                ok, detail = False, f"HTTP {e.response.status_code}: {e.response.text[:120]}"
                answer, sources = "", []
            recall = compute_recall(case, sources) if case["type"] == "qa" else None
            faith, fmethod = (None, "na")
            if case["type"] == "qa":
                faith, fmethod = faithfulness.judge(case.get("question", ""), answer, sources)
            results.append({**case, "pass": ok, "detail": detail,
                            "recall_at_k": recall,
                            "faithfulness": faith, "faithfulness_method": fmethod,
                            "conversation_id": conversation_id,
                            "first_question": first_question,
                            "turns_sent": turns_sent,
                            "last_context": last_ctx,
                            "turn_contexts": turn_ctxs if case["type"] in CHAT_TURN_TYPES else [],
                            "latency_ms": round((time.time() - t0) * 1000)})
            mark = "[PASS]" if ok else "[FAIL]"
            extra = f" | R@k={recall} 忠实度={faith}({fmethod})" if case["type"] == "qa" else ""
            print(f"{mark} {case['id']:10s} [{case['type']:14s}] {detail}{extra}")

        by_type: dict[str, dict] = {}
        for r in results:
            s = by_type.setdefault(r["type"], {"total": 0, "pass": 0})
            s["total"] += 1
            s["pass"] += int(r["pass"])
        total_pass = sum(s["pass"] for s in by_type.values())
        total = len(results)
        print("\n===== 汇总 =====")
        for t, s in by_type.items():
            print(f"  {t:16s} {s['pass']}/{s['total']}")
        print(f"  {'TOTAL':16s} {total_pass}/{total}({total_pass / total:.0%})")

        # P4b-fix ②: 评测隔离断言——对【全部】带会话的用例(36+新增)逐会话核对,不再只抽首末:
        #   a) 全局 message id 归属唯一(任一 id 出现在两个会话即串台,等价两两交集为空);
        #   b) 每会话首条 user 消息 == 该用例实际发出的第一问(无外来内容);
        #   c) 每会话 user 消息条数 == 该用例应发轮数(多轮/种植轮计入)。
        # 断言失败(含拉取消息失败,fail-closed)必须让退出码非 0——隔离被破坏时评测不得绿。
        iso_errors: list[str] = []
        conv_cases = [(r["id"], r["role"], r["first_question"], r["conversation_id"], r["turns_sent"])
                      for r in results if r.get("conversation_id")]
        id_owner: dict[int, str] = {}
        try:
            for case_id, role, first_q, cid, n_turns in conv_cases:
                # 用各用例自己的角色 token 拉取(counselor/admin 用例的会话对 student 是 404)
                mr = c.get(f"{BASE}/api/conversations/{cid}/messages",
                           headers={"Authorization": f"Bearer {tokens[role]}"},
                           params={"limit": 500})
                mr.raise_for_status()
                msgs = mr.json()["messages"]
                for m in msgs:
                    prev = id_owner.setdefault(m["id"], case_id)
                    if prev != case_id:
                        iso_errors.append(f"消息 {m['id']} 同时出现在 {prev} 与 {case_id} 的会话(串台)")
                users = [m for m in msgs if m["role"] == "user"]
                if not users or users[0]["content"] != first_q:
                    head = users[0]["content"][:40] if users else "(无 user 消息)"
                    iso_errors.append(f"{case_id} 会话 {cid} 首条 user 消息不匹配: {head!r}")
                if len(users) != n_turns:
                    iso_errors.append(f"{case_id} 会话 {cid} user 消息数 {len(users)} != 应发轮数 {n_turns}")
        except Exception as e:  # fail-closed:取不到消息也算隔离断言失败
            iso_errors.append(f"隔离断言执行失败: {e}")
        iso_ok = not iso_errors
        if iso_ok:
            print(f"\n[P4b C7 评测隔离] {len(conv_cases)} 个带会话用例全量核对:"
                  f"message id 全局唯一(两两交集为空)、首问逐字匹配、user 条数=应发轮数 → 隔离成立")
        else:
            print(f"\n[P4b C7 评测隔离] 断言失败 {len(iso_errors)} 处(退出码将非 0):")
            for e in iso_errors[:10]:
                print(f"  - {e}")

        recalls = [r["recall_at_k"] for r in results if r["type"] == "qa" and r.get("recall_at_k") is not None]
        faiths = [(r["faithfulness"], r["faithfulness_method"]) for r in results
                  if r["type"] == "qa" and r.get("faithfulness") is not None]
        summary: dict = dict(by_type)
        summary["recall_at_k_avg"] = round(sum(recalls) / len(recalls), 4) if recalls else None
        summary["faithfulness_avg"] = round(sum(f for f, _ in faiths) / len(faiths), 4) if faiths else None
        summary["faithfulness_method"] = ("llm" if faiths and all(m == "llm" for _, m in faiths)
                                          else "proxy" if faiths else "na")
        ref = by_type.get("refusal", {"pass": 0, "total": 0})
        summary["refusal_accuracy"] = round(ref["pass"] / ref["total"], 4) if ref["total"] else None
        print(f"  Recall@k 均值: {summary['recall_at_k_avg']} | 忠实度均值: {summary['faithfulness_avg']}"
              f"({summary['faithfulness_method']}) | 拒答准确率: {summary['refusal_accuracy']}")

        out = HERE.parent / "reports" / f"eval_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(
            {"version": spec["version"], "base": BASE, "summary": summary,
             "total_pass": total_pass, "total": total, "results": results,
             "eval_isolation": {"ok": iso_ok, "checked_conversations": len(conv_cases),
                                "errors": iso_errors}},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[report] {out}")
        # P4b-fix ②: 隔离断言失败与用例失败同等阻塞——退出码非 0
        return 0 if (total_pass == total and iso_ok) else 1


if __name__ == "__main__":
    sys.exit(run())
