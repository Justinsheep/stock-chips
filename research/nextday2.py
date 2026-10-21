"""追加研究六:隔日沖第二輪(登記內容見 RESEARCH.md)。

用法:python -m research.nextday2
輸出:research/nextday2.json 與終端機摘要
"""
import json
import math
import os

from .three_year import BENCH, C, F, H, I, L, O, T, V, WARMUP, jump, load, segment_dates, seg_split

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nextday2.json")
COSTS = {"std": 0.585, "disc": 0.38}
TP = 2.0


def tick(p):
    for limit, t in ((10, 0.01), (50, 0.05), (100, 0.1), (500, 0.5), (1000, 1)):
        if p < limit:
            return t
    return 5


def limit_up(prev_close):
    raw = prev_close * 1.1
    t = tick(raw)
    return round(math.floor(round(raw / t, 6)) * t, 2)


def picks_for(t, panel):
    prev, today = panel[t - 1], panel[t]
    b0, b1 = prev.get(BENCH), today.get(BENCH)
    bench_up = bool(b0 and b1 and b1[C] > b0[C])
    g = {k: [] for k in ("G1", "G2", "G3", "G4", "N2", "G7", "G8", "G9", "G10")}
    for code, x in today.items():
        p = prev.get(code)
        if code == BENCH or not p or x[C] < 10 or p[C] <= 0 or x[V] <= 0:
            continue
        hist = [panel[k].get(code) for k in range(t - 20, t)]
        if any(h is None for h in hist):
            continue
        vol20 = sum(h[V] for h in hist) / 20
        if vol20 <= 1000:
            continue
        chg = (x[C] / p[C] - 1) * 100
        surge = x[V] / vol20
        lu = limit_up(p[C])
        item = (code, surge)
        if lu - 2 * tick(lu) - 1e-9 <= x[C] < lu - 1e-9 and abs(x[C] - x[H]) < 1e-9 and surge >= 2:
            g["G1"].append(item)
            if x[I] > 0:
                g["G2"].append(item)
        strong = 5 <= chg < 9.5 and x[C] >= 0.98 * x[H] and surge >= 2 and x[I] > 0
        if strong:
            g["N2"].append(item)
            if bench_up:
                g["G3"].append(item)
            closes60 = [h[C] for k in range(t - 59, t + 1) if (h := panel[k].get(code))]
            if len(closes60) == 60 and x[C] >= max(closes60):
                g["G4"].append(item)
            if x[C] <= 50:
                g["G9"].append(item)
            if vol20 > 3000:
                g["G10"].append(item)
        if x[F] >= 0.1 * x[V] and chg >= 3 and x[C] >= 0.98 * x[H]:
            g["G7"].append(item)
        prior = [panel[k].get(code) for k in range(t - 9, t)]
        if chg > 0 and all(h is not None and h[T] <= 0 for h in prior) and x[T] >= 0.05 * x[V]:
            g["G8"].append(item)
    return {k: [c for c, _ in sorted(v, key=lambda z: -z[1])[:10]] for k, v in g.items()}


def overnight(panel, code, t, mode):
    """T 收盤買。mode=open:T+1 開盤賣;mode=tp:T+1 停利 2% 否則收盤賣。回傳毛報酬 %。"""
    a, b = panel[t].get(code), panel[t + 1].get(code)
    if not a or not b or b[O] <= 0 or jump(panel, code, t + 1, t + 1):
        return None
    if mode == "open":
        return (b[O] / a[C] - 1) * 100
    target = a[C] * (1 + TP / 100)
    if b[O] >= target:
        return (b[O] / a[C] - 1) * 100
    if b[H] >= target:
        return TP
    return (b[C] / a[C] - 1) * 100


PLAN = {
    "G1 差一點漲停:收盤買→隔天開盤賣": ("G1", "open"),
    "G2 差一點漲停＋法人:收盤買→隔天開盤賣": ("G2", "open"),
    "G3 強勢收高＋法人＋0050 上漲:隔天開盤賣": ("G3", "open"),
    "G4 強勢收高＋法人＋創 60 日新高:隔天開盤賣": ("G4", "open"),
    "G5 強勢收高＋法人:隔天停利 2%": ("N2", "tp"),
    "G6 差一點漲停:隔天停利 2%": ("G1", "tp"),
    "G7 外資大買收高:隔天開盤賣": ("G7", "open"),
    "G8 投信第一天進場:隔天開盤賣": ("G8", "open"),
    "G9 強勢收高＋法人,10～50 元:隔天開盤賣": ("G9", "open"),
    "G10 強勢收高＋法人,均量>3000 張:隔天開盤賣": ("G10", "open"),
}


def run():
    days, panel = load()
    rows = [(t, picks_for(t, panel)) for t in range(WARMUP, len(days) - 1)]
    seg_of, _ = seg_split(rows)
    out = {}
    for name, (grp, mode) in PLAN.items():
        acc = {"train": [], "valid": [], "test": []}
        for i, (t, picks) in enumerate(rows):
            acc[seg_of(i)].extend(x for c in picks[grp] if (x := overnight(panel, c, t, mode)) is not None)
        out[name] = {}
        for s, v in acc.items():
            g = sum(v) / len(v) if v else None
            out[name][s] = {"trades": len(v), "gross": round(g, 3) if v else None,
                            "netStd": round(g - COSTS["std"], 3) if v else None,
                            "netDisc": round(g - COSTS["disc"], 3) if v else None,
                            "winStd": round(sum(1 for x in v if x > COSTS["std"]) / len(v) * 100, 1) if v else None,
                            "perDay": round(len(v) / max(1, sum(1 for j, _ in enumerate(rows) if seg_of(j) == s)), 2)}
    ok = lambda k, key, segs: all(out[k][s][key] is not None and out[k][s][key] > 0 for s in segs)
    s1 = [k for k in out if ok(k, "netStd", ["train"])]
    s2 = [k for k in s1 if ok(k, "netStd", ["valid"])]
    chosen = max(s2, key=lambda k: out[k]["train"]["netStd"]) if s2 else None
    d1 = [k for k in out if ok(k, "netDisc", ["train"])]
    d2 = [k for k in d1 if ok(k, "netDisc", ["valid"])]
    chosen_d = max(d2, key=lambda k: out[k]["train"]["netDisc"]) if d2 else None
    doc = {"segments": segment_dates(days, rows), "results": out,
           "std": {"stage1": s1, "stage2": s2, "chosen": chosen, "passed": bool(chosen and ok(chosen, "netStd", ["test"]))},
           "disc": {"stage1": d1, "stage2": d2, "chosen": chosen_d,
                    "passed": bool(chosen_d and ok(chosen_d, "netDisc", ["test"]))}}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    return doc


if __name__ == "__main__":
    d = run()
    print("期間:", d["segments"])
    for k, v in d["results"].items():
        print(f"{k}\n   " + " | ".join(f"{s} {v[s]['trades']}筆({v[s]['perDay']}/天) 毛 {v[s]['gross']}% 淨(0.585) {v[s]['netStd']}% 淨(0.38) {v[s]['netDisc']}% 勝率 {v[s]['winStd']}%"
                                    for s in ("train", "valid", "test")))
    print("標準成本:", d["std"])
    print("2.8 折成本:", d["disc"])
