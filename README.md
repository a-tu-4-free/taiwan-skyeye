<div align="center">

# 🛡️ SkyEye — 台灣國防情勢監控
### Taiwan Defense Intelligence Monitor

**民間自發・非營利・公開資料來源**
*Civilian-built · Non-profit · Open-source intelligence*

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Telegram](https://img.shields.io/badge/Telegram-@taiwandefence-blue.svg)](https://t.me/taiwandefence)

</div>

---

> ⚠️ **重要聲明 / Disclaimer**
> 本專案內容不構成軍事、政治或投資建議，亦不代表任何官方立場。所有資料均來自公開來源，整理方式可能存在誤差或延遲。正式資訊請以[國防部](https://www.mnd.gov.tw/)、[海巡署](https://www.cga.gov.tw/)、[數位部](https://www.moda.gov.tw/)等政府機關公告為準。
>
> This project does not constitute military, political, or investment advice, nor does it represent any official position. All data comes from open sources and may contain inaccuracies or delays.

---

## 📡 監測項目 / Monitoring Coverage

| 項目 | 資料來源 | 更新頻率 |
|------|---------|---------|
| 共機/共艦擾台 | 國防部新聞稿 | 30 分鐘 |
| 軍機追蹤（ADS-B） | OpenSky Network | 30 分鐘 |
| 海巡動態 | 海巡署新聞稿 | 30 分鐘 |
| 海底電纜狀態 | 數位部 MODA 公告 | 4 小時 |
| AIS 船隻追蹤 | AISStream | 2 小時 |
| 民船徵用偵測 | AIS（兩棲基地周邊分析）| 2 小時 |
| 中共官媒輿論 | 新華社/人民日報/環球時報/CGTN | 2 小時 |
| 國台辦發言 | 國台辦官網 | 1 小時 |
| 國際媒體 | USNI/The War Zone/BBC 等 RSS | 30 分鐘 |
| 智庫分析 | ASPI/CSIS/DFRLab/RAND | 2 小時 |
| PTT 軍武板 | PTT | 30 分鐘 |
| 衛星影像 | Google Maps Static API | 每日 |
| 中國石油消耗 | Our World in Data | 每月 |

---

## 🤖 分析模組 / Analysis Modules

- **威脅評分**：軍事 × 0.5 + 海域 × 0.3 + 資安 × 0.2，0-10 分制
- **異常偵測**：8 種異常類型，偏離14日均值自動觸發
- **AI 研判**：Ollama 本地 LLM（gemma3），Gemini Flash 備援
- **趨勢圖表**：30日威脅趨勢、擾台月統計、三維雷達圖
- **態勢地圖**：ADIZ、中線、電纜、船隻、軍機互動地圖

---

## 📲 Telegram Bot 指令 / Bot Commands

| 指令 | 說明 |
|------|------|
| `/status` | 威脅指數 + 活躍異常摘要 |
| `/summary` | 三句話快速摘要 |
| `/today` | 今日完整情勢報告 |
| `/anomaly` | 異常偵測歷史 |
| `/map` | 台海態勢地圖（HTML，可互動）|
| `/trend` | 30 日威脅趨勢圖 |
| `/cable` | 海底電纜狀態 |
| `/vessel` | 可疑船隻清單 |
| `/satellite` | 今日衛星影像 |
| `/history` | 歷史威脅趨勢 |
| `/weekly` | 本週週報 |
| `/refresh` | 手動觸發資料更新 |
| `/lang` | 切換語言（zh-TW / zh-CN / en）|
| `/panel` | 快捷控制面板 |

---

## 🚀 快速安裝 / Quick Setup

### 需求 / Requirements

- Python 3.11+
- [Ollama](https://ollama.com)（本地 AI，選用）
- Telegram Bot Token（從 [@BotFather](https://t.me/BotFather) 取得）

### 1. 安裝套件

```bash
git clone https://github.com/你的帳號/taiwan-defense-bot.git
cd taiwan-defense-bot
pip install -r requirements.txt
```

### 2. 設定環境變數

```bash
cp .env.example .env
```

編輯 `.env`，填入你的設定：

```env
# 必填
TELEGRAM_BOT_TOKEN=你的Bot Token
TELEGRAM_CHANNEL_ID=@你的頻道ID

# 選填（有才啟用對應功能）
AISSTREAM_API_KEY=        # AIS 船隻追蹤
GEMINI_API_KEY=           # AI 備援分析
GOOGLE_MAPS_API_KEY=      # 衛星圖層

# 本地 AI（使用 Ollama）
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma3:27b

# Web Dashboard 對外網址
WEB_BASE_URL=http://127.0.0.1:5000
```

### 3. 啟動 Ollama（選用）

```bash
# 安裝後執行，首次會下載模型（約 17GB）
ollama run gemma3:27b

# 較小的備用模型（約 8GB）
ollama run gemma3:12b
```

### 4. 啟動 Bot

```bash
python main.py
```

啟動後 Web Dashboard 會在 http://127.0.0.1:5000 開啟。

---

## 取得 Telegram 頻道 ID / Get Channel ID

1. 建立頻道，將 Bot 設為管理員（需有發送訊息權限）
2. 發一則任意訊息到頻道
3. 瀏覽器開啟：`https://api.telegram.org/bot<TOKEN>/getUpdates`
4. 找 `"chat":{"id": -100xxxxxxxx}` 即為頻道 ID

---

## 📁 專案結構 / Project Structure

```
taiwan-defense-bot/
├── main.py                 # 主程式入口
├── config.py               # 設定（從 .env 讀取）
├── scheduler.py            # 排程控制器
├── requirements.txt
├── .env.example            # 環境變數範本
│
├── scrapers/               # 資料爬取
│   ├── mnd.py              # 國防部
│   ├── cga.py              # 海巡署
│   ├── ais.py              # AIS 船隻 + 民船徵用偵測
│   ├── adsb_monitor.py     # ADS-B 軍機追蹤
│   ├── cable_monitor.py    # 海底電纜
│   ├── china_media.py      # 中共官媒輿論
│   ├── gwytb.py            # 國台辦
│   ├── intl_news.py        # 國際媒體
│   ├── thinktank.py        # 智庫
│   ├── ptt.py              # PTT 軍武板
│   ├── satellite.py        # 衛星影像
│   └── oil_monitor.py      # 中國石油消耗指標
│
├── analyzer/               # 分析引擎
│   ├── threat_score.py     # 威脅評分
│   ├── anomaly_detector.py # 異常偵測
│   ├── ollama_client.py    # 本地 AI
│   └── trend.py            # 趨勢圖表
│
├── bot/                    # Telegram Bot
│   ├── telegram_bot.py     # 指令處理
│   ├── alert_engine.py     # 即時警報
│   ├── formatter.py        # 訊息格式
│   ├── map_notifier.py     # 地圖截圖推送
│   ├── card_generator.py   # 圖卡生成
│   ├── i18n.py             # 多語言
│   └── error_notify.py     # 錯誤通知
│
├── maps/
│   └── map_generator.py    # Folium 互動地圖
│
├── database/
│   ├── models.py           # 資料表定義
│   └── db.py               # CRUD 操作
│
└── web/
    └── dashboard.py        # Flask Web Dashboard
```

---

## 🔑 API 申請說明 / API Keys

| 服務 | 必填 | 申請連結 | 備注 |
|------|------|---------|------|
| Telegram Bot | ✅ | [@BotFather](https://t.me/BotFather) | 免費 |
| AISStream | ⭕ | [aisstream.io](https://aisstream.io) | 免費帳號 |
| Google Gemini | ⭕ | [aistudio.google.com](https://aistudio.google.com) | 免費額度 |
| Google Maps | ⭕ | [console.cloud.google.com](https://console.cloud.google.com) | 衛星圖層用 |
| Copernicus | ⭕ | [dataspace.copernicus.eu](https://dataspace.copernicus.eu) | 選用 |

> ⭕ = 選用，沒有對應功能會自動跳過

---

## ⏰ 自動推送排程 / Auto Push Schedule

| 時間 | 任務 |
|------|------|
| 每 2 分鐘 | 高威脅新聞警報（≥7分即時推送）|
| 每 5 分鐘 | 異常偵測掃描 |
| 每 30 分鐘 | 完整爬蟲、ADS-B 軍機、PTT、國際媒體 |
| 每 1 小時 | 國台辦、AI 評分 |
| 每 2 小時 | AIS 船隻、中共官媒、智庫 |
| 每 4 小時 | 海底電纜 |
| 每日 08:00 | 晨間概況推送 + 衛星影像 |
| 每日 19:00 | 威脅評分計算 |
| 每日 20:00 | 情勢日報 + 趨勢圖 |
| 每週日 21:00 | 週報 |
| 每月 1 日 | 石油消耗指標更新 |

---

## 💻 Windows 開機自動啟動（選用）

建立 `start_bot.bat`：

```bat
@echo off
cd /d D:\你的路徑\taiwan-defense-bot
call venv\Scripts\activate
python main.py
pause
```

在「工作排程器」設為開機後啟動即可。

---

## 📐 判斷原則 / Principles

1. **只呈現「發生了什麼」，避免臆測「為什麼」**
2. **多來源交叉比對，降低單一來源誤判**
3. **降低通知疲勞，例行活動不打擾**
4. **衛星影像不附加 AI 判讀**
5. **承認資料限制，不宣稱完整或即時無誤差**

---

## 📜 授權 / License

MIT License — 歡迎 Fork、修改、自行部署。若基於本專案開發，請保留出處說明。

---

<div align="center">

**SkyEye 台灣國防情勢監控** · 民間自發 · 非官方 · 僅供參考

</div>
