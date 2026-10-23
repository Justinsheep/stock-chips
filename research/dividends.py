"""除權息資料(證交所 TWT49U、櫃買 exDailyQ):每次除權息的「權值＋息值」(除權息前收盤 − 參考價)。

用來把報酬加回股利:持有期間(買進日之後、賣出日當天以前)遇到除權息,把權值＋息值加回賣出價。
用法:python -m research.dividends 2018 2026   # 預先下載
"""
import datetime as dt
import sys

from chips import sources


def _roc(s):
    s = s.replace("年", "/").replace("月", "/").replace("日", "")
    y, m, d = (int(x) for x in s.split("/"))
    return dt.date(y + 1911, m, d)


def month(y, m):
    """{(日期, 代號): 權值＋息值(元/股)}。"""
    a = dt.date(y, m, 1)
    b = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
    out = {}
    j = sources._json(f"https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate={a:%Y%m%d}&endDate={b:%Y%m%d}&response=json",
                      f"twse_exr_{a:%Y%m}.json", b)
    for r in (j or {}).get("data") or []:
        v = sources.num(r[5])
        if v > 0:
            out[(_roc(r[0]), r[1].strip())] = v
    j = sources._json(f"https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ?startDate={a:%Y/%m/%d}&endDate={b:%Y/%m/%d}&response=json",
                      f"tpex_exr_{a:%Y%m}.json", b)
    for t in (j or {}).get("tables") or []:
        for r in t.get("data") or []:
            v = sources.num(r[7])
            if v > 0:
                out[(_roc(r[0]), r[1].strip())] = v
    return out


def load(y0, y1):
    """{代號: {日期: 權值＋息值}}。"""
    out = {}
    for y in range(y0, y1 + 1):
        for m in range(1, 13):
            if dt.date(y, m, 1) > dt.date.today():
                break
            for (d, c), v in month(y, m).items():
                out.setdefault(c, {})[d] = v
    return out


if __name__ == "__main__":
    D = load(int(sys.argv[1]), int(sys.argv[2]))
    print("股票數", len(D), "0050:", sorted(D.get("0050", {}).items())[-4:])
