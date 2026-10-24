"""抓取證交所、櫃買中心、集保結算所的盤後公開資料。

所有函式回傳已整理好的 dict;原始回應快取在 cache/(不進版控)。
"""
import datetime as dt
import http.client
import http.cookiejar
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")
DATA = os.path.join(ROOT, "data")
TDCC_DIR = os.path.join(DATA, "tdcc")

UA = {"User-Agent": "Mozilla/5.0 (stock-chips; +https://github.com/)"}
RETRIES = 5
REQUEST_GAP = 2.5        # 每次實際連線後暫停的秒數,避免對官方網站造成負擔
FINAL_HOUR = 22          # 資料日 22:00 以後下載的快取才視為定稿(官方當晚仍可能更正)

# 櫃買中心憑證缺少 Authority Key Identifier,Python 3.13 的嚴格檢查會拒絕;只對櫃買放寬這一項。
_TPEX_SSL = ssl.create_default_context()
_TPEX_SSL.verify_flags &= ~ssl.VERIFY_X509_STRICT


def _ssl_for(url):
    return _TPEX_SSL if urllib.parse.urlparse(url).hostname.endswith("tpex.org.tw") else None


def _download(url, opener=None, data=None):
    req = urllib.request.Request(url, headers=UA, data=data)
    for attempt in range(1, RETRIES + 1):
        try:
            if opener:
                raw = opener.open(req, timeout=90).read()
            else:
                with urllib.request.urlopen(req, timeout=90, context=_ssl_for(url)) as r:
                    raw = r.read()
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as e:
            if attempt == RETRIES:
                raise
            wait = 10 * attempt
            print(f"  連線失敗({e}),{wait} 秒後重試:{url.split('?')[0]}", flush=True)
            time.sleep(wait)
    time.sleep(REQUEST_GAP)
    for enc in ("utf-8-sig", "cp950"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def _cache_path(name):
    os.makedirs(CACHE, exist_ok=True)
    return os.path.join(CACHE, name)


def _is_final(path, day):
    final_at = dt.datetime.combine(day, dt.time(FINAL_HOUR))
    return dt.datetime.fromtimestamp(os.path.getmtime(path)) >= final_at


def _json(url, name, day):
    """抓 JSON;有資料才快取。資料日當晚 22:00 前下載的快取下次會重抓。"""
    path = _cache_path(name)
    if os.path.exists(path) and _is_final(path, day):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    text = _download(url)
    try:
        j = json.loads(text)
    except json.JSONDecodeError:
        return None
    has_rows = bool(j.get("data")) or any(t.get("data") for t in j.get("tables") or [])
    if str(j.get("stat", "")).lower() != "ok" or not has_rows:
        return None   # 尚未公布或非交易日:不快取
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return j


def num(s):
    s = re.sub(r"<[^>]+>", "", str(s)).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def is_common_stock(code):
    return bool(re.fullmatch(r"[1-9]\d{3}", code))


BENCHMARKS = {"上市": "0050", "上櫃": "006201"}


# ---------- 三大法人(單位:股) ----------

def twse_inst(d):
    j = _json(f"https://www.twse.com.tw/rwd/zh/fund/T86?date={d:%Y%m%d}&selectType=ALLBUT0999&response=json",
              f"twse_t86_{d:%Y%m%d}.json", d)
    if not j:
        return None
    if len(j["fields"]) >= 19:
        return {r[0].strip(): {"name": r[1].strip(), "foreign": num(r[4]) + num(r[7]), "trust": num(r[10]),
                               "dealer": num(r[11]), "total": num(r[18])} for r in j["data"]}
    total = len(j["fields"]) - 1   # 2017-12 以前:12 欄(2014-11 前)或 16 欄,外資不分自營商
    return {r[0].strip(): {"name": r[1].strip(), "foreign": num(r[4]), "trust": num(r[7]),
                           "dealer": num(r[8]), "total": num(r[total])} for r in j["data"]}


def tpex_inst(d):
    j = _json(f"https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date={d:%Y/%m/%d}&response=json",
              f"tpex_inst_{d:%Y%m%d}.json", d)
    if not j:
        return None
    table = next((t for t in j["tables"] if t.get("data")), None)
    if not table:
        return None
    if len(table["fields"]) >= 24:
        # 新格式(約 2018 年中以後):外資(不含自營)3、外資自營 3、外資合計 3、投信 3、自營(自行)3、自營(避險)3、自營合計 3、三大法人合計
        idx = {"foreign": 10, "trust": 13, "dealer": 22, "total": 23}
    else:
        # 舊格式(16 欄):外資買/賣/淨、投信買/賣/淨、自營淨、自營(自行)3、自營(避險)3、三大法人合計
        idx = {"foreign": 4, "trust": 7, "dealer": 8, "total": 15}
    return {r[0].strip(): {"name": r[1].strip(), **{k: num(r[i]) for k, i in idx.items()}} for r in table["data"]}


# ---------- 收盤行情(成交量單位:股) ----------

def _signed(sign_html, value):
    return -num(value) if "-" in re.sub(r"<[^>]+>", "", sign_html) or "green" in sign_html else num(value)


def twse_price(d):
    j = _json(f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d:%Y%m%d}&type=ALLBUT0999&response=json",
              f"twse_mi_{d:%Y%m%d}.json", d)
    if not j:
        return None
    table = next((t for t in j["tables"] if t.get("fields") and t["fields"][0] == "證券代號"
                  and "收盤價" in t["fields"]), None)
    if not table:
        return None
    return {r[0].strip(): {"name": r[1].strip(), "vol": num(r[2]), "value": num(r[4]), "open": num(r[5]),
                           "high": num(r[6]), "low": num(r[7]), "close": num(r[8]), "diff": _signed(r[9], r[10])}
            for r in table["data"]}


