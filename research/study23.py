"""研究二十三:VCP、族群連動;隔天開盤買、+35% 停利或第 10 個交易日開盤賣(登記見 RESEARCH.md)。

用法:python -m research.study23 collect | explore | validate
"""
import itertools
import json
import math
import os
import sys

from chips import sources
from . import three_year as TY

ROOT = os.path.dirname(os.path.abspath(__file__))
ROWS = os.path.join(ROOT, "study23_rows.json")
FROZEN = os.path.join(ROOT, "study23_frozen.json")
EXPLORE_OUT = os.path.join(ROOT, "study23_explore.json")
OUT = os.path.join(ROOT, "study23.json")
IND = json.load(open(os.path.join(ROOT, "industry.json"), encoding="utf-8"))
O, H, L, C, V, F, T, I = range(8)
HOLD, TP, TOP = 10, 0.35, 5
COST = (0.585, 0.38)
SPLIT, START = "2020-01-01", "2013-07-01"
WINDOWS = [("20130101", "20171231"), ("20170401", "20221231"), ("20220401", "20261028")]


def rules():
    out = {}
    for c, v, b, ch in itertools.product(("收縮", "收縮且末段<10%"), ("量縮", "不設量縮"), ("突破量>1.5倍", "不設突破量"), ("投信買超", "不設籌碼")):
        out[f"VCP|{c}+{v}+{b}+{ch}"] = ("VCP", c, v, b, ch)
    for th, br, pick in itertools.product((2, 3), ("上漲家數≥60%", "不設家數"), ("龍頭", "落後補漲", "投信最多", "量比最大")):
        out[f"族群|平均漲≥{th}%+{br}|{pick}"] = ("SEC", th, br, pick)
    return out


