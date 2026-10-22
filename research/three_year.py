"""追加研究五:三年資料重找主規則(五 A)與隔日沖規則(五 B)。登記內容見 RESEARCH.md。

用法:python -m research.three_year
輸出:research/three_year.json 與終端機摘要
"""
import datetime as dt
import json
import os
import re

from chips import sources
from chips.revenue import Revenue

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "three_year.json")
START, END = "20230406", "20261020"
WARMUP = 60
COST = 0.585
SPLITS = (0.6, 0.8)
BENCH = "0050"
O, H, L, C, V, F, T, I = range(8)   # 精簡資料欄位:開 高 低 收 張數 外資張 投信張 法人張


def load():
    dates = sorted(m.group(1) for n in os.listdir(sources.CACHE)
                   if (m := re.fullmatch(r"twse_t86_(\d{8})\.json", n)) and START <= m.group(1) <= END)
    days, panel = [], []
    for s in dates:
        d = dt.datetime.strptime(s, "%Y%m%d").date()
        data = sources.load_day(d)
        if not data:
            continue
        days.append(d)
        panel.append({c: (x["open"], x["high"], x["low"], x["close"], x["vol"] / 1000, x["foreign"] / 1000,
                          x["trust"] / 1000, x["inst"] / 1000)
                      for c, x in data.items() if (sources.is_common_stock(c) or c == BENCH) and x["close"] > 0})
    return days, panel


def jump(panel, code, a, b):
    """a..b 之間有沒有超過漲跌停的跳空(減資、分割等重新定價)。"""
    p = None
    for k in range(max(1, a) - 1, -1, -1):   # 停牌時前一天可能沒資料,往前找最近一筆
        if (p := panel[k].get(code)):
            break
    for k in range(max(1, a), b + 1):
        c = panel[k].get(code)
        if p and c and c[O] > 0 and abs(c[O] / p[C] - 1) > 0.11:
            return True
        p = c or p
    return False


def adjusted_closes(panel, code):
    """還原分割後的收盤價序列(只處理重新定價跳空),供 0050 均線使用。"""
    out, factor = [None] * len(panel), 1.0
    for k in range(len(panel) - 1, -1, -1):
        x = panel[k].get(code)
        if x:
            out[k] = x[C] * factor
            p = next((q for j in range(k - 1, -1, -1) if (q := panel[j].get(code))), None)
            if p and x[O] > 0 and abs(x[O] / p[C] - 1) > 0.11:
                factor *= x[O] / p[C]
    return out


def hold(panel, code, t, h):
    """t 收盤選股、t+1 開盤買、t+h 收盤賣(未扣成本,%)。"""
    if t + h >= len(panel) or jump(panel, code, t + 1, t + h):
        return None
    e, x = panel[t + 1].get(code), panel[t + h].get(code)
    if not e or not x or e[O] <= 0:
        return None
    return (x[C] / e[O] - 1) * 100


def seg_split(rows):
    n = len(rows)
    c1, c2 = int(n * SPLITS[0]), int(n * SPLITS[1])
    return lambda i: "train" if i < c1 else "valid" if i < c2 else "test", (c1, c2)


# ---------- 五 A:主規則 ----------

