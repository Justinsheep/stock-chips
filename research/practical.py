"""研究十五:實際操作模擬、持有天數、訊號出場、合併名單(登記見 RESEARCH.md)。

第一步 collect:逐日產生主名單、第 3 名名單,以及每檔 9:10 零股的各種報酬,存成 practical_rows.json。
第二步 analyze:讀取上面的檔案做模擬與檢定,結果存 practical.json。
用法:python -m research.practical collect | analyze
"""
import gc
import json
import math
import os
import sys

from chips import sources
from . import census as CE
from . import grid as G
from . import three_year as TY
from .oddlot import odd_open

ROOT = os.path.dirname(os.path.abspath(__file__))
ROWS = os.path.join(ROOT, "practical_rows.json")
OUT = os.path.join(ROOT, "practical.json")
MAIN = "投信10日>15張+營收動能+無價格條件|依投信買超"
ALT3 = "無籌碼條件+單月營收新高+均線多頭|依投信買超"
HS = (10, 20, 30, 40, 60)
WINDOWS = [("20200401", "20230705", "2020-11-02", "2023-03-31"),
           ("20221101", "20261020", "2023-04-01", "2026-07-20")]
C = 3   # 收盤欄位(TY 的 tuple:O,H,L,C,...)


def _ret(panel, odd, code, t, k):
    """t+1 的 9:10 買、k 的 9:10 賣(%);缺價或跨重新定價回傳 None。"""
    if k >= len(panel) or TY.jump(panel, code, t + 1, k):
        return None
    a, b = odd[t + 1].get(code), odd[k].get(code)
    return (b / a - 1) * 100 if a and b else None


def _signals(S, rf, days, code, k):
    s = S.f[code]
    row = s["row"][k]
    if not row:
        return {}
    rv = rf.get(days[k]).get(code)
    return {"S1": S.win(code, "tr", k, 5) < 0, "S2": row[C] < S.ma(code, k, 20),
            "S3": S.win(code, "tr", k, 10) < 0, "S4": not (rv and rv["high3"] and rv["yoy"] > 20)}


