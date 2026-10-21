"""追加研究九:「主力吸籌完成、準備發動」5 日策略(登記內容見 RESEARCH.md)。

用法:python -m research.accumulation
輸出:research/accumulation.json 與終端機摘要
"""
import json
import math
import os
from collections import deque

from chips import sources

from .census import RevFeats, Series
from .three_year import BENCH, C, V, hold, load

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "accumulation.json")
H = 5
WARMUP = 120
SPLITS = (0.6, 0.8)
COSTS = {"std": 0.585, "disc": 0.38}
TOP = 10


def prior_extreme(vals, w, kind):
    """每個位置 k 的「k 之前 w 天(不含 k)」最大或最小值;資料不全為 None。"""
    better = (lambda a, b: a >= b) if kind == "max" else (lambda a, b: a <= b)
    out, dq = [None] * len(vals), deque()
    for k in range(len(vals)):
        if k >= w and all(vals[j] is not None for j in (k - w, k - 1)) and dq and dq[0] >= k - w:
            out[k] = vals[dq[0]]
        v = vals[k]
        if v is None:
            dq.clear()
            continue
        while dq and better(v, vals[dq[-1]]):
            dq.pop()
        dq.append(k)
        while dq[0] <= k - w:
            dq.popleft()
    return out


def run():
    days, panel = load()
    margin = [sources.margins(d)[0] for d in days]
    S = Series(days, panel, margin)
    ext = {code: {"hi20": prior_extreme(s["close"], 20, "max"), "lo20": prior_extreme(s["close"], 20, "min"),
                  "hi60": prior_extreme(s["close"], 60, "max"), "lo60": prior_extreme(s["close"], 60, "min")}
           for code, s in S.f.items()}
    rf = RevFeats()
    signals = []   # (t, {rule: [codes]})
    for t in range(WARMUP, len(days) - H - 1):
        rev = rf.get(days[t])
        cands = {k: [] for k in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8")}
        for code, x in panel[t].items():
            if code == BENCH or not sources.is_common_stock(code) or x[C] < 10 or not S.full(code, t, 121):
                continue
            v20 = S.win(code, "vol", t - 1, 20) / 20
            if v20 <= 500:
                continue
            e = ext[code]
            hi20, lo20, hi60, lo60 = e["hi20"][t], e["lo20"][t], e["hi60"][t], e["lo60"][t]
            if not (hi20 and lo20 and hi60 and lo60):
                continue
            inst20 = S.win(code, "ins", t, 20) / v20
            trust20 = S.win(code, "tr", t, 20) / v20
            foreign20 = S.win(code, "fo", t, 20) / v20
            inst60 = S.win(code, "ins", t, 60) / v20
            range20, range60 = hi20 / lo20 - 1, hi60 / lo60 - 1
            breakout = x[C] > hi20 and x[V] >= 1.5 * v20
            close = S.f[code]["close"]
            ma20 = S.ma(code, t, 20)
            vol5 = S.win(code, "vol", t, 5) / 5
            m20 = S.win(code, "mg", t, 20)
            tdays15 = S.win(code, "tpos", t, 15)
            ret20 = close[t] / close[t - 20] - 1
            r = rev.get(code)
            momentum = bool(r and r["high3"] and r["yoy"] > 20)
            if inst20 >= 2 and range20 <= 0.12 and breakout:
                cands["A1"].append((code, inst20))
                if momentum:
                    cands["A7"].append((code, inst20))
            if trust20 >= 1 and range20 <= 0.12 and breakout:
                cands["A2"].append((code, trust20))
            if foreign20 >= 2 and range20 <= 0.12 and breakout:
                cands["A3"].append((code, foreign20))
            if inst20 >= 2 and range20 <= 0.10 and vol5 <= 0.8 * v20 and x[C] > ma20:
                cands["A4"].append((code, inst20))
                if m20 < 0:
                    cands["A5"].append((code, inst20))
            if tdays15 >= 10 and abs(ret20) <= 0.05:
                cands["A6"].append((code, trust20))
            if inst60 >= 4 and range60 <= 0.20 and x[C] > hi60 and x[V] >= 1.5 * v20:
                cands["A8"].append((code, inst60))
        signals.append((t, {k: [c for c, _ in sorted(v, key=lambda z: -z[1])[:TOP]] for k, v in cands.items()}))
    n = len(signals)
    c1, c2 = int(n * SPLITS[0]), int(n * SPLITS[1])
    seg_of = lambda i: "train" if i < c1 else "valid" if i < c2 else "test"
    names = {"A1": "A1 法人吸籌＋突破", "A2": "A2 投信吸籌＋突破", "A3": "A3 外資吸籌＋突破", "A4": "A4 法人吸籌＋量縮整理(未突破)",
             "A5": "A5 A4＋融資減少", "A6": "A6 投信連續買＋股價沒動", "A7": "A7 法人吸籌突破＋營收動能", "A8": "A8 法人長期吸籌＋突破60日高"}
    out = {}
    for key, label in names.items():
        for scen, cost in COSTS.items():
            seg = {"train": [], "valid": [], "test": []}
            by_date = []
            for i, (t, picks) in enumerate(signals):
                b = hold(panel, BENCH, t, H)
                if b is None or not picks[key]:
                    continue
                v = [(r - cost, r - cost - b) for c in picks[key] if (r := hold(panel, c, t, H)) is not None]
                seg[seg_of(i)].extend(v)
                if v:
                    by_date.append((t, sum(x for _, x in v) / len(v)))
            sample, last = [], -10 ** 9
            for t, x in by_date:
                if t - last >= H:
                    sample.append(x)
                    last = t
            if len(sample) > 2:
                mean = sum(sample) / len(sample)
                sd = math.sqrt(sum((x - mean) ** 2 for x in sample) / (len(sample) - 1))
                tstat = mean / (sd / math.sqrt(len(sample))) if sd else 0.0
            else:
                tstat = 0.0
            r = {k: {"trades": len(v), "ret": round(sum(a for a, _ in v) / len(v), 2) if v else None,
                     "excess": round(sum(x for _, x in v) / len(v), 2) if v else None,
                     "win": round(sum(1 for a, _ in v if a > 0) / len(v) * 100, 1) if v else None}
                 for k, v in seg.items()}
            ok = (all(r[k]["excess"] is not None and r[k]["excess"] > 0 for k in seg) and tstat >= 2.0
                  and all(r[k]["trades"] >= 50 for k in seg))
            out[f"{label} | {scen}"] = {**r, "tstat": round(tstat, 2), "samples": len(sample),
                                       "signalDays": len(by_date), "pass": ok}
    doc = {"segments": {"train": [str(days[signals[0][0]]), str(days[signals[c1 - 1][0]])],
                        "valid": [str(days[signals[c1][0]]), str(days[signals[c2 - 1][0]])],
                        "test": [str(days[signals[c2][0]]), str(days[signals[-1][0]])]},
           "results": out, "passed": [k for k, v in out.items() if v["pass"]]}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    return doc


if __name__ == "__main__":
    d = run()
    print("期間:", d["segments"])
    for k, v in d["results"].items():
        mark = "✅" if v["pass"] else "  "
        print(f"{mark} {k:<30} " + " | ".join(
            f"{s} {v[s]['trades']}筆 淨 {v[s]['ret']}% 超額 {v[s]['excess']}% 勝率 {v[s]['win']}%" for s in ("train", "valid", "test"))
              + f" | t {v['tstat']:+.2f}(樣本 {v['samples']},訊號日 {v['signalDays']})")
    print("通過:", d["passed"])
