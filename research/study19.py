"""研究十九:0050 與 009816 的進出場時機(登記見 RESEARCH.md)。

收盤判斷、隔天開盤進出;還原分割、加回配息;進出扣手續費 0.1425%、賣出另扣證交稅 0.1%。
用法:python -m research.study19
"""
import datetime as dt
import json
import math
import os
import re

from chips import sources
from . import dividends as DV

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "study19.json")
FEE, TAX = 0.001425, 0.001
RULES = {"E1 收盤>60日均線": ("ma", 60), "E2 收盤>120日均線": ("ma", 120), "E3 收盤>200日均線": ("ma", 200),
         "E4 20日均線>60日均線": ("cross", 20, 60)}
SEGS = [("2013-07-01", "2017-12-31"), ("2018-01-01", "2022-06-30"), ("2022-07-01", "2026-12-31")]


def series(code, start="20120601", end="20261231"):
    """[(日期, 開盤, 收盤, 當天除息金額)],價格已還原分割(以最新股數為準)。"""
    dates = sorted(m.group(1) for n in os.listdir(sources.CACHE)
                   if (m := re.fullmatch(r"twse_mi_(\d{8})\.json", n)) and start <= m.group(1) <= end)
    div = DV.load(2012, 2026).get(code, {})
    raw = []
    for s in dates:
        d = dt.datetime.strptime(s, "%Y%m%d").date()
        x = (sources.twse_price(d) or {}).get(code)
        if x and x["open"] > 0 and x["close"] > 0:
            raw.append([d, x["open"], x["close"], div.get(d, 0.0)])
    cum, out = 1.0, [None] * len(raw)
    for k in range(len(raw) - 1, -1, -1):   # 由後往前還原分割:跨過跳空 > 11% 的日子,之前的價格乘上比例
        d, o, c, dv = raw[k]
        out[k] = [d, o * cum, c * cum, dv * cum]
        if k and abs(o / raw[k - 1][2] - 1) > 0.11 and dv == 0:
            cum *= o / raw[k - 1][2]
    return out


def signal(closes, t, rule):
    if rule[0] == "ma":
        w = rule[1]
        return None if t + 1 < w else closes[t] > sum(closes[t - w + 1:t + 1]) / w
    a, b = rule[1], rule[2]
    return None if t + 1 < b else sum(closes[t - a + 1:t + 1]) / a > sum(closes[t - b + 1:t + 1]) / b


def backtest(px, rule, start):
    """回傳每日報酬列表 [(日期, 報酬)] 與進出次數;rule=None 表示一直持有。"""
    closes = [p[2] for p in px]
    out, pos, trades = [], 0, 0
    for t in range(1, len(px)):
        d, o, c, dv = px[t]
        if str(d) < start:
            continue
        want = 1 if rule is None else (1 if signal(closes, t - 1, rule) else 0)
        r_night = (o + dv) / closes[t - 1] - 1 if pos else 0.0
        cost = 0.0
        if want != pos:
            trades += 1
            cost = FEE if want else FEE + TAX
        r_day = c / o - 1 if want else 0.0
        out.append((str(d), (1 + r_night) * (1 - cost) * (1 + r_day) - 1))
        pos = want
    return out, trades


def stats(rets):
    if len(rets) < 20:
        return None
    xs = [r for _, r in rets]
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in xs:
        eq *= 1 + r
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
    years = len(xs) / 245
    return {"from": rets[0][0], "to": rets[-1][0], "total": round((eq - 1) * 100, 1),
            "annual": round((eq ** (1 / years) - 1) * 100, 1), "mdd": round(mdd * 100, 1),
            "sharpe": round(m / sd * math.sqrt(245), 3) if sd else None}


def run():
    res = {}
    for code, start in (("0050", "2013-07-01"), ("009816", "2026-02-04")):
        px = series(code)
        out = {}
        for name, rule in [("一直持有", None)] + list(RULES.items()):
            rets, trades = backtest(px, rule, start)
            info = {"all": stats(rets), "trades": trades}
            if code == "0050":
                info["seg"] = {f"{a}~{b}": stats([x for x in rets if a <= x[0] <= b]) for a, b in SEGS}
            out[name] = info
        if code == "0050":
            hold = out["一直持有"]
            for name in RULES:
                v = out[name]
                v["pass"] = bool(all(v["seg"][k] and hold["seg"][k] and v["seg"][k]["sharpe"] > hold["seg"][k]["sharpe"] for k in v["seg"])
                                 and v["all"]["mdd"] - hold["all"]["mdd"] >= 10)
        else:
            rets, _ = backtest(series("0050"), None, start)
            out["同期 0050 一直持有"] = {"all": stats(rets)}
        res[code] = out
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return res


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=1))
