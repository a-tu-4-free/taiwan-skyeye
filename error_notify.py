# 檔案名稱：bot/error_notify.py
# 功能說明：系統錯誤通知，排程失敗時私訊管理員

from datetime import datetime
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import TELEGRAM_BOT_TOKEN, ADMIN_USER_ID


async def notify_admin(message: str):
    """私訊管理員（ADMIN_USER_ID 為 list，逐一發送）"""
    from telegram import Bot
    admins = ADMIN_USER_ID if isinstance(ADMIN_USER_ID, (list, tuple)) else [ADMIN_USER_ID]
    now    = datetime.now().strftime('%H:%M:%S')
    try:
        async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
            for uid in admins:
                await bot.send_message(
                    chat_id=uid,
                    text=f"⚠️ <b>SkyEye 系統通知</b>\n<code>{now}</code>\n\n{message}",
                    parse_mode="HTML"
                )
    except Exception as e:
        print(f"[ERROR NOTIFY] 無法發送通知：{e}")
