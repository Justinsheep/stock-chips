"""追加研究十二:規則網格探索與樣本外驗證(登記內容見 RESEARCH.md)。

用法:
  python -m research.grid explore    # 只用探索集,選出最多 20 條 / 持有天數,寫入 grid_selected.json
  python -m research.grid validate   # 只用驗證集,檢驗 grid_selected.json 裡的規則
"""
import itertools
import json
import math
import os
import sys

from chips import sources

from . import census as CE
from . import three_year as TY

ROOT = os.path.dirname(os.path.abspath(__file__))
SELECTED = os.path.join(ROOT, "grid_selected.json")
EXPLORE_OUT = os.path.join(ROOT, "grid_explore.json")
VALIDATE_OUT = os.path.join(ROOT, "grid_validate.json")
HORIZONS = (20, 5)
TOP = 10
MAX_SELECT = 20
JACCARD_MAX = 0.6

CHIP = {
    "投信10日>15張": lambda x: x["t10"] > 15,
    "投信買超力道>0.05": lambda x: x["t10"] / x["v20"] > 0.05,
    "外資10日買超": lambda x: x["f10"] > 0,
    "法人20日買超": lambda x: x["i20"] > 0,
    "投信連買≥3日": lambda x: x["tstreak"] >= 3,
    "融資10日減少": lambda x: x["m10"] < 0,
    "無籌碼條件": None,
}
REV = {
    "營收動能": lambda r: r and r["high3"] and r["yoy"] > 20,
    "年增>30%": lambda r: r and r["yoy"] > 30,
    "營收加速": lambda r: r and r["accel"] > 10,
    "單月營收新高": lambda r: r and r["high1"],
    "無營收條件": None,
}
PRICE = {
    "無價格條件": None,
    "站上季線": lambda x: x["c"] > x["ma60"],
    "均線多頭": lambda x: x["ma5"] > x["ma20"] > x["ma60"],
    "60日漲": lambda x: x["ret60"] > 0,
}
RANK = {
    "依投信買超": lambda x: x["t10"],
    "依投信力道": lambda x: x["t10"] / x["v20"],
    "依低波動": lambda x: -x["std20"],
}


def rule_names():
    for c, v, p, r in itertools.product(CHIP, REV, PRICE, RANK):
        if CHIP[c] is None and REV[v] is None:
            continue
        yield f"{c}+{v}+{p}|{r}", (c, v, p, r)


def collect(start, end, pick_from, pick_to, only=None, keep_picks=False):
    """回傳 {規則: {H: [(選股日, 超額, 報酬, 檔數)]}},以及(選擇性)每日持股。"""
    TY.START, TY.END = start, end
    days, panel = TY.load()
    margin = [sources.margins(d)[0] for d in days]
    S = CE.Series(days, panel, margin)
    rf = CE.RevFeats()
    rules = dict(rule_names())
    if only:
        rules = {k: v for k, v in rules.items() if k in only}
    out = {k: {h: [] for h in HORIZONS} for k in rules}
    picks_log = {k: [] for k in rules} if keep_picks else None
    for t in range(CE.WARMUP, len(days) - max(HORIZONS) - 1):
        d = str(days[t])
        if not (pick_from <= d <= pick_to):
            continue
        rev = rf.get(days[t])
        feats = {c: fx for c in panel[t] if c != TY.BENCH and sources.is_common_stock(c)
                 and (fx := CE.features(S, c, t, rev))}
        pool = set(feats)
        sets = {}
        for name, f in CHIP.items():
            sets[("c", name)] = pool if f is None else {c for c, x in feats.items() if f(x)}
        for name, f in REV.items():
            sets[("v", name)] = pool if f is None else {c for c, x in feats.items() if f(x["rev"])}
        for name, f in PRICE.items():
            sets[("p", name)] = pool if f is None else {c for c, x in feats.items() if f(x)}
        order = {name: sorted(feats, key=lambda c, f=f: -f(feats[c])) for name, f in RANK.items()}
        bench = {h: TY.hold(panel, TY.BENCH, t, h) for h in HORIZONS}
        cache = {}

        def ret(c, h):
            if (c, h) not in cache:
                cache[(c, h)] = TY.hold(panel, c, t, h)
            return cache[(c, h)]

        for key, (c, v, p, r) in rules.items():
            cand = sets[("c", c)] & sets[("v", v)] & sets[("p", p)]
            chosen = []
            if cand:
                for code in order[r]:
                    if code in cand:
                        chosen.append(code)
                        if len(chosen) == TOP:
                            break
            if keep_picks:
                picks_log[key].append(chosen)
            for h in HORIZONS:
                if bench[h] is None:
                    continue
                rets = [x for code in chosen if (x := ret(code, h)) is not None]
                rr = sum(rets) / len(rets) - CE.COST if rets else 0.0
                out[key][h].append((d, rr - bench[h], rr, len(rets)))
    return out, picks_log


