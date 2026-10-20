"""單日流程:抓資料 → 計分 → 產生當日結果與價格檔。"""
import datetime as dt
import json
import os

from . import daytrade, score, sources

DAYS_DIR = os.path.join(sources.DATA, "days")
PRICES_DIR = os.path.join(sources.DATA, "prices")


def _write_json(path, obj, compact=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1)


def save_prices(d, day_data):
    """績效與出場訊號用:{代號: [開盤, 收盤, 三大法人買賣超張數]}。"""
    _write_json(os.path.join(PRICES_DIR, f"{d:%Y-%m-%d}.json"),
                {c: [v["open"], v["close"], round(v["inst"] / 1000)] for c, v in day_data.items()}, compact=True)


def pick_weeks(all_weeks, d0, strict):
    """選本週與上週的集保週別。strict=True(回測)時不使用與交易日同一天的週資料,
    因為集保當天收盤後才公布,當晚 22:00 不一定拿得到。"""
    target = f"{d0:%Y%m%d}"
    usable = [w for w in all_weeks if (w < target if strict else w <= target)]
    if not usable:
        return None, None
    cur = usable[-1]
    prev = usable[-2] if len(usable) >= 2 else None
    return cur, prev


def compute_day(d0, days, holders, strict_weeks=False):
    """days:新到舊的交易日(days[0] == d0)。回傳當日結果 dict。"""
    days_data = []
    for d in days:
        data = sources.load_day(d)
        if data is None:
            raise RuntimeError(f"{d} 沒有盤後資料")
        days_data.append(data)
        save_prices(d, data)
    margin_chg, margin_missing = sources.margins(d0)
    idx = sources.indices(d0)
    week, prev_week = pick_weeks(holders.all_weeks(), d0, strict_weeks)

    def big_lookup(code):
        cur = holders.get(code, week) if week else None
        prev = holders.get(code, prev_week) if prev_week else None
        chg = round(cur - prev, 2) if cur is not None and prev is not None else None
        return cur, chg

    rows = score.build_rows(days_data)
    picks, universe, weak = [], {}, {}
    for mk in score.MARKETS:
        grp = [x for x in rows if x["market"] == mk]
        universe[mk] = len(grp)
        weak[mk] = score.weak_signals(grp, idx.get(mk), days_data[0], mk)
        picks += score.score_market(grp, margin_chg, mk in margin_missing, big_lookup)

    for x in picks:
        x.pop("instHist", None)
    empty_dt = {"long": [], "short": [], "universe": 0}
    try:   # 當沖名單出錯不影響主推薦
        dt_list, dt_missing = sources.daytrade_list(d0)
        # 上市櫃合併排名,任一市場還沒公布就整份先不排,等隔天早上重跑
        day_trade = dict(empty_dt, pending=sorted(dt_missing)) if dt_missing else daytrade.candidates(days_data, dt_list)
    except Exception as e:
        print("當沖名單計算失敗:", repr(e))
        day_trade = dict(empty_dt, error=str(e))
    fmt = lambda w: f"{w[:4]}-{w[4:6]}-{w[6:]}" if w else None
    return {
        "date": f"{d0:%Y-%m-%d}",
        "generatedAt": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
        "tradingDays": [f"{d:%Y-%m-%d}" for d in days],
        "tdccWeek": fmt(week), "tdccPrevWeek": fmt(prev_week),
        "marginPending": sorted(margin_missing),
        "universe": universe,
        "indices": idx,
        "weak": weak,
        "weights": score.WEIGHTS,
        "filters": {"minAvgLots": score.MIN_AVG_LOTS, "minPrice": score.MIN_PRICE, "lookback": score.LOOKBACK},
        "picks": picks,
        "dayTrade": day_trade,
    }


def save_day(doc):
    _write_json(os.path.join(DAYS_DIR, f"{doc['date']}.json"), doc)