def main_rules(days, panel):
    rev, rc = Revenue(), {}
    ma_src = adjusted_closes(panel, BENCH)
    rows = []
    for t in range(WARMUP, len(days) - 20):
        key = days[t].strftime("%Y%m") + ("b" if days[t].day > 10 else "a")
        if key not in rc:
            rc[key] = rev.momentum(days[t])
        r = rc[key]
        pool = []
        for code, x in panel[t].items():
            if code == BENCH or x[C] < 10 or code not in r:
                continue
            hist = [panel[k].get(code) for k in range(t - 19, t + 1)]
            if any(h is None for h in hist):
                continue
            vol20 = sum(h[V] for h in hist) / 20
            trust10 = sum(h[T] for h in hist[-10:])
            m = r[code]
            if vol20 > 300 and trust10 > 15 and m["high3"] and m["yoy"] > 20:
                pool.append((code, vol20, trust10))
        top = lambda items, key: [c for c, *_ in sorted(items, key=key, reverse=True)[:10]]
        r2 = top(pool, lambda x: x[2])
        big = top([p for p in pool if p[1] > 1000], lambda x: x[2])
        intensity = top(pool, lambda x: x[2] / x[1])
        ma60 = [v for v in ma_src[t - 59:t + 1] if v]
        bull = len(ma60) == 60 and ma_src[t] >= sum(ma60) / 60
        rows.append((t, bull, {"M0": r2, "M3": big, "M4": intensity}))
    seg_of, _ = seg_split(rows)
    acc = {}
    for i, (t, bull, picks) in enumerate(rows):
        b = hold(panel, BENCH, t, 20)
        if b is None:
            continue
        rets = {}
        for k, codes in picks.items():
            v = [x for c in codes if (x := hold(panel, c, t, 20)) is not None]
            rets[k] = sum(v) / len(v) - COST if v else 0.0
        variants = {
            "M0 R2 原版": rets["M0"],
            "M1 R2＋大盤弱時空手": rets["M0"] if bull else 0.0,
            "M2 R2＋大盤弱時買 0050": rets["M0"] if bull else b - COST,
            "M3 R2 大型股(均量>1000張)": rets["M3"],
            "M4 R2 依買超力道排序": rets["M4"],
            "M5 M2＋M3": rets["M3"] if bull else b - COST,
        }
        for k, ret in variants.items():
            acc.setdefault(k, {}).setdefault(seg_of(i), []).append((ret, ret - b, bull))
    out = {}
    for k, segs in acc.items():
        out[k] = {s: {"ret": round(sum(x[0] for x in v) / len(v), 2), "excess": round(sum(x[1] for x in v) / len(v), 2),
                      "beat": round(sum(1 for x in v if x[1] > 0) / len(v) * 100, 1),
                      "bullDays": round(sum(1 for x in v if x[2]) / len(v) * 100, 1)} for s, v in segs.items()}
    s1 = [k for k, v in out.items() if v["train"]["excess"] > 0]
    s2 = [k for k in s1 if out[k]["valid"]["excess"] > 0]
    chosen = max(s2, key=lambda k: out[k]["train"]["excess"]) if s2 else None
    return {"results": out, "stage1": s1, "stage2": s2, "chosen": chosen,
            "passed": bool(chosen and out[chosen]["test"]["excess"] > 0),
            "segments": segment_dates(days, rows)}


def segment_dates(days, rows):
    _, (c1, c2) = seg_split(rows)
    return {"train": [str(days[rows[0][0]]), str(days[rows[c1 - 1][0]])],
            "valid": [str(days[rows[c1][0]]), str(days[rows[c2 - 1][0]])],
            "test": [str(days[rows[c2][0]]), str(days[rows[-1][0]])]}


# ---------- 五 B:隔日沖 ----------

