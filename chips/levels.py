"""參考進場價(波段推薦)與當沖停利停損價,以及驗證它們的回測。

只用每日開高低收,所以:
- 掛單是否成交:隔天開盤 ≤ 掛價 → 以開盤價成交;否則最低價 ≤ 掛價 → 以掛價成交;都沒碰到 → 沒買到。
- 當沖同一天停利、停損都碰到時無法得知先後,一律保守當作先停損。
通過標準:資料切成前後兩半,規則在兩半都要贏過基準(隔天開盤直接買)才算通過。
"""
import json
import math
import os

from .exits import price_reset
from .sources import DATA

DAYS_DIR = os.path.join(DATA, "days")
PRICES_DIR = os.path.join(DATA, "prices")
LEVELS_PATH = os.path.join(DATA, "levels.json")

HOLD = 5                 # 波段持有天數(進場日算第 1 天,第 5 天收盤出場)
DT_COST = 0.30           # 當沖來回成本 %:手續費 0.1425%×2 以 5 折估 + 當沖證交稅 0.15%
MIN_FILL = 0.5           # 參考進場價至少要有一半的機會買得到

# 波段進場規則:名稱 -> 由當天指標算出掛價的函式(None 代表開盤市價買)
ENTRY_RULES = {
    "隔天開盤買(基準)": None,
    "收盤價 −1%": lambda k: k["close"] * 0.99,
    "收盤價 −2%": lambda k: k["close"] * 0.98,
    "樞紐價 P": lambda k: k["pivot"],
    "支撐價 S1": lambda k: k["s1"],
    "5 日均線": lambda k: min(k["ma5"], k["close"]) if k["ma5"] else None,
    "收盤 − 0.5×ATR": lambda k: k["close"] - 0.5 * k["atr"] if k["atr"] else None,
    "收盤 − 1×ATR": lambda k: k["close"] - 1.0 * k["atr"] if k["atr"] else None,
}
GAP_SKIP = 3.0           # 「不追高」規則:開盤比昨收高超過 3% 就不買
DT_GRID = [(a, b) for a in (0.3, 0.5, 0.8, 1.2) for b in (0.3, 0.5, 0.8, 1.2)]   # 停利、停損各幾倍 ATR


def _load_dir(path):
    out = {}
    if os.path.isdir(path):
        for n in sorted(os.listdir(path)):
            if n.endswith(".json"):
                with open(os.path.join(path, n), encoding="utf-8") as f:
                    out[n[:-5]] = json.load(f)
    return out


def indicators(code, i, cal, prices):
    """以 cal[i] 收盤後可得的資料計算:收盤、樞紐價、S1、5 日均線、5 日 ATR。資料不足回傳 None。"""
    row = prices[cal[i]].get(code)
    if not row or len(row) < 5 or row[1] <= 0:
        return None
    o, c, _, h, l = row[:5]
    trs, closes = [], [c]
    for k in range(i, max(0, i - 5), -1):
        r = prices[cal[k]].get(code)
        prev = prices[cal[k - 1]].get(code) if k > 0 else None
        if not r or len(r) < 5:
            continue
        if k != i:
            closes.append(r[1])
        pc = prev[1] if prev else r[0]
        trs.append(max(r[3] - r[4], abs(r[3] - pc), abs(r[4] - pc)))
    p = (h + l + c) / 3
    return {"close": c, "high": h, "low": l, "pivot": p, "s1": 2 * p - h,
            "ma5": sum(closes[:5]) / 5 if len(closes) >= 5 else None,
            "atr": sum(trs) / len(trs) if len(trs) >= 3 else None}


def tick(price):
    """台股升降單位。"""
    for limit, t in ((10, 0.01), (50, 0.05), (100, 0.1), (500, 0.5), (1000, 1)):
        if price < limit:
            return t
    return 5


def round_tick(price, down=True):
    t = tick(price)
    n = round(price / t, 6)   # 先消掉浮點誤差,避免 48.35/0.05 變成 966.9999
    n = math.floor(n) if down else math.ceil(n)
    return round(n * t, 2)


# ---------- 波段:參考進場價 ----------

