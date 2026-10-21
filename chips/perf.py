"""績效追蹤:推薦日的下一個交易日開盤進場,持有 1 / 5 / 20 個交易日後以收盤價計算報酬。

基準:同算法的 0050(上市)、006201(上櫃)。全部只讀 data/ 下的檔案,不連網。
"""
import datetime as dt
import json
import os

from . import exits
from .daily import DAYS_DIR, PRICES_DIR, _write_json
from .sources import BENCHMARKS, DATA

HORIZONS = (1, 5, 20)
PB_COST = 0.585   # 觀察名單的來回成本 %(手續費不打折 + 證交稅)
PERF_PATH = os.path.join(DATA, "perf.json")


def _load_dir(path):
    out = {}
    if os.path.isdir(path):
        for n in sorted(os.listdir(path)):
            if n.endswith(".json"):
                with open(os.path.join(path, n), encoding="utf-8") as f:
                    out[n[:-5]] = json.load(f)
    return out


def trade_return(prices, cal, i, code, n):
    """cal[i] 為推薦日;cal[i+1] 開盤進場,持有到 cal[i+n] 收盤。資料不足回傳 None。"""
    if i + n >= len(cal):
        return None
    entry = prices[cal[i + 1]].get(code)
    exit_ = prices[cal[i + n]].get(code)
    if not entry or not exit_ or entry[0] <= 0 or exit_[1] <= 0:
        return None
    if exits.price_reset(code, cal, prices, i + 1, i + n):
        return None
    return exit_[1] / entry[0] - 1


