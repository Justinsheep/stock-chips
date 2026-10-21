"""追加研究四:2023-07 ～ 2025-06 樣本外驗證(登記內容見 RESEARCH.md)。

用法:python -m research.outsample
輸出:research/outsample.json
"""
import json
import os

from chips.revenue import Revenue

from . import engine as E
from . import swing5 as S

OUT = os.path.join(E.ROOT, "outsample.json")
START, END = "20230401", "20250630"
YEARS = {"A": ("2023-07-01", "2024-06-30"), "B": ("2024-07-01", "2025-06-30")}


def run():
    E.START, E.END = START, END
    days, panel, margin = E.load_panel()
    rev, rc = Revenue(), {}
    rows = []
    for t in range(S.WARMUP, len(days) - 1):
        d = str(days[t])
        year = next((y for y, (a, b) in YEARS.items() if a <= d <= b), None)
        if not year:
            continue
        f, g = E.features(t, panel, margin), S.feats(t, panel)
        key = days[t].strftime("%Y%m") + ("b" if days[t].day > 10 else "a")
        if key not in rc:
            rc[key] = rev.momentum(days[t])
        r2 = E.RULES["R2 投信買超+營收動能"](f, rc[key])
        f2 = S.signals(g, rc[key])["F2 好股回檔"]
        rows.append((t, year, {"both": [c for c in r2 if c in f2], "mainOnly": [c for c in r2 if c not in f2],
                               "main": r2, "pullback": f2}))
    out = {"days": len(rows), "from": str(days[rows[0][0]]), "to": str(days[rows[-1][0]]), "results": {}}
    for h in (5, 20):
        trades, ports = {}, {}
        for t, year, groups in rows:
            if t + h >= len(days):
                continue
            b = E.hold_return(panel, E.BENCH, t, h)
            if b is None:
                continue
            for name, codes in groups.items():
                rets = [r - E.COST for c in codes if (r := E.hold_return(panel, c, t, h)) is not None]
                trades.setdefault(name, {}).setdefault(year, []).extend((r, r - b) for r in rets)
                ret = sum(rets) / len(rets) if rets else 0.0   # 沒股票 = 現金
                ports.setdefault(name, {}).setdefault(year, []).append((ret, ret - b, len(rets)))
        res = {}
        for name in trades:
            res[name] = {}
            for y in YEARS:
                tv, pv = trades[name].get(y, []), ports[name].get(y, [])
                res[name][y] = {
                    "trades": len(tv),
                    "ret": round(sum(a for a, _ in tv) / len(tv), 2) if tv else None,
                    "excess": round(sum(x for _, x in tv) / len(tv), 2) if tv else None,
                    "win": round(sum(1 for a, _ in tv if a > 0) / len(tv) * 100, 1) if tv else None,
                    "portRet": round(sum(a for a, _, _ in pv) / len(pv), 2) if pv else None,
                    "portExcess": round(sum(x for _, x, _ in pv) / len(pv), 2) if pv else None,
                    "daysWithPicks": sum(1 for *_, n in pv if n),
                }
        out["results"][str(h)] = res
    r = out["results"]
    ok = lambda v: v is not None
    out["checks"] = {
        "H1 兩份都有 20 日": all(ok(r["20"]["both"][y]["excess"]) and r["20"]["both"][y]["excess"] > 0
                             and r["20"]["both"][y]["excess"] > r["20"]["mainOnly"][y]["excess"] for y in YEARS),
        "H2 兩份都有 5 日": all(ok(r["5"]["both"][y]["excess"]) and r["5"]["both"][y]["excess"] > 0
                            and r["5"]["both"][y]["excess"] > r["5"]["mainOnly"][y]["excess"] for y in YEARS),
        "H3 今日名單 20 日": all(ok(r["20"]["main"][y]["excess"]) and r["20"]["main"][y]["excess"] > 0 for y in YEARS),
        "H4 好股回檔 5 日": all(ok(r["5"]["pullback"][y]["ret"]) and r["5"]["pullback"][y]["ret"] > 0
                             and r["5"]["pullback"][y]["excess"] > 0 for y in YEARS),
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    d = run()
    print(f"選股日 {d['days']} 天:{d['from']} ~ {d['to']}")
    names = {"both": "兩份都有", "mainOnly": "只在今日名單", "main": "今日名單全部", "pullback": "好股回檔"}
    for h, res in d["results"].items():
        print(f"\n== 持有 {h} 日(每筆扣成本)==")
        for k, v in res.items():
            print(f"  {names[k]:<8} " + " | ".join(
                f"{y} {v[y]['trades']}筆 報酬 {v[y]['ret']}% 超額 {v[y]['excess']}% 勝率 {v[y]['win']}% / 每天一組 {v[y]['portRet']}%(超額 {v[y]['portExcess']}%)"
                for y in YEARS))
    print("\n檢驗:", d["checks"])
