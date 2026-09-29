"""P4a M1:拒答硬门控、确定性拒答模板与引用硬校验(代码级,不经 LLM 自由生成)

背景(docs/P4.md §2.3 / EVAL_BASELINE §九):SYSTEM_PROMPT 的 9 条防幻觉规则挡不住
"校园域内但库内无据"的真实问法——sources=[] 时模型会用自有知识成篇作答并虚构 [n] 引用。
修复在代码层:
  1) should_refuse(sources, quality):无来源 / top_score<RERANK_MIN_SCORE / 达标来源数<2
     → 拒答,由 build_refusal 拼装确定性模板(缺口说明 + contacts 出口 + 需补充信息);
  2) strip_invalid_refs(answer, n_sources):答案中 [n] 的 n 超出来源数 → 代码剥离,
     并经 record_fabricated_ref 追加 fabricated_ref badcase(复用 evals/badcases.json 机制)。
出口数据表 contacts.json(官网原文,非 LLM 生成)置于包内 data/ 目录。
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from . import config

logger = logging.getLogger("novaagent.refusal")

_CONTACTS_PATH = Path(__file__).resolve().parent / "data" / "contacts.json"
# 规格曾写 novaagent/data/contacts.json——该目录被 .gitignore 的 data/ 规则整体忽略
# 且 .gitignore 不在本单白名单,故数据放包内;两处都找,便于 Qoder 后续迁移。
_CONTACTS_ALT = Path(config.DATA_DIR) / "contacts.json"

_MAX_MATCHED = 3          # 拒答模板最多附 1~3 条出口
_BADCASES_MAX_HISTORY = 50


def _load_contacts() -> list[dict]:
    for p in (_CONTACTS_PATH, _CONTACTS_ALT):
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return data.get("contacts", [])
            except Exception:  # 数据文件损坏时拒答模板退化为无出口版,不致命
                logger.warning("contacts.json 解析失败: %s", p)
                return []
    return []


def should_refuse(sources: list[dict], quality: dict) -> tuple[bool, str]:
    """P4a C1 硬门控判定。quality 来自 rag.search_with_quality 的质量信号。

    触发(任一):
      - sources 为空(empty_sources);
      - rerank 可用且 top_score(原始 rerank 峰值)< RERANK_MIN_SCORE(low_top_score);
      - rerank 可用且达标分块数 n_above_threshold < 2 且 top_score 低于单来源放行线
        (insufficient_evidence)——单条达标来源需"极强置信"(config.
        REFUSAL_SINGLE_SOURCE_MIN_SCORE=0.9)才放行;实测修正依据:qa-01「研究生申请
        休学材料」仅 1 块 0.9952 达标,一刀切 n_above<2 会误杀高置信单据(见 P4A.md)。
    rerank 不可用的降级路径(quality.rerank_available=False)不做分数门控
    (阈值语义属于 rerank 分),仅按来源空判。
    返回 (是否拒答, 原因码)。
    """
    if not sources:
        return True, "empty_sources"
    if quality.get("rerank_available"):
        top = quality.get("top_score")
        if top is not None and top < config.RERANK_MIN_SCORE:
            return True, "low_top_score"
        if quality.get("n_above_threshold", 0) < 2:
            if top is None or top < config.REFUSAL_SINGLE_SOURCE_MIN_SCORE:
                return True, "insufficient_evidence"
    return False, ""


def match_contacts(question: str) -> list[dict]:
    """按问题文本与 scope_keywords 的命中数挑选 1~3 条出口(命中数降序,稳定排序)。"""
    q = question or ""
    scored = []
    for c in _load_contacts():
        hits = [k for k in c.get("scope_keywords", []) if k and k in q]
        if hits:
            scored.append((len(hits), c))
    scored.sort(key=lambda x: (-x[0], x[1]["dept"]))
    return [c for _, c in scored[:_MAX_MATCHED]]


def build_refusal(question: str, reason: str) -> str:
    """确定性拒答模板(代码拼装,不经 LLM):暂无 + 缺口说明 + 出口 + 需补充信息。"""
    reason_zh = {
        "empty_sources": "知识库中未检索到与该问题相关的分块",
        "low_top_score": f"检索到的内容相关度均低于阈值({config.RERANK_MIN_SCORE}),不足以作为回答依据",
        "insufficient_evidence": "相关度达标的来源不足 2 条,无法交叉印证给出可靠回答",
    }.get(reason, "知识库中暂无相关内容")
    lines = [
        "知识库中暂无相关内容，无法就该问题给出有依据的回答。",
        f"（缺口说明：{reason_zh}。为避免误导，本回答由系统模板生成，未采用模型自由发挥。）",
    ]
    matched = match_contacts(question)
    if matched:
        lines.append("建议咨询出口（来自学校官网公开信息）：")
        for c in matched:
            phones = " / ".join(c.get("phone") or [])
            tail = f"电话：{phones}" if phones else "电话以该部门官网最新公布为准"
            lines.append(f"- {c['dept']}（{tail}；网址 {c['url']}）")
    else:
        lines.append("建议通过学校官方网站（https://www.swjtu.edu.cn/）或对应职能部门页面查询联系方式。")
    lines.append("如需更精确的解答，请补充：具体政策/通知的名称或文号、适用的年级学段、办理时间等背景信息。")
    return "\n".join(lines)


_REF_RE = re.compile(r"\[(\d{1,2})\]")


def strip_invalid_refs(answer: str, n_sources: int) -> tuple[str, list[int]]:
    """C2 引用硬校验:剥离编号越界(n > n_sources 或 n < 1)的 [n] 标注。

    只处理 1~2 位数字的方括号——条款编号〔2025〕、年份 [2026]、文中原有 "[1] 字样"
    若编号落在来源数内则保留(不误伤)。返回 (清理后答案, 被剥离的编号列表)。
    """
    stripped: list[int] = []

    def _sub(m: re.Match) -> str:
        n = int(m.group(1))
        if 1 <= n <= n_sources:
            return m.group(0)
        stripped.append(n)
        return ""

    cleaned = _REF_RE.sub(_sub, answer or "")
    return cleaned, sorted(set(stripped))


def record_fabricated_ref(question: str, stripped: list[int], n_sources: int) -> None:
    """把一次越界引用剥离记入 evals/badcases.json(fabricated_ref 案,复用既有机制)。

    尽力而为:文件缺失/占用/损坏只记日志,绝不影响对话主流程;历史上限 50 条。
    """
    if not stripped:
        return
    path = Path(config.DATA_DIR).parent.parent / "evals" / "badcases.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cases = data.get("cases", [])
        case = next((c for c in cases if c.get("id") == "fabricated_ref"), None)
        if case is None:
            case = {"id": "fabricated_ref", "type": "fabricated_ref", "status": "open",
                    "note": "P4a C2:答案引用编号越界(sources 之外)被代码剥离的现场记录",
                    "first_seen": time.strftime("%Y%m%d_%H%M%S"), "history": []}
            cases.append(case)
            data["cases"] = cases
        case["status"] = "open"
        case["last_seen"] = time.strftime("%Y%m%d_%H%M%S")
        case.setdefault("history", []).append({
            "at": case["last_seen"], "question": (question or "")[:80],
            "stripped_refs": stripped, "sources_count": n_sources,
        })
        case["history"] = case["history"][-_BADCASES_MAX_HISTORY:]
        data["updated_at"] = case["last_seen"]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.warning("fabricated_ref 剥离并记录: refs=%s sources=%d", stripped, n_sources)
    except Exception as e:  # badcase 记录失败不影响回答
        logger.warning("fabricated_ref 记录失败(不影响对话): %s", e)


def learn_stage_note(question: str, sources: list[dict]) -> str:
    """C8 学段声明注入(P4a 只做代码级 prompt 组装,不改 SYSTEM_PROMPT 文案)。

    触发:检索到的来源标题/正文呈现为"本科生"专项办法,而知识库未见研究生对应办法时,
    要求回答开头声明适用学段并提示研究生规定未覆盖(F3 实测:默认按本科生作答)。
    返回注入 context 的提示行(空串=不注入)。
    """
    if not sources:
        return ""
    joined_titles = " ".join(s.get("title", "") for s in sources)
    joined_head = " ".join((s.get("content", "") or "")[:200] for s in sources)
    corpus = joined_titles + " " + joined_head
    if "本科生" not in corpus:
        return ""
    if "研究生" in joined_titles:
        return ""  # 已检索到研究生专项办法,无需声明
    # F3 的原始问句可以不含学段词也须声明(默认按本科生作答即违规),
    # 故只要检索到本科生专属来源且未见研究生对应办法,就注入声明要求。
    return ("[系统提示] 以下检索来源为本科生专项办法(如《本科生荣誉称号评审管理办法》)；"
            "知识库未覆盖研究生对应办法。回答开头必须声明「以下依据本科生办法」，"
            "并明确提示研究生相关规定未在知识库覆盖、请以研究生主管部门最新通知为准；"
            "不得默认该办法适用于研究生。")
