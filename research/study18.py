"""研究十八:2013～2017 全新檢驗期＋擴大搜尋(登記見 RESEARCH.md)。

explore:2018-07 ～ 2026-07 探索 1,224 條(408 規則 × 持有 20/40/60),依登記選法凍結 10 條 → study18_frozen.json
holdout:2013-07 ～ 2017-12 檢驗凍結的 10 條與既有候選 → study18.json
用法:python -m research.study18 explore | holdout
"""
import gc
import json
import math
import os
import sys

from chips import sources
from . import census as CE
from . import dividends as DV
from . import grid as G
from . import three_year as TY

ROOT = os.path.dirname(os.path.abspath(__file__))
FROZEN = os.path.join(ROOT, "study18_frozen.json")
EXPLORE_OUT = os.path.join(ROOT, "study18_explore.json")
OUT = os.path.join(ROOT, "study18.json")
HS = (20, 40, 60)
COST = 0.585
EXPLORE = [("20180101", "20230705", "2018-07-02", "2023-03-31"),
           ("20221101", "20261020", "2023-04-01", "2026-07-20")]
HOLDOUT = [("20130101", "20180430", "2013-07-01", "2017-12-31")]
MAIN = "投信10日>15張+營收動能+無價格條件|依投信買超"
ALT1 = "外資10日買超+營收動能+60日漲|依投信買超"
ALT3 = "無籌碼條件+單月營收新高+均線多頭|依投信買超"


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def tstat_step(xs, step):
    pts = [x for k, x in enumerate(xs) if k % step == 0 and x is not None]
    if len(pts) < 3:
        return 0.0
    m = sum(pts) / len(pts)
    sd = math.sqrt(sum((x - m) ** 2 for x in pts) / (len(pts) - 1))
    return m / (sd / math.sqrt(len(pts))) if sd else 0.0


def collect(windows, only=None, keep_picks=False):
    """回傳 dates、{規則: {H: [每 20 日等值超額]}}、(選擇性){規則: [每日名單]}、主名單候選(給甲 2/甲 3 用)。"""
    div = DV.load(2013, 2026)
    rules = {k: v for k, v in G.rule_names() if only is None or k in only}
    dates, series, picks_all, main_rows = [], {k: {h: [] for h in HS} for k in rules}, {k: [] for k in rules}, []
    for start, end, a, b in windows:
        TY.START, TY.END = start, end
        days, panel = TY.load()
        margin = [sources.margins(d)[0] for d in days]
        S = CE.Series(days, panel, margin)
        rf = CE.RevFeats()
        adj = TY.adjusted_closes(panel, TY.BENCH)

        def trade(code, t, h):
            if t + h >= len(panel) or TY.jump(panel, code, t + 1, t + h):
                return None
            x, y = panel[t + 1].get(code), panel[t + h].get(code)
            if not x or not y or x[TY.O] <= 0 or y[TY.O] <= 0:
                return None
            d0, d1 = days[t + 1], days[t + h]
            dv = sum(v for d, v in div.get(code, {}).items() if d0 < d <= d1)
            return (y[TY.O] + dv) / x[TY.O] - 1

        for t in range(CE.WARMUP, len(days) - max(HS) - 1):
            d = str(days[t])
            if not (a <= d <= b):
                continue
            rev = rf.get(days[t])
            feats = {c: fx for c in panel[t] if c != TY.BENCH and sources.is_common_stock(c)
                     and (fx := CE.features(S, c, t, rev))}
            order = {name: sorted(feats, key=lambda c, f=f: -f(feats[c])) for name, f in G.RANK.items()}
            cache = {}

            def ret(code, h):
                if (code, h) not in cache:
                    cache[(code, h)] = trade(code, t, h)
                return cache[(code, h)]
            bench = {h: ret(TY.BENCH, h) for h in HS}
            dates.append(d)
            for key, (c, v, p, r) in rules.items():
                fc, fv, fp = G.CHIP[c], G.REV[v], G.PRICE[p]
                chosen = []
                for code in order[r]:
                    fx = feats[code]
                    if (fc is None or fc(fx)) and (fv is None or fv(fx["rev"])) and (fp is None or fp(fx)):
                        chosen.append(code)
                        if len(chosen) == G.TOP:
                            break
                if keep_picks:
                    picks_all[key].append(chosen)
                for h in HS:
                    rs = [x for code in chosen if (x := ret(code, h)) is not None]
                    if not rs or bench[h] is None:
                        series[key][h].append(None)
                        continue
                    m = sum(rs) / len(rs) - COST / 100
                    series[key][h].append(((1 + m) ** (20 / h) - (1 + bench[h]) ** (20 / h)) * 100)
            if only is not None and MAIN in rules:
                c, v, p, r = rules[MAIN]
                cand = [code for code in order[r] if G.CHIP[c](feats[code]) and G.REV[v](feats[code]["rev"])][:25]
                tr = {}
                for code in cand + [TY.BENCH]:
                    x = ret(code, 20)
                    e = panel[t + 1].get(code)
                    tr[code] = None if x is None or not e else [e[TY.O], x * 100]
                ma120 = sum(adj[t - 119:t + 1]) / 120 if all(adj[t - 119:t + 1]) else None
                main_rows.append({"d": d, "cand": [[code, round(feats[code]["ret20"] * 100, 2), tr[code] and [tr[code][0], tr[code][1], 0.0]] for code in cand],
                                  "bench": tr[TY.BENCH] and [tr[TY.BENCH][0], tr[TY.BENCH][1], 0.0],
                                  "weak120": None if ma120 is None else adj[t] < ma120, "foreignSell": False})
            if len(dates) % 100 == 0:
                print(f"已算 {len(dates)} 天,到 {d}", flush=True)
        del S, panel
        gc.collect()
    return dates, series, picks_all, main_rows