def tpex_price(d):
    j = _json(f"https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date={d:%Y/%m/%d}&type=EW&response=json",
              f"tpex_otc_{d:%Y%m%d}.json", d)
    if not j:
        return None
    return {r[0].strip(): {"name": r[1].strip(), "close": num(r[2]), "diff": num(r[3]), "open": num(r[4]),
                           "high": num(r[5]), "low": num(r[6]), "vol": num(r[7]), "value": num(r[8]),
                           "shares": num(r[14])}
            for r in j["tables"][0]["data"]}


def twse_shares():
    """上市公司已發行普通股數(證交所公司基本資料),快取 7 天。"""
    path = _cache_path("twse_shares.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 7 * 86400:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    try:
        rows = json.loads(_download("https://openapi.twse.com.tw/v1/opendata/t187ap03_L"))
    except Exception as e:   # 拿不到股數只影響週轉率,不中斷流程
        print("  上市發行股數下載失敗:", e)
        return {}
    out = {r["公司代號"].strip(): num(r.get("已發行普通股數或TDR原股發行股數", 0)) for r in rows if r.get("公司代號")}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f)
    return out


# ---------- 當沖 ----------

def daytrade_list(d):
    """當日沖銷交易標的:回傳 ({代號: {"dtVol": 當沖成交股數, "noShortFirst": 暫停先賣後買}}, 尚未公布的市場集合)。

    當沖成交統計晚上才公布;在那之前證交所只回「可當沖標的」三個欄位、櫃買回空表,都視為尚未公布。"""
    out, missing = {}, set()
    for market, url, name in (
            ("上市", f"https://www.twse.com.tw/rwd/zh/dayTrading/TWTB4U?date={d:%Y%m%d}&selectType=All&response=json",
             f"twse_daytrade_{d:%Y%m%d}.json"),
            ("上櫃", f"https://www.tpex.org.tw/www/zh-tw/intraday/stat?type=Daily&date={d:%Y/%m/%d}&response=json",
             f"tpex_daytrade_{d:%Y%m%d}.json")):
        j = _json(url, name, d)
        table = next((t for t in (j or {}).get("tables", []) if t.get("fields") and t["fields"][0] == "證券代號"), None)
        rows = [r for r in (table or {}).get("data", []) if len(r) >= 4]
        if not rows:
            missing.add(market)
            path = _cache_path(name)
            if os.path.exists(path):   # 不完整的版本不要留在快取裡
                os.remove(path)
            continue
        for r in rows:
            out[r[0].strip()] = {"dtVol": num(r[3]), "noShortFirst": r[2].strip() == "Y"}
    return out, missing