def _swing_trade(code, i, cal, prices, rule, k):
    """回傳 (是否成交, 報酬) ;資料不足回傳 None。"""
    if i + HOLD >= len(cal):
        return None
    nxt = prices[cal[i + 1]].get(code)
    out = prices[cal[i + HOLD]].get(code)
    if not nxt or len(nxt) < 5 or nxt[0] <= 0 or not out or out[1] <= 0:
        return None
    if price_reset(code, cal, prices, i + 1, i + HOLD):
        return None
    o, low = nxt[0], nxt[4]
    if rule == "gap":
        if (o / k["close"] - 1) * 100 > GAP_SKIP:
            return False, None
        price = o
    else:
        f = ENTRY_RULES[rule]
        limit = f(k) if f else None
        if f and limit is None:
            return None
        if limit is None or o <= limit:
            price = o
        elif low <= limit:
            price = limit
        else:
            return False, None
    return True, (out[1] / price - 1) * 100


def _summ(results):
    """results: [(推薦日, 成交, 報酬, 基準報酬)]"""
    n = len(results)
    filled = [r for r in results if r[1]]
    rets = [r[2] for r in filled]
    base = [r[3] for r in results]
    if not n:
        return {"n": 0}
    return {"n": n, "fill": round(len(filled) / n * 100, 1),
            "avg": round(sum(rets) / len(rets), 2) if rets else None,
            "win": round(sum(1 for x in rets if x > 0) / len(rets) * 100, 1) if rets else None,
            "base": round(sum(base) / n, 2),
            # 每一檔推薦平均貢獻:沒買到算 0,反映「錯過」的代價
            "perPick": round(sum(rets) / n, 2)}


