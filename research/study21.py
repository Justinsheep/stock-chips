"""研究二十一:隔日沖(A)、當沖(B)、9:10 零股當沖(C)規則大搜尋(登記見 RESEARCH.md)。

collect :逐日算全部規則的毛報酬 → study21_rows.json(不進版控)
explore :只讀探索期,三族各凍結 10 條 → study21_frozen.json
validate:讀驗證期 → study21.json
用法:python -m research.study21 collect | explore | validate
"""
import gc
import heapq
import itertools
import json
import math
import os
import sys
from collections import deque

from chips import sources
from . import dividends as DV
from . import three_year as TY
from .oddlot import odd_open

ROOT = os.path.dirname(os.path.abspath(__file__))
ROWS = os.path.join(ROOT, "study21_rows.json")
FROZEN = os.path.join(ROOT, "study21_frozen.json")
EXPLORE_OUT = os.path.join(ROOT, "study21_explore.json")
OUT = os.path.join(ROOT, "study21.json")
O, H, L, C, V, F, T, I = range(8)
TOP = 5
WINDOWS = [("20130101", "20171231"), ("20171101", "20221231"), ("20221101", "20261023")]
ODD_START = "2020-10-26"
COST = {"A": (0.38, 0.585), "B": (0.23, 0.435), "C": (0.23, 0.435)}   # (2.8 折, 不打折),%
SPLIT = {"A": "2020-01-01", "B": "2020-01-01", "C": "2023-07-01"}
START = {"A": "2013-07-01", "B": "2013-07-01", "C": "2020-11-01"}

ON_PRICE = {"漲3~9.5%": lambda x: 0.03 <= x["chg"] < 0.095, "漲5~9.5%": lambda x: 0.05 <= x["chg"] < 0.095,
            "收最高且上漲": lambda x: x["atHigh"], "跌≥5%": lambda x: x["chg"] <= -0.05, "創20日新高": lambda x: x["hi20"], "不設價": None}
ON_VOL = {"量>2倍": lambda x: x["volr"] > 2, "量>1.5倍": lambda x: x["volr"] > 1.5, "不設量": None}
CHIPS = {"投信買超": lambda x: x["trust1"] > 0, "外資買超": lambda x: x["foreign1"] > 0, "法人5日買超": lambda x: x["inst5"] > 0, "不設法人": None}
ON_MKT = {"0050上漲": True, "不設大盤": False}
ON_RANK = {"依漲幅": lambda x: -x["chg"], "依量比": lambda x: -x["volr"]}
ON_EXIT = ("隔天開盤賣", "隔天收盤賣")

DT_GAP = {"跳空≥+3%": lambda g: g >= 0.03, "跳空+1~3%": lambda g: 0.01 <= g < 0.03, "跳空-1~-3%": lambda g: -0.03 < g <= -0.01,
          "跳空≤-3%": lambda g: g <= -0.03, "不設跳空": None}
DT_PREV = {"前日漲≥5%": lambda x: x["chg"] >= 0.05, "前日收最高": lambda x: x["atHigh"], "前日跌≥5%": lambda x: x["chg"] <= -0.05, "不設前日": None}
DT_VOL = {"前日量>2倍": lambda x: x["volr"] > 2, "不設量": None}
DT_DIR = ("做多", "做空")
DT_RANK = ("依跳空幅度", "依前日量比")


def rules():
    out = {}
    for p, v, c, m, r, e in itertools.product(ON_PRICE, ON_VOL, CHIPS, ON_MKT, ON_RANK, ON_EXIT):
        if ON_PRICE[p] is None and ON_VOL[v] is None and CHIPS[c] is None:
            continue
        out[f"A|{p}+{v}+{c}+{m}|{r}|{e}"] = ("A", p, v, c, m, r, e)
    for g, p, v, c, d, r in itertools.product(DT_GAP, DT_PREV, DT_VOL, CHIPS, DT_DIR, DT_RANK):
        if DT_GAP[g] is None and DT_PREV[p] is None and DT_VOL[v] is None and CHIPS[c] is None:
            continue
        out[f"B|{g}+{p}+{v}+{c}|{d}|{r}"] = ("B", g, p, v, c, d, r)
        if d == "做多":
            out[f"C|{g}+{p}+{v}+{c}|{r}"] = ("C", g, p, v, c, d, r)
    return out


