"""追加研究十:2020-07 ～ 2023-03 樣本外驗證 6 條 20 日規則(登記內容見 RESEARCH.md)。

用法:python -m research.validate2020
輸出:research/validate2020.json
"""
import gc
import json
import math
import os

from chips import sources

from . import census as CE
from . import three_year as TY

OUT = os.path.join(CE.ROOT, "validate2020.json")
RULES = ["V1 投信＋營收動能(R2)", "X1 R2＋站上季線", "X5 R2＋大盤濾網", "X6 投信買＋融資減＋營收動能",
         "V4 單月營收新高＋站上季線", "P5 均線多頭排列"]
H = 20


def excess_series(start, end, pick_from, pick_to):
    """回傳 {規則: [(選股日, 超額報酬)]},只含 pick_from ～ pick_to 的選股日。"""
    TY.START, TY.END = start, end
    days, panel = TY.load()
    margin = [sources.margins(d)[0] for d in days]
    S = CE.Series(days, panel, margin)
    rf = CE.RevFeats()
    rules = CE.build_rules()
    bench_adj = TY.adjusted_closes(panel, TY.BENCH)
    out = {r: [] for r in RULES}
    for t in range(CE.WARMUP, len(days) - H - 1):
        d = str(days[t])
        if not (pick_from <= d <= pick_to):
            continue
        rev = rf.get(days[t])
        feats = {c: fx for c in panel[t] if c != TY.BENCH and sources.is_common_stock(c)
                 and (fx := CE.features(S, c, t, rev))}
        picks = {}
        for name in RULES:
            if name == "X5 R2＋大盤濾網":
                continue
            cond, rank = rules[name]
            picks[name] = [c for c, _ in sorted(((c, rank(fx)) for c, fx in feats.items() if cond(fx)), key=lambda z: -z[1])[:CE.TOP]]
        ma = [v for v in bench_adj[t - 59:t + 1] if v]
        bull = len(ma) == 60 and bench_adj[t] >= sum(ma) / 60
        b = TY.hold(panel, TY.BENCH, t, H)
        if b is None:
            continue
        for name in RULES:
            if name == "X5 R2＋大盤濾網":
                if not bull:
                    out[name].append((d, -CE.COST))   # 改買 0050:超額 = −成本
                    continue
                codes = picks["V1 投信＋營收動能(R2)"]
            else:
                codes = picks[name]
            rets = [r for c in codes if (r := TY.hold(panel, c, t, H)) is not None]
            ret = sum(rets) / len(rets) - CE.COST if rets else 0.0
            out[name].append((d, ret - b))
    del panel, S
    gc.collect()
    return out


def tstat(series):
    xs = [x for k, (_, x) in enumerate(series) if k % H == 0]
    if len(xs) < 3:
        return 0.0, len(xs)
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
    return (m / (sd / math.sqrt(len(xs))) if sd else 0.0), len(xs)


def run():
    new = excess_series("20200101", "20230405", "2020-07-01", "2023-03-31")
    old = excess_series("20230406", "20261020", "2023-09-27", "2026-09-16")   # 研究七的選股期間
    res = {}
    for name in RULES:
        v = new[name]
        a = [x for d, x in v if d <= "2021-12-31"]
        b = [x for d, x in v if d >= "2022-01-01"]
        t_new, n_new = tstat(v)
        t_all, n_all = tstat(v + old[name])
        res[name] = {"甲 2020-07～2021-12": round(sum(a) / len(a), 2), "乙 2022-01～2023-03": round(sum(b) / len(b), 2),
                     "全段": round(sum(x for _, x in v) / len(v), 2), "t": round(t_new, 2), "n": n_new,
                     "合併約6年 t": round(t_all, 2), "合併 n": n_all,
                     "pass": sum(a) / len(a) > 0 and sum(b) / len(b) > 0 and t_new >= 1.65}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    return res


if __name__ == "__main__":
    for k, v in run().items():
        print(("✅ " if v["pass"] else "   ") + k, v)
