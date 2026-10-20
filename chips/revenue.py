"""月營收(公開資訊觀測站彙總表,上市 sii / 上櫃 otc)。

公司須在次月 10 日前公布,所以 M 月營收視為 M+1 月 11 日起才可使用,避免回測用到未來資料。
"""
import datetime as dt
import html as htmlmod
import json
import os
import re

from .sources import DATA, _download, is_common_stock

REV_DIR = os.path.join(DATA, "revenue")   # 每月一個小檔,進版控,每晚只需抓新月份

URL = "https://mopsov.twse.com.tw/nas/t21/{kind}/t21sc03_{roc}_{m}_0.html"


def _parse(text):
    """回傳 {代號: 當月營收(千元)}。"""
    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.S):
        cells = [htmlmod.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
        if len(cells) >= 3 and is_common_stock(cells[0]):
            try:
                out[cells[0]] = float(cells[2].replace(",", ""))
            except ValueError:
                pass
    return out


def month(year, mon):
    """單月全市場營收 {代號: 千元};資料月份還沒公布或抓不到回傳 None。結果存在 data/revenue/。"""
    os.makedirs(REV_DIR, exist_ok=True)
    path = os.path.join(REV_DIR, f"{year}{mon:02d}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    out = {}
    for kind in ("sii", "otc"):
        try:
            text = _download(URL.format(kind=kind, roc=year - 1911, m=mon))
        except Exception as e:
            print(f"  月營收下載失敗 {kind} {year}/{mon}:{e}")
            return None
        out.update(_parse(text))
    if len(out) < 500:   # 尚未公布完整
        return None
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), sort_keys=True)
    return out


def available_month(day):
    """day 當天可使用的最新營收月份 (year, month):過了次月 10 日才算公布。"""
    y, m = day.year, day.month - (1 if day.day > 10 else 2)
    while m <= 0:
        y, m = y - 1, m + 12
    return y, m


def prev_month(y, m, k=1):
    """往前 k 個月(k 為負數則往後)。"""
    total = y * 12 + (m - 1) - k
    return total // 12, total % 12 + 1


class Revenue:
    """依交易日查營收動能:3 個月平均是否創 12 個月新高、最新月年增率。"""

    def __init__(self):
        self._cache = {}

    def _get(self, y, m):
        if (y, m) not in self._cache:
            self._cache[(y, m)] = month(y, m)
        return self._cache[(y, m)]

    def momentum(self, day):
        """回傳 {代號: {"yoy": 年增率%, "high3": 3 月均創 12 月新高}};資料不足的股票不列。"""
        y, m = available_month(day)
        months = [prev_month(y, m, k) for k in range(0, 15)]   # 最新往回 15 個月
        data = [self._get(*ym) for ym in months]
        if any(d is None for d in data[:15]):
            return {}
        out = {}
        for code, cur in data[0].items():
            vals = [d.get(code) for d in data]
            if any(v is None for v in vals[:15]) or vals[12] <= 0:
                continue
            avg3 = [sum(vals[k:k + 3]) / 3 for k in range(0, 13)]   # 最新、往回 12 個月的 3 月均
            out[code] = {"yoy": (vals[0] / vals[12] - 1) * 100, "high3": avg3[0] >= max(avg3[:12])}
        return out


def fetch_range(start, end):
    y, m = start
    while (y, m) <= end:
        r = month(y, m)
        print(f"{y}/{m:02d}:{'OK ' + str(len(r)) if r else '沒有資料'}", flush=True)
        y, m = prev_month(y, m, -1)


if __name__ == "__main__":
    import sys
    a, b = sys.argv[1], sys.argv[2]
    fetch_range((int(a[:4]), int(a[4:])), (int(b[:4]), int(b[4:])))
