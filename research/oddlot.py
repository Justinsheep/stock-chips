"""盤中零股每日行情:取「當日第一次成交價」(現制為 9:10 第一次撮合;上市自 2026-12-07 起改為 9:00)。

資料自 2020-10-26(盤中零股開始)起。快取在 cache/。
用法:python -m research.oddlot 20201026 20261020   # 抓取區間
"""
import datetime as dt
import sys

from chips import sources


def odd_open(d):
    """{代號: 第一次成交價};沒成交的不列。非交易日或抓不到回傳 {}。"""
    out = {}
    j = sources._json(f"https://www.twse.com.tw/rwd/zh/afterTrading/TWTC7U?date={d:%Y%m%d}&response=json",
                      f"twse_odd_{d:%Y%m%d}.json", d)
    if j and j.get("data"):
        for r in j["data"]:
            p = sources.num(r[5])
            if p > 0:
                out[r[0].strip()] = p
    j = sources._json(f"https://www.tpex.org.tw/www/zh-tw/afterTrading/oddQuote?date={d:%Y/%m/%d}&response=json",
                      f"tpex_odd_{d:%Y%m%d}.json", d)
    for t in (j or {}).get("tables", []):
        for r in t.get("data") or []:
            p = sources.num(r[4])
            if p > 0:
                out[r[0].strip()] = p
    return out


if __name__ == "__main__":
    a, b = (dt.datetime.strptime(x, "%Y%m%d").date() for x in sys.argv[1:3])
    d, n = a, 0
    while d <= b:
        if d.weekday() < 5 and sources.twse_inst(d) is not None:
            odd_open(d)
            n += 1
            if n % 100 == 0:
                print(f"已抓 {n} 天,到 {d}", flush=True)
        d += dt.timedelta(days=1)
    print(f"完成:{n} 天", flush=True)
