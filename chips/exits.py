"""出場模擬:每一筆推薦都當成一筆交易,逐日檢查出場規則,記錄「第一次亮燈」的日期與原因。

- 進場:推薦日的下一個交易日開盤價。
- 出場:某天收盤後亮燈 → 下一個交易日開盤賣出;持有滿 max_hold 日仍沒亮燈 → 當天收盤賣出。
- 依規則提醒,不是買賣建議。

只讀 data/days、data/prices 與已存的集保資料(data/tdcc 快照、cache/ 的逐檔查詢結果),不連網。
"""
import json
import os
import re

from .sources import BENCHMARKS, CACHE, DATA, TDCC_DIR

DAYS_DIR = os.path.join(DATA, "days")
PRICES_DIR = os.path.join(DATA, "prices")

# 網頁「出場訊號」區使用的預設規則
DEFAULT_RULES = {"stop": -7.0, "inst_days": 2, "ma_days": 2, "big_drop": -0.5, "max_hold": 20}
MA_LEN = 10          # 均線天數
EVAL_DAYS = 10       # 規則比較時,所有規則都最多持有 10 日,讓樣本一致

# 規則比較:(名稱, 規則)。沒列的規則代表不使用。
COMPARE = [
    ("固定持有 5 日", {"max_hold": 5}),
    ("固定持有 10 日", {"max_hold": EVAL_DAYS}),
    ("停損 7%", {"stop": -7.0, "max_hold": EVAL_DAYS}),
    ("停損 + 法人連 2 日賣超", {"stop": -7.0, "inst_days": 2, "max_hold": EVAL_DAYS}),
    ("停損 + 法人 + 單日跌破均線", {"stop": -7.0, "inst_days": 2, "ma_days": 1, "max_hold": EVAL_DAYS}),
    ("停損 + 法人 + 連 2 日跌破均線", {"stop": -7.0, "inst_days": 2, "ma_days": 2, "max_hold": EVAL_DAYS}),
    ("全部規則(預設)", dict(DEFAULT_RULES, max_hold=EVAL_DAYS)),
]


def _load_dir(path):
    out = {}
    if os.path.isdir(path):
        for n in sorted(os.listdir(path)):
            if n.endswith(".json"):
                with open(os.path.join(path, n), encoding="utf-8") as f:
                    out[n[:-5]] = json.load(f)
    return out


def price_reset(code, cal, prices, a, b):
    """cal[a..b] 之間是否有減資、除權等重新定價:開盤與前一天收盤差超過漲跌停幅度(10%)。
    價格沒有還原權值,跨過這種事件的報酬沒有意義,統計時要排除。"""
    for k in range(max(1, a), min(b, len(cal) - 1) + 1):
        prev, cur = prices[cal[k - 1]].get(code), prices[cal[k]].get(code)
        if prev and cur and prev[1] > 0 and cur[0] > 0 and abs(cur[0] / prev[1] - 1) > 0.11:
            return True
    return False


class BigOffline:
    """千張大戶週增減,只用已存的資料。as_of(code, day) -> (週別, 週增減) 或 (None, None)。"""

    def __init__(self):
        weeks = set()
        if os.path.isdir(TDCC_DIR):
            weeks |= {n[:8] for n in os.listdir(TDCC_DIR) if re.fullmatch(r"\d{8}\.json", n)}
        if os.path.isdir(CACHE):
            weeks |= {m.group(1) for n in os.listdir(CACHE) if (m := re.fullmatch(r"tdccq_(\d{8})_\w+\.txt", n))}
        self.weeks = sorted(weeks)
        self._snap = {}

    def value(self, code, week):
        if week not in self._snap:
            path = os.path.join(TDCC_DIR, f"{week}.json")
            self._snap[week] = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None
        if self._snap[week] is not None:
            return self._snap[week].get(code)
        path = os.path.join(CACHE, f"tdccq_{week}_{code}.txt")
        if os.path.exists(path):
            v = open(path).read().strip()
            return float(v) if v else None
        return None

    def as_of(self, code, day):
        """day 為 YYYY-MM-DD。只用資料日早於 day 的週別(與回測相同,避免用到當晚才公布的資料)。"""
        target = day.replace("-", "")
        usable = [w for w in self.weeks if w < target]
        if len(usable) < 2:
            return None, None
        cur, prev = self.value(code, usable[-1]), self.value(code, usable[-2])
        if cur is None or prev is None:
            return usable[-1], None
        return usable[-1], round(cur - prev, 2)