def compute():
    prices = _load_dir(PRICES_DIR)
    cal = sorted(prices)
    pos = {d: i for i, d in enumerate(cal)}
    days = _load_dir(DAYS_DIR)

    per_day = {}
    buckets = {}   # (市場, n) -> [(報酬, 超額)]
    for date, doc in sorted(days.items()):
        if date not in pos:
            continue
        i = pos[date]
        entries = {}
        next_day = prices[cal[i + 1]] if i + 1 < len(cal) else {}
        for p in doc["picks"]:
            e = {"entry": (next_day.get(p["code"]) or [None])[0]}
            for n in HORIZONS:
                r = trade_return(prices, cal, i, p["code"], n)
                b = trade_return(prices, cal, i, BENCHMARKS[p["market"]], n)
                e[f"r{n}"] = None if r is None else round(r * 100, 2)
                e[f"x{n}"] = None if r is None or b is None else round((r - b) * 100, 2)
                if r is not None and b is not None:
                    for mk in (p["market"], "全部"):
                        buckets.setdefault((mk, n), []).append((r, r - b))
            entries[p["code"]] = e
        per_day[date] = entries

    # 當沖:隔日開盤進場、當天收盤出場;做空報酬取相反數
    dt_per_day, dt_vals = {}, {"long": [], "short": []}
    for date, doc in sorted(days.items()):
        if date not in pos or pos[date] + 1 >= len(cal) or not doc.get("dayTrade"):
            continue
        nxt = prices[cal[pos[date] + 1]]
        res = {}
        for side in ("long", "short"):
            for p in doc["dayTrade"].get(side, []):
                ohlc = nxt.get(p["code"])
                if not ohlc or ohlc[0] <= 0 or ohlc[1] <= 0 or exits.price_reset(p["code"], cal, prices, pos[date] + 1, pos[date] + 1):
                    continue
                r = ohlc[1] / ohlc[0] - 1
                r = r if side == "long" else -r
                res[f"{side}:{p['code']}"] = round(r * 100, 2)
                dt_vals[side].append(r)
        dt_per_day[date] = res
    dt_summary = {side: {"n": len(v),
                         "winRate": round(sum(1 for r in v if r > 0) / len(v) * 100, 1) if v else None,
                         "avg": round(sum(v) / len(v) * 100, 2) if v else None} for side, v in dt_vals.items()}

    # 投信+營收名單:回測依據是持有 20 日,基準一律 0050
    tr_hz = (1, 5, 10, 20)
    tr_days, tr_vals = {}, {n: [] for n in tr_hz}
    for date, doc in sorted(days.items()):
        if date not in pos or not doc.get("trustRev"):
            continue
        i = pos[date]
        res = {}
        for p in doc["trustRev"]:
            e = {}
            for n in tr_hz:
                r, b = trade_return(prices, cal, i, p["code"], n), trade_return(prices, cal, i, "0050", n)
                e[f"r{n}"] = None if r is None else round(r * 100, 2)
                e[f"x{n}"] = None if r is None or b is None else round((r - b) * 100, 2)
                if r is not None and b is not None:
                    tr_vals[n].append((r, r - b))
            res[p["code"]] = e
        tr_days[date] = res
    tr_summary = {str(n): {"n": len(v),
                           "winRate": round(sum(1 for r, _ in v if r > 0) / len(v) * 100, 1) if v else None,
                           "avg": round(sum(r for r, _ in v) / len(v) * 100, 2) if v else None,
                           "excess": round(sum(x for _, x in v) / len(v) * 100, 2) if v else None} for n, v in tr_vals.items()}

    # 觀察名單「好股回檔」:隔天開盤買、第 5 日收盤賣;上線日以後另外統計
    from .strategy import PB_GO_LIVE, PB_HOLD
    pb_days, pb_vals = {}, {"live": [], "history": []}
    for date, doc in sorted(days.items()):
        if date not in pos or not doc.get("pullback"):
            continue
        i = pos[date]
        res, day_vals = {}, []
        for p in doc["pullback"]:
            r, b = trade_return(prices, cal, i, p["code"], PB_HOLD), trade_return(prices, cal, i, "0050", PB_HOLD)
            res[p["code"]] = {"r5": None if r is None else round(r * 100, 2),
                              "x5": None if r is None or b is None else round((r - b) * 100, 2)}
            if r is not None and b is not None:
                day_vals.append((r * 100, (r - b) * 100))
        pb_days[date] = res
        if day_vals:   # 每天一組等權,扣成本
            ret = sum(a for a, _ in day_vals) / len(day_vals) - PB_COST
            exc = sum(x for _, x in day_vals) / len(day_vals) - PB_COST
            pb_vals["live" if date >= PB_GO_LIVE else "history"].append((date, ret, exc, len(day_vals)))
    pb_summary = {}
    for k, v in pb_vals.items():
        if not v:
            pb_summary[k] = {"days": 0}
            continue
        avg = sum(x[1] for x in v) / len(v)
        pb_summary[k] = {"days": len(v), "from": v[0][0], "to": v[-1][0], "ret": round(avg, 2),
                         "excess": round(sum(x[2] for x in v) / len(v), 2),
                         "monthly": round(((1 + avg / 100) ** (21 / PB_HOLD) - 1) * 100, 1),
                         "winDays": round(sum(1 for x in v if x[1] > 0) / len(v) * 100, 1)}

    # 兩份名單都有的股票(投信+營收 ∩ 好股回檔):每筆扣成本,持有 5 日與 20 日,上線日以後另外統計
    ov_vals = {(h, k): [] for h in (5, 20) for k in ("live", "history")}
    ov_days = {}
    for date, doc in sorted(days.items()):
        if date not in pos or not doc.get("trustRev") or not doc.get("pullback"):
            continue
        both = {p["code"] for p in doc["trustRev"]} & {p["code"] for p in doc["pullback"]}
        if not both:
            continue
        ov_days[date] = sorted(both)
        i = pos[date]
        for h in (5, 20):
            b = trade_return(prices, cal, i, "0050", h)
            for c in both:
                r = trade_return(prices, cal, i, c, h)
                if r is not None and b is not None:
                    ov_vals[(h, "live" if date >= PB_GO_LIVE else "history")].append(
                        (date, r * 100 - PB_COST, (r - b) * 100 - PB_COST))
    ov_summary = {}
    for (h, k), v in ov_vals.items():
        ov_summary.setdefault(str(h), {})[k] = {"n": len(v)} if not v else {
            "n": len(v), "from": min(x[0] for x in v), "to": max(x[0] for x in v),
            "ret": round(sum(x[1] for x in v) / len(v), 2), "excess": round(sum(x[2] for x in v) / len(v), 2),
            "win": round(sum(1 for x in v if x[1] > 0) / len(v) * 100, 1)}

    summary = {}
    for mk in ("全部", "上市", "上櫃"):
        summary[mk] = {}
        for n in HORIZONS:
            vals = buckets.get((mk, n), [])
            if not vals:
                summary[mk][str(n)] = {"n": 0}
                continue
            summary[mk][str(n)] = {
                "n": len(vals),
                "winRate": round(sum(1 for r, _ in vals if r > 0) / len(vals) * 100, 1),
                "avg": round(sum(r for r, _ in vals) / len(vals) * 100, 2),
                "excess": round(sum(x for _, x in vals) / len(vals) * 100, 2),
                "beatRate": round(sum(1 for _, x in vals if x > 0) / len(vals) * 100, 1),
            }
    doc = {
        "updated": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
        "horizons": list(HORIZONS),
        "firstDate": min(per_day) if per_day else None,
        "summary": summary,
        "days": per_day,
        "dayTrade": {"summary": dt_summary, "days": dt_per_day},
        "exitCompare": exits.compare_rules(),
        "trustRev": {"horizons": list(tr_hz), "summary": tr_summary, "days": tr_days},
        "pullback": {"goLive": PB_GO_LIVE, "cost": PB_COST, "summary": pb_summary, "days": pb_days},
        "overlap": {"goLive": PB_GO_LIVE, "cost": PB_COST, "summary": ov_summary, "days": ov_days},
    }
    _write_json(PERF_PATH, doc)
    return doc
