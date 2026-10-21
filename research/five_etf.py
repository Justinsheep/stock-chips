"""追加研究八:5 日第三輪(ETF 輪動、擇時、外資大買 5 日)。登記內容見 RESEARCH.md。

用法:python -m research.five_etf
輸出:research/five_etf.json 與終端機摘要
"""
import json
import math
import os

from chips import sources

from .nextday2 import picks_for
from .three_year import BENCH, C, V, adjusted_closes, hold, load

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "five_etf.json")
H = 5
WARMUP = 120
SPLITS = (0.6, 0.8)
BASKET = ["0050", "006208", "0051", "0052", "0056", "00878", "00891", "00881", "00692", "00850", "00713", "00919"]
LEV = "00631L"
COST = {"etf": {"std": 0.385, "disc": 0.18}, "stock": {"std": 0.585, "disc": 0.38}}


def add_etfs(days, panel):
    for k, d in enumerate(days):
        p = sources.twse_price(d) or {}
        for e in BASKET + [LEV]:
            x = p.get(e)
            if x and x["close"] > 0 and e not in panel[k]:
                panel[k][e] = (x["open"], x["high"], x["low"], x["close"], x["vol"] / 1000, 0.0, 0.0, 0.0)


def run():
    days, panel = load()
    add_etfs(days, panel)
    adj = {e: adjusted_closes(panel, e) for e in BASKET + [LEV]}
    b = adj[BENCH]
    ma = lambda t, w: (sum(b[t - w + 1:t + 1]) / w) if all(b[t - w + 1:t + 1]) else None
    rows = []
    for t in range(WARMUP, len(days) - H - 1):
        mom = lambda w: sorted(((e, adj[e][t] / adj[e][t - w] - 1) for e in BASKET if adj[e][t] and adj[e][t - w]),
                               key=lambda z: -z[1])
        m20, m60 = mom(20), mom(60)
        ma20, ma60 = ma(t, 20), ma(t, 60)
        up20, up60 = bool(ma20 and b[t] > ma20), bool(ma60 and b[t] > ma60)
        g = picks_for(t, panel)["G7"]
        big = []
        for c in g:
            hist = [panel[k].get(c) for k in range(t - 20, t)]
            if all(hist) and sum(h[V] for h in hist) / 20 > 3000:
                big.append(c)
        rows.append((t, {
            "E1 ETF 20日動能第1": ("etf", [m20[0][0]] if m20 else []),
            "E2 ETF 20日動能前3": ("etf", [e for e, _ in m20[:3]]),
            "E3 ETF 60日動能第1": ("etf", [m60[0][0]] if m60 else []),
            "E4 0050 站上月線才持有": ("etf", [BENCH] if up20 else []),
            "E5 00631L 0050站上季線才持有": ("etf", [LEV] if up60 else []),
            "E6 00631L 0050站上月線且季線": ("etf", [LEV] if up20 and up60 else []),
            "K1 外資大買收高 持有5日": ("stock", g),
            "K2 外資大買收高(大型) 持有5日": ("stock", big),
        }))
    n = len(rows)
    c1, c2 = int(n * SPLITS[0]), int(n * SPLITS[1])
    seg_of = lambda i: "train" if i < c1 else "valid" if i < c2 else "test"
    out = {}
    for name in rows[0][1]:
        for scen in ("std", "disc"):
            seg = {"train": [], "valid": [], "test": []}
            trades = dict.fromkeys(seg, 0)
            series = []
            for i, (t, picks) in enumerate(rows):
                bench = hold(panel, BENCH, t, H)
                if bench is None:
                    continue
                kind, codes = picks[name]
                rets = [r for c in codes if (r := hold(panel, c, t, H)) is not None]
                ret = sum(rets) / len(rets) - COST[kind][scen] if rets else 0.0   # 空手 = 現金
                s = seg_of(i)
                seg[s].append((ret, ret - bench))
                trades[s] += len(rets)
                series.append((ret, ret - bench))
            nonover = [x for k, x in enumerate(series) if k % H == 0]
            ex = [x for _, x in nonover]
            mean = sum(ex) / len(ex)
            sd = math.sqrt(sum((x - mean) ** 2 for x in ex) / (len(ex) - 1))
            tstat = mean / (sd / math.sqrt(len(ex))) if sd else 0.0
            eq, peak, mdd = 1.0, 1.0, 0.0
            for r, _ in nonover:
                eq *= 1 + r / 100
                peak = max(peak, eq)
                mdd = min(mdd, eq / peak - 1)
            r = {k: {"ret": round(sum(a for a, _ in v) / len(v), 3), "excess": round(sum(x for _, x in v) / len(v), 3),
                     "monthly": round(((1 + sum(a for a, _ in v) / len(v) / 100) ** (21 / H) - 1) * 100, 1),
                     "trades": trades[k]} for k, v in seg.items()}
            timing = name[:2] in ("E4", "E5", "E6")
            ok = (all(r[k]["excess"] > 0 for k in seg) and tstat >= 2.0
                  and (timing or all(r[k]["trades"] >= 100 for k in seg)))
            out[f"{name} | {scen}"] = {**r, "tstat": round(tstat, 2), "maxDrawdown": round(mdd * 100, 1), "pass": ok}
    doc = {"segments": {"train": [str(days[rows[0][0]]), str(days[rows[c1 - 1][0]])],
                        "valid": [str(days[rows[c1][0]]), str(days[rows[c2 - 1][0]])],
                        "test": [str(days[rows[c2][0]]), str(days[rows[-1][0]])]},
           "results": out, "passed": [k for k, v in out.items() if v["pass"]]}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    return doc


if __name__ == "__main__":
    d = run()
    print("期間:", d["segments"])
    for k, v in d["results"].items():
        mark = "✅" if v["pass"] else "  "
        print(f"{mark} {k:<34} " + " | ".join(f"{s} 5日 {v[s]['ret']:+.2f}% 超額 {v[s]['excess']:+.2f}% 月化 {v[s]['monthly']:+.1f}%"
                                               for s in ("train", "valid", "test")) + f" | t {v['tstat']:+.2f} 最大回撤 {v['maxDrawdown']}%")
    print("通過:", d["passed"])
