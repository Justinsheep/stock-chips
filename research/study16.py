"""研究十六:加回股利、2018 起、檔數、排除漲多、大盤濾網、半 0050(登記見 RESEARCH.md)。

collect:逐日存主名單候選(前 25 名,含近 20 日漲幅)、開盤買／第 20 日開盤賣的報酬與股利、大盤狀態 → study16_rows.json
analyze:模擬與檢定 → study16.json
用法:python -m research.study16 collect | analyze
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
ROWS = os.path.join(ROOT, "study16_rows.json")
OUT = os.path.join(ROOT, "study16.json")
MAIN = "投信10日>15張+營收動能+無價格條件|依投信買超"
H = 20
WINDOWS = [("20180101", "20230405", "2018-07-02", "2023-03-31"),
           ("20221101", "20261020", "2023-04-01", "2026-09-16")]


def _trade(panel, days, div, code, t):
    """t+1 開盤買、t+H 開盤賣:回傳 (買價, 報酬%, 股利%);跨重新定價或缺價回傳 None。"""
    if t + H >= len(panel) or TY.jump(panel, code, t + 1, t + H):
        return None
    a, b = panel[t + 1].get(code), panel[t + H].get(code)
    if not a or not b or a[TY.O] <= 0 or b[TY.O] <= 0:
        return None
    d0, d1 = days[t + 1], days[t + H]
    dv = sum(v for d, v in div.get(code, {}).items() if d0 < d <= d1)
    return [a[TY.O], (b[TY.O] / a[TY.O] - 1) * 100, dv / a[TY.O] * 100]


def collect():
    div = DV.load(2018, 2026)
    c, v, p, r = dict(G.rule_names())[MAIN]
    fc, fv = G.CHIP[c], G.REV[v]
    rows = []
    for start, end, a, b in WINDOWS:
        TY.START, TY.END = start, end
        days, panel = TY.load()
        margin = [sources.margins(d)[0] for d in days]
        S = CE.Series(days, panel, margin)
        rf = CE.RevFeats()
        adj = TY.adjusted_closes(panel, TY.BENCH)
        fsum = [sum(x[TY.F] for code, x in day.items() if code != TY.BENCH) for day in panel]
        for t in range(CE.WARMUP, len(days) - H - 1):
            d = str(days[t])
            if not (a <= d <= b):
                continue
            rev = rf.get(days[t])
            feats = {code: fx for code in panel[t] if code != TY.BENCH and sources.is_common_stock(code)
                     and (fx := CE.features(S, code, t, rev))}
            cand = sorted((code for code in feats if fc(feats[code]) and fv(feats[code]["rev"])),
                          key=lambda code: -G.RANK[r](feats[code]))[:25]
            ma120 = sum(adj[t - 119:t + 1]) / 120 if all(adj[t - 119:t + 1]) else None
            rows.append({"d": d, "cand": [[code, round(feats[code]["ret20"] * 100, 2), _trade(panel, days, div, code, t)] for code in cand],
                         "bench": _trade(panel, days, div, TY.BENCH, t),
                         "weak120": None if ma120 is None else adj[t] < ma120,
                         "foreignSell": sum(fsum[t - 9:t + 1]) < 0})
            if len(rows) % 200 == 0:
                print(f"已算 {len(rows)} 天,到 {d}", flush=True)
        del S, panel
        gc.collect()
    with open(ROWS, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
    print(f"完成:{len(rows)} 天", flush=True)


# ---------- 分析 ----------
COST, ETF_COST = 0.585, 0.385
FEE, TAX, ETF_TAX = 0.001425, 0.003, 0.001


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def picks(row, n=10, xmax=None):
    return [c for c in row["cand"] if xmax is None or c[1] <= xmax][:n]


def port(row, n=10, xmax=None, div=True):
    m = _mean(c[2][1] + (c[2][2] if div else 0) for c in picks(row, n, xmax) if c[2])
    return None if m is None else m - COST


def bench(row, div=True):
    b = row["bench"]
    return None if not b else b[1] + (b[2] if div else 0)


def weak(row, kind):
    w1, w2 = bool(row["weak120"]), row["foreignSell"]
    return {"F1": w1, "F2": w2, "F3": w1 and w2}[kind]


def tstat_step(xs, step=H):
    pts = [x for k, x in enumerate(xs) if k % step == 0 and x is not None]
    if len(pts) < 3:
        return 0.0
    m = sum(pts) / len(pts)
    sd = math.sqrt(sum((x - m) ** 2 for x in pts) / (len(pts) - 1))
    return m / (sd / math.sqrt(len(pts))) if sd else 0.0


def sharpe(xs):
    """不重疊取樣(間隔 20)的平均 ÷ 標準差,對 20 種起點取平均。"""
    out = []
    for o in range(H):
        pts = [x for k, x in enumerate(xs) if k % H == o and x is not None]
        if len(pts) >= 3:
            m = sum(pts) / len(pts)
            sd = math.sqrt(sum((x - m) ** 2 for x in pts) / (len(pts) - 1))
            if sd:
                out.append(m / sd)
    return sum(out) / len(out) if out else None


def simulate(rows, minfee, offset, mode="base", capital=100000.0):
    """10 萬元每 20 天買一次:整數股、最低手續費、股利以現金收回。mode: base / F1 / F2 / F3 / H1。"""
    cash, curve = capital, []
    for i in range(offset, len(rows), H):
        row = rows[i]
        if mode in ("F1", "F2", "F3") and weak(row, mode):
            legs = [(1.0, row["bench"], True)] if row["bench"] else []
        else:
            share = 0.5 if mode == "H1" else 1.0
            legs = [(share / 10, c[2], False) for c in picks(row) if c[2]]
            if mode == "H1" and row["bench"]:
                legs.append((0.5, row["bench"], True))
        start, spent, back = cash, 0.0, 0.0
        for w, (p1, r, dv), etf in legs:
            budget = start * w
            sh = int(budget // (p1 * (1 + FEE)))
            while sh > 0 and p1 * sh + max(minfee, p1 * sh * FEE) > budget:
                sh -= 1
            if sh <= 0:
                continue
            spent += p1 * sh + max(minfee, p1 * sh * FEE)
            val = p1 * (1 + r / 100) * sh
            back += val - max(minfee, val * FEE) - val * (ETF_TAX if etf else TAX) + p1 * dv / 100 * sh
        cash = cash - spent + back
        curve.append(cash)
    peak, mdd = capital, 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return cash, mdd


def bench_hold(rows, offset, div=True, capital=100000.0):
    v = capital
    for i in range(offset, len(rows), H):
        b = bench(rows[i], div)
        if b is not None:
            v *= 1 + b / 100
    return v


def analyze():
    rows = json.load(open(ROWS, encoding="utf-8"))
    n = len(rows)
    years = (n + H) / 245
    c1, c2 = int(n * 0.6), int(n * 0.8)
    segs = {"train": (0, c1), "valid": (c1, c2), "test": (c2, n)}

    def seg(xs):
        return {k: (None if (m := _mean(xs[a:b])) is None else round(m, 2)) for k, (a, b) in segs.items()}

    def yearly(xs):
        return {y: round(_mean(x for r, x in zip(rows, xs) if r["d"][:4] == y) or 0, 2) for y in sorted({r["d"][:4] for r in rows})}

    def excess(f):
        out = []
        for r in rows:
            p, b = f(r), bench(r)
            out.append(None if p is None or b is None else p - b)
        return out

    res = {"from": rows[0]["d"], "to": rows[-1]["d"], "days": n,
           "segments": {k: [rows[a]["d"], rows[b - 1]["d"]] for k, (a, b) in segs.items()}}

    # 七:股利
    base = excess(port)
    nodiv = []
    for r in rows:
        p, b = port(r, div=False), bench(r, False)
        nodiv.append(None if p is None or b is None else p - b)
    res["dividend"] = {
        "主名單 20 日報酬(扣成本)": {"含股利": round(_mean(port(r) for r in rows), 2), "不含": round(_mean(port(r, div=False) for r in rows), 2)},
        "0050 20 日報酬": {"含股利": round(_mean(bench(r) for r in rows), 2), "不含": round(_mean(bench(r, False) for r in rows), 2)},
        "超額": {"含股利": round(_mean(base), 2), "不含": round(_mean(nodiv), 2)},
        "超額分年(含股利)": yearly(base), "超額分年(不含)": yearly(nodiv)}

    # 八、一、二:10 萬元模擬
    sim = {}
    for mode in ("base", "F1", "F2", "F3", "H1"):
        for minfee in ((1, 20) if mode == "base" else (1,)):
            runs = [simulate(rows, minfee, o, mode) for o in range(H)]
            finals = sorted(f for f, _ in runs)
            mdds = sorted(m for _, m in runs)
            med = finals[H // 2]
            sim[f"{mode}|最低手續費 {minfee} 元"] = {"median": round(med), "worst": round(finals[0]), "best": round(finals[-1]),
                                                 "annual": round(((med / 100000) ** (1 / years) - 1) * 100, 1),
                                                 "mddMedian": round(mdds[H // 2] * 100, 1), "mddWorst": round(mdds[0] * 100, 1)}
    bh = sorted(bench_hold(rows, o) for o in range(H))
    sim["0050 買進持有(含股利)"] = {"median": round(bh[H // 2]), "worst": round(bh[0]), "best": round(bh[-1]),
                                 "annual": round(((bh[H // 2] / 100000) ** (1 / years) - 1) * 100, 1)}
    res["simulation"] = sim

    # 四、五:檔數、排除漲多
    tests, var = [], {}
    for name, kw in (("N5 前 5 檔", {"n": 5}), ("N15 前 15 檔", {"n": 15}),
                     ("X20 排除近20日漲>20%", {"xmax": 20}), ("X30 排除近20日漲>30%", {"xmax": 30})):
        xs = excess(lambda r, kw=kw: port(r, **kw))
        diff = [None if x is None or y is None else x - y for x, y in zip(xs, base)]
        t = tstat_step(diff)
        var[name] = {"excess": round(_mean(xs), 2), "seg": seg(xs), "diff": round(_mean(diff), 2), "diffSeg": seg(diff),
                     "t": round(t, 2), "p": round(0.5 * math.erfc(t / math.sqrt(2)), 4), "byYear": yearly(xs)}
        tests.append(name)
    alive = True
    for i, k in enumerate(sorted(tests, key=lambda k: var[k]["p"])):
        alive = alive and var[k]["p"] <= 0.05 / (len(tests) - i)
        var[k]["pass"] = bool(alive and all(x is not None and x > 0 for x in var[k]["diffSeg"].values()))
    res["base"] = {"excess": round(_mean(base), 2), "seg": seg(base), "t": round(tstat_step(base), 2), "byYear": yearly(base)}
    res["countFilter"] = var

    # 一、二:風險調整
    def raw(mode):
        out = []
        for r in rows:
            p, b = port(r), bench(r)
            if mode == "base":
                out.append(p)
            elif mode == "H1":
                out.append(None if p is None or b is None else 0.5 * p + 0.5 * (b - ETF_COST))
            elif weak(r, mode):
                out.append(None if b is None else b - ETF_COST)
            else:
                out.append(p)
        return out
    risk = {}
    for mode in ("base", "F1", "F2", "F3", "H1"):
        xs = raw(mode)
        risk[mode] = {"ret": round(_mean(xs), 2), "sharpe": round(sharpe(xs), 3),
                      "sharpeSeg": {k: round(sharpe(xs[a:b]), 3) for k, (a, b) in segs.items()},
                      "weakShare": None if mode in ("base", "H1") else round(100 * sum(weak(r, mode) for r in rows) / n, 1)}
    for mode in ("F1", "F2", "F3", "H1"):
        risk[mode]["pass"] = all(risk[mode]["sharpeSeg"][k] > risk["base"]["sharpeSeg"][k] for k in segs)
    bs = [bench(r) for r in rows]
    risk["0050"] = {"ret": round(_mean(bs), 2), "sharpe": round(sharpe(bs), 3),
                    "sharpeSeg": {k: round(sharpe(bs[a:b]), 3) for k, (a, b) in segs.items()}}
    res["risk"] = risk
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    {"collect": collect, "analyze": analyze}[sys.argv[1]]()
