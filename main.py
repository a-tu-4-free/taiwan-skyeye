# 檔案名稱：main.py
# 功能說明：主程式入口，初始化資料庫、啟動排程器、啟動 Telegram Bot，整合所有模組統一運行

import asyncio
import os
import socket
# feedparser.parse(url) / urllib 沒有 timeout 參數，網路卡住會讓排程永遠掛住
# （log 中「海底電纜監控 / 完整爬蟲 skipped: maximum number of running instances」即此原因）
socket.setdefaulttimeout(30)
os.makedirs(os.path.join(os.path.dirname(__file__), "logs"), exist_ok=True)
os.makedirs(os.path.join(os.path.dirname(__file__), "data"), exist_ok=True)
import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

# ==============================
# Log 設定（加 Rotation 避免爆硬碟）
# ==============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            os.path.join(os.path.dirname(__file__), "logs", "defense_bot.log"),
            maxBytes=10 * 1024 * 1024,  # 單檔最大 10MB
            backupCount=3,
            encoding="utf-8"
        )
    ]
)
logger = logging.getLogger("main")

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)


def banner():
    print("""
╔══════════════════════════════════════════════════╗
║         Taiwan Defense Bot  🛡️                   ║
║         台灣國防情勢監控系統                     ║
║         v2.0  |  民間開源  |  本地AI驅動         ║
╚══════════════════════════════════════════════════╝
""")


def print_system_info():
    """印出系統資訊、資料來源、分析模組說明"""
    print("=" * 55)
    print("📡  資料來源")
    print("=" * 55)
    sources = [
        ("國防部新聞稿",     "https://www.mnd.gov.tw",          "30分鐘",   "共機共艦擾台深度解析"),
        ("海巡署新聞稿",     "https://www.cga.gov.tw",          "30分鐘",   "海警動態/電纜事件"),
        ("自由時報/自由亞洲", "https://news.ltn.com.tw",        "30分鐘",   "台海相關國際新聞"),
        ("PTT軍武/Military", "https://www.ptt.cc",              "30分鐘",   "即時軍事討論"),
        ("國台辦",           "http://www.gwytb.gov.tw",         "60分鐘",   "對台措辭（台灣DNS封鎖）"),
        ("USNI/WarZone/BBC", "https://usni.org",                "30分鐘",   "國際軍事媒體"),
        ("AIS船隻追蹤",      "https://aisstream.io",            "2小時",    "台灣周邊可疑船隻"),
        ("ADS-B軍機追蹤",    "https://opensky-network.org",     "30分鐘",   "台海周邊軍機動態"),
        ("中共官媒",         "新華社/人民日報/環球時報",          "2小時",    "對台措辭升溫偵測"),
        ("MODA海底電纜",     "https://www.moda.gov.tw",         "4小時",    "台灣海底電纜狀態"),
        ("Google Maps衛星",  "https://maps.googleapis.com",     "每日08:05","重點軍事基地影像"),
        ("Our World in Data","https://ourworldindata.org",      "每月",     "中國石油消耗指標"),
    ]
    for name, url, interval, note in sources:
        print(f"  {'✅'} {name:<18} [{interval:<8}] {note}")

    print()
    print("=" * 55)
    print("🤖  分析模組")
    print("=" * 55)
    modules = [
        ("威脅評分",     "analyzer/threat_score.py",    "每日19:00", "軍事/海事/資安三維評分(0-10)"),
        ("異常偵測",     "analyzer/anomaly_detector.py","每5分鐘",   "8種異常類型自動偵測"),
        ("Ollama AI",   "analyzer/ollama_client.py",   "每60分鐘",  "本地LLM新聞摘要與研判"),
        ("Gemini AI",   "adsb_monitor / china_media",  "備援",      "Ollama失敗時的備援分析"),
        ("趨勢圖表",    "analyzer/trend.py",           "每日推播",  "30日威脅趨勢/擾臺月統計/雷達圖"),
        ("態勢地圖",    "maps/map_generator.py",       "30分鐘",    "ADIZ/中線/電纜/軍機互動地圖"),
        ("擾臺解析",    "scrapers/mnd.py",             "即時",      "機型/數量/越中線/進入方向"),
        ("措辭分析",    "scrapers/china_media.py",     "每2小時",   "中共官媒L1/L2/L3升溫分類"),
        ("認知作戰",    "factcheck + narratives",      "每3小時",   "事實查核機構結果＋對台說法比對（不用AI）"),
    ]
    for name, module, timing, desc in modules:
        print(f"  🔧 {name:<12} {timing:<12} {desc}")

    print()
    print("=" * 55)
    print("📲  推播設定")
    print("=" * 55)
    pushes = [
        ("每日08:00",   "晨間概況",  "台海概況+活躍異常+衛星影像"),
        ("每日20:00",   "情勢日報",  "威脅指數+AI研判+擾臺統計+重點新聞"),
        ("每週日21:00", "週報",      "本週統計+趨勢分析+AI週報"),
        ("即時",        "高威脅警報","威脅指數≥7自動推送"),
        ("即時",        "異常警報",  "偵測到異常時推送（含說明）"),
        ("即時",        "電纜警報",  "電纜障礙/中斷24小時冷卻推送"),
        ("即時",        "軍機警報",  "ADS-B偵測到中共/美軍軍機"),
    ]
    for timing, name, desc in pushes:
        print(f"  📣 [{timing:<10}] {name:<8} {desc}")

    print("=" * 55)
    print()


