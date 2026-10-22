"""每個排名位置各用 1 萬元模擬(2020-11 ～ 2026-09,9:10 盤中零股買賣、持有 20 日、每次扣 0.585%)。

做法:每條規則的第 k 名各一個帳戶,本金 1 萬平均分成 20 份,每份每 20 個交易日輪一次:
第 i 個選股日的第 k 名,由第 i mod 20 份買進,隔天 9:10 買、20 日後 9:10 賣,賣完整份再投入。
當天沒有第 k 名、或沒有零股成交、或期間有除權減資跳價,該份那一輪就放現金。
用法:python -m research.rank_slots
"""
import json
import os

from . import grid as G
from . import three_year as TY
from .oddlot_all import WINDOWS

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "rank_slots.json")
RULES = {"主名單": "投信10日>15張+營收動能+無價格條件|依投信買超",
         "第1名": "外資10日買超+營收動能+60日漲|依投信買超",
         "第3名": "無籌碼條件+單月營收新高+均線多頭|依投信買超"}
H, COST, CAP, LANES = 20, 0.585, 10000.0, 20


def collect():
    rows = []   # (日期, {規則: [第1..10名報酬或None]}, 0050報酬)
    for start, end, a, b in WINDOWS:
        days, panel, picks = G.daily_picks(start, end, a, b, set(RULES.values()))
        hold = G.make_hold("odd", days, panel)
        for t, p in picks:
            rows.append((str(days[t]), {k: [hold(c, t, H) for c in p[r]] for k, r in RULES.items()}, hold(TY.BENCH, t, H)))
    return rows


def simulate(rows):
    out = {}
    def run(get):
        lanes = [CAP / LANES] * LANES
        for i, row in enumerate(rows):
            r = get(row)
            if r is not None:
                lanes[i % LANES] *= 1 + (r - COST) / 100
        return round(sum(lanes))
    for k in RULES:
        out[k] = [run(lambda row, k=k, n=n: row[1][k][n] if n < len(row[1][k]) else None) for n in range(10)]
    out["0050"] = run(lambda row: None if row[2] is None else row[2] + COST)   # 0050 只算買進持有,不扣個股成本
    return out


if __name__ == "__main__":
    rows = collect()
    res = simulate(rows)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"from": rows[0][0], "to": rows[-1][0], "result": res, "rows": rows}, f, ensure_ascii=False)
    print(rows[0][0], "～", rows[-1][0])
    for k, v in res.items():
        print(k, v)
