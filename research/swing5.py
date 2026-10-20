"""追加研究三:5 日波段策略(登記內容見 RESEARCH.md)。

用法:python -m research.swing5
輸出:research/swing5.json 與終端機摘要
"""
import json
import os

from chips.revenue import Revenue

from . import engine as E

OUT = os.path.join(E.ROOT, "swing5.json")
START, END = "20250701", "20261016"
H = 5
WARMUP = 60
MIN_LOTS = 500
TOP = 10
TP_ATR, LIMIT_ATR = 1.5, 0.5


def feats(t, panel):
    out = {}
    for code, x in panel[t].items():
        if not E.sources.is_common_stock(code) or x["close"] < E.MIN_PRICE:
            continue
        hist = [panel[k].get(code) for k in range(t - 60, t + 1)]
        if any(h is None or h["close"] <= 0 for h in hist):
            continue
        closes = [h["close"] for h in hist]
        vol20 = sum(h["vol"] for h in hist[-20:]) / 20 / 1000
        if vol20 <= MIN_LOTS:
            continue
        ma = lambda n: sum(closes[-n:]) / n
        d1, d2 = closes[-1] - closes[-2], closes[-2] - closes[-3]
        up = max(d1, 0) + max(d2, 0)
        down = max(-d1, 0) + max(-d2, 0)
        rsi2 = 100.0 if down == 0 else 100 - 100 / (1 + up / down)
        trs = [max(h["high"] - h["low"], abs(h["high"] - p["close"]), abs(h["low"] - p["close"]))
               for p, h in zip(hist[-11:-1], hist[-10:])]
        out[code] = {
            "close": x["close"], "low": x["low"], "vol": x["vol"] / 1000, "vol20": vol20,
            "ma5": ma(5), "ma10": ma(10), "ma20": ma(20), "ma60": ma(60), "rsi2": rsi2,
            "atr": sum(trs) / len(trs), "high20": max(closes[-20:]),
            "trust10": sum(h["trust"] for h in hist[-10:]) / 1000, "inst1": x["inst"] / 1000,
        }
    return out


def top(items, key, reverse=True):
    return [c for c, _ in sorted(items, key=lambda kv: key(kv[1]), reverse=reverse)[:TOP]]


def signals(f, rev):
    return {
        "F1 RSI(2) 回檔": top([(c, x) for c, x in f.items() if x["close"] > x["ma60"] and x["rsi2"] < 10],
                            lambda x: x["rsi2"], reverse=False),
        "F2 好股回檔": top([(c, x) for c, x in f.items() if x["trust10"] > 15 and E.rev_ok(c, rev)
                         and x["close"] > x["ma60"] and x["rsi2"] < 20], lambda x: x["trust10"]),
        "F3 均線回測": top([(c, x) for c, x in f.items() if x["ma5"] > x["ma10"] > x["ma20"]
                         and x["low"] <= x["ma10"] <= x["close"] and x["trust10"] > 0], lambda x: x["trust10"]),
        "F4 帶量突破": top([(c, x) for c, x in f.items() if x["close"] >= x["high20"] and x["vol"] > 2 * x["vol20"]
                         and x["inst1"] > 0], lambda x: x["vol"] / x["vol20"]),
    }


def trade(panel, code, t, mode, k):
    """回傳 (報酬% 未扣成本, 是否達標) ;沒買到回傳 False;資料不足回傳 None。"""
    if t + H >= len(panel):
        return None
    if E.reset(panel, code, t + 1, t + H):
        return None
    e = panel[t + 1].get(code)
    if not e or e["open"] <= 0:
        return None
    if mode == "E3":
        limit = k["close"] - LIMIT_ATR * k["atr"]
        if e["open"] <= limit:
            entry = e["open"]
        elif e["low"] <= limit:
            entry = limit
        else:
            return False
    else:
        entry = e["open"]
    target = entry + TP_ATR * k["atr"]
    for j in range(t + 1, t + H + 1):
        x = panel[j].get(code)
        if not x or x["close"] <= 0:
            continue
        # 進場當天:E3 是盤中掛單買到,當天高點不一定發生在買進之後,保守起見進場日不算達標
        if mode in ("E2", "E3") and not (mode == "E3" and j == t + 1):
            if x["open"] >= target and j > t + 1:
                return (x["open"] / entry - 1) * 100, True
            if x["high"] >= target:
                return (target / entry - 1) * 100, True
        if j == t + H:
            return (x["close"] / entry - 1) * 100, False
    return None


