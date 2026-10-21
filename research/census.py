"""追加研究七:多因子規則普查(登記內容見 RESEARCH.md)。23 條規則 × 持有 20 / 5 日。

用法:python -m research.census
輸出:research/census.json 與終端機摘要
"""
import datetime as dt
import json
import math
import os
from collections import deque

from chips import sources
from chips.revenue import Revenue, available_month, prev_month

from .three_year import BENCH, C, F, H, I, L, O, T, V, adjusted_closes, hold, load

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "census.json")
WARMUP = 120
COST = 0.585
SPLITS = (0.6, 0.8)
HORIZONS = (20, 5)
TOP = 10


# ---------- 每檔股票的時間序列指標(一次算好) ----------

class Series:
    def __init__(self, days, panel, margin):
        n = len(days)
        self.n = n
        codes = {c for p in panel for c in p}
        self.f = {}
        for code in codes:
            row = [p.get(code) for p in panel]
            close = [r[C] if r else None for r in row]
            pres = [1 if r else 0 for r in row]
            cum = lambda vals: [0.0] + list(_accumulate(vals))
            P = cum(pres)
            vol = cum([r[V] if r else 0 for r in row])
            tr = cum([r[T] if r else 0 for r in row])
            fo = cum([r[F] if r else 0 for r in row])
            ins = cum([r[I] if r else 0 for r in row])
            mg = cum([margin[k].get(code, 0.0) if r else 0 for k, r in enumerate(row)])
            tpos = cum([1 if r and r[T] > 0 else 0 for r in row])
            cl = cum([c or 0 for c in close])
            rets = [None] + [(close[k] / close[k - 1] - 1) if close[k] and close[k - 1] else None for k in range(1, n)]
            r1 = cum([x or 0 for x in rets])
            r2 = cum([(x or 0) ** 2 for x in rets])
            hi120 = _rolling_max(close, 120)
            self.f[code] = dict(row=row, close=close, P=P, vol=vol, tr=tr, fo=fo, ins=ins, mg=mg, tpos=tpos, cl=cl,
                                r1=r1, r2=r2, hi120=hi120)

    def full(self, code, t, w):
        """t 往回 w 天(含 t)資料都在。"""
        s = self.f[code]
        return t - w + 1 >= 0 and s["P"][t + 1] - s["P"][t - w + 1] == w

    def win(self, code, key, t, w):
        s = self.f[code][key]
        return s[t + 1] - s[t - w + 1]

    def ma(self, code, t, w):
        return self.win(code, "cl", t, w) / w

    def vol_std20(self, code, t):
        n = 20
        a, b = self.win(code, "r1", t, n), self.win(code, "r2", t, n)
        return math.sqrt(max(b / n - (a / n) ** 2, 0))


def _accumulate(vals):
    s = 0.0
    for v in vals:
        s += v
        yield s


def _rolling_max(vals, w):
    out, dq = [None] * len(vals), deque()
    for k, v in enumerate(vals):
        if v is None:
            dq.clear()
            continue
        while dq and vals[dq[-1]] <= v:
            dq.pop()
        dq.append(k)
        while dq[0] <= k - w:
            dq.popleft()
        out[k] = vals[dq[0]] if k - w + 1 >= 0 and all(vals[j] is not None for j in (k - w + 1, k)) else None
    return out


# ---------- 營收指標 ----------

class RevFeats:
    def __init__(self):
        self.rev, self.cache = Revenue(), {}

    def get(self, day):
        y, m = available_month(day)
        if (y, m) in self.cache:
            return self.cache[(y, m)]
        data = [self.rev._get(*prev_month(y, m, k)) for k in range(0, 16)]
        out = {}
        if all(d is not None for d in data):
            for code, cur in data[0].items():
                vals = [d.get(code) for d in data]
                if any(v is None or v <= 0 for v in vals):
                    continue
                avg3 = [sum(vals[k:k + 3]) / 3 for k in range(0, 13)]
                yoy = [(vals[k] / vals[k + 12] - 1) * 100 for k in range(0, 4)]
                out[code] = {"high3": avg3[0] >= max(avg3[:12]), "yoy": yoy[0],
                             "accel": yoy[0] - sum(yoy[1:4]) / 3, "high1": vals[0] >= max(vals[:12])}
        self.cache[(y, m)] = out
        return out


# ---------- 規則 ----------

