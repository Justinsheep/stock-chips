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


# ---------- 觀察名單:好股回檔(5 日,未通過回測,上線追蹤中) ----------
# 研究細節見 research/RESEARCH.md 追加研究三 F2 × E1

PB_NAME = "好股回檔"
PB_HISTORY = 61        # 需要 61 個交易日(60 日均線 + 前一天)
PB_MIN_LOTS = 500      # 20 日均量(張)
PB_RSI = 20
PB_HOLD = 5
PB_GO_LIVE = "2026-10-21"   # 這天(含)以後的名單才算上線後追蹤


def rsi2(closes):
    """2 日 RSI(簡單平均版),closes 舊到新至少 3 筆。"""
    d1, d2 = closes[-1] - closes[-2], closes[-2] - closes[-3]
    up = max(d1, 0) + max(d2, 0)
    down = max(-d1, 0) + max(-d2, 0)
    return 100.0 if down == 0 else 100 - 100 / (1 + up / down)


def pullback_picks(d0, hist, names, revenue=None):
    """hist:舊到新、最後一天為 d0 的價格檔內容({代號: [開, 收, 法人, 高, 低, 張數, 投信張數]})。
    names:{代號: (名稱, 市場)}。資料不足回傳 None。"""
    if len(hist) < PB_HISTORY:
        return None
    hist = hist[-PB_HISTORY:]
    rev = (revenue or Revenue()).momentum(d0)
    rows = []
    for code, today in hist[-1].items():
        if not is_common_stock(code) or code not in names or today[1] < MIN_PRICE:
            continue
        series = [h.get(code) for h in hist]
        if any(s is None or s[1] <= 0 or len(s) < 7 for s in series):
            continue
        closes = [s[1] for s in series]
        vol20 = sum(s[5] for s in series[-20:]) / 20
        trust10 = sum(s[6] for s in series[-10:])
        ma60 = sum(closes[-60:]) / 60
        r = rev.get(code)
        rsi = rsi2(closes)
        if vol20 <= PB_MIN_LOTS or trust10 <= TRUST_MIN or not r or not r["high3"] or r["yoy"] <= YOY_MIN:
            continue
        if closes[-1] <= ma60 or rsi >= PB_RSI:
            continue
        name, market = names[code]
        rows.append({"code": code, "name": name, "market": market, "close": closes[-1],
                     "chgPct": round((closes[-1] / closes[-2] - 1) * 100, 2), "rsi2": round(rsi, 1),
                     "ma60Gap": round((closes[-1] / ma60 - 1) * 100, 1), "trust10": round(trust10),
                     "yoy": round(r["yoy"], 1)})
    rows.sort(key=lambda x: -x["trust10"])
    out = rows[:TOP]
    for i, x in enumerate(out, 1):
        x["rank"] = i
        x["reason"] = (f"投信近 10 日買超 {x['trust10']:,} 張、營收年增 {x['yoy']:.1f}%;股價在 60 日均線上方 {x['ma60Gap']:.1f}%,"
                       f"RSI(2) {x['rsi2']:.0f} 短線超賣。")
    return out
