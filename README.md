# stock-chips:籌碼選股

每個交易日盤後,用證交所、櫃買中心、集保結算所與公開資訊觀測站的公開資料選股並追蹤績效。主名單是通過一年三段回測的「投信買超＋營收動能」(持有 20 個交易日);另保留原網站的籌碼分數名單與當沖名單作參考。完整規格見 [SPEC.md](SPEC.md)。

> 本專案非證券投資顧問事業,內容僅為公開資料整理與規則篩選,不構成投資建議。

## 使用方式

只需要 Python 3.11 以上,不用安裝任何套件。

```bash
python run_daily.py              # 最近一個交易日:計分 → 更新績效 → 產生 docs/index.html
python run_daily.py 20261019     # 指定日期
python run_daily.py --force      # 已是定稿也重算
python backtest.py 20260701 20261016   # 回測一段期間(第一次會花比較久)
python -m unittest               # 單元測試
```

## 自動化

`.github/workflows/daily.yml` 在台灣時間平日 22:15 跑一次,隔天 08:30 再重算前一交易日(抓官方更正後的定稿),結果 commit 回 `data/` 與 `docs/`。
GitHub Pages 設定:Settings → Pages → Deploy from a branch → `main` / `docs`。

## 檔案

| 路徑 | 內容 |
|---|---|
| `chips/sources.py` | 抓取官方資料(快取在 `cache/`,不進版控) |
| `chips/strategy.py` | 主名單:投信買超＋營收動能 |
| `chips/revenue.py` | 月營收(存在 `data/revenue/`) |
| `chips/score.py` | 籌碼分數、標籤、大盤偏弱判斷 |
| `research/` | 規則研究:預先登記的規則、回測引擎與結果 |
| `chips/daily.py` | 單日流程 |
| `chips/perf.py` | 績效計算 |
| `chips/build_site.py`、`chips/template.html` | 產生網頁 |
| `data/days/` | 每日推薦結果 |
| `data/prices/` | 每日開盤、收盤價(績效用) |
| `data/tdcc/` | 每週全市場千張大戶比例 |
| `data/perf.json` | 績效統計 |
| `docs/index.html` | 網頁 |