def tstat(series, h):
    xs = [x for k, (_, x, _, _) in enumerate(series) if k % h == 0]
    if len(xs) < 3:
        return 0.0
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
    return m / (sd / math.sqrt(len(xs))) if sd else 0.0


def explore():
    out, picks = collect("20230406", "20261020", "2023-10-01", "2026-09-30", keep_picks=True)
    summary, selected = {}, {}
    for h in HORIZONS:
        rows = []
        for k, v in out.items():
            s = v[h]
            n = len(s)
            thirds = [s[:n // 3], s[n // 3:2 * n // 3], s[2 * n // 3:]]
            ex = [sum(x for _, x, _, _ in part) / len(part) for part in thirds]
            rows.append((k, ex, tstat(s, h), sum(x for _, x, _, _ in s) / n))
        summary[h] = {k: {"thirds": [round(e, 2) for e in ex], "t": round(t, 2), "excess": round(m, 2)} for k, ex, t, m in rows}
        cands = sorted((r for r in rows if all(e > 0 for e in r[1])), key=lambda r: -r[2])
        chosen = []
        for k, ex, t, m in cands:
            dup = False
            for j in chosen:
                pairs = [(set(a), set(b)) for a, b in zip(picks[k], picks[j]) if a and b]
                jac = sum(len(a & b) / len(a | b) for a, b in pairs) / len(pairs) if pairs else 0
                if jac > JACCARD_MAX:
                    dup = True
                    break
            if not dup:
                chosen.append(k)
            if len(chosen) == MAX_SELECT:
                break
        selected[str(h)] = chosen
    with open(EXPLORE_OUT, "w", encoding="utf-8") as f:
        json.dump({"rules": len(out), "summary": {str(h): v for h, v in summary.items()}}, f, ensure_ascii=False)
    with open(SELECTED, "w", encoding="utf-8") as f:
        json.dump(selected, f, ensure_ascii=False, indent=1)
    return len(out), summary, selected


def holm_threshold(m, alpha=0.05):
    """回傳依排名的單尾 Holm 門檻 t 值(常態近似)。"""
    from statistics import NormalDist
    return [NormalDist().inv_cdf(1 - alpha / (m - i)) for i in range(m)]


def validate():
    with open(SELECTED, encoding="utf-8") as f:
        selected = json.load(f)
    allrules = {k for v in selected.values() for k in v}
    out, _ = collect("20180101", "20230405", "2018-07-01", "2023-03-31", only=allrules)
    res = []
    for h, names in selected.items():
        h = int(h)
        for k in names:
            s = out[k][h]
            sub = {"2018-19": [x for d, x, _, _ in s if d < "2020-01-01"],
                   "2020-21": [x for d, x, _, _ in s if "2020-01-01" <= d < "2022-01-01"],
                   "2022-23": [x for d, x, _, _ in s if d >= "2022-01-01"]}
            eq, peak, mdd = 1.0, 1.0, 0.0
            for j, (_, _, r, _) in enumerate(s):
                if j % h == 0:
                    eq *= 1 + r / 100
                    peak = max(peak, eq)
                    mdd = min(mdd, eq / peak - 1)
            years = len(s) / 245
            res.append({"rule": k, "H": h, "excess": round(sum(x for _, x, _, _ in s) / len(s), 2),
                        "t": round(tstat(s, h), 2),
                        "sub": {kk: round(sum(v) / len(v), 2) if v else None for kk, v in sub.items()},
                        "win": round(sum(1 for _, x, _, _ in s if x > 0) / len(s) * 100, 1),
                        "annual": round((eq ** (1 / years) - 1) * 100, 1) if years > 0 else None,
                        "maxDrawdown": round(mdd * 100, 1),
                        "avgPicks": round(sum(n for *_, n in s) / len(s), 1)})
    res.sort(key=lambda r: -r["t"])
    thr = holm_threshold(len(res))
    stop = False
    for i, r in enumerate(res):
        r["holmT"] = round(thr[i], 2)
        r["pass"] = (not stop) and r["excess"] > 0 and r["t"] >= thr[i]
        if not r["pass"]:
            stop = True   # Holm:一旦未通過,之後都不算通過
        r["tier"] = "pass" if r["pass"] else ("promising" if r["excess"] > 0 else "fail")
    with open(VALIDATE_OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return res


if __name__ == "__main__":
    if sys.argv[1:] == ["explore"]:
        n, summary, selected = explore()
        print("規則數:", n)
        for h, names in selected.items():
            print(f"\n持有 {h} 日 選入驗證 {len(names)} 條:")
            for k in names:
                print("  ", k, summary[int(h)][k])
    elif sys.argv[1:] == ["validate"]:
        for r in validate():
            mark = {"pass": "✅", "promising": "⚠️", "fail": "❌"}[r["tier"]]
            print(mark, r)
