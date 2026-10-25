"""研究二十:價值因子、大型股、多因子打分(登記見 RESEARCH.md)。

collect :2013-07 ～ 2026-09 逐日算 792 條網格＋6 條多因子的每 20 日超額 → study20_rows.json(不進版控)
explore :只讀 2019-12 以前,依登記選法凍結 10 條網格規則 → study20_frozen.json
validate:讀 2020-01 以後,檢驗 16 條 → study20.json
用法:python -m research.study20 collect | explore | validate
"""
import gc
import heapq
import itertools
import json
import math
import os
import sys

from chips import sources
from . import census as CE
from . import dividends as DV
from . import grid as G
from . import three_year as TY
from .valuation import day as val_day

ROOT = os.path.dirname(os.path.abspath(__file__))
ROWS = os.path.join(ROOT, "study20_rows.json")
FROZEN = os.path.join(ROOT, "study20_frozen.json")
EXPLORE_OUT = os.path.join(ROOT, "study20_explore.json")
OUT = os.path.join(ROOT, "study20.json")
H, COST, TOP, BIG = 20, 0.585, 10, 150
SPLIT = "2020-01-01"
WINDOWS = [("20130101", "20180430", "2013-07-01", "2017-12-31"),
           ("20170701", "20230405", "2018-01-01", "2022-12-31"),
           ("20220701", "20261020", "2023-01-01", "2026-09-16")]

CHIP = {"投信10日>15張": lambda x: x["t10"] > 15, "外資10日買超": lambda x: x["f10"] > 0,
        "法人20日買超": lambda x: x["i20"] > 0, "融資10日減少": lambda x: x["m10"] < 0, "無籌碼條件": None}
REV = {k: G.REV[k] for k in ("營收動能", "單月營收新高", "年增>30%", "無營收條件")}
VAL = {"無價值條件": None,
       "本益比0~15": lambda x: x["pe"] is not None and 0 < x["pe"] <= 15,
       "本益比0~25": lambda x: x["pe"] is not None and 0 < x["pe"] <= 25,
       "殖利率>4%": lambda x: x["dy"] is not None and x["dy"] > 4,
       "淨值比<2": lambda x: x["pb"] is not None and 0 < x["pb"] < 2}
PRICE = {"無價格條件": None, "站上季線": lambda x: x["c"] > x["ma60"]}
UNIV = ("全部", "大型股")
RANK = {"依投信買超": lambda x: -x["t10"], "依本益比低": lambda x: x["pe"] if x["pe"] and x["pe"] > 0 else 1e9}
MULTI = {"M1 四項等權": (("chip", "rev", "mom", "val"), "全部", False), "M2 籌碼＋營收＋動能": (("chip", "rev", "mom"), "全部", False),
         "M3 籌碼＋營收": (("chip", "rev"), "全部", False), "M4 營收＋價值": (("rev", "val"), "全部", False),
         "M5 四項等權・大型股": (("chip", "rev", "mom", "val"), "大型股", False), "M6 四項等權・營收年增>0": (("chip", "rev", "mom", "val"), "全部", True)}


def rule_names():
    for c, v, val, p, u, r in itertools.product(CHIP, REV, VAL, PRICE, UNIV, RANK):
        if CHIP[c] is None and REV[v] is None and VAL[val] is None:
            continue
        yield f"{c}+{v}+{val}+{p}+{u}|{r}", (c, v, val, p, u, r)


def _pct(codes, key):
    """{代號: 0～1 百分位};key 回傳 None 的給 0。"""
    vals = sorted((key(c), c) for c in codes if key(c) is not None)
    n = len(vals)
    out = {c: 0.0 for c in codes}
    for i, (_, c) in enumerate(vals):
        out[c] = (i + 1) / n
    return out


