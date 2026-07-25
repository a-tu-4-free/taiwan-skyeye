# 檔案名稱：config.py
# 功能說明：全域設定檔，敏感資訊從 .env 讀取，其餘維持常數

import os
from dotenv import load_dotenv

# 載入 .env（若不存在則略過，改從系統環境變數讀）
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))


def _require(key: str) -> str:
    """讀取必填環境變數，未設定時提示明確訊息"""
    val = os.getenv(key, "")
    if not val or val.startswith("填入"):
        # 啟動時由 main.py 的 check_environment() 統一處理
        return f"MISSING_{key}"
    return val


# ==============================
# Telegram 設定（從 .env 讀取）
# ==============================
TELEGRAM_BOT_TOKEN   = _require("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID  = os.getenv("TELEGRAM_CHANNEL_ID", "@taiwandefence")

# ==============================
# API Keys（從 .env 讀取）
# ==============================
AISSTREAM_API_KEY        = os.getenv("AISSTREAM_API_KEY", "")
GEMINI_API_KEY           = os.getenv("GEMINI_API_KEY", "")
COPERNICUS_CLIENT_ID     = os.getenv("COPERNICUS_CLIENT_ID", "")
COPERNICUS_CLIENT_SECRET = os.getenv("COPERNICUS_CLIENT_SECRET", "")
GOOGLE_MAPS_API_KEY      = os.getenv("GOOGLE_MAPS_API_KEY", "")

# ==============================
# Ollama 本地AI設定
# ==============================
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "gemma3:27b")

# ==============================
# 資料庫設定
# ==============================
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "defense.db")

# ==============================
# 多語言（保留設定，未來擴充）
# ==============================
SUPPORTED_LANGUAGES = ["zh", "en"]
DEFAULT_LANGUAGE    = "zh"

# ==============================
# 爬蟲設定
# ==============================
SCRAPER_INTERVAL_MINUTES     = 30   # 一般爬蟲間隔（分鐘）
ALERT_CHECK_INTERVAL_MINUTES = 5    # 即時警報檢查間隔（分鐘）
DAILY_REPORT_HOUR            = 20   # 每日報告推送時間（24小時制）
DAILY_REPORT_MINUTE          = 0

REQUEST_TIMEOUT = 15
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# ==============================
# 資料來源 URL
# ==============================
SOURCES = {
    "mnd_news":   "https://www.mnd.gov.tw/news/pressreleaselist",
    "mnd_rss":    "https://www.mnd.gov.tw/RssNews.aspx",
    "cga_news":   "https://www.cga.gov.tw/GipOpen/wSite/lp?ctNode=650&mp=999",
    "cna_rss":    "https://www.cna.com.tw/rss/aall.aspx",
    "ltn_defense":"https://news.ltn.com.tw/rss/politics.xml",
    "rti_rss":    "https://www.rti.org.tw/ajax/news/category/6/json",
}

# ==============================
# 威脅評分閾值
# ==============================
THREAT_ALERT_THRESHOLD = 7   # 觸發即時警報
THREAT_WARN_THRESHOLD  = 4   # 警示標記

# ==============================
# 關鍵字設定
# ==============================
MILITARY_KEYWORDS = [
    "共機", "共艦", "解放軍", "殲-", "運-", "轟-", "空母",
    "擾臺", "ADIZ", "防空識別區", "越中線", "中線",
    "飛彈", "導彈", "軍演", "演習", "封鎖",
    "航母", "遼寧", "山東", "福建",
    "共軍", "北京", "習近平", "對台", "涉台",
    "軍機", "軍艦", "戰機", "偵察機", "無人機",
    "台海局勢", "兩岸緊張",
]

MARITIME_KEYWORDS = [
    "海巡", "海警", "船艦", "艦艇", "潛艦", "潛水艇",
    "領海", "專屬經濟區", "EEZ", "金門", "馬祖", "東沙", "太平島",
    "海底電纜", "斷纜", "通訊電纜",
]

CYBER_KEYWORDS = [
    "駭客", "網攻", "資安", "DDoS", "滲透", "情報",
    "間諜", "內應", "統戰", "認知作戰", "假訊息",
]

ALL_KEYWORDS = MILITARY_KEYWORDS + MARITIME_KEYWORDS + CYBER_KEYWORDS

# ==============================
# 地圖設定
# ==============================
MAP_CENTER      = [23.5, 121.0]
MAP_ZOOM        = 7
MAP_OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "data", "latest_map.html")

# ==============================
# Web Dashboard 設定
# ==============================
# /about 頁面的完整 URL（啟動後在 format_project_intro() 裡也需更新）
WEB_BASE_URL = os.getenv("WEB_BASE_URL", "http://127.0.0.1:5000")

# ==============================
# Log 設定
# ==============================
LOG_PATH  = os.path.join(os.path.dirname(__file__), "logs", "defense_bot.log")
LOG_LEVEL = "INFO"

# ==============================
# 白名單 / 管理員
# ==============================
USE_WHITELIST    = False
ALLOWED_USER_IDS = [6926003425]
ADMIN_USER_ID    = [6926003425]
