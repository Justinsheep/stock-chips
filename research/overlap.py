"""探索性比較(看過資料後才做,非預先登記):同時在「投信買超＋營收動能」與「好股回檔」的股票,
跟只在投信＋營收名單的股票比,持有 5 日、20 日的每筆表現。

用法:python -m research.overlap
輸出:research/overlap.json
"""
import json
import os

from chips.revenue import Revenue

from . import engine as E
from . import swing5 as S

OUT = os.path.join(E.ROOT, "overlap.json")


def run():
    E.START, E.END = S.START, S.END
    days, panel, margin = E.load_panel()
    rev, rc = Revenue(), {}
    rows = []
    for t in range(S.WARMUP, len(days) - 1):
        f, g = E.features(t, panel, margin), S.feats(t, panel)
        key = days[t].strftime("%Y%m") + ("b" if days[t].day > 10 else "a")
        if key not in rc:
            rc[key] = rev.momentum(days[t])
        rows.append((t, E.RULES["R2 投信買超+營收動能"](f, rc[key]), S.signals(g, rc[key])["F2 好股回檔"]))
    n = len(rows)
    cut1, cut2 = int(n * E.SPLITS[0]), int(n * E.SPLITS[1])
    seg_of = lambda i: "train" if i < cut1 else "valid" if i < cut2 else "test"
    out = {"segments": {"train": [str(days[rows[0][0]]), str(days[rows[cut1 - 1][0]])],
                        "valid": [str(days[rows[cut1][0]]), str(days[rows[cut2 - 1][0]])],
                        "test": [str(days[rows[cut2][0]]), str(days[rows[-1][0]])]}, "results": {}}
    for h in (5, 20):
        acc = {}
        for i, (t, r2, f2) in enumerate(rows):
            if t + h >= len(days):
                continue
            b = E.hold_return(panel, E.BENCH, t, h)
            if b is None:
                continue
            groups = {"both": [c for c in r2 if c in f2], "mainOnly": [c for c in r2 if c not in f2], "mainAll": r2}
            for name, codes in groups.items():
                for c in codes:
                    r = E.hold_return(panel, c, t, h)
                    if r is not None:
                        acc.setdefault(name, {}).setdefault(seg_of(i), []).append((r - E.COST, r - E.COST - b))
        out["results"][str(h)] = {name: {s: {"n": len(v), "ret": round(sum(a for a, _ in v) / len(v), 2),
                                             "excess": round(sum(x for _, x in v) / len(v), 2),
                                             "win": round(sum(1 for a, _ in v if a > 0) / len(v) * 100, 1)}
                                         for s, v in segs.items()} for name, segs in acc.items()}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    d = run()
    for h, r in d["results"].items():
        print(f"持有 {h} 日")
        for name, segs in r.items():
            print(f"  {name:<9}", " | ".join(f"{s} {v['n']}筆 報酬 {v['ret']:+.2f}% 超額 {v['excess']:+.2f}%" for s, v in segs.items()))