def collect():
    div = DV.load(2013, 2026)
    rules = dict(rule_names())
    rows = []
    for start, end, a, b in WINDOWS:
        TY.START, TY.END = start, end
        days, panel = TY.load()
        margin = [sources.margins(d)[0] for d in days]
        S = CE.Series(days, panel, margin)
        rf = CE.RevFeats()

        def trade(code, t):
            if t + H >= len(panel) or TY.jump(panel, code, t + 1, t + H):
                return None
            x, y = panel[t + 1].get(code), panel[t + H].get(code)
            if not x or not y or x[TY.O] <= 0 or y[TY.O] <= 0:
                return None
            d0, d1 = days[t + 1], days[t + H]
            return (y[TY.O] + sum(v for d, v in div.get(code, {}).items() if d0 < d <= d1)) / x[TY.O] - 1

        for t in range(CE.WARMUP, len(days) - H - 1):
            d = str(days[t])
            if not (a <= d <= b):
                continue
            rev = rf.get(days[t])
            vals = val_day(days[t])
            feats = {}
            for c in panel[t]:
                if c == TY.BENCH or not sources.is_common_stock(c):
                    continue
                fx = CE.features(S, c, t, rev)
                if fx:
                    pe, dy, pb = vals.get(c, (None, None, None))
                    fx.update(pe=pe, dy=dy, pb=pb, value=fx["v20"] * fx["c"])
                    feats[c] = fx
            big = set(sorted(feats, key=lambda c: -feats[c]["value"])[:BIG])
            cache = {}

            def ret(code):
                if code not in cache:
                    cache[code] = trade(code, t)
                return cache[code]
            bench = ret(TY.BENCH)
            if bench is None:
                continue
            out = {}

            def score(chosen):
                rs = [x for c in chosen if (x := ret(c)) is not None]
                return None if not rs else round((sum(rs) / len(rs) - COST / 100 - bench) * 100, 3)
            allc = set(feats)
            sets = {"c": {k: allc if f is None else {c for c in feats if f(feats[c])} for k, f in CHIP.items()},
                    "v": {k: allc if f is None else {c for c in feats if f(feats[c]["rev"])} for k, f in REV.items()},
                    "val": {k: allc if f is None else {c for c in feats if f(feats[c])} for k, f in VAL.items()},
                    "p": {k: allc if f is None else {c for c in feats if f(feats[c])} for k, f in PRICE.items()},
                    "u": {"全部": allc, "大型股": big}}
            rank_val = {name: {c: f(feats[c]) for c in feats} for name, f in RANK.items()}
            for key, (c, v, val, p, u, r) in rules.items():
                cand = sets["c"][c] & sets["v"][v] & sets["val"][val] & sets["p"][p] & sets["u"][u]
                rv = rank_val[r]
                chosen = heapq.nsmallest(TOP, cand, key=lambda code: (rv[code], code))
                out[key] = [score(chosen), ",".join(chosen) if d < SPLIT else None]
            for name, (factors, u, need_yoy) in MULTI.items():
                pool = [c for c in feats if (u == "全部" or c in big)
                        and (not need_yoy or (feats[c]["rev"] and feats[c]["rev"]["yoy"] > 0))]
                ranks = {"chip": _pct(pool, lambda c: feats[c]["t10"] / feats[c]["v20"]),
                         "rev": _pct(pool, lambda c: feats[c]["rev"]["yoy"] if feats[c]["rev"] else None),
                         "mom": _pct(pool, lambda c: feats[c]["ret60"]),
                         "val": _pct(pool, lambda c: 1 / feats[c]["pe"] if feats[c]["pe"] and feats[c]["pe"] > 0 else None)}
                chosen = sorted(pool, key=lambda c: -sum(ranks[f][c] for f in factors))[:TOP]
                out[name] = [score(chosen), None]
            rows.append({"d": d, "x": out})
            if len(rows) % 100 == 0:
                print(f"已算 {len(rows)} 天,到 {d}", flush=True)
        del S, panel
        gc.collect()
    with open(ROWS, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
    print(f"完成:{len(rows)} 天", flush=True)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def tstat(xs, step=H):
    pts = [x for k, x in enumerate(xs) if k % step == 0 and x is not None]
    if len(pts) < 3:
        return 0.0
    m = sum(pts) / len(pts)
    sd = math.sqrt(sum((x - m) ** 2 for x in pts) / (len(pts) - 1))
    return m / (sd / math.sqrt(len(pts))) if sd else 0.0


def explore():
    rows = [r for r in json.load(open(ROWS, encoding="utf-8")) if r["d"] < SPLIT]
    n = len(rows)
    thirds = [(0, n // 3), (n // 3, 2 * n // 3), (2 * n // 3, n)]
    stats = []
    for key, _ in rule_names():
        xs = [r["x"][key][0] for r in rows]
        segs = [_mean(xs[a:b]) for a, b in thirds]
        stats.append({"rule": key, "excess": round(_mean(xs) or 0, 2), "t": round(tstat(xs), 2),
                      "thirds": [None if s is None else round(s, 2) for s in segs],
                      "avgPicks": round(sum(len(list(filter(None, r["x"][key][1].split(",")))) for r in rows) / n, 1)})
    ok = sorted((s for s in stats if all(x is not None and x > 0 for x in s["thirds"])), key=lambda s: -s["t"])

    def jaccard(a, b):
        v = []
        for r in rows:
            x, y = set(filter(None, r["x"][a][1].split(","))), set(filter(None, r["x"][b][1].split(",")))
            if x or y:
                v.append(len(x & y) / len(x | y))
        return sum(v) / len(v) if v else 0.0
    frozen = []
    for s in ok:
        if all(jaccard(s["rule"], f["rule"]) <= 0.6 for f in frozen):
            frozen.append(s)
        if len(frozen) == 10:
            break
    multi = {}
    for name in MULTI:
        xs = [r["x"][name][0] for r in rows]
        multi[name] = {"excess": round(_mean(xs) or 0, 2), "t": round(tstat(xs), 2),
                       "thirds": [None if (m := _mean(xs[a:b])) is None else round(m, 2) for a, b in thirds]}
    with open(EXPLORE_OUT, "w", encoding="utf-8") as f:
        json.dump({"from": rows[0]["d"], "to": rows[-1]["d"], "days": n, "rules": len(stats), "allThirdsPositive": len(ok),
                   "top50": ok[:50], "multi": multi}, f, ensure_ascii=False, indent=1)
    with open(FROZEN, "w", encoding="utf-8") as f:
        json.dump(frozen, f, ensure_ascii=False, indent=1)
    print(f"探索 {len(stats)} 條、三段皆正 {len(ok)} 條;凍結:")
    for s in frozen:
        print(" ", s)
    print("多因子(探索期):", json.dumps(multi, ensure_ascii=False))


def validate():
    rows = json.load(open(ROWS, encoding="utf-8"))
    frozen = [f["rule"] for f in json.load(open(FROZEN, encoding="utf-8"))]
    names = frozen + list(MULTI)
    val = [r for r in rows if r["d"] >= SPLIT]
    res = {"validFrom": val[0]["d"], "validTo": val[-1]["d"], "days": len(val), "rules": {}}
    for k in names:
        xs = [r["x"][k][0] for r in val]
        allx = [r["x"][k][0] for r in rows]
        t = tstat(xs)
        res["rules"][k] = {"excess": round(_mean(xs) or 0, 2), "t": round(t, 2), "p": round(0.5 * math.erfc(t / math.sqrt(2)), 4),
                           "all2013": round(_mean(allx) or 0, 2), "explore": round(_mean(x for r in rows if r["d"] < SPLIT for x in [r["x"][k][0]]) or 0, 2),
                           "byYear": {y: round(_mean(r["x"][k][0] for r in rows if r["d"][:4] == y) or 0, 2) for y in sorted({r["d"][:4] for r in rows})}}
    alive = True
    for i, k in enumerate(sorted(names, key=lambda k: res["rules"][k]["p"])):
        v = res["rules"][k]
        alive = alive and v["p"] <= 0.05 / (len(names) - i)
        v["pass"] = bool(alive and v["excess"] > 0)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    for k, v in res["rules"].items():
        print(k, {x: v[x] for x in v if x != "byYear"})


if __name__ == "__main__":
    {"collect": collect, "explore": explore, "validate": validate}[sys.argv[1]]()