def compare_entries():
    prices = _load_dir(PRICES_DIR)
    cal = sorted(prices)
    pos = {d: i for i, d in enumerate(cal)}
    days = _load_dir(DAYS_DIR)
    rules = list(ENTRY_RULES) + ["gap"]
    rows = {r: [] for r in rules}
    for d, doc in sorted(days.items()):
        if d not in pos:
            continue
        i = pos[d]
        for p in doc["picks"]:
            k = indicators(p["code"], i, cal, prices)
            base = _swing_trade(p["code"], i, cal, prices, "隔天開盤買(基準)", k) if k else None
            if not k or not base or base[1] is None:
                continue
            for r in rules:
                t = _swing_trade(p["code"], i, cal, prices, r, k)
                if t is not None:
                    rows[r].append((d, t[0], t[1], base[1]))
    dates = sorted({x[0] for v in rows.values() for x in v})
    if not dates:
        return {"results": [], "chosen": None}
    mid = dates[len(dates) // 2]
    out = []
    for r in rules:
        allr = rows[r]
        first, second = [x for x in allr if x[0] < mid], [x for x in allr if x[0] >= mid]
        s_all, s1, s2 = _summ(allr), _summ(first), _summ(second)
        name = f"不追高(開盤漲 >{GAP_SKIP:.0f}% 不買)" if r == "gap" else r
        is_base = r == "隔天開盤買(基準)"
        passed = (not is_base and all(s.get("avg") is not None and s["avg"] > s["base"] and s["fill"] >= MIN_FILL * 100
                                      for s in (s1, s2)))
        out.append({"key": r, "name": name, "all": s_all, "first": s1, "second": s2, "passed": passed})
    passing = [x for x in out if x["passed"]]
    chosen = max(passing, key=lambda x: x["all"]["avg"])["key"] if passing else None
    return {"hold": HOLD, "split": mid, "from": dates[0], "to": dates[-1], "results": out, "chosen": chosen}


# ---------- 當沖:停利停損 ----------

def _dt_trade(side, nxt, atr_pct, a, b):
    """隔天開盤進場。回傳扣成本前的報酬 %。a、b 為 None 時收盤出場。"""
    o, c, h, l = nxt[0], nxt[1], nxt[3], nxt[4]
    if a is None:
        r = (c / o - 1) * 100
        return r if side == "long" else -r
    tp, sl = a * atr_pct, b * atr_pct
    if side == "long":
        hit_tp, hit_sl = (h / o - 1) * 100 >= tp, (l / o - 1) * 100 <= -sl
        if hit_sl:
            return -sl        # 同一天兩個都碰到:保守當作先停損
        if hit_tp:
            return tp
        return (c / o - 1) * 100
    hit_tp, hit_sl = (1 - l / o) * 100 >= tp, (h / o - 1) * 100 >= sl
    if hit_sl:
        return -sl
    if hit_tp:
        return tp
    return (1 - c / o) * 100


def compare_daytrade():
    prices = _load_dir(PRICES_DIR)
    cal = sorted(prices)
    pos = {d: i for i, d in enumerate(cal)}
    days = _load_dir(DAYS_DIR)
    combos = [(None, None)] + DT_GRID
    rows = {side: {c: [] for c in combos} for side in ("long", "short")}
    for d, doc in sorted(days.items()):
        if d not in pos or pos[d] + 1 >= len(cal) or not doc.get("dayTrade"):
            continue
        i = pos[d]
        for side in ("long", "short"):
            for p in doc["dayTrade"].get(side, []):
                k = indicators(p["code"], i, cal, prices)
                nxt = prices[cal[i + 1]].get(p["code"])
                if (not k or not k["atr"] or not nxt or len(nxt) < 5 or nxt[0] <= 0
                        or price_reset(p["code"], cal, prices, i + 1, i + 1)):
                    continue
                atr_pct = k["atr"] / k["close"] * 100
                for c in combos:
                    rows[side][c].append((d, _dt_trade(side, nxt, atr_pct, *c) - DT_COST))
    out = {}
    for side in ("long", "short"):
        dates = sorted({x[0] for x in rows[side][(None, None)]})
        if not dates:
            out[side] = {"results": [], "chosen": None}
            continue
        mid = dates[len(dates) // 2]

        def stat(v):
            return {"n": len(v), "avg": round(sum(x[1] for x in v) / len(v), 2) if v else None,
                    "win": round(sum(1 for x in v if x[1] > 0) / len(v) * 100, 1) if v else None}
        res = []
        for c in combos:
            v = rows[side][c]
            s1, s2 = stat([x for x in v if x[0] < mid]), stat([x for x in v if x[0] >= mid])
            res.append({"tp": c[0], "sl": c[1], "all": stat(v), "first": s1, "second": s2})
        base = res[0]
        for r in res:
            # 通過:前後兩半都是正報酬(已扣成本),而且都贏過「開盤進、收盤出」
            r["passed"] = r["tp"] is not None and all(
                r[h]["avg"] is not None and r[h]["avg"] > 0 and r[h]["avg"] > base[h]["avg"] for h in ("first", "second"))
        passing = [r for r in res if r["passed"]]
        best = max(passing, key=lambda r: r["all"]["avg"]) if passing else None
        out[side] = {"split": mid, "from": dates[0], "to": dates[-1], "results": res,
                     "chosen": [best["tp"], best["sl"]] if best else None}
    out["cost"] = DT_COST
    return out


def compute_and_save():
    doc = {"entry": compare_entries(), "dayTrade": compare_daytrade()}
    with open(LEVELS_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return doc


# ---------- 產生當日參考價 ----------

def annotate(doc, chosen):
    """把當日推薦、當沖名單加上參考價(只有通過回測的規則才加)。"""
    prices = _load_dir(PRICES_DIR)
    cal = sorted(d for d in prices if d <= doc["date"])
    if doc["date"] not in cal:
        return
    i = len(cal) - 1
    entry_rule = chosen["entry"]["chosen"]
    for p in doc["picks"]:
        k = indicators(p["code"], i, cal, prices)
        p["entryRef"] = None
        if not k or not entry_rule:
            continue
        if entry_rule == "gap":
            p["entryRef"] = {"rule": "gap", "maxOpen": round_tick(k["close"] * (1 + GAP_SKIP / 100))}
        else:
            f = ENTRY_RULES[entry_rule]
            limit = f(k) if f else None
            if limit:
                p["entryRef"] = {"rule": entry_rule, "limit": round_tick(limit)}
    dt = doc.get("dayTrade") or {}
    for side in ("long", "short"):
        combo = (chosen["dayTrade"].get(side) or {}).get("chosen")
        for p in dt.get(side, []):
            p["levels"] = None
            k = indicators(p["code"], i, cal, prices)
            if not combo or not k or not k["atr"]:
                continue
            a, b = combo
            atr_pct = k["atr"] / k["close"] * 100
            ref = k["close"]   # 以今天收盤估算;實際以明天開盤價為準
            up = side == "long"
            p["levels"] = {
                "entry": ref, "tpPct": round(a * atr_pct, 2), "slPct": round(b * atr_pct, 2),
                "tp": round_tick(ref * (1 + a * atr_pct / 100) if up else ref * (1 - a * atr_pct / 100), down=not up),
                "sl": round_tick(ref * (1 - b * atr_pct / 100) if up else ref * (1 + b * atr_pct / 100), down=up),
            }