def check_environment():
    """環境檢查（從 .env 讀取，確認必填項目已設定）"""
    issues = []
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
    if not TELEGRAM_BOT_TOKEN or "MISSING" in TELEGRAM_BOT_TOKEN:
        issues.append("❌ 請在 .env 設定 TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHANNEL_ID or "MISSING" in TELEGRAM_CHANNEL_ID:
        issues.append("❌ 請在 .env 設定 TELEGRAM_CHANNEL_ID")

    if issues:
        print("\n⚠️  環境設定不完整：")
        for issue in issues:
            print(f"   {issue}")
        print("\n請在 .env 填入設定後重新啟動（參考 .env.example）\n")
        return False
    return True


def init_system():
    """初始化系統"""
    print("🔧 初始化系統...")

    for d in ["data", "logs", "data/satellite"]:
        os.makedirs(os.path.join(os.path.dirname(__file__), d), exist_ok=True)

    from database.models import init_db
    init_db()
    print("✅ 資料庫初始化完成")

    for pkg in ["scrapers", "database", "analyzer", "bot", "maps"]:
        init_file = os.path.join(os.path.dirname(__file__), pkg, "__init__.py")
        if not os.path.exists(init_file):
            open(init_file, "w").close()

    from analyzer.ollama_client import check_ollama_available
    if check_ollama_available():
        from config import OLLAMA_MODEL
        print(f"✅ Ollama 連線正常，模型：{OLLAMA_MODEL}")
    else:
        print(f"⚠️  Ollama 未啟動，AI分析功能將停用")

    print("✅ 系統初始化完成\n")


def main():
    """主程式"""
    banner()

    if not check_environment():
        sys.exit(1)

    init_system()
    print_system_info()

    from telegram.ext import Application
    from bot.telegram_bot import build_app
    from scheduler import build_scheduler, print_schedule
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
    from telegram.constants import ParseMode

    app = build_app()

    bot_post_init = app.post_init        # build_app() 設定的 set_my_commands，避免被覆蓋

    async def post_init(application):
        bot = application.bot
        if bot_post_init:
            try:
                await bot_post_init(application)
            except Exception as e:
                print(f"⚠️  指令選單設定失敗（非致命）：{e}")

        me = await bot.get_me()
        print(f"✅ Telegram Bot 連線：@{me.username}\n")

        # 啟動爬蟲
        print("🔍 啟動時執行初始爬蟲...")
        try:
            from scrapers.mnd import run as mnd_run
            from scrapers.cga import run as cga_run
            from scrapers.news import run as news_run
            await asyncio.to_thread(mnd_run)
            await asyncio.to_thread(cga_run)
            await asyncio.to_thread(news_run)
            print("✅ 初始爬蟲完成\n")
        except Exception as e:
            print(f"⚠️  初始爬蟲失敗（非致命）：{e}\n")

        # 啟動排程器
        scheduler = build_scheduler(bot)
        scheduler.start()
        print_schedule(scheduler)
        application.bot_data["scheduler"] = scheduler

        # 推送啟動通知
        try:
            from bot.formatter import format_startup_message
            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=format_startup_message(),
                parse_mode=ParseMode.HTML
            )
            print("✅ 啟動通知已推送至頻道")
        except Exception as e:
            print(f"⚠️  啟動通知推送失敗：{e}")

    async def post_stop(application):
        scheduler = application.bot_data.get("scheduler")
        if scheduler:
            scheduler.shutdown(wait=False)

    app.post_init = post_init
    app.post_stop = post_stop
    
    import threading
    from web.dashboard import run_dashboard
    web_thread = threading.Thread(
        target=run_dashboard,
        kwargs={"host": "127.0.0.1", "port": 5000},
        daemon=True
    )
    web_thread.start()

    print("\n" + "=" * 55)
    print("🟢 SkyEye 運行中")
    print("✅ Web Dashboard 啟動：http://127.0.0.1:5000")
    print(f"   時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("   按 Ctrl+C 停止")
    print("=" * 55 + "\n")

    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 SkyEye 已停止")