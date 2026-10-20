"""籌碼計分、標籤與大盤偏弱判斷。純計算,不連網(大戶資料由呼叫端傳入的函式提供)。"""
from .sources import is_common_stock

LOOKBACK = 5            # 法人累計、均量、連買看的交易日數
MIN_AVG_LOTS = 1000     # 5 日均量下限(張)
MIN_PRICE = 10          # 股價下限
TOP_N = 20              # 每個市場推薦檔數
CANDIDATES = 50         # 每個市場進入大戶計分的候選數
MARKETS = ("上市", "上櫃")
WEIGHTS = {"inst1": 25, "inst5": 25, "streak": 10, "margin": 15, "big": 25}

# 大盤偏弱:三項中符合 WEAK_MIN_SIGNALS 項以上
WEAK_INDEX_DROP = -1.0  # 指數跌幅(%)
WEAK_BUY_RATIO = 0.40   # 候選池中法人買超家數佔比
WEAK_MIN_SIGNALS = 2


def pct_rank(values):
    """每個值在清單中的百分位(0~1);同值取平均名次。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    denom = max(1, len(values) - 1)
    pos = 0
    while pos < len(order):
        end = pos
        while end + 1 < len(order) and values[order[end + 1]] == values[order[pos]]:
            end += 1
        for k in range(pos, end + 1):
            ranks[order[k]] = (pos + end) / 2 / denom
        pos = end + 1
    return ranks


def streak(series):
    """新到舊的序列,從最新一天起連續 > 0 的天數。"""
    n = 0
    for v in series:
        if v <= 0:
            break
        n += 1
    return n


def big_score(chg):
    """千張大戶週增減(百分點)→ 0~1:+1 以上滿分,−1 以下 0 分。"""
    if chg is None:
        chg = 0.0
    return max(0.0, min(1.0, (chg + 1) / 2))


def build_rows(days_data):
    """days_data:新到舊的單日資料(sources.load_day 的結果)。回傳符合流動性條件的股票列。"""
    today = days_data[0]
    rows = []
    for code, t in today.items():
        if not is_common_stock(code) or t["close"] <= 0:
            continue   # 排除 ETF 基準(0050 / 006201)與無收盤價
        hist = [d.get(code) for d in days_data]
        vols = [h["vol"] / 1000 for h in hist if h]
        avg_vol = sum(vols) / len(vols)
        if avg_vol < MIN_AVG_LOTS or t["close"] < MIN_PRICE:
            continue
        inst_hist = [round(h["inst"] / 1000) if h else 0 for h in hist]
        prev = t["close"] - t["diff"]
        rows.append({
            "code": code, "name": t["name"], "market": t["market"], "close": t["close"],
            "chgPct": round(t["diff"] / prev * 100, 2) if prev else 0.0,
            "volume": round(t["vol"] / 1000), "avgVol": round(avg_vol),
            "instNet": round(t["inst"] / 1000), "foreignNet": round(t["foreign"] / 1000),
            "trustNet": round(t["trust"] / 1000), "dealerNet": round(t["dealer"] / 1000),
            "instHist": inst_hist, "inst5d": sum(inst_hist),
            "foreignStreak": streak([h["foreign"] if h else 0 for h in hist]),
            "trustStreak": streak([h["trust"] if h else 0 for h in hist]),
        })
    return rows


def score_market(rows, margin_chg, margin_missing, big_lookup, lookback=LOOKBACK):
    """同一市場的股票列 → 前 TOP_N 名(已含分數、標籤、說明)。

    margin_chg: {代號: 融資增減張數};margin_missing: 該市場融資是否尚未公布
    big_lookup(code) -> (本週千張大戶%, 週增減百分點) ;任一可為 None
    """
    if not rows:
        return []
    w = dict(WEIGHTS)
    if margin_missing:   # 融資未公布:不計分,其餘等比例放大回 100
        scale = 100 / (100 - w["margin"])
        w = {k: 0 if k == "margin" else v * scale for k, v in w.items()}
    for x in rows:
        x["marginChg"] = None if margin_missing else round(margin_chg.get(x["code"], 0))
    r1 = pct_rank([x["instNet"] / x["avgVol"] for x in rows])
    r5 = pct_rank([x["inst5d"] / (x["avgVol"] * lookback) for x in rows])
    rs = pct_rank([x["foreignStreak"] + x["trustStreak"] * 1.5 for x in rows])
    rm = pct_rank([-(x["marginChg"] or 0) / x["avgVol"] for x in rows])
    for x, a, b, c, e in zip(rows, r1, r5, rs, rm):
        x["parts"] = {"inst1": round(a * w["inst1"], 1), "inst5": round(b * w["inst5"], 1),
                      "streak": round(c * w["streak"], 1), "margin": round(e * w["margin"], 1), "big": 0.0}
    cands = sorted((x for x in rows if x["instNet"] > 0), key=lambda x: -sum(x["parts"].values()))[:CANDIDATES]
    for x in cands:
        x["bigPct"], x["bigChg"] = big_lookup(x["code"])
        x["parts"]["big"] = round(big_score(x["bigChg"]) * w["big"], 1)
        x["score"] = round(sum(x["parts"].values()), 1)
    picks = sorted(cands, key=lambda x: (-x["score"], x["code"]))[:TOP_N]
    for i, x in enumerate(picks, 1):
        x["rank"] = i
        x["tags"] = tags(x)
        x["reason"] = reason(x)
    return picks


def tags(x):
    t = []
    if x["trustStreak"] >= 3:
        t.append(f"投信連買{x['trustStreak']}日")
    if x["foreignStreak"] >= 3:
        t.append(f"外資連買{x['foreignStreak']}日")
    if x.get("bigChg") is not None and x["bigChg"] >= 0.5:
        t.append("大戶增持")
    if x["marginChg"] is not None and -x["marginChg"] >= x["avgVol"] * 0.05:
        t.append("融資大減")
    if x["inst5d"] > x["avgVol"]:
        t.append("5日買超>均量")
    return t


def reason(x):
    s = [f"三大法人買超 {x['instNet']:,} 張(外資 {x['foreignNet']:+,}、投信 {x['trustNet']:+,})"]
    if x["foreignStreak"] >= 2:
        s.append(f"外資連買 {x['foreignStreak']} 日")
    if x["trustStreak"] >= 2:
        s.append(f"投信連買 {x['trustStreak']} 日")
    s.append(f"近 5 日法人累計 {x['inst5d']:+,} 張")
    if x.get("bigPct") is not None:
        if x.get("bigChg") is not None:
            word = "增加" if x["bigChg"] >= 0 else "減少"
            s.append(f"千張大戶持股 {x['bigPct']:.2f}%,較前一週{word} {abs(x['bigChg']):.2f} 個百分點")
        else:
            s.append(f"千張大戶持股 {x['bigPct']:.2f}%")
    if x["marginChg"] is not None:
        s.append(f"融資{'增加' if x['marginChg'] > 0 else '減少'} {abs(x['marginChg']):,} 張")
    return ";".join(s) + "。"


def weak_signals(rows, index_info, day_data, market):
    """大盤偏弱判斷。rows:該市場候選池;day_data:當日全部資料(算外資+投信金額)。"""
    fi_amount = sum((v["foreign"] + v["trust"]) * v["close"] for code, v in day_data.items()
                    if v["market"] == market and is_common_stock(code))
    buy_ratio = sum(1 for x in rows if x["instNet"] > 0) / len(rows) if rows else 0.0
    chg = index_info.get("chgPct") if index_info else None
    signals = {
        "indexDrop": chg is not None and chg <= WEAK_INDEX_DROP,
        "fiSell": fi_amount < 0,
        "fewBuyers": buy_ratio < WEAK_BUY_RATIO,
    }
    return {
        "weak": sum(signals.values()) >= WEAK_MIN_SIGNALS,
        "signals": signals,
        "indexChgPct": chg,
        "fiAmount": round(fi_amount / 1e8, 1),   # 億元
        "buyRatio": round(buy_ratio, 3),
    }
