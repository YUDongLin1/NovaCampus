import asyncio
import json
import sys

sys.path.insert(0, ".")
from novaagent import config, db, rag  # noqa: E402

Q = {"qa-12": "研究生奖助学金评审是怎么规定的?",
     "qa-13": "学生在宿舍使用违章电器该怎么处理?"}


async def main():
    db.connect()
    print("FTS 可用=%s" % db._fts_ok)
    out = {}
    for cid, q in Q.items():
        row = {}
        for label, flag in (("stopwords_ON", True), ("stopwords_OFF", False)):
            config.KEYWORD_STOPWORDS_ENABLED = flag
            srcs, qual = await rag.search_with_quality(q, 1)
            row[label] = {"titles": [s["title"][:34] for s in srcs],
                          "scores": [round(float(s["score"]), 4) for s in srcs],
                          "top": qual.get("top_score"), "n_above": qual.get("n_above_threshold"),
                          "fused": qual.get("fused_candidates")}
        same = sorted(row["stopwords_ON"]["titles"]) == sorted(row["stopwords_OFF"]["titles"])
        row["same_set"] = same
        out[cid] = row
        print("[%s] 停用词开/关 来源集合相同=%s" % (cid, same))
        for label in ("stopwords_ON", "stopwords_OFF"):
            r = row[label]
            print("   %-13s top=%s n_above=%s fused=%s" % (label, r["top"], r["n_above"], r["fused"]))
            for t, s in zip(r["titles"], r["scores"]):
                print("        %-36s %s" % (t, s))
    json.dump(out, open("../docs/p4d/evidence/after/review_stopword_ab.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n[OK] 证据写入 docs/p4d/evidence/after/review_stopword_ab.json")


asyncio.run(main())
