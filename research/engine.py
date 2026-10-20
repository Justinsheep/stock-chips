"""研究用回測引擎:照 RESEARCH.md 預先登記的規則與三段驗證跑一次。

用法:python -m research.engine            # 讀 cache/ 的歷史資料,不連網(月營收若未快取才會抓)
輸出:research/results.json 與終端機摘要
"""
import datetime as dt
import json
import os
import re

from chips import sources
from chips.revenue import Revenue
from chips.score import pct_rank

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "results.json")

START, END = "20251001", "20261016"
HORIZONS = (5, 10, 20)
MAIN_H = 20
COST = 0.585            # 手續費 0.1425%×2 + 證交稅 0.3%
TOP = 10
MIN_LOTS = 300          # 20 日均量(張)
MIN_PRICE = 10
SPLITS = (0.6, 0.8)     # 訓練 / 驗證 / 測試 切點
BENCH = "0050"


def load_panel():
    dates = sorted(m.group(1) for n in os.listdir(sources.CACHE)
                   if (m := re.fullmatch(r"twse_t86_(\d{8})\.json", n)) and START <= m.group(1) <= END)
    days, panel, margin = [], [], []
    for s in dates:
        d = dt.datetime.strptime(s, "%Y%m%d").date()
        data = sources.load_day(d)
        if not data:
            continue
        mg, _ = sources.margins(d)
        days.append(d)
        panel.append(data)
        margin.append(mg)
    return days, panel, margin


def features(t, panel, margin):
    """第 t 天收盤後的特徵(只用 t 以前的資料)。"""
    today = panel[t]
    out = {}
    for code, x in today.items():
        if not sources.is_common_stock(code) or x["close"] < MIN_PRICE or x["close"] <= 0:
            continue
        hist = [panel[k].get(code) for k in range(max(0, t - 59), t + 1)]
        last20 = [h for h in hist[-20:] if h]
        if len(last20) < 20:
            continue
        vol20 = sum(h["vol"] for h in last20) / 20 / 1000
        if vol20 <= MIN_LOTS:
            continue
        last10 = [h for h in hist[-10:] if h]
        last5 = [h for h in hist[-5:] if h]
        closes60 = [h["close"] for h in hist if h]
        foreign = [h["foreign"] for h in reversed(last5)]
        trust = [h["trust"] for h in reversed(last5)]
        out[code] = {
            "close": x["close"], "vol": x["vol"] / 1000, "vol20": vol20,
            "trust10": sum(h["trust"] for h in last10) / 1000,
            "foreign10": sum(h["foreign"] for h in last10) / 1000,
            "inst1": x["inst"] / 1000, "inst5": sum(h["inst"] for h in last5) / 1000,
            "avg5": sum(h["vol"] for h in last5) / len(last5) / 1000,
            "fStreak": next((i for i, v in enumerate(foreign) if v <= 0), len(foreign)),
            "tStreak": next((i for i, v in enumerate(trust) if v <= 0), len(trust)),
            "margin": margin[t].get(code, 0.0),
            "high60": len(closes60) >= 60 and x["close"] >= max(closes60),
            "ret20": (x["close"] / last20[0]["close"] - 1) * 100 if last20[0]["close"] else 0,
        }
    return out


def rev_ok(code, rev):
    r = rev.get(code)
    return bool(r and r["high3"] and r["yoy"] > 20)


def top(items, key):
    return [c for c, _ in sorted(items, key=lambda kv: -key(kv[1]))[:TOP]]


def rule_r0(f, rev):
    """現行籌碼分數(不含千張大戶),全市場百分位,當日法人須買超。"""
    codes = list(f)
    if not codes:
        return []
    r1 = pct_rank([f[c]["inst1"] / f[c]["avg5"] for c in codes])
    r5 = pct_rank([f[c]["inst5"] / (f[c]["avg5"] * 5) for c in codes])
    rs = pct_rank([f[c]["fStreak"] + f[c]["tStreak"] * 1.5 for c in codes])
    rm = pct_rank([-f[c]["margin"] / f[c]["avg5"] for c in codes])
    score = {c: a * 25 + b * 25 + s * 10 + m * 15 for c, a, b, s, m in zip(codes, r1, r5, rs, rm)}
    return top([(c, score[c]) for c in codes if f[c]["inst1"] > 0], lambda s: s)


RULES = {
    "R0 現行籌碼分數(不含大戶)": rule_r0,
    "R1 投信10日買超": lambda f, rev: top([(c, x) for c, x in f.items() if x["trust10"] > 15], lambda x: x["trust10"]),
    "R2 投信買超+營收動能": lambda f, rev: top([(c, x) for c, x in f.items() if x["trust10"] > 15 and rev_ok(c, rev)],
                                         lambda x: x["trust10"]),
    "R3 營收動能": lambda f, rev: top([(c, rev[c]["yoy"]) for c in f if rev_ok(c, rev)], lambda y: y),
    "R4 投信買+外資賣": lambda f, rev: top([(c, x) for c, x in f.items() if x["trust10"] > 15 and x["foreign10"] < 0],
                                     lambda x: x["trust10"]),
    "R5 投信買+外資賣+營收動能": lambda f, rev: top([(c, x) for c, x in f.items()
                                            if x["trust10"] > 15 and x["foreign10"] < 0 and rev_ok(c, rev)],
                                           lambda x: x["trust10"]),
    "R6 60日新高+量增": lambda f, rev: top([(c, x) for c, x in f.items() if x["high60"] and x["vol"] > 1.5 * x["vol20"]],
                                      lambda x: x["ret20"]),
}


