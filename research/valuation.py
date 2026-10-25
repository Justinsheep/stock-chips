"""每日本益比、殖利率、股價淨值比(證交所 BWIBBU_d、櫃買 peQryDate),快取在 cache/。

day(d) -> {代號: (本益比或 None, 殖利率%, 股價淨值比或 None)}
用法:python -m research.valuation 20130101 20261023   # 預先下載(只抓有法人資料的交易日)
"""
import datetime as dt
import sys

from chips import sources


def _f(s):
    try:
        v = float(str(s).replace(",", ""))
    except ValueError:
        return None
    return v


def _rows(fields, data):
    i = {k: n for n, k in enumerate(fields)}
    pe, dy, pb = i.get("本益比"), i.get("殖利率(%)"), i.get("股價淨值比")
    out = {}
    for r in data:
        out[str(r[0]).strip()] = (_f(r[pe]) if pe is not None else None, _f(r[dy]) if dy is not None else None,
                                  _f(r[pb]) if pb is not None else None)
    return out


def day(d):
    out = {}
    j = sources._json(f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date={d:%Y%m%d}&selectType=ALL&response=json",
                      f"twse_pe_{d:%Y%m%d}.json", d)
    if j and j.get("data"):
        out.update(_rows(j["fields"], j["data"]))
    j = sources._json(f"https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate?date={d:%Y/%m/%d}&response=json",
                      f"tpex_pe_{d:%Y%m%d}.json", d)
    for t in (j or {}).get("tables") or []:
        if t.get("data"):
            out.update(_rows(t["fields"], t["data"]))
    return out


if __name__ == "__main__":
    a, b = (dt.datetime.strptime(x, "%Y%m%d").date() for x in sys.argv[1:3])
    d, n = a, 0
    while d <= b:
        if d.weekday() < 5 and sources.twse_inst(d) is not None:
            day(d)
            n += 1
            if n % 200 == 0:
                print(f"已抓 {n} 天,到 {d}", flush=True)
        d += dt.timedelta(days=1)
    print(f"完成:{n} 天", flush=True)