def collect():
    R = rules()
    rows = {}
    for start, end in WINDOWS:
        TY.START, TY.END = start, end
        days, panel = TY.load()
        n = len(days)
        codes = {c for d in panel for c in d if c != TY.BENCH and sources.is_common_stock(c)}
        ser = {c: [d.get(c) for d in panel] for c in codes | {TY.BENCH}}

        def trade(code, t):
            """t+1 開盤買;+35% 停利或 t+1+10 開盤賣。回傳報酬(小數)或 None。"""
            s = ser[code]
            if t + 1 + HOLD >= n or not s[t + 1] or s[t + 1][O] <= 0 or TY.jump(panel, code, t + 1, t + 1 + HOLD):
                return None
            e = s[t + 1][O]
            for k in range(t + 1, t + 1 + HOLD):
                x = s[k]
                if not x:
                    continue
                if k > t + 1 and x[O] >= e * (1 + TP):
                    return x[O] / e - 1
                if x[H] >= e * (1 + TP):
                    return TP
            x = s[t + 1 + HOLD]
            if not x or x[O] <= 0:
                return None
            return x[O] / e - 1

        for t in range(121, n - HOLD - 2):
            d = str(days[t])
            if d in rows or d < START:
                continue
            feats = {}
            for c in codes:
                s = ser[c]
                x, p = s[t], s[t - 1]
                if not x or not p or x[C] < 10 or p[C] <= 0:
                    continue
                win = s[t - 120:t + 1]
                if sum(1 for y in win if y) < 115:
                    continue
                vols = [y[V] for y in s[t - 49:t + 1] if y]
                v20 = sum(y[V] for y in s[t - 19:t + 1] if y) / 20
                if v20 <= 500:
                    continue
                closes = [y[C] for y in win if y]
                ma = lambda w: sum(closes[-w:]) / w
                seg = []
                for a, b in ((t - 59, t - 39), (t - 39, t - 19), (t - 19, t)):
                    hs = [y[H] for y in s[a:b] if y]
                    ls = [y[L] for y in s[a:b] if y]
                    seg.append((max(hs) - min(ls)) / min(ls) if hs and ls and min(ls) > 0 else 9)
                prior20 = [y[H] for y in s[t - 20:t] if y]
                v50 = sum(vols) / len(vols)
                v10 = sum(y[V] for y in s[t - 10:t] if y) / 10
                feats[c] = {"chg": x[C] / p[C] - 1, "trend": x[C] > ma(20) > ma(60) > ma(120),
                            "nearHigh": x[C] >= max(y[H] for y in win if y) * 0.75, "breakout": bool(prior20) and x[C] > max(prior20),
                            "contract": seg[0] > seg[1] > seg[2], "tight": seg[2] < 0.10, "dry": v10 < v50 * 0.8,
                            "volr": x[V] / v50 if v50 else 0, "t10": sum(y[T] for y in s[t - 9:t + 1] if y),
                            "ind": IND.get(c)}
            groups = {}
            for c, fx in feats.items():
                if fx["ind"]:
                    groups.setdefault(fx["ind"], []).append(c)
            gstat = {}
            for g, cs in groups.items():
                if len(cs) >= 5:
                    chs = [feats[c]["chg"] for c in cs]
                    gstat[g] = (sum(chs) / len(chs), sum(1 for x in chs if x > 0) / len(chs))
            cache = {}

            def ret(c):
                if c not in cache:
                    cache[c] = trade(c, t)
                return cache[c]
            bench = trade(TY.BENCH, t) if ser[TY.BENCH][t] else None
            if bench is None:
                continue
            bench_noTP = None
            sb = ser[TY.BENCH]
            if sb[t + 1] and sb[t + 1 + HOLD]:
                bench_noTP = sb[t + 1 + HOLD][O] / sb[t + 1][O] - 1
            out = {}
            for key, spec in R.items():
                if spec[0] == "VCP":
                    _, cc, vv, bb, ch = spec
                    cand = [c for c, fx in feats.items() if fx["trend"] and fx["nearHigh"] and fx["breakout"] and fx["contract"]
                            and (cc == "收縮" or fx["tight"]) and (vv == "不設量縮" or fx["dry"])
                            and (bb == "不設突破量" or fx["volr"] > 1.5) and (ch == "不設籌碼" or fx["t10"] > 0)]
                    chosen = sorted(cand, key=lambda c: (-feats[c]["volr"], c))[:TOP]
                else:
                    _, th, br, pick = spec
                    hot = [g for g, (m, up) in gstat.items() if m >= th / 100 and (br == "不設家數" or up >= 0.6)]
                    hot = sorted(hot, key=lambda g: -gstat[g][0])[:2]
                    chosen = []
                    for g in hot:
                        cs = groups[g]
                        avg = gstat[g][0]
                        if pick.startswith("龍頭"):
                            pool = sorted(cs, key=lambda c: -feats[c]["chg"])
                        elif pick.startswith("落後補漲"):
                            pool = sorted((c for c in cs if 0 <= feats[c]["chg"] < avg), key=lambda c: -feats[c]["chg"])
                        elif pick == "投信最多":
                            pool = sorted(cs, key=lambda c: -feats[c]["t10"])
                        else:
                            pool = sorted(cs, key=lambda c: -feats[c]["volr"])
                        if pick.endswith("投信買超"):
                            pool = [c for c in pool if feats[c]["t10"] > 0]
                        pool = [c for c in pool if feats[c]["chg"] < 0.095]   # 收盤漲停隔天開盤仍可能買不到,保守排除
                        chosen += pool[:3]
                    chosen = chosen[:TOP]
                rs = [x for c in chosen if (x := ret(c)) is not None]
                out[key] = None if not rs else [round((sum(rs) / len(rs) - bench_noTP) * 100, 3) if bench_noTP is not None else None,
                                                round(sum(rs) / len(rs) * 100, 3), len(rs),
                                                round(sum(1 for c in chosen if cache.get(c) == TP) / len(rs), 2)]
            rows[d] = out
            if len(rows) % 200 == 0:
                print(f"已算 {len(rows)} 天,到 {d}", flush=True)
        del panel, ser
    data = [{"d": d, "x": rows[d]} for d in sorted(rows)]
    with open(ROWS, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"完成:{len(data)} 天", flush=True)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def tstat(xs, step=HOLD + 1):
    """不重疊取樣:對所有起點取平均 t,降低只取單一起點的雜訊。"""
    ts = []
    for o in range(step):
        pts = [x for k, x in enumerate(xs) if k % step == o and x is not None]
        if len(pts) >= 3:
            m = sum(pts) / len(pts)
            sd = math.sqrt(sum((x - m) ** 2 for x in pts) / (len(pts) - 1))
            if sd:
                ts.append(m / (sd / math.sqrt(len(pts))))
    return sum(ts) / len(ts) if ts else 0.0