def build_rules():
    momentum = lambda r: r and r["high3"] and r["yoy"] > 20
    return {
        "C1 投信10日買超>15張": (lambda x: x["t10"] > 15, lambda x: x["t10"]),
        "C2 投信買超力道": (lambda x: x["t10"] > 0, lambda x: x["t10"] / x["v20"]),
        "C3 外資買超力道": (lambda x: x["f10"] > 0, lambda x: x["f10"] / x["v20"]),
        "C4 投信連買≥3日": (lambda x: x["tstreak"] >= 3, lambda x: x["t10"]),
        "C5 法人20日買超力道": (lambda x: x["i20"] > 0, lambda x: x["i20"] / x["v20"]),
        "C6 法人買＋融資減": (lambda x: x["i10"] > 0 and x["m10"] < 0, lambda x: -x["m10"] / x["v20"]),
        "C7 投信第一天進場": (lambda x: x["tfirst"], lambda x: x["tday"] / max(x["vday"], 1e-9)),
        "V1 投信＋營收動能(R2)": (lambda x: x["t10"] > 15 and momentum(x["rev"]), lambda x: x["t10"]),
        "V2 營收創高＋年增>30%": (lambda x: x["rev"] and x["rev"]["high3"] and x["rev"]["yoy"] > 30, lambda x: x["rev"]["yoy"]),
        "V3 營收加速": (lambda x: x["rev"] and x["rev"]["yoy"] > 20 and x["rev"]["accel"] > 10, lambda x: x["rev"]["accel"]),
        "V4 單月營收新高＋站上季線": (lambda x: x["rev"] and x["rev"]["high1"] and x["c"] > x["ma60"], lambda x: x["ret20"]),
        "V5 營收動能＋外資買": (lambda x: momentum(x["rev"]) and x["f10"] > 0, lambda x: x["f10"] / x["v20"]),
        "P1 60日動能(大型)": (lambda x: x["c"] > x["ma60"] and x["v20"] > 1000, lambda x: x["ret60"]),
        "P2 120日新高＋量增": (lambda x: x["hi120"] and x["vday"] > 1.5 * x["v20prev"], lambda x: x["vday"] / x["v20prev"]),
        "P3 低波動(大型、站上季線)": (lambda x: x["c"] > x["ma60"] and x["v20"] > 1000, lambda x: -x["std20"]),
        "P4 短期反轉(大型、站上半年線)": (lambda x: x["c"] > x["ma120"] and x["v20"] > 1000, lambda x: -x["ret5"]),
        "P5 均線多頭排列": (lambda x: x["ma5"] > x["ma20"] > x["ma60"], lambda x: x["ret20"]),
        "X1 R2＋站上季線": (lambda x: x["t10"] > 15 and momentum(x["rev"]) and x["c"] > x["ma60"], lambda x: x["t10"]),
        "X2 投信買＋60日動能": (lambda x: x["t10"] > 0 and x["ret60"] > 0, lambda x: x["t10"] / x["v20"]),
        "X3 外資投信同買＋營收動能": (lambda x: x["t10"] > 0 and x["f10"] > 0 and momentum(x["rev"]), lambda x: (x["t10"] + x["f10"]) / x["v20"]),
        "X4 營收動能＋低波動": (lambda x: momentum(x["rev"]) and x["c"] > x["ma60"], lambda x: -x["std20"]),
        "X5 R2＋大盤濾網": "special",
        "X6 投信買＋融資減＋營收動能": (lambda x: x["t10"] > 15 and x["m10"] < 0 and momentum(x["rev"]), lambda x: x["t10"]),
    }


def features(S, code, t, rev):
    s = S.f[code]
    x = s["row"][t]
    if not x or x[C] < 10 or not S.full(code, t, 121):
        return None
    v20 = S.win(code, "vol", t, 20) / 20
    if v20 <= 300:
        return None
    close = s["close"]
    tday = x[T]
    prior_pos = S.win(code, "tpos", t - 1, 9)
    return {
        "c": x[C], "v20": v20, "v20prev": S.win(code, "vol", t - 1, 20) / 20, "vday": x[V], "tday": tday,
        "t10": S.win(code, "tr", t, 10), "f10": S.win(code, "fo", t, 10), "i10": S.win(code, "ins", t, 10),
        "i20": S.win(code, "ins", t, 20), "m10": S.win(code, "mg", t, 10),
        "tstreak": 3 if all(s["row"][k][T] > 0 for k in (t, t - 1, t - 2)) else 0,
        "tfirst": prior_pos == 0 and tday >= 0.05 * x[V] and x[C] > close[t - 1],
        "ma5": S.ma(code, t, 5), "ma20": S.ma(code, t, 20), "ma60": S.ma(code, t, 60), "ma120": S.ma(code, t, 120),
        "ret5": close[t] / close[t - 5] - 1, "ret20": close[t] / close[t - 20] - 1, "ret60": close[t] / close[t - 60] - 1,
        "std20": S.vol_std20(code, t), "hi120": s["hi120"][t] is not None and x[C] >= s["hi120"][t],
        "rev": rev.get(code),
    }


