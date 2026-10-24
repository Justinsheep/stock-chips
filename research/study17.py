"""研究十七:產業上限、月營收公布後的買進時機(登記見 RESEARCH.md)。

沿用研究十六的每日候選(study16_rows.json,先跑 python -m research.study16 collect)。
用法:python -m research.study17
"""
import json
import math
import os
from collections import Counter

from . import study16 as S

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "study17.json")
IND = json.load(open(os.path.join(ROOT, "industry.json"), encoding="utf-8"))


def capped(row, k):
    """依候選順序取股,同產業最多 k 檔,湊滿 10 檔。"""
    out, cnt = [], Counter()
    for c in row["cand"]:
        ind = IND.get(c[0], c[0])
        if cnt[ind] < k:
            out.append(c)
            cnt[ind] += 1
        if len(out) == 10:
            break
    return out


def ret_of(cands):
    m = S._mean(c[2][1] + c[2][2] for c in cands if c[2])
    return None if m is None else m - S.COST


def tstat(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 3:
        return 0.0
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
    return m / (sd / math.sqrt(len(xs))) if sd else 0.0


def holm(res, names):
    alive = True
    for i, k in enumerate(sorted(names, key=lambda k: res[k]["p"])):
        alive = alive and res[k]["p"] <= 0.05 / (len(names) - i)
        res[k]["pass"] = bool(alive and all(x is not None and x > 0 for x in res[k]["diffSeg"].values()))


def simulate(rows, offset, pick, capital=100000.0):
    cash, peak, mdd = capital, capital, 0.0
    for i in range(offset, len(rows), S.H):
        legs = [c[2] for c in pick(rows[i]) if c[2]]
        start, spent, back = cash, 0.0, 0.0
        for p1, r, dv in legs:
            sh = int(start / 10 // (p1 * (1 + S.FEE)))
            while sh > 0 and p1 * sh + max(1, p1 * sh * S.FEE) > start / 10:
                sh -= 1
            if sh <= 0:
                continue
            spent += p1 * sh + max(1, p1 * sh * S.FEE)
            val = p1 * (1 + r / 100) * sh
            back += val - max(1, val * S.FEE) - val * S.TAX + p1 * dv / 100 * sh
        cash = cash - spent + back
        peak = max(peak, cash)
        mdd = min(mdd, cash / peak - 1)
    return cash, mdd


def run():
    rows = json.load(open(S.ROWS, encoding="utf-8"))
    n = len(rows)
    c1, c2 = int(n * 0.6), int(n * 0.8)
    seg_of = lambda i: "train" if i < c1 else "valid" if i < c2 else "test"
    bench = [S.bench(r) for r in rows]
    base = [None if (p := S.port(r)) is None or b is None else p - b for r, b in zip(rows, bench)]
    res = {"days": n, "from": rows[0]["d"], "to": rows[-1]["d"], "cap": {}, "timing": {}}

    def summarize(xs, diff, step):
        seg = {k: S._mean(x for i, x in enumerate(diff) if seg_of(i) == k) for k in ("train", "valid", "test")}
        t = S.tstat_step(diff, step) if step else tstat(diff)
        return {"excess": round(S._mean(xs), 2), "diff": round(S._mean(diff), 2),
                "diffSeg": {k: None if v is None else round(v, 2) for k, v in seg.items()},
                "t": round(t, 2), "p": round(0.5 * math.erfc(t / math.sqrt(2)), 4)}

    # 五:產業上限
    def worst(pick):
        runs = [simulate(rows, o, pick) for o in range(S.H)]
        f = sorted(x for x, _ in runs)
        m = sorted(y for _, y in runs)
        return {"median": round(f[S.H // 2]), "mddMedian": round(m[S.H // 2] * 100, 1), "mddWorst": round(m[0] * 100, 1)}
    res["cap"]["基準"] = {"excess": round(S._mean(base), 2), **worst(lambda r: S.picks(r))}
    for k in (2, 3):
        xs = [None if (p := ret_of(capped(r, k))) is None or b is None else p - b for r, b in zip(rows, bench)]
        diff = [None if x is None or y is None else x - y for x, y in zip(xs, base)]
        res["cap"][f"K{k}"] = {**summarize(xs, diff, S.H), **worst(lambda r, k=k: capped(r, k))}
    holm(res["cap"], ["K2", "K3"])

    # 六:買進時機(逐月)
    months = {}
    for i, r in enumerate(rows):
        months.setdefault(r["d"][:7], []).append(i)
    for name, day in (("B1", 1), ("B11", 11), ("B16", 16), ("B21", 21)):
        xs, diff, idx = [], [], []
        for m, ids in sorted(months.items()):
            pick = next((i for i in ids if int(rows[i]["d"][8:]) >= day), None)
            allm = S._mean(base[i] for i in ids)
            if pick is None or base[pick] is None or allm is None:
                continue
            xs.append(base[pick])
            diff.append(base[pick] - allm)
            idx.append(pick)
        seg = {k: S._mean(d for d, i in zip(diff, idx) if seg_of(i) == k) for k in ("train", "valid", "test")}
        t = tstat(diff)
        res["timing"][name] = {"months": len(xs), "excess": round(S._mean(xs), 2), "diff": round(S._mean(diff), 2),
                               "diffSeg": {k: None if v is None else round(v, 2) for k, v in seg.items()},
                               "t": round(t, 2), "p": round(0.5 * math.erfc(t / math.sqrt(2)), 4)}
    holm(res["timing"], ["B1", "B11", "B16", "B21"])
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return res


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=1))
