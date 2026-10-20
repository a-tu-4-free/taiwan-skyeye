# 檔案名稱：bot/telegram_bot.py
# 功能說明：Telegram Bot 主體
# 指令只做輕量查詢（讀資料庫/快取）；完整日報、週報、地圖由排程推送到頻道

import asyncio
import os
import sys
from datetime import datetime, timedelta
from functools import wraps

from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID,
    USE_WHITELIST, ALLOWED_USER_IDS
)
from database.db import (
    get_recent_news, get_intrusion_stats,
    get_all_cable_status, get_recent_scores,
)
from analyzer.threat_score import run_daily_scoring, get_threat_level_emoji
from analyzer.trend import run_all_charts
from analyzer.ollama_client import generate_daily_report, check_ollama_available
from bot.formatter import (
    format_daily_report, format_threat_card,
    format_cable_status, format_vessel_alert,
    format_anomaly_summary, format_project_intro,
)
from bot.i18n import get_user_lang, set_user_lang


# ==============================
# 白名單裝飾器
# ==============================

def restricted(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not USE_WHITELIST:
            return await func(update, context)
        if update.effective_user.id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ 此功能僅限授權用戶使用")
            return
        return await func(update, context)
    return wrapper


# ==============================
# 指令處理器
# ==============================


def _lang(update) -> str:
    """取得用戶語言設定"""
    try:
        from bot.i18n import get_user_lang
        return get_user_lang(update.effective_user.id)
    except Exception:
        return "zh-TW"


def _rt(update, zh_tw: str, zh_cn: str = "", en: str = "") -> str:
    """依語言回傳對應字串"""
    lang = _lang(update)
    if lang == "en" and en:
        return en
    if lang == "zh-CN" and zh_cn:
        return zh_cn
    return zh_tw


@restricted
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start：歡迎訊息＋專案介紹（給新訂閱者）"""
    msg = format_project_intro()
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


@restricted
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    if lang == "en":
        msg = (
            f"🛡️ <b>SkyEye Commands</b>\n"
            f"{'─' * 28}\n"
            f"/summary   — Quick summary\n"
            f"/status    — Threat index + active anomalies\n"
            f"/anomaly   — Anomaly history\n"
            f"/history   — Threat index history\n"
            f"/cable     — Submarine cable status\n"
            f"/vessel    — Suspicious vessels (24h)\n"
            f"/satellite — Today's satellite image\n"
            f"/lang      — Switch language\n"
            f"{'─' * 28}\n"
            f"<i>Full reports are pushed to the channel: 08:00 brief | 20:00 daily | Sun 21:00 weekly</i>"
        )
    elif lang == "zh-CN":
        msg = (
            f"🛡️ <b>SkyEye 指令说明</b>\n"
            f"{'─' * 28}\n"
            f"/summary   — 快速摘要\n"
            f"/status    — 威胁指数 + 活跃异常\n"
            f"/anomaly   — 异常侦测历史\n"
            f"/history   — 威胁指数历史\n"
            f"/cable     — 海底电缆状态\n"
            f"/vessel    — 可疑船只（24小时）\n"
            f"/satellite — 今日卫星影像\n"
            f"/lang      — 切换语言\n"
            f"{'─' * 28}\n"
            f"<i>完整报告由频道自动推送：08:00 晨报 ｜ 20:00 日报 ｜ 周日 21:00 周报</i>"
        )
    else:
        msg = (
            f"🛡️ <b>SkyEye 指令說明</b>\n"
            f"{'─' * 28}\n"
            f"/summary   — 快速摘要\n"
            f"/status    — 威脅指數 + 活躍異常\n"
            f"/anomaly   — 異常偵測歷史\n"
            f"/history   — 威脅指數歷史\n"
            f"/cable     — 海底電纜狀態\n"
            f"/vessel    — 可疑船隻（24小時）\n"
            f"/satellite — 今日衛星影像\n"
            f"/lang      — 切換語言\n"
            f"{'─' * 28}\n"
            f"<i>完整報告由頻道自動推送：08:00 晨報 ｜ 20:00 日報 ｜ 週日 21:00 週報</i>"
        )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


@restricted
async def cmd_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args    = context.args
    if args and args[0] in ("en", "zh"):
        set_user_lang(user_id, args[0])
        msg = "✅ Language set to English" if args[0] == "en" else "✅ 語言已切換為繁體中文"
    else:
        current = get_user_lang(user_id)
        msg = f"目前語言：<code>{current}</code>\n切換：/lang zh 或 /lang en"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


@restricted
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status — 威脅指數 + 活躍異常摘要"""
    await update.message.reply_text(_rt(update, "⏳ 計算中...", "⏳ 计算中...", "⏳ Calculating..."))

    scores = get_recent_scores(days=7)
    if not scores:
        await update.message.reply_text(_rt(update,
            "📭 尚無足夠資料，請等待首次日報生成。",
            "📭 尚无足够资料，请等待首次日报生成。",
            "📭 No data yet. Please wait for the first daily report."))
        return

    from analyzer.threat_score import calculate_trend
    latest = scores[-1]
    trend  = calculate_trend(scores)

    threat_data = {
        "overall":    latest.overall_score,
        "military":   latest.military_score,
        "maritime":   latest.maritime_score,
        "cyber":      latest.cyber_score,
        "trend":      trend,
        "news_count": latest.news_count,
    }

    # 威脅指數卡片
    card_msg = format_threat_card(threat_data)

    # 活躍異常摘要（新增）
    try:
        from analyzer.anomaly_detector import get_current_anomaly_summary
        anomaly_summary = get_current_anomaly_summary()
        anomaly_msg     = format_anomaly_summary(anomaly_summary)
        full_msg        = card_msg + "\n\n" + anomaly_msg
    except Exception:
        full_msg = card_msg

    await update.message.reply_text(full_msg, parse_mode=ParseMode.HTML)


@restricted
async def cmd_anomaly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/anomaly [天數] — 異常偵測歷史，預設顯示今日活躍 + 近7天紀錄"""
    args = context.args
    days = 7
    if args:
        try:
            days = max(1, min(int(args[0]), 30))
        except ValueError:
            pass

    try:
        from analyzer.anomaly_detector import get_current_anomaly_summary
        from database.db import get_anomaly_history
        from bot.formatter import format_anomaly_summary

        # 活躍異常
        active_msg = format_anomaly_summary(get_current_anomaly_summary())

        # 歷史紀錄
        history = get_anomaly_history(days=days)
        if not history:
            history_msg = f"<i>近 {days} 天無異常紀錄</i>"
        else:
            sev_icon = {"LOW": "⚪", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}
            lines = [f"\n📋 <b>近 {days} 天異常歷史（{len(history)} 筆）</b>"]
            for a in history[:15]:
                icon     = sev_icon.get(a.severity, "⚪")
                detected = a.detected_at.strftime("%m/%d %H:%M")
                status   = "已解除" if a.resolved_at else "持續中"
                lines.append(
                    f"{icon} <code>{detected}</code> {a.anomaly_type}\n"
                    f"   <i>{a.description[:50]}…</i>  [{status}]"
                )
            history_msg = "\n".join(lines)

        full_msg = active_msg + "\n" + history_msg
        await update.message.reply_text(full_msg, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"❌ 查詢異常失敗：{e}")


@restricted
async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /summary — 快速摘要
    只讀資料庫既有的評分（不重算），避免使用者指令覆寫排程算好的當日評分與 AI 研判
    """
    scores             = get_recent_scores(days=7)
    intrusion_stats, _ = get_intrusion_stats(days=1)
    recent_news        = get_recent_news(hours=24)

    from analyzer.threat_score import calculate_trend
    overall  = scores[-1].overall_score if scores else 0
    emoji    = get_threat_level_emoji(overall)
    trend    = calculate_trend(scores) if scores else "→ 持平"
    aircraft = intrusion_stats.get("total_aircraft", 0)
    now_str  = datetime.now().strftime("%m/%d %H:%M")

    top       = sorted(recent_news, key=lambda n: n.threat_score or 0, reverse=True)
    top_title = (top[0].title or "")[:45] if top else "無"

    if intrusion_stats.get("median_line_crossings", 0) > 0:
        sea_line = "⚠️ 共軍今日越海峽中線"
    elif aircraft > 0:
        sea_line = f"共機 {aircraft} 架次擾臺"
    else:
        sea_line = "✅ 台海今日平靜"

    try:
        from analyzer.anomaly_detector import get_current_anomaly_summary
        anomaly = get_current_anomaly_summary()
        anomaly_line = (
            f"⚠️ 活躍異常 <b>{anomaly['count']}</b> 個（最高：{anomaly['max_severity']}）"
            if anomaly["count"] > 0 else "✅ 目前無異常"
        )
    except Exception:
        anomaly_line = ""

    msg = (
        f"⚡ <b>SkyEye 快速摘要</b>  <code>{now_str}</code>\n"
        f"{'─' * 28}\n\n"
        f"{emoji} 威脅指數 <b>{overall:.1f}/10</b>  {trend}\n\n"
        f"🌊 台海：{sea_line}\n"
        f"📰 監測：{len(recent_news)} 則新聞\n"
        f"🔥 最高：{top_title}\n"
    )
    if anomaly_line:
        msg += f"{anomaly_line}\n"
    msg += f"\n{'─' * 28}\n/status 威脅細項　/anomaly 異常詳情"

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


@restricted
async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/history [天數] — 歷史威脅趨勢，預設 7 天"""
    args = context.args
    days = 7
    if args:
        try:
            days = max(1, min(int(args[0]), 30))
        except ValueError:
            pass

    scores = get_recent_scores(days=days)
    if not scores:
        await update.message.reply_text("📭 尚無歷史資料")
        return

    now_str = datetime.now().strftime("%m/%d %H:%M")
    lines   = [
        f"📈 <b>威脅指數歷史記錄</b>",
        f"過去 {days} 天（共 {len(scores)} 筆）  <code>{now_str}</code>",
        "─" * 28,
        "",
    ]

    for s in scores:
        date_str = s.date.strftime("%m/%d")
        emoji    = get_threat_level_emoji(s.overall_score)
        bar      = "█" * int(s.overall_score) + "░" * (10 - int(s.overall_score))
        lines += [
            f"{emoji} <b>{date_str}</b>  <code>{s.overall_score:.1f}/10</code>",
            f"   <code>{bar}</code>",
            f"   軍{s.military_score:.1f} 海{s.maritime_score:.1f} 資{s.cyber_score:.1f}",
            "",
        ]

    avg      = sum(s.overall_score for s in scores) / len(scores)
    peak     = max(scores, key=lambda s: s.overall_score)
    lines += [
        "─" * 28,
        f"平均：<code>{avg:.1f}/10</code>",
        f"最高：<code>{peak.overall_score:.1f}/10</code>（{peak.date.strftime('%m/%d')}）",
        f"更新：{now_str}",
    ]

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def _send_long_message(update: Update, text: str, chunk_size: int = 4000):
    """自動切割超長訊息，按行分段發送，避免 HTML tag 被截斷"""
    lines = text.split("\n")
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > chunk_size:
            if chunk.strip():
                await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)
            chunk = line + "\n"
        else:
            chunk += line + "\n"
    if chunk.strip():
        await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)


@restricted
async def cmd_cable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cable — 海底電纜狀態（已去重，只顯示每條電纜最新一筆）"""
    await update.message.reply_text(_rt(update, "⏳ 查詢電纜狀態...", "⏳ 查询电缆状态...", "⏳ Checking cable status..."))
    try:
        cables = get_all_cable_status()
        msg    = format_cable_status(cables)
        await _send_long_message(update, msg)
    except Exception as e:
        await update.message.reply_text(f"❌ 查詢失敗：{e}")


@restricted
async def cmd_satellite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/satellite — 今日衛星影像（只讀快取，不會額外呼叫 Google Maps API）"""
    import glob
    from scrapers.satellite import CACHE_DIR
    today = datetime.now().strftime('%Y%m%d')
    files = sorted(glob.glob(os.path.join(CACHE_DIR, f"*_{today}.png")))

    if not files:
        await update.message.reply_text(
            _rt(update,
                "📡 今日衛星影像尚未取得（每日 08:05 自動更新）",
                "📡 今日卫星影像尚未取得（每日 08:05 自动更新）",
                "📡 No satellite imagery yet today (auto-updated daily at 08:05)")
        )
        return

    for img_path in files:
        area_name = os.path.basename(img_path).rsplit("_", 1)[0]
        caption = (
            f"🛰️ <b>衛星影像：{area_name}</b>\n"
            f"{'─' * 28}\n"
            f"來源：Google Maps Static API\n"
            f"時間：{datetime.now().strftime('%Y-%m-%d')}\n"
            f"<i>（商業衛星圖，解析度有限，僅供參考）</i>"
        )
        with open(img_path, "rb") as f:
            await update.message.reply_photo(photo=f, caption=caption, parse_mode=ParseMode.HTML)


@restricted
async def cmd_vessel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/vessel — 可疑船隻清單"""
    from database.models import VesselTracking
    from database.db import get_session
    from sqlalchemy import desc
    session = get_session()
    try:
        cutoff  = datetime.now() - timedelta(hours=24)
        vessels = session.query(VesselTracking).filter(
            VesselTracking.is_suspicious == True,
            VesselTracking.recorded_at   >= cutoff
        ).order_by(desc(VesselTracking.recorded_at)).limit(10).all()

        vessel_list = [{
            "name": v.vessel_name, "flag": v.flag,
            "type": v.vessel_type, "reason": v.suspicion_reason,
            "lat":  v.latitude,   "lon":    v.longitude,
        } for v in vessels]

        msg = format_vessel_alert(vessel_list) or "✅ 近24小時無可疑船隻紀錄"
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    finally:
        session.close()


# ==============================
# 主動推送函式
# ==============================

async def push_daily_report(bot: Bot):
    """每日自動推送報告到頻道"""
    print("[BOT] 推送每日報告...")
    try:
        threat_data        = run_daily_scoring()
        intrusion_stats, _ = get_intrusion_stats(days=1)
        recent_news        = get_recent_news(hours=24)

        from database.db import get_cog_war_news
        threat_data["cog_war_news"]       = get_cog_war_news(hours=24)

        top_news = sorted(
            [{
                "title":   n.title,    "score":   n.threat_score or 0,
                "url":     n.url or "", "source": n.source or "",
                "summary": n.ai_summary or "",
                "content": (n.content or "")[:100],
            } for n in recent_news],
            key=lambda x: x["score"], reverse=True
        )[:5]

        ai_analysis = ""
        if check_ollama_available():
            ai_analysis = await asyncio.to_thread(
                generate_daily_report,
                news_summaries=top_news,
                intrusion_stats=intrusion_stats,
                threat_scores={
                    "military": threat_data["military"],
                    "maritime": threat_data["maritime"],
                    "cyber":    threat_data["cyber"],
                },
                date=datetime.now()
            )

        msg = format_daily_report(threat_data, ai_analysis, top_news, intrusion_stats)
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=msg,
            parse_mode=ParseMode.HTML       # 改用 HTML
        )

        # 推送威脅指數卡片圖
        try:
            from bot.card_generator import make_threat_card
            card_path = make_threat_card({
                "overall":       threat_data.get("overall", 0),
                "military":      threat_data.get("military", 0),
                "maritime":      threat_data.get("maritime", 0),
                "cyber":         threat_data.get("cyber", 0),
                "trend":         threat_data.get("trend", "→ 持平"),
                "anomaly_count": threat_data.get("anomaly_count", 0),
            })
            if card_path and os.path.exists(card_path):
                with open(card_path, "rb") as f:
                    await bot.send_photo(
                        chat_id=TELEGRAM_CHANNEL_ID,
                        photo=f,
                        caption=f"📊 今日威脅指數  {datetime.now().strftime('%Y-%m-%d')}"
                    )
                os.remove(card_path)
        except Exception as e:
            print(f"[BOT] 威脅卡片推送失敗（非致命）：{e}")

        # 推送雷達圖
        try:
            charts = run_all_charts(
                threat_data["military"],
                threat_data["maritime"],
                threat_data["cyber"]
            )
            if charts.get("radar") and os.path.exists(charts["radar"]):
                with open(charts["radar"], "rb") as f:
                    await bot.send_photo(
                        chat_id=TELEGRAM_CHANNEL_ID,
                        photo=f,
                        caption=f"📈 今日威脅雷達圖  {datetime.now().strftime('%Y-%m-%d')}"
                    )
        except Exception as e:
            print(f"[BOT] 雷達圖推送失敗（非致命）：{e}")

        print("[BOT] 每日報告推送完成")
    except Exception as e:
        print(f"[BOT ERROR] push_daily_report: {e}")


