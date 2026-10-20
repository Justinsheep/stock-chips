"""每晚入口:抓最近一個交易日 → 計分 → 更新績效 → 產生網頁。

用法:
  python run_daily.py              # 最近一個有盤後資料的交易日
  python run_daily.py 20261019     # 指定日期(取該日或之前最近的交易日)
  python run_daily.py --force      # 即使已有定稿也重算
"""
import datetime as dt
import json
import os
import sys

from chips import build_site, daily, perf, score, sources

TW = dt.timezone(dt.timedelta(hours=8))
FINAL_NEXT_DAY_HOUR = 8   # 隔天 08:00 以後產生的結果視為定稿,之後不再重算


def already_final(d0):
    path = os.path.join(daily.DAYS_DIR, f"{d0:%Y-%m-%d}.json")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        gen = dt.datetime.fromisoformat(json.load(f)["generatedAt"])
    final_at = dt.datetime.combine(d0 + dt.timedelta(days=1), dt.time(FINAL_NEXT_DAY_HOUR), tzinfo=TW)
    return gen >= final_at


def main(argv):
    force = "--force" in argv
    args = [a for a in argv if not a.startswith("--")]
    end = dt.datetime.strptime(args[0], "%Y%m%d").date() if args else dt.datetime.now(TW).date()

    try:
        week = sources.tdcc_snapshot()
        print("集保最新週:", week)
    except Exception as e:   # 集保暫時連不上不影響其他項目,大戶分數會改用逐檔查詢
        print("集保開放資料下載失敗:", e)

    days = sources.trading_days(end, score.LOOKBACK)
    if not days:
        print("找不到最近的交易日資料,結束。")
        return 0
    d0 = days[0]
    print("交易日:", ", ".join(f"{d:%m/%d}" for d in days))
    if already_final(d0) and not force:
        print(f"{d0} 已是定稿,略過計分(加 --force 可重算)。")
    else:
        doc = daily.compute_day(d0, days, sources.BigHolders())
        daily.save_day(doc)
        print(f"集保週別:{doc['tdccWeek']}(上週 {doc['tdccPrevWeek']});融資未公布:{doc['marginPending'] or '無'}")
        for mk, w in doc["weak"].items():
            print(f"{mk} 偏弱={w['weak']} 指數 {w['indexChgPct']}% 外資+投信 {w['fiAmount']} 億 買超家數佔比 {w['buyRatio']:.0%}")
        for x in doc["picks"]:
            print(f"  {x['market']} {x['rank']:>2} {x['code']} {x['name']:<6} {x['score']:>5} {' '.join(x['tags'])}")

    p = perf.compute()
    s = p["summary"]["全部"]
    print("績效(全部):", {n: s[n] for n in s})
    print("網頁:", build_site.build())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
