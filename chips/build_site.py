"""把 data/ 的推薦結果與績效嵌入模板,產生 docs/index.html。"""
import json
import os

from .daily import DAYS_DIR
from .exits import DEFAULT_RULES, holding_series
from .perf import PERF_PATH
from .sources import ROOT

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")
SITE = os.path.join(ROOT, "docs", "index.html")   # GitHub Pages 從 docs/ 發布
HISTORY_DAYS = 25   # 網頁歷史清單保留的天數
HOLDING_LOOKBACK = 40   # 「我有買」可追蹤的推薦範圍(交易日)


def build():
    days = []
    if os.path.isdir(DAYS_DIR):
        names = sorted(n for n in os.listdir(DAYS_DIR) if n.endswith(".json"))[-HISTORY_DAYS:]
        for n in reversed(names):
            with open(os.path.join(DAYS_DIR, n), encoding="utf-8") as f:
                days.append(json.load(f))
    perf = None
    if os.path.exists(PERF_PATH):
        with open(PERF_PATH, encoding="utf-8") as f:
            perf = json.load(f)
        keep = {d["date"] for d in days}
        perf["days"] = {k: v for k, v in perf["days"].items() if k in keep}
        if perf.get("foreignON"):
            perf["foreignON"]["days"] = {k: v for k, v in perf["foreignON"]["days"].items() if k in keep}
        if perf.get("pullback"):
            perf["pullback"]["days"] = {k: v for k, v in perf["pullback"]["days"].items() if k in keep}
        if perf.get("trustRev"):
            perf["trustRev"]["days"] = {k: v for k, v in perf["trustRev"]["days"].items() if k in keep}
        if perf.get("dayTrade"):
            perf["dayTrade"]["days"] = {k: v for k, v in perf["dayTrade"]["days"].items() if k in keep}
    lv_path = os.path.join(os.path.dirname(PERF_PATH), "levels.json")
    lv = json.load(open(lv_path, encoding="utf-8")) if os.path.exists(lv_path) else None
    series = holding_series(days[0]["date"], lookback=HOLDING_LOOKBACK) if days else {}   # 要涵蓋歷史清單能選到的股票
    research = os.path.join(ROOT, "research", "results.json")
    research = json.load(open(research, encoding="utf-8")) if os.path.exists(research) else None
    g7 = os.path.join(ROOT, "research", "g7_exec.json")
    g7 = json.load(open(g7, encoding="utf-8")) if os.path.exists(g7) else None
    overlap = os.path.join(ROOT, "research", "overlap.json")
    overlap = json.load(open(overlap, encoding="utf-8")) if os.path.exists(overlap) else None
    swing = os.path.join(ROOT, "research", "swing5.json")
    swing = json.load(open(swing, encoding="utf-8")) if os.path.exists(swing) else None
    payload = json.dumps({"research": research and {"decision": research["decision"], "main": research["results"]["20"]},
                          "overlap": overlap, "g7": g7,
                          "swing": swing and {"segments": swing["segments"], "f2": swing["results"].get("F2 好股回檔 × E1")},
                          "days": days, "perf": perf, "series": series, "exitRules": DEFAULT_RULES, "levels": lv}, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")   # 避免資料中的字串提前結束 <script>
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read().replace("/*__DATA__*/null", payload)
    os.makedirs(os.path.dirname(SITE), exist_ok=True)
    with open(SITE, "w", encoding="utf-8") as f:
        f.write(html)
    return SITE