# ==============================
# Bot 啟動
# ==============================

async def _on_error(update, context: ContextTypes.DEFAULT_TYPE):
    """
    全域錯誤處理：網路斷線（getaddrinfo / ConnectError）只印一行，
    不再讓 PTB 每次把整段 traceback 寫進 log
    """
    from telegram.error import NetworkError, TimedOut
    err = context.error
    if isinstance(err, (NetworkError, TimedOut)):
        print(f"[BOT] 網路錯誤（自動重試）：{str(err)[:80]}")
        return
    import logging
    logging.getLogger("bot").error("未處理例外", exc_info=err)


def build_app():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("lang",      cmd_lang))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("anomaly",   cmd_anomaly))   # 新增
    app.add_handler(CommandHandler("summary",   cmd_summary))
    app.add_handler(CommandHandler("history",   cmd_history))
    app.add_handler(CommandHandler("cable",     cmd_cable))
    app.add_handler(CommandHandler("vessel",    cmd_vessel))
    app.add_handler(CommandHandler("satellite", cmd_satellite))
    app.add_error_handler(_on_error)

    async def post_init(application):
        await application.bot.set_my_commands([
            ("summary",   "⚡ 今日快速摘要"),
            ("status",    "📊 威脅指數 + 活躍異常"),
            ("anomaly",   "⚠️ 異常偵測歷史"),
            ("history",   "📈 歷史威脅趨勢"),
            ("satellite", "🛰️ 衛星影像"),
            ("cable",     "🔌 海底電纜狀態"),
            ("vessel",    "🚢 可疑船隻"),
            ("lang",      "🌐 切換語言"),
            ("help",      "❓ 指令說明"),
        ])

    app.post_init = post_init
    return app


if __name__ == "__main__":
    print("[BOT] 啟動 Telegram Bot...")
    app = build_app()
    app.run_polling(allowed_updates=["message", "callback_query"])