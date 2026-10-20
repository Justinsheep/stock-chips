"""把 data/ 的推薦結果與績效嵌入模板,產生 docs/index.html。"""
import json
import os

from .daily import DAYS_DIR
from .perf import PERF_PATH
from .sources import ROOT

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")
SITE = os.path.join(ROOT, "docs", "index.html")   # GitHub Pages 從 docs/ 發布
HISTORY_DAYS = 60   # 網頁歷史清單保留的天數


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
        if perf.get("dayTrade"):
            perf["dayTrade"]["days"] = {k: v for k, v in perf["dayTrade"]["days"].items() if k in keep}
    payload = json.dumps({"days": days, "perf": perf}, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")   # 避免資料中的字串提前結束 <script>
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read().replace("/*__DATA__*/null", payload)
    os.makedirs(os.path.dirname(SITE), exist_ok=True)
    with open(SITE, "w", encoding="utf-8") as f:
        f.write(html)
    return SITE
