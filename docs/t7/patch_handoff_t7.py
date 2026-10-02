import pathlib, sys
p = pathlib.Path("HANDOFF.md"); s = p.read_text(encoding="utf-8")
marker = "\n## 六、踩坑清单"
ROOT = "E:" + chr(92) + "AILearn" + chr(92) + "NovaCampus"
new_para = (
"\n**T7 已排期给 Zcode（2026-10-02，`docs/t7/zcode-order-t7.md`，尚未开工）**：负责人指定「下下一单交给 Zcode」。"
"**Gate 在 T11 合并之后**（本项目同一时刻只有一个写入者，T11 期间主工作树 `" + ROOT + "` 归 WorkBuddy），"
"所以这份指令是**先入库待命**，Zcode 收到不许动手，等我发「开工」信号。"
"本单定位已写死在指令 §0：**487 块量下向量暴力扫描不是性能瓶颈**，收益写的是可扩展性 + 单文件架构一致性 + "
"可验证的工程判断，验收核心是**等价性**（新旧路径 top-12 `chunk_id` 集合一致率 100%、误差 ≤1e-5），不是速度 —— "
"防止做成『为换库而换库』。**零额度保障**：开工时我另交 `docs/t7/fixtures/`（全库块向量 / 30 条查询向量 / "
"现网 numpy 的 top-12 基线），Zcode 不需要任何 key；fixture 里 30 次 embedding 由我在负责人授权后跑，"
"**故意不在本时点生成**，因为 T11 要改 `db.py`、语料也可能动，提前做出来的基线会过期。\n"
)
if "T7 已排期给 Zcode" in s:
    print("[skip] 已打过"); sys.exit(0)
assert s.count(marker) == 1, s.count(marker)
p.write_text(s.replace(marker, new_para + marker, 1), encoding="utf-8")
print("[ok] HANDOFF next-step section updated")