def simulate(code, i_pick, cal, prices, rules, big=None):
    """模擬一筆交易。cal[i_pick] 為推薦日。回傳 dict;還沒進場回傳 None。"""
    last = len(cal) - 1
    i_entry = i_pick + 1
    if i_entry > last:
        return None
    row = prices[cal[i_entry]].get(code)
    if not row or row[0] <= 0:
        return None
    entry = row[0]
    if price_reset(code, cal, prices, i_entry, min(last, i_entry + rules.get("max_hold", 20) - 1)):
        return None
    entry_week = big.as_of(code, cal[i_entry])[0] if big else None
    max_hold = rules.get("max_hold", 20)
    sells = below = 0
    close = entry
    for k in range(i_entry, min(last, i_entry + max_hold - 1) + 1):
        day = cal[k]
        row = prices[day].get(code)
        if not row or row[1] <= 0:
            continue
        close = row[1]
        held = k - i_entry + 1
        reasons = []
        ret = (close / entry - 1) * 100
        if rules.get("stop") is not None and ret <= rules["stop"]:
            reasons.append(f"停損(跌 {abs(ret):.1f}%)")
        sells = sells + 1 if len(row) > 2 and row[2] < 0 else 0
        if rules.get("inst_days") and sells >= rules["inst_days"]:
            reasons.append(f"法人連 {rules['inst_days']} 日賣超")
        if rules.get("ma_days"):
            closes = [(prices[d].get(code) or [0, 0])[1] for d in cal[max(0, k - MA_LEN + 1):k + 1]]
            ma = sum(closes) / MA_LEN if len(closes) == MA_LEN and all(closes) else None
            below = below + 1 if ma and close < ma else 0
            if below >= rules["ma_days"]:
                reasons.append("跌破 10 日均線" if rules["ma_days"] == 1 else f"連 {rules['ma_days']} 日跌破 10 日均線")
        if rules.get("big_drop") is not None and big:
            week, chg = big.as_of(code, day)
            if week != entry_week and chg is not None and chg <= rules["big_drop"]:   # 只看進場後才公布的新週別
                reasons.append(f"大戶週減 {abs(chg):.2f} 個百分點")
        if reasons:
            if k + 1 <= last and (prices[cal[k + 1]].get(code) or [0])[0] > 0:
                exit_day, exit_price, status = cal[k + 1], prices[cal[k + 1]][code][0], "closed"
            else:
                exit_day, exit_price, status = None, None, "exiting"   # 今晚亮燈,明天開盤賣
            return _trade(code, cal, i_pick, i_entry, entry, day, reasons, exit_day, exit_price, status, close, held)
        if held == max_hold:
            return _trade(code, cal, i_pick, i_entry, entry, day, [f"持有滿 {max_hold} 日"], day, close, "closed",
                          close, held)
    return _trade(code, cal, i_pick, i_entry, entry, None, [], None, None, "open", close, last - i_entry + 1)


def _trade(code, cal, i_pick, i_entry, entry, signal_day, reasons, exit_day, exit_price, status, close, held):
    mark = exit_price if exit_price else close
    return {"code": code, "pickedOn": cal[i_pick], "entryDate": cal[i_entry], "entry": entry,
            "signalDate": signal_day, "reasons": reasons, "exitDate": exit_day, "exit": exit_price,
            "status": status, "close": close, "held": held, "ret": round((mark / entry - 1) * 100, 2)}