def next_day(days, panel):
    rows = []
    for t in range(WARMUP, len(days) - 2):
        strong, limit = [], []
        prev = panel[t - 1]
        for code, x in panel[t].items():
            p = prev.get(code)
            if code == BENCH or not p or x[C] < 10 or p[C] <= 0:
                continue
            hist = [panel[k].get(code) for k in range(t - 20, t)]
            if any(h is None for h in hist):
                continue
            vol20 = sum(h[V] for h in hist) / 20
            if vol20 <= 1000:
                continue
            chg = (x[C] / p[C] - 1) * 100
            surge = x[V] / vol20
            trust10 = sum(panel[k][code][T] for k in range(t - 9, t + 1) if code in panel[k])
            if 5 <= chg < 9.5 and x[C] >= 0.98 * x[H] and surge >= 2:
                strong.append((code, surge, x[I], trust10))
            elif chg >= 9.5 and x[C] >= x[H]:
                limit.append((code, surge, x[I], trust10))
        top = lambda items: [c for c, *_ in sorted(items, key=lambda z: -z[1])[:10]]
        rows.append((t, {"N1": top(strong), "N2": top([s for s in strong if s[2] > 0]),
                         "N3": top([s for s in strong if s[3] > 0]), "LIMIT": top(limit)}))
    seg_of, _ = seg_split(rows)

    def ret(code, t, kind):
        a, b = panel[t].get(code), panel[t + 1].get(code)
        if kind == "close_open":
            if not a or not b or b[O] <= 0 or jump(panel, code, t + 1, t + 1):
                return None
            return (b[O] / a[C] - 1) * 100
        if kind == "close_close":
            if not a or not b or jump(panel, code, t + 1, t + 1):
                return None
            return (b[C] / a[C] - 1) * 100
        c = panel[t + 2].get(code)   # open_open:T+1 開盤買、T+2 開盤賣
        if not b or not c or b[O] <= 0 or c[O] <= 0 or jump(panel, code, t + 2, t + 2):
            return None
        return (c[O] / b[O] - 1) * 100

    plan = {"N1 強勢收高:收盤買→隔天開盤賣": ("N1", "close_open"), "N2 ＋法人買超:收盤買→隔天開盤賣": ("N2", "close_open"),
            "N3 ＋投信買超:收盤買→隔天開盤賣": ("N3", "close_open"), "N4 強勢收高:收盤買→隔天收盤賣": ("N1", "close_close"),
            "N5 ＋法人買超:收盤買→隔天收盤賣": ("N2", "close_close"), "P1 提前一天選:隔天開盤買→後天開盤賣": ("N1", "open_open"),
            "P2 ＋法人買超,提前一天選:隔天開盤買→後天開盤賣": ("N2", "open_open"),
            "(參考)漲停收盤買→隔天開盤賣,常買不到": ("LIMIT", "close_open")}
    out = {}
    for name, (grp, kind) in plan.items():
        acc = {"train": [], "valid": [], "test": []}
        bench = {"train": [], "valid": [], "test": []}
        for i, (t, picks) in enumerate(rows):
            v = [x for c in picks[grp] if (x := ret(c, t, kind)) is not None]
            acc[seg_of(i)].extend(x - COST for x in v)
            br = ret(BENCH, t, kind)
            if br is not None:
                bench[seg_of(i)].append(br)
        out[name] = {s: {"trades": len(v), "ret": round(sum(v) / len(v), 2) if v else None,
                         "win": round(sum(1 for x in v if x > 0) / len(v) * 100, 1) if v else None,
                         "gross": round(sum(v) / len(v) + COST, 2) if v else None,
                         "bench0050": round(sum(bench[s]) / len(bench[s]), 3) if bench[s] else None}
                     for s, v in acc.items()}
    cands = [k for k in out if not k.startswith("(參考)")]
    s1 = [k for k in cands if (out[k]["train"]["ret"] or -1) > 0]
    s2 = [k for k in s1 if (out[k]["valid"]["ret"] or -1) > 0]
    chosen = max(s2, key=lambda k: out[k]["train"]["ret"]) if s2 else None
    return {"results": out, "stage1": s1, "stage2": s2, "chosen": chosen,
            "passed": bool(chosen and (out[chosen]["test"]["ret"] or -1) > 0),
            "segments": segment_dates(days, rows)}


if __name__ == "__main__":
    days, panel = load()
    print(f"交易日 {len(days)} 天:{days[0]} ~ {days[-1]}")
    a = main_rules(days, panel)
    print("\n== 五 A 主規則(20 日,扣成本,超額比 0050)==", a["segments"])
    for k, v in a["results"].items():
        print(f"  {k:<22} " + " | ".join(f"{s} 報酬 {v[s]['ret']:+.2f}% 超額 {v[s]['excess']:+.2f}% 贏 {v[s]['beat']}%"
                                         for s in ("train", "valid", "test")))
    print("  訓練通過", a["stage1"], "驗證通過", a["stage2"], "採用", a["chosen"], "最終測試", a["passed"])
    b = next_day(days, panel)
    print("\n== 五 B 隔日沖(每筆扣成本 0.585%)==", b["segments"])
    for k, v in b["results"].items():
        print(f"  {k}\n     " + " | ".join(f"{s} {v[s]['trades']}筆 淨 {v[s]['ret']}% (未扣 {v[s]['gross']}%) 勝率 {v[s]['win']}% 0050 {v[s]['bench0050']}%"
                                           for s in ("train", "valid", "test")))
    print("  訓練通過", b["stage1"], "驗證通過", b["stage2"], "採用", b["chosen"], "最終測試", b["passed"])
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"main": a, "nextDay": b}, fh, ensure_ascii=False, indent=1)
