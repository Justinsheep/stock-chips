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


# ---------- 隔日沖觀察名單:外資大買收高(盤後才知道,隔天開盤買) ----------
# 研究細節見 research/RESEARCH.md 研究六 G7 與研究十一

FO_HISTORY = 21          # 今天 + 前 20 個交易日
FO_MIN_LOTS = 1000
FO_GO_LIVE = "2026-10-22"


def foreign_overnight(days_data):
    """days_data:新到舊的單日資料(sources.load_day),至少 21 天。今天外資買超 ≥ 當日量 10%、漲 ≥ 3%、收在高點附近。"""
    if len(days_data) < FO_HISTORY:
        return None
    today, prev = days_data[0], days_data[1]
    rows = []
    for code, x in today.items():
        p = prev.get(code)
        if not is_common_stock(code) or not p or x["close"] < MIN_PRICE or p["close"] <= 0 or x["vol"] <= 0:
            continue
        hist = [d.get(code) for d in days_data[1:FO_HISTORY]]
        if any(h is None for h in hist):
            continue
        vol20 = sum(h["vol"] for h in hist) / 20 / 1000
        chg = (x["close"] / p["close"] - 1) * 100
        if vol20 <= FO_MIN_LOTS or chg < 3 or x["close"] < 0.98 * x["high"] or x["foreign"] < 0.1 * x["vol"]:
            continue
        rows.append({"code": code, "name": x["name"], "market": x["market"], "close": x["close"], "chgPct": round(chg, 2),
                     "foreignLots": round(x["foreign"] / 1000), "foreignPct": round(x["foreign"] / x["vol"] * 100, 1),
                     "surge": round(x["vol"] / 1000 / vol20, 2)})
    rows.sort(key=lambda r: -r["surge"])
    out = rows[:TOP]
    for i, r in enumerate(out, 1):
        r["rank"] = i
    return out


# ---------- 候選名單:研究十二的第 1、3 名(有潛力、未通過校正) ----------
# 研究細節見 research/RESEARCH.md 研究十二;條件與 research/grid.py 相同

ALT_HISTORY = 121
ALT_LISTS = {
    "alt1": "外資買超＋營收動能＋60日上漲",
    "alt3": "單月營收新高＋均線多頭",
}
ALT_GO_LIVE = "2026-10-22"
TR_GO_LIVE = "2026-10-20"   # 今日名單(投信＋營收)上線日,之前的是回補


def alt_picks(d0, hist, names, revenue=None):
    """hist:舊到新的價格檔內容(最後一天為 d0),至少 121 天。回傳 {"alt1": [...], "alt3": [...]};資料不足回傳 None。"""
    from .revenue import features as rev_features
    if len(hist) < ALT_HISTORY:
        return None
    hist = hist[-ALT_HISTORY:]
    rev = rev_features(revenue or Revenue(), d0)
    rows = {"alt1": [], "alt3": []}
    for code, today in hist[-1].items():
        if not is_common_stock(code) or code not in names or today[1] < MIN_PRICE:
            continue
        s = [h.get(code) for h in hist]
        if any(x is None or x[1] <= 0 or len(x) < 8 for x in s):
            continue
        closes = [x[1] for x in s]
        v20 = sum(x[5] for x in s[-20:]) / 20
        if v20 <= 300:
            continue
        t10, f10 = sum(x[6] for x in s[-10:]), sum(x[7] for x in s[-10:])
        ma = lambda n: sum(closes[-n:]) / n
        ret60 = closes[-1] / closes[-61] - 1
        r = rev.get(code)
        momentum = bool(r and r["high3"] and r["yoy"] > 20)
        name, market = names[code]
        base = {"code": code, "name": name, "market": market, "close": closes[-1],
                "chgPct": round((closes[-1] / closes[-2] - 1) * 100, 2), "trust10": t10, "foreign10": f10,
                "yoy": round(r["yoy"], 1) if r else None, "ret60": round(ret60 * 100, 1)}
        if f10 > 0 and momentum and ret60 > 0:
            rows["alt1"].append(base)
        if r and r["high1"] and ma(5) > ma(20) > ma(60):
            rows["alt3"].append(dict(base))
    out = {}
    for k, v in rows.items():
        v.sort(key=lambda x: -x["trust10"])
        out[k] = v[:TOP]
        for i, x in enumerate(out[k], 1):
            x["rank"] = i
    return out