def series(rows, key, cost):
    return [None if not r["x"].get(key) or r["x"][key][0] is None else r["x"][key][0] - cost for r in rows]


def explore():
    data = [r for r in json.load(open(ROWS, encoding="utf-8")) if r["d"] < SPLIT]
    n = len(data)
    thirds = [(0, n // 3), (n // 3, 2 * n // 3), (2 * n // 3, n)]
    frozen, report = {}, {}
    for fam in ("VCP", "族群"):
        stats = []
        for key in rules():
            if not key.startswith(fam):
                continue
            xs = series(data, key, COST[0])
            k = sum(1 for x in xs if x is not None)
            segs = [_mean(xs[a:b]) for a, b in thirds]
            stats.append({"rule": key, "excess": round(_mean(xs) or 0, 3), "t": round(tstat(xs), 2), "days": k,
                          "thirds": [None if s is None else round(s, 3) for s in segs]})
        ok = sorted((s for s in stats if s["days"] >= 100 and all(x is not None and x > 0 for x in s["thirds"])), key=lambda s: -s["t"])
        frozen[fam] = ok[:5]
        report[fam] = {"all": sorted(stats, key=lambda s: -s["t"]), "ok": len(ok)}
        print(fam, f"{len(stats)} 條、三段皆正 {len(ok)} 條")
        for s in sorted(stats, key=lambda s: -s["t"]):
            print("  ", s)
    json.dump(report, open(EXPLORE_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(frozen, open(FROZEN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def validate():
    data = json.load(open(ROWS, encoding="utf-8"))
    val = [r for r in data if r["d"] >= SPLIT]
    frozen = json.load(open(FROZEN, encoding="utf-8"))
    res = {}
    for fam, items in frozen.items():
        out = {}
        for s in items:
            key = s["rule"]
            xs = series(val, key, COST[0])
            t = tstat(xs)
            raw = [r["x"][key] for r in val if r["x"].get(key)]
            out[key] = {"explore": s["excess"], "excess": round(_mean(xs) or 0, 3), "excess28": round(_mean(series(val, key, COST[1])) or 0, 3),
                        "ret": round(_mean(x[1] for x in raw) or 0, 3), "days": len(raw), "avgPicks": round(_mean(x[2] for x in raw) or 0, 1),
                        "tpRate": round(100 * (_mean(x[3] for x in raw) or 0), 1), "t": round(t, 2), "p": round(0.5 * math.erfc(t / math.sqrt(2)), 4),
                        "byYear": {y: round(_mean(x for r, x in zip(val, xs) if r["d"][:4] == y) or 0, 2) for y in sorted({r["d"][:4] for r in val})},
                        "all2013": round(_mean(series(data, key, COST[0])) or 0, 3)}
        alive = True
        for i, key in enumerate(sorted(out, key=lambda k: out[k]["p"])):
            alive = alive and out[key]["p"] <= 0.05 / (len(out) - i)
            out[key]["pass"] = bool(alive and out[key]["excess"] > 0)
        res[fam] = out
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for fam, v in res.items():
        print("==", fam)
        for k, x in v.items():
            print(" ", k, x)


if __name__ == "__main__":
    {"collect": collect, "explore": explore, "validate": validate}[sys.argv[1]]()