# ---------- 指數 ----------

def indices(d):
    """{"上市": {name, close, chg, chgPct}, "上櫃": {...}}"""
    out = {}
    j = _json(f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d:%Y%m%d}&type=ALLBUT0999&response=json",
              f"twse_mi_{d:%Y%m%d}.json", d)
    if j:
        for t in j["tables"]:
            for r in t.get("data") or []:
                if r and r[0].strip() == "發行量加權股價指數":
                    out["上市"] = {"name": "加權指數", "close": num(r[1]), "chg": _signed(r[2], r[3]), "chgPct": num(r[4])}
    j = _json(f"https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?date={d:%Y/%m/%d}&response=json",
              f"tpex_inx_{d:%Y%m%d}.json", d)
    row = next((r for r in (j or {}).get("tables", [{}])[0].get("data", []) if r[0] == f"{d:%Y/%m/%d}"), None)
    if row:
        close, chg = num(row[4]), num(row[5])
        out["上櫃"] = {"name": "櫃買指數", "close": close, "chg": chg,
                     "chgPct": round(chg / (close - chg) * 100, 2) if close != chg else 0.0}
    return out


# ---------- 融資(單位:張) ----------

def margins(d):
    """回傳 ({代號: 融資增減張數}, 尚未公布的市場集合)。融資融券約 21:30 公布。"""
    out, missing = {}, set()
    j = _json(f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={d:%Y%m%d}&selectType=ALL&response=json",
              f"twse_margin_{d:%Y%m%d}.json", d)
    table = next((t for t in (j or {}).get("tables", []) if t.get("fields") and t["fields"][0] == "代號"), None)
    if table:
        for r in table["data"]:
            out[r[0].strip()] = num(r[6]) - num(r[5])   # 今日餘額 - 前日餘額
    else:
        missing.add("上市")
    j = _json(f"https://www.tpex.org.tw/www/zh-tw/margin/balance?date={d:%Y/%m/%d}&response=json",
              f"tpex_margin_{d:%Y%m%d}.json", d)
    if j:
        for r in j["tables"][0]["data"]:
            out[r[0].strip()] = num(r[6]) - num(r[2])   # 資餘額 - 前資餘額
    else:
        missing.add("上櫃")
    return out, missing


# ---------- 合併成單日資料 ----------

def load_day(d):
    """單一交易日:{代號: {name, market, close, open, diff, vol, foreign, trust, dealer, inst}};非交易日回傳 None。"""
    tw_inst = twse_inst(d)
    if tw_inst is None:
        return None
    tw_px = twse_price(d) or {}
    tp_inst = tpex_inst(d) or {}
    tp_px = tpex_price(d) or {}
    tw_shares = twse_shares()
    out = {}
    for market, px, inst in (("上市", tw_px, tw_inst), ("上櫃", tp_px, tp_inst)):
        for code, p in px.items():
            if not (is_common_stock(code) or code == BENCHMARKS[market]):
                continue
            i = inst.get(code, {})
            out[code] = {"name": p["name"], "market": market, "close": p["close"], "open": p["open"],
                         "high": p["high"], "low": p["low"], "diff": p["diff"], "vol": p["vol"],
                         "shares": p.get("shares") or tw_shares.get(code, 0.0), "foreign": i.get("foreign", 0.0),
                         "trust": i.get("trust", 0.0), "dealer": i.get("dealer", 0.0), "inst": i.get("total", 0.0)}
    return out


def trading_days(end, n, max_back=40):
    """從 end 往回找 n 個有盤後資料的交易日,新到舊。"""
    days, d = [], end
    while len(days) < n and (end - d).days <= max_back:
        if d.weekday() < 5 and twse_inst(d) is not None:
            days.append(d)
        d -= dt.timedelta(days=1)
    return days


