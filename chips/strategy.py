"""通過三段驗證的選股規則:投信買超 + 營收動能(研究細節見 research/RESEARCH.md)。

每天收盤後:
- 股票池:普通股、股價 >= 10 元、20 日均量 > 300 張(上市上櫃合併)
- 投信 10 日累計買超 > 15 張
- 月營收近 3 個月平均創 12 個月新高,且最新月營收年增 > 20%(次月 11 日起才使用)
- 依投信 10 日買超張數排序取前 10 檔
回測依據:隔天開盤買、持有 20 個交易日收盤賣。
"""
from .revenue import Revenue
from .sources import is_common_stock

NAME = "投信買超＋營收動能"
LOOKBACK = 20
MIN_PRICE = 10
MIN_LOTS = 300
TRUST_MIN = 15
YOY_MIN = 20
TOP = 10
HOLD = 20


def picks(d0, days_data, revenue=None):
    """days_data:新到舊、至少 20 個交易日的單日資料(sources.load_day)。回傳名單。"""
    if len(days_data) < LOOKBACK:
        return []
    rev = (revenue or Revenue()).momentum(d0)
    today = days_data[0]
    rows = []
    for code, x in today.items():
        if not is_common_stock(code) or x["close"] < MIN_PRICE:
            continue
        hist = [d.get(code) for d in days_data[:LOOKBACK]]
        if any(h is None for h in hist):
            continue
        vol20 = sum(h["vol"] for h in hist) / LOOKBACK / 1000
        trust10 = sum(h["trust"] for h in hist[:10]) / 1000
        r = rev.get(code)
        if vol20 <= MIN_LOTS or trust10 <= TRUST_MIN or not r or not r["high3"] or r["yoy"] <= YOY_MIN:
            continue
        prev = x["close"] - x["diff"]
        rows.append({
            "code": code, "name": x["name"], "market": x["market"], "close": x["close"],
            "chgPct": round(x["diff"] / prev * 100, 2) if prev else 0.0,
            "trust10": round(trust10), "foreign10": round(sum(h["foreign"] for h in hist[:10]) / 1000),
            "yoy": round(r["yoy"], 1), "vol20": round(vol20),
        })
    rows.sort(key=lambda x: -x["trust10"])
    out = rows[:TOP]
    for i, x in enumerate(out, 1):
        x["rank"] = i
        x["reason"] = (f"投信近 10 日買超 {x['trust10']:,} 張(外資 {x['foreign10']:+,} 張);"
                       f"月營收 3 個月平均創 12 個月新高,最新月年增 {x['yoy']:.1f}%。")
    return out
