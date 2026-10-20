"""一次性回測:把規則套到過去一段期間的每個交易日,產生歷史推薦,讓績效一上線就有數字。

用法:python backtest.py 20260701 20261016 [--force]

集保開放資料只有最新一週,所以舊週別會逐檔查集保網站(結果快取在 cache/),第一次跑會花比較久。
為避免用到未來資料,回測時不使用與交易日同一天的集保週資料(見 daily.pick_weeks)。
"""
import datetime as dt
import os
import sys

from chips import build_site, daily, perf, score, sources


def main(argv):
    force = "--force" in argv
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 2:
        print(__doc__)
        return 1
    start, end = (dt.datetime.strptime(a, "%Y%m%d").date() for a in args)

    holders = sources.BigHolders()
    d = start
    while d <= end:
        if d.weekday() < 5 and not (os.path.exists(os.path.join(daily.DAYS_DIR, f"{d:%Y-%m-%d}.json")) and not force):
            days = sources.trading_days(d, score.LOOKBACK)
            if days and days[0] == d:
                doc = daily.compute_day(d, days, holders, strict_weeks=True, with_exits=False)
                daily.save_day(doc)
                print(f"{d} 完成:{len(doc['picks'])} 檔,集保 {doc['tdccWeek']} vs {doc['tdccPrevWeek']}", flush=True)
        d += dt.timedelta(days=1)

    # 回測最後一天之後的交易日價格也要有,才算得出持有報酬:補抓到今天
    d = end + dt.timedelta(days=1)
    today = dt.date.today()
    while d <= today:
        if d.weekday() < 5:
            data = sources.load_day(d)
            if data:
                daily.save_prices(d, data)
        d += dt.timedelta(days=1)

    p = perf.compute()
    for mk, s in p["summary"].items():
        print(mk, s)
    print("網頁:", build_site.build())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