# ---------- 集保股權分散表(千張大戶 = 第 15 級) ----------

def tdcc_snapshot():
    """下載集保開放資料最新一週的全市場千張大戶比例,存成 data/tdcc/YYYYMMDD.json。回傳週別日期。"""
    text = _download("https://opendata.tdcc.com.tw/getOD.ashx?id=1-5")
    week, out = None, {}
    for line in text.splitlines()[1:]:
        p = line.split(",")
        if len(p) >= 6 and p[2].strip() == "15":
            week = p[0].strip()
            code = p[1].strip()
            if is_common_stock(code):
                out[code] = float(p[5])
    if not week:
        return None
    os.makedirs(TDCC_DIR, exist_ok=True)
    path = os.path.join(TDCC_DIR, f"{week}.json")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return week


def tdcc_saved_weeks():
    if not os.path.isdir(TDCC_DIR):
        return []
    return sorted(n[:8] for n in os.listdir(TDCC_DIR) if re.fullmatch(r"\d{8}\.json", n))


def tdcc_load(week):
    path = os.path.join(TDCC_DIR, f"{week}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class TdccQuery:
    """集保「股權分散表查詢」頁面:查單一股票指定週的千張大戶比例(約可查一年內)。"""
    URL = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"

    TOKEN_RE = r'name="SYNCHRONIZER_TOKEN" value="([^"]+)"'

    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self._weeks = None
        self._token = None   # 每次查詢結果頁都附上下一次可用的 token,接著用就不必每次重抓表單

    def _form(self):
        html = _download(self.URL, opener=self.opener)
        self._weeks = re.findall(r'<option value="(\d{8})"', html)
        self._token = re.search(self.TOKEN_RE, html).group(1)

    def weeks(self):
        if self._weeks is None:
            self._form()
        return sorted(self._weeks)

    def big_pct(self, code, week):
        path = _cache_path(f"tdccq_{week}_{code}.txt")
        if os.path.exists(path):
            with open(path) as f:
                v = f.read().strip()
            return float(v) if v else None
        weeks = self.weeks()
        if week not in weeks:
            return None
        if self._token is None:
            self._form()
        data = {"SYNCHRONIZER_TOKEN": self._token, "SYNCHRONIZER_URI": "/portal/zh/smWeb/qryStock",
                "method": "submit", "firDate": weeks[-1], "scaDate": week, "sqlMethod": "StockNo",
                "stockNo": code, "stockName": ""}
        try:
            html = _download(self.URL, opener=self.opener, data=urllib.parse.urlencode(data).encode())
        finally:
            self._token = None   # 失敗時下次重抓表單
        tok = re.search(self.TOKEN_RE, html)
        self._token = tok.group(1) if tok else None
        m = re.search(r"<td[^>]*>15</td>\s*<td[^>]*>[^<]+</td>\s*<td[^>]*>[\d,]+</td>\s*"
                      r"<td[^>]*>[\d,]+</td>\s*<td[^>]*>([\d.]+)</td>", html)
        val = float(m.group(1)) if m else None
        with open(path, "w") as f:
            f.write("" if val is None else str(val))
        return val


class BigHolders:
    """取得某週、某股票的千張大戶比例:優先用 data/tdcc 的全市場快照,沒有才逐檔查集保網站。"""

    def __init__(self):
        self.query = TdccQuery()
        self._snap = {}

    def all_weeks(self):
        try:
            remote = self.query.weeks()
        except Exception as e:   # 查詢頁暫時連不上時,只用已存的快照
            print("  集保查詢頁連線失敗:", e)
            remote = []
        return sorted(set(remote) | set(tdcc_saved_weeks()))

    def get(self, code, week):
        if week not in self._snap:
            self._snap[week] = tdcc_load(week)
        snap = self._snap[week]
        if snap is not None:
            return snap.get(code)
        for attempt in range(3):
            try:
                return self.query.big_pct(code, week)
            except Exception as e:
                print(f"  集保查詢失敗 {code} {week}:{e}")
                time.sleep(5)
        return None
