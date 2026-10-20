"""抓研究用的歷史盤後資料(行情、三大法人、融資),存在 cache/,不進版控。

用法:python -m research.fetch_history 20251001 20260731
已經抓過的日期會直接讀快取,中斷後重跑會接著抓。
"""
import datetime as dt
import sys

from chips import sources


def main(argv):
    start, end = (dt.datetime.strptime(a, "%Y%m%d").date() for a in argv[:2])
    d, n = start, 0
    while d <= end:
        if d.weekday() < 5 and sources.twse_inst(d) is not None:
            sources.load_day(d)
            sources.margins(d)
            n += 1
            if n % 10 == 0:
                print(f"已抓 {n} 個交易日,到 {d}", flush=True)
        d += dt.timedelta(days=1)
    print(f"完成:{n} 個交易日", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
