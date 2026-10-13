"""谈心谈话摘要:主题枚举 + 台账句式模板(纯函数层,不发网络请求、不碰数据库)。

【为什么不直接让模型写整句】
  用户要的摘要句式是**固定**的:「就该学生职业规划情况进行谈心谈话」。让模型自由生成整句,
  句式不受控(它会写成「本次谈话探讨了…」),且无法用单测卡住;让模型**只选主题**,
  整句由本模块拼装,则句式恒等、非法输出可判、零虚构风险。这与本项目一贯的
  「确定性优先」口径同源(拒答模板也是代码拼装,不经模型自由生成)。

【枚举项是主题词本体,不含「情况」】
  句式模板负责补「情况」。枚举项若自带「情况」会拼出「学业情况情况」(第一版实测踩过)。

【非法即空,不猜】
  模型返回值归一化后不在枚举内 → 判定失败,摘要留空,由前端显示占位串。
  宁可留空让辅导员手填,也不给一条记录挂一个没说过的主题。
"""
from __future__ import annotations
from .prompts import TOPIC_PROMPT

# 主题枚举(UI 下拉与模型可选值同源,顺序即展示顺序)。
TALK_TOPICS: tuple[str, ...] = (
    "学业",
    "职业规划",
    "心理健康",
    "家庭",
    "人际关系",
    "奖惩资助",
    "思想引导",
    "其他",
)

# 枚举项在台账句里的主题短语;「其他」写成「综合」更贴合辅导员用语。
_TOPIC_CORE: dict[str, str] = {**{t: t for t in TALK_TOPICS}, "其他": "综合"}

SUMMARY_TEMPLATE = "就该学生{core}情况进行谈心谈话"

# 历史碎片没有姓名/摘要时,展示与导出用的占位串(与 mcp/weekly/server.py 的同名常量
# **各自一份**——那边 Dockerfile 只 `COPY server.py`,两包不共享代码,
# 改一处必须同时改另一处,否则界面占位与导出占位会分叉)。
PLACEHOLDER_SUMMARY = "（未生成摘要）"
PLACEHOLDER_NAME = "（未登记姓名）"

# 模型常带的尾缀词,剥离后再精确匹配枚举。**不用子串回退**——
# 「学业与心理」用子串判会静默命中「学业」,把一个说不清的多主题答案伪装成一条有主题的台账。
_STRIP_SUFFIXES: tuple[str, ...] = ("情况", "状况", "方面", "问题", "类", "等")

# 近义词 → 枚举项。只收**同义替换**,不收语义更宽或更窄的词。
_TOPIC_ALIASES: dict[str, str] = {
    "学习": "学业",
    "课业": "学业",
    "就业规划": "职业规划",
    "生涯规划": "职业规划",
    "未来规划": "职业规划",
    "就业指导": "职业规划",
    "心理": "心理健康",
    "情绪": "心理健康",
    "寝室关系": "人际关系",
    "宿舍矛盾": "人际关系",
    "同学关系": "人际关系",
    "社交": "人际关系",
    "家访": "家庭",
    "父母": "家庭",
    "奖助学金": "奖惩资助",
    "奖学金": "奖惩资助",
    "助学金": "奖惩资助",
    "处分": "奖惩资助",
    "资助": "奖惩资助",
    "奖惩": "奖惩资助",
    "评优": "奖惩资助",
    "思想政治": "思想引导",
    "思想动态": "思想引导",
    "入党": "思想引导",
    "综合": "其他",
}


def normalize_topic(raw: object) -> str | None:
    """把模型返回的主题归一化到枚举项。无法确定 → None(**不回落「其他」**)。

    回落「其他」看着安全,实际是把"模型没说清"伪装成"辅导员没别的意思",
    台账会因此出现一批主题错误且无人察觉的记录。
    """
    s = str(raw or "").strip()
    if not s:
        return None
    # 去掉引号、标点与「主题:」前缀、「1.」编号
    for ch in "\"'“”‘’。.、;；:：,，":
        s = s.replace(ch, "")
    s = s.strip()
    for prefix in ("谈话主题", "主题", "分类", "类别"):
        if s.startswith(prefix):
            s = s[len(prefix):].strip()
            break
    s = s.lstrip("0123456789-)）]. ").strip()
    if not s:
        return None
    if s in TALK_TOPICS:
        return s
    # 剥一层尾缀再判(只剥一次,且剥完必须**非空**)
    for suf in _STRIP_SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf):
            s = s[: -len(suf)]
            break
    if s in TALK_TOPICS:
        return s
    return _TOPIC_ALIASES.get(s)


def build_summary(topic: str) -> str:
    """主题枚举 → 台账摘要整句。非枚举项 → 空串(调用方据此留空)。"""
    core = _TOPIC_CORE.get(topic)
    return SUMMARY_TEMPLATE.format(core=core) if core else ""


def summary_or_placeholder(summary: str) -> str:
    """空摘要 → 占位串。展示与导出共用这一个出口,避免两处各写一套判空。"""
    return (summary or "").strip() or PLACEHOLDER_SUMMARY


def name_or_placeholder(name: str) -> str:
    return (name or "").strip() or PLACEHOLDER_NAME