def _bench_return(market, entry_date, exit_date, exit_at_close, prices):
    b = BENCHMARKS[market]
    e, x = prices[entry_date].get(b), prices[exit_date].get(b)
    if not e or not x or e[0] <= 0:
        return None
    return (x[1] if exit_at_close else x[0]) / e[0] - 1


def _category(reason):
    for word, label in (("停損", "停損"), ("法人", "法人賣超"), ("均線", "跌破均線"), ("大戶", "大戶週減"), ("持有滿", "持有到期")):
        if word in reason:
            return label
    return reason


def compare_rules():
    """所有歷史推薦套用各組出場規則,比較平均報酬、勝率、平均持有天數與超額報酬。"""
    prices = _load_dir(PRICES_DIR)
    cal = sorted(prices)
    pos = {d: i for i, d in enumerate(cal)}
    days = _load_dir(DAYS_DIR)
    big = BigOffline()
    picks = [(pos[d], p) for d, doc in days.items() if d in pos for p in doc["picks"]
             if pos[d] + EVAL_DAYS < len(cal)]   # 只用已滿 EVAL_DAYS 的推薦,各規則樣本相同
    out = []
    for name, rules in COMPARE:
        rets, excess, held, reasons = [], [], [], {}
        for i, p in picks:
            t = simulate(p["code"], i, cal, prices, rules, big)
            if not t or t["status"] != "closed":
                continue
            rets.append(t["ret"])
            held.append(t["held"])
            b = _bench_return(p["market"], t["entryDate"], t["exitDate"], t["exitDate"] == t["signalDate"], prices)
            if b is not None:
                excess.append(t["ret"] - b * 100)
            key = _category(t["reasons"][0])
            reasons[key] = reasons.get(key, 0) + 1
        n = len(rets)
        out.append({
            "name": name, "rules": rules, "n": n,
            "avg": round(sum(rets) / n, 2) if n else None,
            "winRate": round(sum(1 for r in rets if r > 0) / n * 100, 1) if n else None,
            "excess": round(sum(excess) / len(excess), 2) if excess else None,
            "avgHeld": round(sum(held) / n, 1) if n else None,
            "worst": round(min(rets), 2) if n else None,
            "reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        })
    return {"evalDays": EVAL_DAYS, "picksFrom": min(cal[i] for i, _ in picks) if picks else None,
            "picksTo": max(cal[i] for i, _ in picks) if picks else None, "results": out}


def holding_series(d0_str, lookback=40):
    """網頁「我的持股」用:近 lookback 個交易日推薦過的股票,從第一次被推薦起每天的
    [日期, 開盤, 收盤, 法人張數, 10 日均線, 集保週別, 大戶週增減]。出場訊號在瀏覽器依使用者的買進價計算。"""
    prices = _load_dir(PRICES_DIR)
    cal = [d for d in sorted(prices) if d <= d0_str]
    big = BigOffline()
    first = {}   # 代號 -> (第一次推薦日, 名稱, 市場)
    for day in cal[-lookback:]:
        path = os.path.join(DAYS_DIR, f"{day}.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
            alt = doc.get("alt") or {}
            for p in doc["picks"] + (doc.get("trustRev") or []) + (doc.get("pullback") or []) + alt.get("alt1", []) + alt.get("alt3", []):
                first.setdefault(p["code"], (day, p["name"], p["market"]))
    out = {}
    for code, (day, name, market) in first.items():
        rows = []
        for k in range(cal.index(day), len(cal)):
            row = prices[cal[k]].get(code)
            if not row or row[1] <= 0:
                continue
            closes = [(prices[d].get(code) or [0, 0])[1] for d in cal[max(0, k - MA_LEN + 1):k + 1]]
            ma = round(sum(closes) / MA_LEN, 2) if len(closes) == MA_LEN and all(closes) else None
            week, chg = big.as_of(code, cal[k])
            rows.append([cal[k], row[0], row[1], row[2] if len(row) > 2 else 0, ma, week, chg])
        out[code] = {"name": name, "market": market, "pickedOn": day, "rows": rows}
    return out