def run():
    E.START, E.END = START, END
    days, panel, margin = E.load_panel()
    rev, rc = Revenue(), {}
    rows = []
    for t in range(WARMUP, len(days) - H):
        f = feats(t, panel)
        key = days[t].strftime("%Y%m") + ("b" if days[t].day > 10 else "a")
        if key not in rc:
            rc[key] = rev.momentum(days[t])
        rows.append((t, f, signals(f, rc[key])))
    n = len(rows)
    cut1, cut2 = int(n * E.SPLITS[0]), int(n * E.SPLITS[1])
    seg_of = lambda i: "train" if i < cut1 else "valid" if i < cut2 else "test"
    results = {}
    for fam in rows[0][2]:
        for mode in ("E1", "E2", "E3"):
            seg = {"train": [], "valid": [], "test": []}
            trades = []
            for i, (t, f, sig) in enumerate(rows):
                b = E.hold_return(panel, E.BENCH, t, H)
                if b is None:
                    continue
                res = [r for c in sig[fam] if (r := trade(panel, c, t, mode, f[c]))]
                trades += res
                ret = sum(r for r, _ in res) / len(res) - E.COST if res else 0.0
                seg[seg_of(i)].append((ret, ret - b, len(res)))
            stat = lambda v: {"ret": round(sum(x[0] for x in v) / len(v), 2), "excess": round(sum(x[1] for x in v) / len(v), 2),
                              "monthly": round(((1 + sum(x[0] for x in v) / len(v) / 100) ** (21 / H) - 1) * 100, 1),
                              "avgN": round(sum(x[2] for x in v) / len(v), 1)}
            results[f"{fam} × {mode}"] = {
                **{k: stat(v) for k, v in seg.items()},
                "trades": len(trades),
                "win": round(sum(1 for r, _ in trades if r - E.COST > 0) / len(trades) * 100, 1) if trades else None,
                "hitTarget": round(sum(1 for _, h in trades if h) / len(trades) * 100, 1) if trades else None,
            }
    s1 = [k for k, v in results.items() if v["train"]["ret"] > 0 and v["train"]["excess"] > 0]
    s2 = [k for k in s1 if results[k]["valid"]["ret"] > 0 and results[k]["valid"]["excess"] > 0]
    chosen = max(s2, key=lambda k: results[k]["train"]["excess"]) if s2 else None
    passed = bool(chosen and results[chosen]["test"]["ret"] > 0 and results[chosen]["test"]["excess"] > 0)
    doc = {"segments": {"train": [str(days[rows[0][0]]), str(days[rows[cut1 - 1][0]])],
                        "valid": [str(days[rows[cut1][0]]), str(days[rows[cut2 - 1][0]])],
                        "test": [str(days[rows[cut2][0]]), str(days[rows[-1][0]])]},
           "results": results, "stage1": s1, "stage2": s2, "chosen": chosen, "passed": passed}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    return doc


if __name__ == "__main__":
    d = run()
    print("期間:", d["segments"])
    for k, v in d["results"].items():
        print(f"{k:<20} " + " | ".join(f"{s} 5日 {v[s]['ret']:+.2f}% 超額 {v[s]['excess']:+.2f}% 月化 {v[s]['monthly']:+.1f}% 檔 {v[s]['avgN']}"
                                       for s in ("train", "valid", "test")) + f" | 勝率 {v['win']}% 達標 {v['hitTarget']}%")
    print("訓練通過:", d["stage1"])
    print("驗證通過:", d["stage2"])
    print("採用:", d["chosen"], "最終測試通過:", d["passed"])
