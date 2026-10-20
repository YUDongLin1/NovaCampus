# -*- coding: utf-8 -*-
"""在 TASKS.md 的「管道假象」段落后插入 badcases.json 取证说明（按行号定位 + 断言，防锚点漂移）。"""
import io

P = "docs/TASKS.md"
ANCHOR = "管道假象，不是实测"
NEW = (
    "\n"
    "⚠ **`evals/badcases.json` 我这轮也被改脏了，但那不是交付变化 → 已 revert、不入库**。"
    "跑完整评测会让**服务端**的 `refusal.record_fabricated_ref` 往这个 git 跟踪文件里追加 `fabricated_ref` 记录，"
    "而它有 **50 条滚动上限**（`case[\"history\"][-_BADCASES_MAX_HISTORY:]`），于是我这轮把 4 条 `20260930_1103xx` 旧记录挤掉了。"
    "按坑 38 做**双向集合比对**后再定性质：`cases` 8→8、id 集合不变、除 `last_seen` 外**没有任何 case 字段变化**、"
    "history 总条数 70→70、丢的 4 条与被加的 4 条是同一越界现场的滚动重复 → **纯运行时副作用**，"
    "我这轮的数据在报告 JSON 里，不靠这个文件留证。"
    "**铁律补充：「只增不删」对 case 成立、对 history 不成立**——复核这个文件必须先做集合比对，"
    "**不能按增删行数判性质**（34 增 34 删看着像重写，实际是滚动窗口）。\n"
)

lines = io.open(P, encoding="utf-8").read().splitlines(True)
idx = [i for i, l in enumerate(lines) if ANCHOR in l]
assert len(idx) == 1, "anchor not unique: %r" % idx
i = idx[0]
# 该行后面应紧跟空行
assert lines[i + 1].strip() == "", "unexpected layout after anchor line: %r" % lines[i + 1][:40]
lines.insert(i + 2, NEW)
io.open(P, "w", encoding="utf-8", newline="").write("".join(lines))
print("inserted after line %d" % (i + 1))