REAL = False   # 更正版:考慮漲跌停鎖住時無法成交(見 RESEARCH.md 研究二十一更正)
ONLY = None


def limit(d):
    """漲跌幅限制:2015-06-01 以前 7%,之後 10%;留 0.5% 緩衝判斷是否鎖住。"""
    return (0.07 if d < "2015-06-01" else 0.10) - 0.005


def collect():
    div = DV.load(2013, 2026)
    R = {k: v for k, v in rules().items() if ONLY is None or k in ONLY}
    rows = {}
    for start, end in WINDOWS:
        TY.START, TY.END = start, end
        days, panel = TY.load()
        hist = {}   # 代號 -> deque[(量, 高)],最近 20 天(不含當天)
        prev = {}   # 前一天的特徵
        inst_hist = {}
        for t in range(1, len(days) - 1):
            d = str(days[t])
            day, yday, nxt = panel[t], panel[t - 1], panel[t + 1]
            b0, b1 = day.get(TY.BENCH), yday.get(TY.BENCH)
            mkt_up = bool(b0 and b1 and b0[C] > b1[C])
            feats = {}
            for code, x in day.items():
                p = yday.get(code)
                h = hist.setdefault(code, deque(maxlen=20))
                ih = inst_hist.setdefault(code, deque(maxlen=5))
                if p and len(h) == 20 and code != TY.BENCH and sources.is_common_stock(code) and x[C] >= 10 and p[C] > 0 and x[O] > 0:
                    v20 = sum(a for a, _ in h) / 20
                    if v20 > 1000:
                        chg = x[C] / p[C] - 1
                        feats[code] = {"chg": chg, "atHigh": chg > 0 and x[C] >= x[H] * 0.99, "volr": x[V] / v20 if v20 else 0,
                                       "hi20": x[C] >= max(b for _, b in h), "trust1": p[T], "foreign1": p[F],
                                       "inst5": sum(ih) if len(ih) == 5 else 0, "gap": x[O] / p[C] - 1}
                h.append((x[V], x[H]))
                ih.append(x[I])
            if d in rows or d < START["A"]:   # 法人欄位(trust1、foreign1、inst5)都只到前一天
                prev = feats
                continue
            odd = odd_open(days[t]) if d >= ODD_START else {}
            out = {}

            def on_ret(code, exit_):
                y = nxt.get(code)
                x = day[code]
                if not y or y[O] <= 0 or abs(y[O] / x[C] - 1) > 0.11:
                    return None
                dv = div.get(code, {}).get(days[t + 1], 0.0)
                px = y[O] if exit_ == "隔天開盤賣" else y[C]
                if REAL and exit_ == "隔天開盤賣" and y[O] <= x[C] * (1 - lim):
                    px = y[C]   # 隔天開在跌停可能賣不掉,改收盤賣
                return (px + dv) / x[C] - 1

            # A 隔日沖:今天收盤買
            sets_on = {"p": {k: set(feats) if f is None else {c for c in feats if f(feats[c])} for k, f in ON_PRICE.items()},
                       "v": {k: set(feats) if f is None else {c for c in feats if f(feats[c])} for k, f in ON_VOL.items()},
                       "c": {k: set(feats) if f is None else {c for c in feats if f(feats[c])} for k, f in CHIPS.items()}}
            lim = limit(d) if REAL else 0.095
            buyable = {c for c in feats if feats[c]["chg"] < lim}
            # B/C 當沖:用前一天特徵＋今天開盤跳空
            dt_pool = {c for c in feats if c in prev and abs(feats[c]["gap"]) <= 0.11}
            sets_dt = {"g": {k: dt_pool if f is None else {c for c in dt_pool if f(feats[c]["gap"])} for k, f in DT_GAP.items()},
                       "p": {k: dt_pool if f is None else {c for c in dt_pool if f(prev[c])} for k, f in DT_PREV.items()},
                       "v": {k: dt_pool if f is None else {c for c in dt_pool if f(prev[c])} for k, f in DT_VOL.items()},
                       "c": {k: dt_pool if f is None else {c for c in dt_pool if f(feats[c])} for k, f in CHIPS.items()}}   # feats 的法人欄位就是前一天
            cache = {}
            for key, spec in R.items():
                fam = spec[0]
                if fam == "A":
                    _, p, v, c, m, r, e = spec
                    if ON_MKT[m] and not mkt_up:
                        out[key] = None
                        continue
                    cand = sets_on["p"][p] & sets_on["v"][v] & sets_on["c"][c] & buyable
                    chosen = heapq.nsmallest(TOP, cand, key=lambda k: (ON_RANK[r](feats[k]), k))
                    rs = [x for k in chosen if (x := cache.setdefault((k, e), on_ret(k, e))) is not None]
                else:
                    _, g, p, v, c, dirn, r = spec
                    if fam == "C" and not odd:
                        out[key] = None
                        continue
                    cand = sets_dt["g"][g] & sets_dt["p"][p] & sets_dt["v"][v] & sets_dt["c"][c]
                    if dirn == "做多":
                        cand = {k for k in cand if feats[k]["gap"] < lim}
                    else:
                        cand = {k for k in cand if feats[k]["gap"] > -lim}
                    rank = (lambda k: (-abs(feats[k]["gap"]), k)) if r == "依跳空幅度" else (lambda k: (-prev[k]["volr"], k))
                    chosen = heapq.nsmallest(TOP, cand, key=rank)
                    rs = []
                    for k in chosen:
                        x = day[k]
                        entry = odd.get(k) if fam == "C" else x[O]
                        if not entry or entry <= 0:
                            continue
                        out_px = x[C]
                        if REAL:   # 收盤鎖在對自己不利的停板:當天平不了倉,改隔天開盤出場
                            pc, nx = yday[k][C], nxt.get(k)
                            locked = x[C] <= pc * (1 - lim) if dirn == "做多" else x[C] >= pc * (1 + lim)
                            if locked:
                                if not nx or nx[O] <= 0:
                                    continue
                                out_px = nx[O]
                        rs.append(out_px / entry - 1 if dirn == "做多" else (entry - out_px) / entry)
                fam_split = SPLIT[fam]
                out[key] = None if not rs else [round(sum(rs) / len(rs) * 100, 4), len(rs), ",".join(chosen) if d < fam_split else None]
            rows[d] = out
            prev = feats
            if len(rows) % 200 == 0:
                print(f"已算 {len(rows)} 天,到 {d}", flush=True)
        del panel
        gc.collect()
    data = [{"d": d, "x": rows[d]} for d in sorted(rows)]
    with open(ROWS, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"完成:{len(data)} 天", flush=True)


