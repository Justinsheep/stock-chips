"""探索性比較(非預先登記):主名單只買籌碼分數 >= 門檻的股票,跟原本 10 檔全買比。

用法:python -m research.chip70 [門檻,預設 70]
用 data/days(主名單與籌碼分數)與 data/perf.json(每檔後續報酬)。報酬未扣成本,兩組成本相同。
"""
import json
import os
import sys

from chips.daily import DAYS_DIR
from chips.perf import PERF_PATH


def main(th=70):
    perf = json.load(open(PERF_PATH, encoding="utf-8"))["trustRev"]["days"]
    out = {}
    for h in (5, 10, 20):
        all_ret, all_x, hi_ret, hi_x, lo_ret, lo_x = [], [], [], [], [], []
        port_all, port_hi = [], []   # 每天一組等權組合
        days_none = days_used = 0
        for name in sorted(os.listdir(DAYS_DIR)):
            doc = json.load(open(os.path.join(DAYS_DIR, name), encoding="utf-8"))
            res = perf.get(doc["date"], {})
            picks = [p for p in (doc.get("trustRev") or []) if res.get(p["code"], {}).get(f"r{h}") is not None]
            if not picks:
                continue
            days_used += 1
            hi = [p for p in picks if p.get("chip") and p["chip"]["score"] >= th]
            for p in picks:
                r = res[p["code"]]
                (hi_ret if p in hi else lo_ret).append(r[f"r{h}"])
                (hi_x if p in hi else lo_x).append(r[f"x{h}"])
                all_ret.append(r[f"r{h}"])
                all_x.append(r[f"x{h}"])
            port_all.append((sum(res[p["code"]][f"r{h}"] for p in picks) / len(picks),
                             sum(res[p["code"]][f"x{h}"] for p in picks) / len(picks)))
            if hi:
                port_hi.append((sum(res[p["code"]][f"r{h}"] for p in hi) / len(hi),
                                sum(res[p["code"]][f"x{h}"] for p in hi) / len(hi)))
            else:
                days_none += 1
                port_hi.append((0.0, -sum(res[p["code"]][f"r{h}"] - res[p["code"]][f"x{h}"] for p in picks) / len(picks)))
        avg = lambda v: round(sum(v) / len(v), 2) if v else None
        out[h] = {
            "days": days_used, "daysNoQualify": days_none,
            "allPicks": {"n": len(all_ret), "ret": avg(all_ret), "excess": avg(all_x),
                         "win": round(sum(1 for r in all_ret if r > 0) / len(all_ret) * 100, 1) if all_ret else None},
            "chipHigh": {"n": len(hi_ret), "ret": avg(hi_ret), "excess": avg(hi_x),
                         "win": round(sum(1 for r in hi_ret if r > 0) / len(hi_ret) * 100, 1) if hi_ret else None},
            "chipLow": {"n": len(lo_ret), "ret": avg(lo_ret), "excess": avg(lo_x)},
            "portfolioAll": {"ret": avg([a for a, _ in port_all]), "excess": avg([b for _, b in port_all])},
            "portfolioHigh": {"ret": avg([a for a, _ in port_hi]), "excess": avg([b for _, b in port_hi])},
        }
    return out


if __name__ == "__main__":
    th = float(sys.argv[1]) if len(sys.argv) > 1 else 70
    for h, r in main(th).items():
        print(f"持有 {h} 日:{r['days']} 天,其中 {r['daysNoQualify']} 天沒有分數 >= {th:g} 的股票")
        print(f"  原本 10 檔全買  每筆平均 {r['allPicks']['ret']}% 比 0050 {r['allPicks']['excess']}% 勝率 {r['allPicks']['win']}% ({r['allPicks']['n']} 筆)")
        print(f"  只買分數 >= {th:g}  每筆平均 {r['chipHigh']['ret']}% 比 0050 {r['chipHigh']['excess']}% 勝率 {r['chipHigh']['win']}% ({r['chipHigh']['n']} 筆)")
        print(f"  分數 < {th:g} 或無分數  每筆平均 {r['chipLow']['ret']}% 比 0050 {r['chipLow']['excess']}% ({r['chipLow']['n']} 筆)")
        print(f"  每天一組:全買 {r['portfolioAll']['ret']}%(超額 {r['portfolioAll']['excess']}%)"
              f" vs 只買高分 {r['portfolioHigh']['ret']}%(超額 {r['portfolioHigh']['excess']}%,沒股票的日子算現金)")