def collect():
    rules = {k: v for k, v in G.rule_names() if k in (MAIN, ALT3)}
    rows = []
    for start, end, a, b in WINDOWS:
        TY.START, TY.END = start, end
        days, panel = TY.load()
        odd = [odd_open(d) for d in days]
        margin = [sources.margins(d)[0] for d in days]
        S = CE.Series(days, panel, margin)
        rf = CE.RevFeats()
        for t in range(CE.WARMUP, len(days) - max(HS) - 1):
            d = str(days[t])
            if not (a <= d <= b):
                continue
            rev = rf.get(days[t])
            feats = {c: fx for c in panel[t] if c != TY.BENCH and sources.is_common_stock(c)
                     and (fx := CE.features(S, c, t, rev))}
            picks = {}
            for key, (c, v, p, r) in rules.items():
                fc, fv, fp = G.CHIP[c], G.REV[v], G.PRICE[p]
                cand = [code for code in feats if (fc is None or fc(feats[code])) and (fv is None or fv(feats[code]["rev"]))
                        and (fp is None or fp(feats[code]))]
                picks[key] = sorted(cand, key=lambda code: -G.RANK[r](feats[code]))[:G.TOP]
            px = {}
            for code in set(picks[MAIN]) | set(picks[ALT3]) | {TY.BENCH}:
                x = {"p1": odd[t + 1].get(code), "r": {h: _ret(panel, odd, code, t, t + h) for h in HS}}
                if code in picks[MAIN]:
                    sig = {}
                    for name in ("S1", "S2", "S3", "S4"):
                        exit_k = None
                        for k in range(t + 1, t + 20):
                            if _signals(S, rf, days, code, k).get(name) and odd[k + 1].get(code):
                                exit_k = k + 1
                                break
                        sig[name] = [x["r"][20], 20] if exit_k is None else [_ret(panel, odd, code, t, exit_k), exit_k - t]
                    x["s"] = sig
                px[code] = x
            rows.append({"d": d, "main": picks[MAIN], "alt3": picks[ALT3], "px": px})
            if len(rows) % 100 == 0:
                print(f"已算 {len(rows)} 天,到 {d}", flush=True)
        del S, panel, odd
        gc.collect()
    with open(ROWS, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
    print(f"完成:{len(rows)} 天", flush=True)


# ---------- 分析 ----------
COST = 0.585
FEE, TAX = 0.001425, 0.003


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def simulate(rows, lanes, minfee, offset, capital=100000.0):
    """主名單 10 萬元實際操作:分 lanes 份,每 20/lanes 天買一次,整數股,最低手續費。"""
    step = 20 // lanes
    cash = [capital / lanes] * lanes
    pending = {}   # 結算列 -> [(lane, 金額)]
    locked = [0.0] * lanes
    curve = []
    for i, row in enumerate(rows):
        for lane, val in pending.pop(i, []):
            cash[lane] += val
            locked[lane] = 0.0
        if i >= offset and (i - offset) % step == 0:
            lane = ((i - offset) // step) % lanes
            budget, spent, proceeds = cash[lane] / 10, 0.0, 0.0
            for code in row["main"]:
                x = row["px"][code]
                p1, r = x["p1"], x["r"]["20"]
                if not p1 or r is None:
                    continue
                sh = int(budget // (p1 * (1 + FEE)))
                while sh > 0 and p1 * sh + max(minfee, p1 * sh * FEE) > budget:
                    sh -= 1
                if sh <= 0:
                    continue
                cost = p1 * sh + max(minfee, p1 * sh * FEE)
                val = p1 * (1 + r / 100) * sh
                spent += cost
                proceeds += val - max(minfee, val * FEE) - val * TAX
            if spent:
                cash[lane] -= spent
                locked[lane] = spent
                pending.setdefault(i + 20, []).append((lane, proceeds))
        curve.append(sum(cash) + sum(locked))
    for vals in pending.values():
        for lane, val in vals:
            cash[lane] += val
    final = sum(cash)
    peak, mdd = 0.0, 0.0
    for v in curve + [final]:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return final, mdd


def bench_hold(rows, offset, capital=100000.0):
    v = capital
    for i in range(offset, len(rows), 20):
        r = rows[i]["px"][TY.BENCH]["r"]["20"]
        if r is not None:
            v *= 1 + r / 100
    return v


def tstat_step(xs, step):
    pts = [x for k, x in enumerate(xs) if k % step == 0 and x is not None]
    if len(pts) < 3:
        return 0.0
    m = sum(pts) / len(pts)
    sd = math.sqrt(sum((x - m) ** 2 for x in pts) / (len(pts) - 1))
    return m / (sd / math.sqrt(len(pts))) if sd else 0.0


def variants(rows):
    def b(row, h):
        return row["px"][TY.BENCH]["r"][str(h)]

    def eq20(r, h):
        return ((1 + r / 100) ** (20 / h) - 1) * 100

    def base(row):
        m, bb = _mean(row["px"][c]["r"]["20"] for c in row["main"]), b(row, 20)
        return None if m is None or bb is None else m - COST - bb

    out = {"基準 主名單 20 日": (base, 20)}
    for h in (10, 30, 40, 60):
        def f(row, h=h):
            m, bb = _mean(row["px"][c]["r"][str(h)] for c in row["main"]), b(row, h)
            return None if m is None or bb is None else eq20(m - COST, h) - eq20(bb, h)
        out[f"H{h} 持有 {h} 日"] = (f, max(h, 20))
    names = {"S1": "S1 投信5日轉賣超出場", "S2": "S2 跌破20日均線出場", "S3": "S3 投信10日轉賣超出場", "S4": "S4 營收動能消失出場"}
    for k, label in names.items():
        def f(row, k=k):
            m, bb = _mean(row["px"][c]["s"][k][0] for c in row["main"]), b(row, 20)
            return None if m is None or bb is None else m - COST - bb
        out[label] = (f, 20)

    def c1(row):
        m = _mean(row["px"][c]["r"]["20"] for c in row["main"])
        a = _mean(row["px"][c]["r"]["20"] for c in row["alt3"])
        bb = b(row, 20)
        if bb is None or (m is None and a is None):
            return None
        mix = m if a is None else a if m is None else (m + a) / 2
        return mix - COST - bb

    def c2(row):
        m = _mean(row["px"][c]["r"]["20"] for c in dict.fromkeys(row["main"] + row["alt3"]))
        bb = b(row, 20)
        return None if m is None or bb is None else m - COST - bb
    out["C1 主名單與第3名各半"] = (c1, 20)
    out["C2 兩份名單聯集等權"] = (c2, 20)
    return out


def analyze():
    rows = json.load(open(ROWS, encoding="utf-8"))
    n = len(rows)
    years = (n + 20) / 245
    res = {"from": rows[0]["d"], "to": rows[-1]["d"], "days": n, "practical": {}, "variants": {}}
    for lanes, label in ((20, "每天買"), (4, "每 5 天買"), (1, "每 20 天買")):
        for minfee in (1, 20):
            sims = [simulate(rows, lanes, minfee, o) for o in range(20 // lanes)]
            finals = sorted(f for f, _ in sims)
            med = finals[len(finals) // 2]
            res["practical"][f"{label}|最低手續費 {minfee} 元"] = {
                "median": round(med), "worst": round(finals[0]), "best": round(finals[-1]),
                "annual": round(((med / 100000) ** (1 / years) - 1) * 100, 1),
                "maxDrawdown": round(min(m for _, m in sims) * 100, 1)}
    bh = sorted(bench_hold(rows, o) for o in range(20))
    res["practical"]["0050 買進持有"] = {"median": round(bh[10]), "worst": round(bh[0]), "best": round(bh[-1]),
                                       "annual": round(((bh[10] / 100000) ** (1 / years) - 1) * 100, 1)}
    c1, c2 = int(n * 0.6), int(n * 0.8)
    segs = {"train": (0, c1), "valid": (c1, c2), "test": (c2, n)}
    V = variants(rows)
    base = [V["基準 主名單 20 日"][0](r) for r in rows]
    tests = []
    for name, (f, step) in V.items():
        xs = [f(r) for r in rows]
        info = {"excess": round(_mean(xs), 2),
                "seg": {k: round(_mean(xs[a:b]), 2) for k, (a, b) in segs.items()},
                "byYear": {y: round(_mean(x for r, x in zip(rows, xs) if r["d"][:4] == y), 2) for y in sorted({r["d"][:4] for r in rows})}}
        if name.startswith("基準"):
            res["variants"][name] = info
            continue
        diff = [None if x is None or y is None else x - y for x, y in zip(xs, base)]
        t = tstat_step(diff, step)
        info.update({"diff": round(_mean(diff), 2), "diffSeg": {k: round(_mean(diff[a:b]), 2) for k, (a, b) in segs.items()},
                     "t": round(t, 2), "p": round(0.5 * math.erfc(t / math.sqrt(2)), 4)})
        if name[0] == "S":
            k = name[:2]
            info["avgHeld"] = round(_mean(r["px"][c]["s"][k][1] for r in rows for c in r["main"]), 1)
        res["variants"][name] = info
        tests.append(name)
    order = sorted(tests, key=lambda k: res["variants"][k]["p"])
    alive = True
    for i, k in enumerate(order):
        v = res["variants"][k]
        alive = alive and v["p"] <= 0.05 / (len(order) - i)
        v["pass"] = bool(alive and all(x > 0 for x in v["diffSeg"].values()))
    res["segments"] = {k: [rows[a]["d"], rows[b - 1]["d"]] for k, (a, b) in segs.items()}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    {"collect": collect, "analyze": analyze}[sys.argv[1]]()
