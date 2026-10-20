# 更新紀錄 / Changelog

## 2026-10-20

### 修正
- **地圖底圖出現「API KEY REQUIRED」**：CARTO 底圖改為需要 API key。預設改用免 key 的 Esri Dark Gray；`.env` 填 `CARTO_API_KEY` 可改回 CARTO。
- **海底電纜狀態錯誤**：MODA 障礙表欄位對錯，導致「斷纜」從未判定為中斷、每天寫入重複紀錄，名稱欄還混入「距○○公里處」。改成從右側對齊解析，支援多筆障礙的合併儲存格；啟動時自動清除舊格式錯誤紀錄。
- **電纜已修復判定**：從 MODA 表上移除的電纜，會自動寫入「已修復」。
- **電纜路線重繪**：依實際登陸站（淡水／八里／頭城）重畫成示意路由，全程避開陸地與島嶼；同一登陸站的電纜錯開顯示；依「距○○約 N 公里」推估標示故障點。
- **海峽中線座標**：改為 27°N/122°E – 23°N/118°E。
- **ADS-B 掃描每次報錯**：高度或航向為 None 時格式化失敗（`NoneType.__format__`）。
- **排程卡死**：`feedparser` 抓網址時沒有逾時，加上全域 socket 逾時 30 秒。
- **擾台地圖從未產生**：補上缺少的 `HIGH_THREAT_TYPES`。
- **日報、週報地圖快照失敗**：Playwright sync API 改在 thread 中執行。
- **TG 指令選單沒設定**：`main.py` 的 `post_init` 蓋掉了 `build_app` 的設定，改為兩者都執行。
- **TG 斷網時 log 洗版**：新增全域 error handler。
- **管理員錯誤通知發不出去**：`ADMIN_USER_ID` 是 list，改為逐一發送。
- **Gemini 備援失效**：`gemini-2.0-flash-lite` 已下架，改用 `gemini-2.5-flash-lite`，可用 `GEMINI_MODEL` 設定。
- **電纜警報重複推送**：長期障礙不再每 2 小時重推，只在異常組合改變時推送；電纜監控與異常偵測不再同時推送同一事件。
- **沒有 Ollama 時高威脅警報不會觸發**：改用規則評分補上 threat_score。
- **Ollama 呼叫卡住 Bot**：同步呼叫改在 thread 中執行，不再阻塞 TG 指令與其他排程。
- **Ollama 模型檢查誤判**：改成完整名稱比對，找不到時提示要 pull 的模型。
- 每週清理改用絕對路徑，並涵蓋 `map_shots/`、`cards/`。

### 新增
- `OLLAMA_TIMEOUT`：Ollama 單次呼叫逾時（預設 180 秒），慢的硬體可以調高。
- `CARTO_API_KEY`、`GEMINI_MODEL` 設定項。
- `maps/cable_data.py`：電纜資料的單一來源，地圖、警報、卡片、爬蟲共用。
- README 新增「硬體需求」與「地圖說明」。

### 變更
- 預設模型 `gemma3:27b` 改為 `gemma3:12b`。
- `requirements.txt`：補上 `flask`、`playwright`；移除未使用的 `pandas`、`ollama`、`python-dateutil`、`pytz`、`py7zr`；版本改為下限，支援 Python 3.13。

### 移除
- 已停用的衛星 AI 分析程式，以及約 20 個未被呼叫的函式（如 `push_alerts`、`push_routine_status`、`make_cga_map` 等）。
