"""主名單(R2)與網格第 1、3 名在完全相同期間的直接比較,含配對差異 t 值。

用法:python -m research.head2head [open|odd]
  open:隔天開盤價買、第 20 日收盤賣(與先前研究相同)
  odd :隔天 9:10 盤中零股第一盤買、第 20 日 9:10 零股第一盤賣(需先抓零股資料;2020-10-26 起)
"""
import json
import math
import os
import sys

from . import grid as G

ROOT = os.path.dirname(os.path.abspath(__file__))
RULES = {
    "主名單 投信>15張+營收動能": "投信10日>15張+營收動能+無價格條件|依投信買超",
    "第1名 外資買超+營收動能+60日漲": "外資10日買超+營收動能+60日漲|依投信買超",
    "第3名 單月營收新高+均線多頭": "無籌碼條件+單月營收新高+均線多頭|依投信買超",
}
PERIODS = [("驗證期", "20180101", "20230405", "2018-07-01", "2023-03-31"),
           ("探索期", "20230406", "20261020", "2023-10-01", "2026-09-30")]
H = 20


def tstat(xs):
    xs = [x for k, x in enumerate(xs) if k % H == 0]
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
    return (m / (sd / math.sqrt(len(xs))) if sd else 0.0), len(xs)


def run(mode="open"):
    out = {}
    for label, start, end, a, b in PERIODS:
        res, _ = G.collect(start, end, a, b, only=set(RULES.values()), exec_mode=mode)
        series = {name: res[key][H] for name, key in RULES.items()}
        base = series["主名單 投信>15張+營收動能"]
        out[label] = {}
        for name, s in series.items():
            ex = [x for _, x, _, _ in s]
            t, n = tstat(ex)
            row = {"excess": round(sum(ex) / len(ex), 2), "t": round(t, 2), "n": n,
                   "sub": {}}
            for y0, y1 in (("2018", "2019"), ("2020", "2021"), ("2022", "2023"), ("2024", "2024"), ("2025", "2026")):
                v = [x for d, x, _, _ in s if y0 <= d[:4] <= y1]
                if v:
                    row["sub"][f"{y0}-{y1[2:]}"] = round(sum(v) / len(v), 2)
            if name != "主名單 投信>15張+營收動能":
                diff = [x - y for (_, x, _, _), (_, y, _, _) in zip(s, base)]
                dt, dn = tstat(diff)
                row["vsMain"] = {"diff": round(sum(diff) / len(diff), 2), "t": round(dt, 2)}
            out[label][name] = row
    path = os.path.join(ROOT, f"head2head_{mode}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "open"
    for label, rows in run(mode).items():
        print(f"== {label}({mode})==")
        for name, r in rows.items():
            print(" ", name, r)
