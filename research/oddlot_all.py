"""全部策略在三種買賣時點下的比較(2020-11 ～ 2026-09,盤中零股資料期間)。

買賣時點:
  open     隔天開盤(整股)買、第 H 日收盤賣(先前研究的設定)
  openopen 隔天開盤(整股)買、第 H 日開盤賣
  odd      隔天 9:10 盤中零股第一盤買、第 H 日 9:10 零股第一盤賣
用法:python -m research.oddlot_all
"""
import gc
import json
import math
import os

from . import grid as G
from . import three_year as TY

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "oddlot_all.json")
MODES = ("open", "openopen", "odd")
WINDOWS = [("20200401", "20230405", "2020-11-02", "2023-03-31"),
           ("20221101", "20261020", "2023-04-01", "2026-09-16")]


def strategies():
    with open(os.path.join(ROOT, "grid_validate.json"), encoding="utf-8") as f:
        top10 = [r["rule"] for r in json.load(f)[:10]]
    main = "投信10日>15張+營收動能+無價格條件|依投信買超"
    return [main] + [r for r in top10 if r != main]


def run():
    names = strategies()
    series = {m: {n: {h: [] for h in G.HORIZONS} for n in names} for m in MODES}
    for start, end, a, b in WINDOWS:
        days, panel, rows = G.daily_picks(start, end, a, b, set(names))
        holds = {m: G.make_hold(m, days, panel) for m in MODES}
        for t, picks in rows:
            for m, hold in holds.items():
                for h in G.HORIZONS:
                    bench = hold(TY.BENCH, t, h)
                    if bench is None:
                        continue
                    for n in names:
                        rets = [x for c in picks[n] if (x := hold(c, t, h)) is not None]
                        r = sum(rets) / len(rets) - G.CE.COST if rets else 0.0
                        series[m][n][h].append((str(days[t]), r - bench, r, len(rets)))
        del panel, rows
        gc.collect()
    out = {}
    for m in MODES:
        for n in names:
            for h in G.HORIZONS:
                s = series[m][n][h]
                xs = [x for _, x, _, _ in s]
                out.setdefault(n, {}).setdefault(str(h), {})[m] = {
                    "excess": round(sum(xs) / len(xs), 2), "t": round(G.tstat(s, h), 2),
                    "ret": round(sum(r for _, _, r, _ in s) / len(s), 2),
                    "avgPicks": round(sum(k for *_, k in s) / len(s), 1),
                    "byYear": {y: round(sum(x for d, x, _, _ in s if d[:4] == y) / max(1, sum(1 for d, *_ in s if d[:4] == y)), 2)
                               for y in ("2020", "2021", "2022", "2023", "2024", "2025", "2026")}}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    for n, hs in run().items():
        print(n)
        for h, ms in hs.items():
            print(f"  {h}日 " + " | ".join(f"{m}: 超額 {v['excess']:+.2f}% t {v['t']:+.2f} 檔 {v['avgPicks']}" for m, v in ms.items()))
