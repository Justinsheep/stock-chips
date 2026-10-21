"""追加研究十一:外資大買收高的可執行版本(T 日盤後才知道訊號)。登記內容見 RESEARCH.md。

用法:python -m research.g7_exec
"""
import json
import os

from .nextday2 import picks_for
from .three_year import C, O, WARMUP, jump, load, segment_dates, seg_split

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "g7_exec.json")
COSTS = {"G7a 隔天開盤買→隔天收盤賣(當沖)": {"std": 0.435, "disc": 0.23},
         "G7b 隔天開盤買→後天開盤賣": {"std": 0.585, "disc": 0.38}}


def run():
    days, panel = load()
    rows = [(t, picks_for(t, panel)["G7"]) for t in range(WARMUP, len(days) - 2)]
    seg_of, _ = seg_split(rows)
    out = {}
    for name, cost in COSTS.items():
        acc = {"train": [], "valid": [], "test": []}
        for i, (t, codes) in enumerate(rows):
            for c in codes:
                b, e = panel[t + 1].get(c), panel[t + 2].get(c)
                if not b or b[O] <= 0 or jump(panel, c, t + 1, t + 1):
                    continue
                if name.startswith("G7a"):
                    acc[seg_of(i)].append((b[C] / b[O] - 1) * 100)
                elif e and e[O] > 0 and not jump(panel, c, t + 2, t + 2):
                    acc[seg_of(i)].append((e[O] / b[O] - 1) * 100)
        out[name] = {s: {"trades": len(v), "gross": round(sum(v) / len(v), 3),
                         "netStd": round(sum(v) / len(v) - cost["std"], 3), "netDisc": round(sum(v) / len(v) - cost["disc"], 3),
                         "win": round(sum(1 for x in v if x > cost["std"]) / len(v) * 100, 1)} for s, v in acc.items()}
        out[name]["pass"] = all(out[name][s]["netStd"] > 0 and out[name][s]["trades"] >= 100 for s in acc)
        out[name]["passDisc"] = all(out[name][s]["netDisc"] > 0 and out[name][s]["trades"] >= 100 for s in acc)
    doc = {"segments": segment_dates(days, rows), "results": out}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    return doc


if __name__ == "__main__":
    d = run()
    print(d["segments"])
    for k, v in d["results"].items():
        print(k, "通過" if v["pass"] else "未通過", "| 2.8折", "通過" if v["passDisc"] else "未通過")
        for s in ("train", "valid", "test"):
            print("  ", s, v[s])