def reset(panel, code, a, b):
    for k in range(max(1, a), b + 1):
        p, c = panel[k - 1].get(code), panel[k].get(code)
        if p and c and p["close"] > 0 and c["open"] > 0 and abs(c["open"] / p["close"] - 1) > 0.11:
            return True
    return False


def hold_return(panel, code, t, h):
    """t 收盤選股,t+1 開盤買,t+h 收盤賣,扣成本(%);資料不足或跨重新定價回傳 None。"""
    e, x = panel[t + 1].get(code), panel[t + h].get(code)
    if not e or not x or e["open"] <= 0 or x["close"] <= 0 or reset(panel, code, t + 1, t + h):
        return None
    return (x["close"] / e["open"] - 1) * 100


def run():
    days, panel, margin = load_panel()
    print(f"交易日 {len(days)} 天:{days[0]} ~ {days[-1]}")
    rev = Revenue()
    rev_by_month = {}
    start_t = 20
    cohorts = []   # (t, {rule: picks})
    for t in range(start_t, len(days) - 1):
        f = features(t, panel, margin)
        ym = days[t].strftime("%Y%m") + ("b" if days[t].day > 10 else "a")
        if ym not in rev_by_month:
            rev_by_month[ym] = rev.momentum(days[t])
        r = rev_by_month[ym]
        cohorts.append((t, {name: fn(f, r) for name, fn in RULES.items()}))
    results = {}
    for h in HORIZONS:
        rows = [(t, picks) for t, picks in cohorts if t + h < len(days)]
        n = len(rows)
        cut1, cut2 = int(n * SPLITS[0]), int(n * SPLITS[1])
        seg_of = lambda i: "train" if i < cut1 else "valid" if i < cut2 else "test"
        per_rule = {}
        for name in RULES:
            seg = {"train": [], "valid": [], "test": []}
            for i, (t, picks) in enumerate(rows):
                b = hold_return(panel, BENCH, t, h)
                if b is None:
                    continue
                rets = [r for c in picks[name] if (r := hold_return(panel, c, t, h)) is not None]
                ret = sum(rets) / len(rets) - COST if rets else 0.0   # 沒選到股票 = 持有現金
                seg[seg_of(i)].append((ret, ret - b, len(rets)))
            per_rule[name] = {k: {
                "cohorts": len(v),
                "ret": round(sum(x[0] for x in v) / len(v), 2) if v else None,
                "excess": round(sum(x[1] for x in v) / len(v), 2) if v else None,
                "beat": round(sum(1 for x in v if x[1] > 0) / len(v) * 100, 1) if v else None,
                "avgPicks": round(sum(x[2] for x in v) / len(v), 1) if v else None,
            } for k, v in seg.items()}
        results[h] = {"segments": {
            "train": [str(days[rows[0][0]]), str(days[rows[cut1 - 1][0]])],
            "valid": [str(days[rows[cut1][0]]), str(days[rows[cut2 - 1][0]])],
            "test": [str(days[rows[cut2][0]]), str(days[rows[-1][0]])]}, "rules": per_rule}
    # 依 RESEARCH.md 的選法
    m = results[MAIN_H]["rules"]
    stage1 = [r for r in m if m[r]["train"]["excess"] is not None and m[r]["train"]["excess"] > 0]
    stage2 = [r for r in stage1 if m[r]["valid"]["excess"] is not None and m[r]["valid"]["excess"] > 0]
    chosen = max(stage2, key=lambda r: m[r]["train"]["excess"]) if stage2 else None
    passed = bool(chosen and m[chosen]["test"]["excess"] is not None and m[chosen]["test"]["excess"] > 0)
    decision = {"stage1": stage1, "stage2": stage2, "chosen": chosen, "passed": passed}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"results": results, "decision": decision, "cost": COST, "top": TOP}, fh, ensure_ascii=False, indent=1)
    return results, decision


if __name__ == "__main__":
    res, dec = run()
    for h, r in res.items():
        print(f"\n== 持有 {h} 日 == 訓練 {r['segments']['train']} 驗證 {r['segments']['valid']} 測試 {r['segments']['test']}")
        for name, s in r["rules"].items():
            print(f"{name:<22} " + " | ".join(
                f"{k} 超額 {s[k]['excess']}% 報酬 {s[k]['ret']}% 贏大盤 {s[k]['beat']}% 檔數 {s[k]['avgPicks']}"
                for k in ("train", "valid", "test")))
    print("\n決策:", dec)