def run():
    days, panel = load()
    margin = []
    for d in days:
        mg, _ = sources.margins(d)
        margin.append(mg)
    S = Series(days, panel, margin)
    rf = RevFeats()
    rules = build_rules()
    bench_adj = adjusted_closes(panel, BENCH)
    hmax = max(HORIZONS)
    rows = []
    for t in range(WARMUP, len(days) - hmax - 1):
        rev = rf.get(days[t])
        feats = {}
        for code in panel[t]:
            if code == BENCH or not sources.is_common_stock(code):
                continue
            fx = features(S, code, t, rev)
            if fx:
                feats[code] = fx
        picks = {}
        for name, rule in rules.items():
            if rule == "special":
                continue
            cond, rank = rule
            cands = [(c, rank(fx)) for c, fx in feats.items() if cond(fx)]
            picks[name] = [c for c, _ in sorted(cands, key=lambda z: -z[1])[:TOP]]
        ma = [v for v in bench_adj[t - 59:t + 1] if v]
        picks["X5 R2＋大盤濾網"] = picks["V1 投信＋營收動能(R2)"] if len(ma) == 60 and bench_adj[t] >= sum(ma) / 60 else ["__0050__"]
        rows.append((t, picks))
    n = len(rows)
    c1, c2 = int(n * SPLITS[0]), int(n * SPLITS[1])
    seg_of = lambda i: "train" if i < c1 else "valid" if i < c2 else "test"
    results = {}
    for h in HORIZONS:
        for name in rows[0][1]:
            seg = {"train": [], "valid": [], "test": []}
            trades = {"train": 0, "valid": 0, "test": 0}
            cover = {"train": 0, "valid": 0, "test": 0}
            series = []
            for i, (t, picks) in enumerate(rows):
                b = hold(panel, BENCH, t, h)
                if b is None:
                    continue
                codes = picks[name]
                if codes == ["__0050__"]:
                    rets = [b]
                else:
                    rets = [r for c in codes if (r := hold(panel, c, t, h)) is not None]
                s = seg_of(i)
                ret = sum(rets) / len(rets) - COST if rets else 0.0
                seg[s].append(ret - b)
                trades[s] += len(rets)
                cover[s] += 1 if rets else 0
                series.append((t, ret - b))
            nonover = [x for k, (t, x) in enumerate(series) if k % h == 0]
            mean = sum(nonover) / len(nonover)
            sd = math.sqrt(sum((x - mean) ** 2 for x in nonover) / (len(nonover) - 1))
            tstat = mean / (sd / math.sqrt(len(nonover))) if sd else 0.0
            r = {k: {"excess": round(sum(v) / len(v), 2), "trades": trades[k],
                     "coverage": round(cover[k] / len(v) * 100, 1)} for k, v in seg.items()}
            ok1 = all(r[k]["excess"] > 0 for k in seg)
            ok2 = tstat >= 2.0
            ok3 = all(r[k]["trades"] >= 100 and r[k]["coverage"] >= 60 for k in seg)
            results[f"{name} | {h}日"] = {**r, "tstat": round(tstat, 2), "nonOverlapN": len(nonover),
                                         "pass": ok1 and ok2 and ok3, "ok": [ok1, ok2, ok3]}
    passed = [k for k, v in results.items() if v["pass"]]
    # 通過策略之間的持股重疊(Jaccard,依選股日平均)
    overlap = {}
    names = sorted({k.split(" | ")[0] for k in passed})
    for a in names:
        for b in names:
            if a < b:
                js = [len(set(p[a]) & set(p[b])) / len(set(p[a]) | set(p[b])) for _, p in rows if p[a] and p[b]]
                overlap[f"{a} × {b}"] = round(sum(js) / len(js) * 100, 1) if js else None
    seg_dates = {"train": [str(days[rows[0][0]]), str(days[rows[c1 - 1][0]])],
                 "valid": [str(days[rows[c1][0]]), str(days[rows[c2 - 1][0]])],
                 "test": [str(days[rows[c2][0]]), str(days[rows[-1][0]])]}
    doc = {"segments": seg_dates, "tests": len(results), "results": results, "passed": passed, "overlap": overlap}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    return doc


if __name__ == "__main__":
    d = run()
    print("期間:", d["segments"], "測試數:", d["tests"])
    for k, v in d["results"].items():
        mark = "✅" if v["pass"] else "  "
        print(f"{mark} {k:<28} 訓練 {v['train']['excess']:+.2f}% 驗證 {v['valid']['excess']:+.2f}% 測試 {v['test']['excess']:+.2f}%"
              f" | t {v['tstat']:+.2f} | 筆數 {v['train']['trades']}/{v['valid']['trades']}/{v['test']['trades']}"
              f" 覆蓋 {v['train']['coverage']}/{v['valid']['coverage']}/{v['test']['coverage']}%")
    print("\n通過:", d["passed"])
    print("持股重疊:", d["overlap"])
