import io, sys, pathlib
p = pathlib.Path("docs/TASKS.md")
s = p.read_text(encoding="utf-8")
old = "**下一步 = 下发 T11**（`db` 单例连接跨线程不安全 —— 学生首屏历史列表不加载的根因，见技术债 T11 与 `docs/p5/review_qoder_p5_round2.md` §3），以及 `pf-03` 判据降级与 `personas` 只读投影的收尾小单。"
new = ("**下一步 = 下发 T11**（`db` 单例连接跨线程不安全 —— 学生首屏历史列表不加载的根因，"
       "见技术债 T11 与 `docs/p5/review_qoder_p5_round2.md` §3；执行者默认 WorkBuddy，"
       "开单指令由我写），以及 `pf-03` 判据降级与 `personas` 只读投影的收尾小单。"
       "**下下一单 T7（向量层 sqlite-vec）已排期给 Zcode**：开单指令 `docs/t7/zcode-order-t7.md` 已入库，"
       "**Gate 在 T11 合并之后**（单一写入者纪律），开工时我再补 `docs/t7/fixtures/` 三份向量物料让它全程零额度。")
if new in s:
    print("[skip] 已打过，幂等退出"); sys.exit(0)
assert s.count(old) == 1, f"锚点出现 {s.count(old)} 次，不唯一则不改"
p.write_text(s.replace(old, new, 1), encoding="utf-8")
print("[ok] TASKS.md 顶部持棒栏已同步 T7 排期")