def explore():
    dates, series, picks, _ = collect(EXPLORE, keep_picks=True)
    n = len(dates)
    thirds = [(0, n // 3), (n // 3, 2 * n // 3), (2 * n // 3, n)]
    stats = []
    for key in series:
        for h in HS:
            xs = series[key][h]
            segs = [_mean(xs[a:b]) for a, b in thirds]
            stats.append({"rule": key, "H": h, "excess": round(_mean(xs) or 0, 2), "t": round(tstat_step(xs, h), 2),
                          "thirds": [None if s is None else round(s, 2) for s in segs],
                          "avgPicks": round(sum(len(p) for p in picks[key]) / n, 1)})
    ok = [s for s in stats if all(x is not None and x > 0 for x in s["thirds"])]
    ok.sort(key=lambda s: -s["t"])

    def jaccard(a, b):
        vals = [len(set(x) & set(y)) / len(set(x) | set(y)) for x, y in zip(picks[a], picks[b]) if x or y]
        return sum(vals) / len(vals) if vals else 0.0
    frozen = []
    for s in ok:
        if all(s["rule"] != f["rule"] and jaccard(s["rule"], f["rule"]) <= 0.6 for f in frozen):
            frozen.append(s)
        if len(frozen) == 10:
            break
    with open(EXPLORE_OUT, "w", encoding="utf-8") as f:
        json.dump({"from": dates[0], "to": dates[-1], "days": n, "rules": len(stats), "allThirdsPositive": len(ok),
                   "top50": ok[:50]}, f, ensure_ascii=False, indent=1)
    with open(FROZEN, "w", encoding="utf-8") as f:
        json.dump(frozen, f, ensure_ascii=False, indent=1)
    print(f"探索 {len(stats)} 條、三段皆正 {len(ok)} 條;凍結:")
    for s in frozen:
        print(" ", s)


if __name__ == "__main__":
    {"explore": explore}[sys.argv[1]]()
