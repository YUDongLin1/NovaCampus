# Bad Case 清单维护流程(T2)

> 目标:让"评测失败用例 → 归档跟踪 → 修复回归"形成闭环,而不是让失败散落在历次报告里。
> 配套文件:`evals/extract_badcases.py`(提取器)、`evals/badcases.json`(累积档案)。

## 1. 何时提取

每次执行 `python evals/run_evals.py` 产出新报告后,**紧接着跑一次**:

```bash
python evals/extract_badcases.py
```

时机包括:① 每轮 RAG/提示词迭代前后;② 修复某个已知问题后重跑评测;③ Review 合并前(确认没有新增 open)。

## 2. badcases.json 结构

```json
{
  "version": 1,
  "updated_at": "…",
  "cases": [
    {
      "id": "qa-01",                     // 用例 id(与 cases.json 对应)
      "type": "qa|refusal|permission_api|kb_hidden",
      "role": "student",
      "question": "研究生申请休学需要提交哪些材料?",
      "expect": "命中关键词 书面申请、诊断证明",   // 期望
      "actual": "回答未命中关键词: […]",          // 实际(最近一次失败详情)
      "status": "open",                   // open / fixing / fixed / wontfix
      "note": "",                         // 人工备注,提取器永不覆盖
      "first_seen": "20260927_124959",
      "last_seen": "20260927_124959",
      "fixed_in": "",                     // 置 fixed 时的报告文件名
      "history": [ { "report": "…", "detail": "…", "at": "…" } ]
    }
  ]
}
```

原则:**累积档案,只增不删**。用例不再复现不删除条目——它就是"迭代前后对比"的证据链,也是简历叙事里"优化留痕"的素材。

## 3. 状态机

```
open ──(最新报告通过,自动)──▶ fixed ──(再次失败,自动重开)──▶ open
  │  ▲
  │  └── fixing(人工置,提取器不改;确认修复后人工置 fixed)
  └────── wontfix(人工置,提取器不改;如"超出范围不接受")
```

- `open`:待迭代,默认状态。
- `fixing`:已定位、修复中(人工设置;此时若最新报告恰好通过,提取器只回填 `fixed_in`,不改状态,由人工确认)。
- `fixed`:已修复。**最新报告通过时由 `open` 自动翻转**,记录 `fixed_in`;已 fixed 的用例再次失败会被自动重开为 `open`(回归告警)。
- `wontfix`:决策不修(人工设置),提取器不再流转。

## 4. 修复后的回归流程

1. 在任务分支上修复代码(改 `novaagent/**` 需在 TASKS.md 对应任务白名单内);
2. `python evals/run_evals.py` 重跑评测;
3. `python evals/extract_badcases.py` 刷新档案;
4. 核对:目标用例 status 应为 `fixed`(或人工 `fixing` → 人工确认后置 `fixed`),且**没有新增 open**(修复引入回归会被自动重开标出);
5. 把结果写进交接回执(用例 id + 修复前/后 detail)。

## 5. 与其他任务的关系

- **T4**(Recall@k / 忠实度):指标深化后,`actual` 字段会带上量化分数,bad case 可以按忠实度排序;
- **T5**(评测看板):看板读取 `reports/` 趋势时,叠加本档案的 open/fixed 计数,展示"失败用例收敛曲线";
- **Review 闸门**(COLLAB.md 第五节):合并前检查 `badcases.json` 无新增 open,是 Review 的一项固定动作。
