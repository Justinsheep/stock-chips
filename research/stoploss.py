"""追加研究一:R2 投信買超+營收動能加停損(登記內容見 RESEARCH.md)。

用法:python -m research.stoploss
輸出:research/stoploss.json 與終端機摘要
"""
import json
import os

from chips.revenue import Revenue

from . import engine as E

OUT = os.path.join(E.ROOT, "stoploss.json")
H = 20
RULE = "R2 投信買超+營收動能"
VARIANTS = {"R2 不停損(基準)": None,
            "S7c 收盤停損 7%": ("close", 7), "S10c 收盤停損 10%": ("close", 10), "S15c 收盤停損 15%": ("close", 15),
            "S7i 盤中停損 7%": ("intraday", 7), "S10i 盤中停損 10%": ("intraday", 10), "S15i 盤中停損 15%": ("intraday", 15)}


def trade(panel, code, t, variant):
    """t 收盤選股、t+1 開盤買;回傳 (報酬%,是否停損)。資料不足或跨重新定價回傳 None。"""
    e, last = panel[t + 1].get(code), panel[t + H].get(code)
    if not e or not last or e["open"] <= 0 or last["close"] <= 0 or E.reset(panel, code, t + 1, t + H):
        return None
    entry = e["open"]
    if variant:
        kind, pct = variant
        stop = entry * (1 - pct / 100)
        for k in range(t + 1, t + H + 1):
            x = panel[k].get(code)
            if not x or x["close"] <= 0:
                continue
            if kind == "intraday":
                if x["open"] <= stop:
                    return (x["open"] / entry - 1) * 100, True
                if x["low"] <= stop:
                    return (stop / entry - 1) * 100, True
            elif x["close"] <= stop and k < t + H:
                nxt = panel[k + 1].get(code)
                if nxt and nxt["open"] > 0:
                    return (nxt["open"] / entry - 1) * 100, True
    return (last["close"] / entry - 1) * 100, False


def run():
    days, panel, margin = E.load_panel()
    rev, rev_cache = Revenue(), {}
    rows = []
    for t in range(20, len(days) - H):
        f = E.features(t, panel, margin)
        key = days[t].strftime("%Y%m") + ("b" if days[t].day > 10 else "a")
        if key not in rev_cache:
            rev_cache[key] = rev.momentum(days[t])
        rows.append((t, E.RULES[RULE](f, rev_cache[key])))
    n = len(rows)
    cut1, cut2 = int(n * E.SPLITS[0]), int(n * E.SPLITS[1])
    seg_of = lambda i: "train" if i < cut1 else "valid" if i < cut2 else "test"
    out = {}
    for name, v in VARIANTS.items():
        seg = {"train": [], "valid": [], "test": []}
        trades = []
        for i, (t, picks) in enumerate(rows):
            b = E.hold_return(panel, E.BENCH, t, H)
            if b is None:
                continue
            res = [r for c in picks if (r := trade(panel, c, t, v)) is not None]
            trades += res
            ret = sum(r for r, _ in res) / len(res) - E.COST if res else 0.0
            seg[seg_of(i)].append((ret, ret - b))
        out[name] = {
            **{k: {"excess": round(sum(x[1] for x in s) / len(s), 2), "ret": round(sum(x[0] for x in s) / len(s), 2),
                   "beat": round(sum(1 for x in s if x[1] > 0) / len(s) * 100, 1)} for k, s in seg.items()},
            "stopRate": round(sum(1 for _, hit in trades if hit) / len(trades) * 100, 1) if trades else None,
            "worst": round(min(r for r, _ in trades), 2) if trades else None,
            "loss20": round(sum(1 for r, _ in trades if r <= -20) / len(trades) * 100, 1) if trades else None,
        }
    base = out["R2 不停損(基準)"]
    passing = [k for k, s in out.items() if VARIANTS[k] and all(
        s[g]["excess"] > 0 and s[g]["excess"] > base[g]["excess"] for g in ("train", "valid", "test"))]
    chosen = max(passing, key=lambda k: out[k]["train"]["excess"]) if passing else None
    doc = {"hold": H, "segments": {"train": [str(days[rows[0][0]]), str(days[rows[cut1 - 1][0]])],
                                   "valid": [str(days[rows[cut1][0]]), str(days[rows[cut2 - 1][0]])],
                                   "test": [str(days[rows[cut2][0]]), str(days[rows[-1][0]])]},
           "results": out, "passing": passing, "chosen": chosen}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    return doc


if __name__ == "__main__":
    d = run()
    print("期間:", d["segments"])
    for k, s in d["results"].items():
        print(f"{k:<16} 訓練 {s['train']['excess']:+.2f}% 驗證 {s['valid']['excess']:+.2f}% 測試 {s['test']['excess']:+.2f}%"
              f" | 停損比例 {s['stopRate']}% 最差一筆 {s['worst']}% 虧 20% 以上 {s['loss20']}%")
    print("通過:", d["passing"], "採用:", d["chosen"])
