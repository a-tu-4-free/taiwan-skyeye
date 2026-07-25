# 檔案名稱：bot/error_notify.py
# 功能說明：系統錯誤通知，排程或爬蟲失敗時私訊管理員

import asyncio
import traceback
from datetime import datetime
from functools import wraps
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import TELEGRAM_BOT_TOKEN, ADMIN_USER_ID


async def notify_admin(message: str):
    """私訊管理員"""
    try:
        from telegram import Bot
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        now = datetime.now().strftime('%H:%M:%S')
        await bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=f"⚠️ <b>TDB 系統通知</b>\n<code>{now}</code>\n\n{message}",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"[ERROR NOTIFY] 無法發送通知：{e}")


def safe_task(task_name: str):
    """
    排程任務的安全包裝器
    捕獲例外並通知管理員
    
    用法：
    @safe_task("PTT即時監控")
    async def task_ptt_realtime():
        ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                error_msg = (
                    f"🔴 <b>任務失敗：{task_name}</b>\n"
                    f"錯誤：<code>{str(e)[:200]}</code>\n"
                    f"時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                print(f"[ERROR] {task_name}: {e}")
                # 非同步發送通知
                asyncio.create_task(notify_admin(error_msg))
        return wrapper
    return decorator


async def notify_scraper_error(scraper_name: str, error: Exception):
    """爬蟲錯誤通知"""
    msg = (
        f"🔴 <b>爬蟲失敗：{scraper_name}</b>\n"
        f"錯誤：<code>{str(error)[:200]}</code>\n"
        f"時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await notify_admin(msg)


async def notify_startup(success: bool, details: str = ""):
    """系統啟動通知（私訊管理員，不推頻道）"""
    if success:
        msg = (
            f"✅ <b>TDB 系統啟動成功</b>\n"
            f"時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"{details}"
        )
    else:
        msg = (
            f"❌ <b>TDB 系統啟動失敗</b>\n"
            f"時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"錯誤：{details}"
        )
    await notify_admin(msg)


async def notify_daily_summary(stats: dict):
    """每日系統運行摘要（私訊管理員）"""
    msg = (
        f"📊 <b>TDB 每日系統摘要</b>\n"
        f"{'─'*28}\n"
        f"新聞總筆數：{stats.get('total_news', 0)}\n"
        f"擾臺事件：{stats.get('intrusions', 0)}\n"
        f"警報推送：{stats.get('alerts_sent', 0)}\n"
        f"爬蟲錯誤：{stats.get('scraper_errors', 0)}\n"
        f"AI評分完成：{stats.get('ai_scored', 0)}\n"
        f"{'─'*28}\n"
        f"威脅指數：{stats.get('threat_score', 0):.1f}/10"
    )
    await notify_admin(msg)