def _t(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 3:
        return 0.0, len(xs)
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
    return (m / (sd / math.sqrt(len(xs))) if sd else 0.0), len(xs)


def explore():
    data = json.load(open(ROWS, encoding="utf-8"))
    R = rules()
    frozen, report = {}, {}
    for fam in ("A", "B", "C"):
        rows = [r for r in data if START[fam] <= r["d"] < SPLIT[fam]]
        n = len(rows)
        thirds = [(0, n // 3), (n // 3, 2 * n // 3), (2 * n // 3, n)]
        cost = COST[fam][0]
        stats = []
        for key, spec in R.items():
            if spec[0] != fam:
                continue
            xs = [None if r["x"].get(key) is None else r["x"][key][0] - cost for r in rows]
            t, k = _t(xs)
            segs = [_mean(xs[a:b]) for a, b in thirds]
            if k < 200:
                continue
            stats.append({"rule": key, "net": round(_mean(xs), 3), "t": round(t, 2), "days": k,
                          "thirds": [None if s is None else round(s, 3) for s in segs]})
        ok = sorted((s for s in stats if all(x is not None and x > 0 for x in s["thirds"])), key=lambda s: -s["t"])

        def picks(key):
            return [set(filter(None, (r["x"].get(key) or [0, 0, ""])[2].split(","))) if r["x"].get(key) else set() for r in rows]
        chosen, cache = [], {}
        for s in ok:
            pa = cache.setdefault(s["rule"], picks(s["rule"]))
            dup = False
            for f in chosen:
                pb = cache.setdefault(f["rule"], picks(f["rule"]))
                v = [len(a & b) / len(a | b) for a, b in zip(pa, pb) if a or b]
                if v and sum(v) / len(v) > 0.6:
                    dup = True
                    break
            if not dup:
                chosen.append(s)
            if len(chosen) == 10:
                break
        frozen[fam] = chosen
        report[fam] = {"from": rows[0]["d"], "to": rows[-1]["d"], "rules": len(stats), "allThirdsPositive": len(ok), "top30": ok[:30]}
        print(f"{fam}:{len(stats)} 條(≥200 天)、三段皆正 {len(ok)} 條,凍結 {len(chosen)} 條")
        for s in chosen:
            print("  ", s)
    with open(EXPLORE_OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    with open(FROZEN, "w", encoding="utf-8") as f:
        json.dump(frozen, f, ensure_ascii=False, indent=1)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def validate():
    data = json.load(open(ROWS, encoding="utf-8"))
    frozen = json.load(open(FROZEN, encoding="utf-8"))
    res = {}
    for fam, items in frozen.items():
        rows = [r for r in data if r["d"] >= SPLIT[fam]]
        out = {}
        for s in items:
            key = s["rule"]
            gross = [None if r["x"].get(key) is None else r["x"][key][0] for r in rows]
            net = [None if g is None else g - COST[fam][0] for g in gross]
            full = [None if g is None else g - COST[fam][1] for g in gross]
            t, k = _t(net)
            out[key] = {"explore": s["net"], "net": round(_mean(net) or 0, 3), "netFull": round(_mean(full) or 0, 3), "t": round(t, 2),
                        "p": round(0.5 * math.erfc(t / math.sqrt(2)), 4), "days": k,
                        "win": round(100 * sum(1 for x in net if x is not None and x > 0) / max(1, k), 1),
                        "byYear": {y: round(_mean(x for r, x in zip(rows, net) if r["d"][:4] == y) or 0, 3) for y in sorted({r["d"][:4] for r in rows})}}
        alive = True
        for i, key in enumerate(sorted(out, key=lambda k: out[k]["p"])):
            alive = alive and out[key]["p"] <= 0.05 / (len(out) - i)
            out[key]["pass"] = bool(alive and out[key]["net"] > 0)
            out[key]["passFull"] = bool(out[key]["pass"] and out[key]["netFull"] > 0)
        res[fam] = {"from": rows[0]["d"], "to": rows[-1]["d"], "rules": out}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    for fam, v in res.items():
        print("==", fam, v["from"], v["to"])
        for k, x in v["rules"].items():
            print(" ", k, {a: x[a] for a in x if a != "byYear"})


def real():
    """更正版:只重算凍結的規則,探索期與驗證期都列出。"""
    global REAL, ONLY, ROWS, OUT
    frozen = json.load(open(FROZEN, encoding="utf-8"))
    REAL, ONLY = True, {s["rule"] for v in frozen.values() for s in v}
    ROWS = os.path.join(ROOT, "study21_rows_real.json")
    collect()
    data = json.load(open(ROWS, encoding="utf-8"))
    res = {}
    for fam, items in frozen.items():
        out = {}
        for s in items:
            key = s["rule"]
            info = {}
            for name, a, b in (("explore", START[fam], SPLIT[fam]), ("valid", SPLIT[fam], "9999")):
                rows = [r for r in data if a <= r["d"] < b]
                gross = [None if r["x"].get(key) is None else r["x"][key][0] for r in rows]
                net = [None if g is None else g - COST[fam][0] for g in gross]
                t, k = _t(net)
                info[name] = {"net": round(_mean(net) or 0, 3), "netFull": round(_mean(None if g is None else g - COST[fam][1] for g in gross) or 0, 3),
                              "t": round(t, 2), "p": round(0.5 * math.erfc(t / math.sqrt(2)), 4), "days": k}
            out[key] = info
        alive = True
        for i, key in enumerate(sorted(out, key=lambda k: out[k]["valid"]["p"])):
            v = out[key]["valid"]
            alive = alive and v["p"] <= 0.05 / (len(out) - i)
            v["pass"] = bool(alive and v["net"] > 0)
            v["passFull"] = bool(v["pass"] and v["netFull"] > 0)
        res[fam] = out
    with open(os.path.join(ROOT, "study21_real.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    for fam, v in res.items():
        print("==", fam)
        for k, x in v.items():
            print(" ", k, x)


if __name__ == "__main__":
    {"collect": collect, "explore": explore, "validate": validate, "real": real}[sys.argv[1]]()
