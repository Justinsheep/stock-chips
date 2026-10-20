"""追加研究二:R2 條件不變,改依籌碼分數排序取前 10(登記內容見 RESEARCH.md)。

用法:python -m research.rank_by_score
"""
import json
import os

from chips.revenue import Revenue
from chips.score import pct_rank

from . import engine as E

OUT = os.path.join(E.ROOT, "rank_by_score.json")
H = 20


def chip_scores(f):
    codes = list(f)
    r1 = pct_rank([f[c]["inst1"] / f[c]["avg5"] for c in codes])
    r5 = pct_rank([f[c]["inst5"] / (f[c]["avg5"] * 5) for c in codes])
    rs = pct_rank([f[c]["fStreak"] + f[c]["tStreak"] * 1.5 for c in codes])
    rm = pct_rank([-f[c]["margin"] / f[c]["avg5"] for c in codes])
    return {c: a * 25 + b * 25 + s * 10 + m * 15 for c, a, b, s, m in zip(codes, r1, r5, rs, rm)}


def run():
    days, panel, margin = E.load_panel()
    rev, rev_cache = Revenue(), {}
    rows = []
    for t in range(20, len(days) - H):
        f = E.features(t, panel, margin)
        key = days[t].strftime("%Y%m") + ("b" if days[t].day > 10 else "a")
        if key not in rev_cache:
            rev_cache[key] = rev.momentum(days[t])
        r = rev_cache[key]
        base = E.RULES["R2 投信買超+營收動能"](f, r)
        sc = chip_scores(f)
        pool = [c for c, x in f.items() if x["trust10"] > 15 and E.rev_ok(c, r)]
        by_score = sorted(pool, key=lambda c: -sc[c])[:E.TOP]
        rows.append((t, {"R2 依投信買超(原版)": base, "R2 依籌碼分數": by_score}))
    n = len(rows)
    cut1, cut2 = int(n * E.SPLITS[0]), int(n * E.SPLITS[1])
    seg_of = lambda i: "train" if i < cut1 else "valid" if i < cut2 else "test"
    out = {}
    for name in rows[0][1]:
        seg = {"train": [], "valid": [], "test": []}
        for i, (t, picks) in enumerate(rows):
            b = E.hold_return(panel, E.BENCH, t, H)
            if b is None:
                continue
            rets = [x for c in picks[name] if (x := E.hold_return(panel, c, t, H)) is not None]
            ret = sum(rets) / len(rets) - E.COST if rets else 0.0
            seg[seg_of(i)].append(ret - b)
        out[name] = {k: round(sum(v) / len(v), 2) for k, v in seg.items()}
    a, b = out["R2 依籌碼分數"], out["R2 依投信買超(原版)"]
    passed = all(a[k] > 0 and a[k] > b[k] for k in ("train", "valid", "test"))
    doc = {"results": out, "passed": passed}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    return doc


if __name__ == "__main__":
    d = run()
    for k, v in d["results"].items():
        print(f"{k:<14} 訓練 {v['train']:+.2f}% 驗證 {v['valid']:+.2f}% 測試 {v['test']:+.2f}%")
    print("通過:", d["passed"])
