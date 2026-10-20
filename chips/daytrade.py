"""當沖參考名單:上市、上櫃合併排名,做多、做空各 20 檔。純計算,不連網。

做多「強勢續攻」:今天上漲、三大法人買超
  漲幅 20 + 收盤位置 15 + 法人買超佔量 20 + 量增 15 + 週轉率 20 + 當沖比率 10
做空「隔日沖賣壓」:今天上漲、三大法人沒有買超、可先賣後買
  漲幅 20 + 收盤位置 10 + 法人越少買越高 20 + 量增 20 + 週轉率 20 + 當沖比率 10
做空補足「弱勢續跌」:隔日沖賣壓不足 20 檔時,今天下跌、法人賣超、可先賣後買
  跌幅 20 + 收低 15 + 法人賣超佔量 20 + 量增 15 + 週轉率 20 + 當沖比率 10
各項皆為候選池內的百分位 × 權重。
"""
from .score import MIN_PRICE, TOP_N, pct_rank
from .sources import is_common_stock

MIN_LOTS = 2000   # 當日成交量下限(張)
LONG_W = {"chg": 20, "pos": 15, "inst": 20, "surge": 15, "turnover": 20, "dt": 10}
SHORT_W = {"chg": 20, "pos": 10, "inst": 20, "surge": 20, "turnover": 20, "dt": 10}
FIELDS = {"chg": "chgPct", "pos": "pos", "inst": "instRatio", "surge": "surge", "turnover": "turnover", "dt": "dtRatio"}


def build_pool(days_data, dt_list):
    """days_data:新到舊的單日資料;dt_list:sources.daytrade_list 的結果。"""
    today = days_data[0]
    pool = []
    for code, t in today.items():
        if not is_common_stock(code) or code not in dt_list or t["close"] < MIN_PRICE or not t["shares"]:
            continue
        lots = t["vol"] / 1000
        prev = [d[code]["vol"] / 1000 for d in days_data[1:] if code in d and d[code]["vol"]]
        if lots < MIN_LOTS or not prev:
            continue
        prev_close = t["close"] - t["diff"]
        inst = round(t["inst"] / 1000)
        pool.append({
            "code": code, "name": t["name"], "market": t["market"], "close": t["close"],
            "chgPct": round(t["diff"] / prev_close * 100, 2) if prev_close else 0.0,
            "volume": round(lots), "turnover": round(t["vol"] / t["shares"] * 100, 2),
            "dtRatio": round(dt_list[code]["dtVol"] / t["vol"] * 100, 1),
            "surge": round(lots / (sum(prev) / len(prev)), 2),
            "pos": round((t["close"] - t["low"]) / (t["high"] - t["low"]), 2) if t["high"] > t["low"] else 1.0,
            "instNet": inst, "instRatio": inst / lots,
            "shortable": not dt_list[code]["noShortFirst"],
        })
    return pool


def _score(ranks, weights, flip=()):
    return round(sum(((1 - ranks[k]) if k in flip else ranks[k]) * w for k, w in weights.items()), 1)


def tags(x, side):
    t = []
    if x["thesis"] == "弱勢續跌":
        t.append("弱勢續跌")
    if x["chgPct"] >= 9.5:
        t.append("漲停")
    if x["chgPct"] <= -9.5:
        t.append("跌停")
    if x["chgPct"] >= 5 and x["surge"] >= 2 and x["pos"] >= 0.8 and x["instNet"] <= 0:
        t.append("隔日沖賣壓")
    if x["surge"] >= 2:
        t.append(f"爆量 {x['surge']:.1f} 倍")
    if x["turnover"] >= 10:
        t.append("高週轉")
    if x["dtRatio"] >= 40:
        t.append("當沖熱")
    if side == "long" and x["pos"] >= 0.95:
        t.append("收最高")
    if x["thesis"] == "弱勢續跌" and x["pos"] <= 0.05:
        t.append("收最低")
    if side == "long" and x["instNet"] > 0:
        t.append("法人買超")
    if side == "short" and x["instNet"] < 0:
        t.append("法人賣超")
    return t


def reason(x):
    return (f"漲跌 {x['chgPct']:+.2f}%,收盤位於當日區間 {x['pos'] * 100:.0f}%;"
            f"成交量為前 4 日均量的 {x['surge']:.1f} 倍,週轉率 {x['turnover']:.2f}%,當沖比率 {x['dtRatio']:.1f}%;"
            f"三大法人{'買超' if x['instNet'] >= 0 else '賣超'} {abs(x['instNet']):,} 張。")


def candidates(days_data, dt_list, n=TOP_N):
    pool = build_pool(days_data, dt_list)
    if not pool:
        return {"long": [], "short": [], "universe": 0}
    ranks = {k: pct_rank([x[f] for x in pool]) for k, f in FIELDS.items()}
    for i, x in enumerate(pool):
        r = {k: v[i] for k, v in ranks.items()}
        x["longScore"] = _score(r, LONG_W)
        x["shortScore"] = _score(r, SHORT_W, flip=("inst",))
        x["weakScore"] = _score(r, LONG_W, flip=("chg", "pos", "inst"))

    longs = sorted((x for x in pool if x["chgPct"] > 0 and x["instNet"] > 0), key=lambda x: -x["longScore"])[:n]
    picks = {"long": [(x, x["longScore"], "強勢續攻") for x in longs]}
    shorts = sorted((x for x in pool if x["chgPct"] > 0 and x["instNet"] <= 0 and x["shortable"]),
                    key=lambda x: -x["shortScore"])[:n]
    short_list = [(x, x["shortScore"], "隔日沖賣壓") for x in shorts]
    if len(short_list) < n:
        weak = sorted((x for x in pool if x["chgPct"] < 0 and x["instNet"] < 0 and x["shortable"]),
                      key=lambda x: -x["weakScore"])[:n - len(short_list)]
        short_list += [(x, x["weakScore"], "弱勢續跌") for x in weak]
    picks["short"] = short_list

    keep = ("code", "name", "market", "close", "chgPct", "volume", "turnover", "dtRatio", "surge", "pos", "instNet")
    out = {"universe": len(pool)}
    for side, lst in picks.items():
        out[side] = []
        for i, (x, s, thesis) in enumerate(lst, 1):
            row = {k: x[k] for k in keep}
            row.update(rank=i, score=s, thesis=thesis)
            row["tags"] = tags(row, side)
            row["reason"] = reason(row)
            out[side].append(row)
    return out
