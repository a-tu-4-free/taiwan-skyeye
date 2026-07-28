# 檔案名稱：bot/telegram_bot.py
# 功能說明：Telegram Bot 主體
# 全面改用 parse_mode=HTML，新增 /anomaly /status 整合異常顯示

import asyncio
import os
import sys
from datetime import datetime, timedelta
from functools import wraps

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID,
    THREAT_ALERT_THRESHOLD, USE_WHITELIST, ALLOWED_USER_IDS
)
from database.db import (
    get_recent_news, get_intrusion_stats,
    get_all_cable_status, get_recent_scores,
    get_unalerted_high_threat_news, mark_news_alerted
)
from analyzer.threat_score import run_daily_scoring, get_threat_level_emoji
from analyzer.trend import run_all_charts
from analyzer.ollama_client import (
    generate_daily_report, generate_alert_message,
    generate_weekly_report, check_ollama_available
)
from bot.formatter import (
    format_daily_report, format_alert_message,
    format_weekly_report, format_threat_card,
    format_cable_status, format_vessel_alert,
    format_startup_message, format_anomaly_summary,
    format_project_intro,
)
from bot.i18n import get_user_lang, set_user_lang, t
from maps.map_generator import generate_defense_map


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
            f"/status    — Threat index + active anomalies\n"
            f"/today     — Full daily situation report\n"
            f"/summary   — 3-sentence quick summary\n"
            f"/anomaly   — Anomaly detection history\n"
            f"/map       — Situation map (HTML)\n"
            f"/trend     — 30-day threat trend chart\n"
            f"/cable     — Submarine cable status\n"
            f"/vessel    — Suspicious vessel list\n"
            f"/satellite — Satellite imagery\n"
            f"/history   — Historical threat trend\n"
            f"/weekly    — Weekly report\n"
            f"/refresh   — Manual data refresh\n"
            f"/lang      — Switch language (zh-TW / zh-CN / en)\n"
            f"{'─' * 28}\n"
            f"<i>Auto push: 20:00 daily report | Sun 21:00 weekly | Real-time alerts</i>"
        )
    elif lang == "zh-CN":
        msg = (
            f"🛡️ <b>SkyEye 指令说明</b>\n"
            f"{'─' * 28}\n"
            f"/status    — 威胁指数 + 活跃异常\n"
            f"/today     — 今日完整态势报告\n"
            f"/summary   — 三句话快速摘要\n"
            f"/anomaly   — 异常侦测历史\n"
            f"/map       — 态势地图（HTML）\n"
            f"/trend     — 30日威胁趋势图\n"
            f"/cable     — 海底电缆状态\n"
            f"/vessel    — 可疑船只清单\n"
            f"/satellite — 卫星影像\n"
            f"/history   — 历史威胁趋势\n"
            f"/weekly    — 本周周报\n"
            f"/refresh   — 手动触发资料更新\n"
            f"/lang      — 切换语言 (zh-TW / zh-CN / en)\n"
            f"{'─' * 28}\n"
            f"<i>自动推送：20:00 日报 ｜ 周日 21:00 周报 ｜ 即时异常警报</i>"
        )
    else:
        msg = (
            f"🛡️ <b>SkyEye 指令說明</b>\n"
            f"{'─' * 28}\n"
            f"/status    — 威脅指數 + 活躍異常\n"
            f"/today     — 今日完整情勢報告\n"
            f"/summary   — 三句話快速摘要\n"
            f"/anomaly   — 異常偵測歷史\n"
            f"/map       — 態勢地圖（HTML）\n"
            f"/trend     — 30日威脅趨勢圖\n"
            f"/cable     — 海底電纜狀態\n"
            f"/vessel    — 可疑船隻清單\n"
            f"/satellite — 衛星影像\n"
            f"/history   — 歷史威脅趨勢\n"
            f"/weekly    — 本週週報\n"
            f"/refresh   — 手動觸發資料更新\n"
            f"/lang      — 切換語言 (zh-TW / zh-CN / en)\n"
            f"{'─' * 28}\n"
            f"<i>自動推送：20:00 日報 ｜ 週日 21:00 週報 ｜ 即時異常警報</i>"
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
async def cmd_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🛡️ 威脅快覽", callback_data="status"),
         InlineKeyboardButton("⚠️ 異常偵測", callback_data="anomaly")],
        [InlineKeyboardButton("📋 今日報告", callback_data="today"),
         InlineKeyboardButton("⚡ 快速摘要", callback_data="summary")],
        [InlineKeyboardButton("🗺️ 態勢地圖", callback_data="map"),
         InlineKeyboardButton("📈 趨勢圖",   callback_data="trend")],
        [InlineKeyboardButton("🔌 電纜狀態", callback_data="cable"),
         InlineKeyboardButton("🚢 可疑船隻", callback_data="vessel")],
        [InlineKeyboardButton("📅 本週週報", callback_data="weekly"),
         InlineKeyboardButton("🔄 手動更新", callback_data="refresh")],
    ]
    await update.message.reply_text(
        "🛡️ <b>SkyEye 控制面板</b>\n請選擇功能：",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


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
    """/summary — 三句話快速摘要"""
    threat_data        = run_daily_scoring()
    intrusion_stats, _ = get_intrusion_stats(days=1)
    recent_news        = get_recent_news(hours=24)

    overall  = threat_data.get("overall", 0)
    emoji    = get_threat_level_emoji(overall)
    trend    = threat_data.get("trend", "→ 持平")
    aircraft = intrusion_stats.get("total_aircraft", 0)
    now_str  = datetime.now().strftime("%m/%d %H:%M")

    top       = sorted(recent_news, key=lambda n: n.threat_score or 0, reverse=True)
    top_title = (top[0].title or "")[:45] if top else "無"

    if intrusion_stats.get("median_line_crossings", 0) > 0:
        sea_line = "⚠️ 共軍今日越越中線"
    elif aircraft > 0:
        sea_line = f"共機 {aircraft} 架次擾臺"
    else:
        sea_line = "✅ 台海今日平靜"

    # 活躍異常數量
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
        f"⚡ <b>TDB 快速摘要</b>  <code>{now_str}</code>\n"
        f"{'─' * 28}\n\n"
        f"{emoji} 威脅指數 <b>{overall:.1f}/10</b>  {trend}\n\n"
        f"🌊 台海：{sea_line}\n"
        f"📰 監測：{len(recent_news)} 則新聞\n"
        f"🔥 最高：{top_title}\n"
    )
    if anomaly_line:
        msg += f"{anomaly_line}\n"
    msg += f"\n{'─' * 28}\n/today 看完整報告　/anomaly 看異常詳情"

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


@restricted
async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/today — 今日完整報告"""
    await update.message.reply_text(_rt(update,
        "⏳ 生成今日報告中，請稍候...",
        "⏳ 生成今日报告中，请稍候...",
        "⏳ Generating today's report, please wait..."))

    threat_data        = run_daily_scoring()
    intrusion_stats, _ = get_intrusion_stats(days=1)
    recent_news        = get_recent_news(hours=24)

    from scrapers.satellite import get_latest_analysis
    from database.db import get_cog_war_news
    threat_data["satellite_analysis"] = get_latest_analysis()
    threat_data["cog_war_news"]       = get_cog_war_news(hours=24)

    top_news = sorted(
        [{
            "title":   n.title,   "score":   n.threat_score or 0,
            "url":     n.url or "", "source": n.source or "",
            "summary": n.ai_summary or "",
            "content": (n.content or "")[:100],
        } for n in recent_news],
        key=lambda x: x["score"], reverse=True
    )[:5]

    ai_analysis = ""
    if check_ollama_available():
        ai_analysis = generate_daily_report(
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
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


@restricted
async def cmd_map(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/map — 傳送態勢地圖（HTML 檔案）"""
    await update.message.reply_text(_rt(update, "⏳ 生成地圖中...", "⏳ 生成地图中...", "⏳ Generating map..."))
    try:
        map_path = generate_defense_map()
        with open(map_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=f"taiwan_defense_map_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                caption="🗺️ 台灣國防態勢地圖\n用瀏覽器開啟，可互動查看"
            )
    except Exception as e:
        await update.message.reply_text(f"❌ 地圖生成失敗：{e}")


@restricted
async def cmd_trend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/trend — 威脅趨勢圖表"""
    await update.message.reply_text(_rt(update, "⏳ 生成圖表中...", "⏳ 生成图表中...", "⏳ Generating chart..."))
    try:
        scores   = get_recent_scores(days=1)
        military = scores[-1].military_score if scores else 0
        maritime = scores[-1].maritime_score if scores else 0
        cyber    = scores[-1].cyber_score    if scores else 0
        charts   = run_all_charts(military, maritime, cyber)
        sent     = 0
        for name, path in charts.items():
            if path and os.path.exists(path):
                with open(path, "rb") as f:
                    await update.message.reply_photo(photo=f)
                sent += 1
        if sent == 0:
            await update.message.reply_text("📭 尚無圖表資料")
    except Exception as e:
        await update.message.reply_text(f"❌ 圖表生成失敗：{e}")


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
        cables = get_all_cable_status(days=90)
        msg    = format_cable_status(cables)
        await _send_long_message(update, msg)
    except Exception as e:
        await update.message.reply_text(f"❌ 查詢失敗：{e}")


@restricted
async def cmd_satellite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/satellite — 今日衛星分析"""
    from scrapers.satellite import get_latest_analysis
    results = get_latest_analysis()

    if not results:
        await update.message.reply_text(
            "📡 今日尚無衛星分析資料\n每日 08:00 自動分析，或等待 Gemini API 配額重置"
        )
        return

    lines = [f"📡 <b>今日衛星影像分析</b>", "─" * 28]
    for r in results:
        title   = r.get("title", "")[:45]
        content = r.get("content", "")[:300]
        lines += [f"\n🛰️ <b>{title}</b>", content]
    lines += ["─" * 28, f"更新：{datetime.now().strftime('%H:%M')}"]

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


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


@restricted
async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/weekly — 週報"""
    await update.message.reply_text(_rt(update, "⏳ 生成週報中...", "⏳ 生成周报中...", "⏳ Generating weekly report..."))

    stats, _   = get_intrusion_stats(days=7)
    scores     = get_recent_scores(days=7)
    avg_threat = (sum(s.overall_score for s in scores) / len(scores)) if scores else 0
    peak       = max(scores, key=lambda s: s.overall_score) if scores else None

    weekly_data = {
        "week_start":       (datetime.now() - timedelta(days=7)).strftime("%m/%d"),
        "week_end":         datetime.now().strftime("%m/%d"),
        "total_intrusions": stats.get("total_incidents", 0),
        "total_aircraft":   stats.get("total_aircraft", 0),
        "median_crossings": stats.get("median_line_crossings", 0),
        "avg_threat":       round(avg_threat, 2),
        "peak_day":         peak.date.strftime("%m/%d") if peak else "N/A",
        "peak_score":       peak.overall_score if peak else 0,
    }

    ai_weekly = generate_weekly_report(weekly_data) if check_ollama_available() else ""
    msg       = format_weekly_report(weekly_data, ai_weekly)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


@restricted
async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/refresh — 手動觸發資料更新"""
    await update.message.reply_text("⏳ 手動更新中，請稍候...")
    from scrapers.mnd import run as mnd_run
    from scrapers.cga import run as cga_run
    from scrapers.news import run as news_run

    mnd_count  = len(await asyncio.to_thread(mnd_run)  or [])
    cga_count  = len(await asyncio.to_thread(cga_run)  or [])
    news_count = len(await asyncio.to_thread(news_run) or [])

    msg = (
        f"✅ <b>更新完成</b>\n"
        f"國防部：{mnd_count} 筆\n"
        f"海巡署：{cga_count} 筆\n"
        f"新聞聚合：{news_count} 筆\n"
        f"時間：{datetime.now().strftime('%H:%M:%S')}"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


# ==============================
# Inline Keyboard 回呼
# ==============================

@restricted
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    action = query.data
    await query.edit_message_text("⏳ 處理中...")

    try:
        if action == "status":
            scores = get_recent_scores(days=7)
            if not scores:
                await query.edit_message_text("📭 尚無足夠資料")
                return
            from analyzer.threat_score import calculate_trend
            latest = scores[-1]
            card   = format_threat_card({
                "overall":    latest.overall_score,
                "military":   latest.military_score,
                "maritime":   latest.maritime_score,
                "cyber":      latest.cyber_score,
                "trend":      calculate_trend(scores),
                "news_count": latest.news_count,
            })
            try:
                from analyzer.anomaly_detector import get_current_anomaly_summary
                anomaly_msg = format_anomaly_summary(get_current_anomaly_summary())
                msg = card + "\n\n" + anomaly_msg
            except Exception:
                msg = card
            await query.edit_message_text(msg, parse_mode=ParseMode.HTML)

        elif action == "anomaly":
            from analyzer.anomaly_detector import get_current_anomaly_summary
            from database.db import get_anomaly_history
            active  = format_anomaly_summary(get_current_anomaly_summary())
            history = get_anomaly_history(days=3)
            sev_icon = {"LOW": "⚪", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}
            lines   = [active, "", f"<b>近3天紀錄（{len(history)}筆）</b>"]
            for a in history[:8]:
                icon = sev_icon.get(a.severity, "⚪")
                ts   = a.detected_at.strftime("%m/%d %H:%M")
                st   = "✅" if a.resolved_at else "🔴"
                lines.append(f"{icon} <code>{ts}</code> {st} {a.anomaly_type}")
            await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML)

        elif action == "summary":
            threat_data        = run_daily_scoring()
            intrusion_stats, _ = get_intrusion_stats(days=1)
            recent_news        = get_recent_news(hours=24)
            overall  = threat_data.get("overall", 0)
            emoji    = get_threat_level_emoji(overall)
            aircraft = intrusion_stats.get("total_aircraft", 0)
            top      = sorted(recent_news, key=lambda n: n.threat_score or 0, reverse=True)
            top_title = (top[0].title or "")[:45] if top else "無"
            sea_line  = (
                "⚠️ 共軍越中線" if intrusion_stats.get("median_line_crossings", 0) > 0
                else f"共機 {aircraft} 架次擾臺" if aircraft > 0
                else "✅ 台海平靜"
            )
            msg = (
                f"⚡ <b>快速摘要</b>\n{'─'*28}\n"
                f"{emoji} 威脅 <b>{overall:.1f}/10</b>\n"
                f"🌊 {sea_line}\n"
                f"📰 {len(recent_news)} 則新聞\n"
                f"🔥 {top_title}"
            )
            await query.edit_message_text(msg, parse_mode=ParseMode.HTML)

        elif action == "cable":
            cables = get_all_cable_status()
            msg    = format_cable_status(cables)
            await query.edit_message_text(msg, parse_mode=ParseMode.HTML)

        elif action == "vessel":
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
                await query.edit_message_text(msg, parse_mode=ParseMode.HTML)
            finally:
                session.close()

        elif action == "refresh":
            from scrapers.mnd import run as mnd_run
            from scrapers.cga import run as cga_run
            from scrapers.news import run as news_run
            mnd_count  = len(await asyncio.to_thread(mnd_run)  or [])
            cga_count  = len(await asyncio.to_thread(cga_run)  or [])
            news_count = len(await asyncio.to_thread(news_run) or [])
            msg = (
                f"✅ <b>更新完成</b>\n"
                f"國防部 {mnd_count} ｜ 海巡 {cga_count} ｜ 新聞 {news_count}"
            )
            await query.edit_message_text(msg, parse_mode=ParseMode.HTML)

        elif action in ("today", "weekly", "map", "trend"):
            # 需要傳送圖片/檔案，改成傳新訊息
            await query.edit_message_text("⏳ 生成中，結果將另外傳送...")
            chat_id = query.message.chat_id

            if action == "today":
                threat_data        = await asyncio.to_thread(run_daily_scoring)
                intrusion_stats, _ = get_intrusion_stats(days=1)
                recent_news        = get_recent_news(hours=24)
                top_news = sorted(
                    [{"title": n.title, "score": n.threat_score or 0,
                      "url": n.url or "", "source": n.source or "",
                      "summary": n.ai_summary or "", "content": (n.content or "")[:100]}
                     for n in recent_news],
                    key=lambda x: x["score"], reverse=True
                )[:5]
                ai_analysis = ""
                if check_ollama_available():
                    ai_analysis = await asyncio.to_thread(
                        generate_daily_report, top_news, intrusion_stats,
                        {"military": threat_data["military"],
                         "maritime": threat_data["maritime"],
                         "cyber":    threat_data["cyber"]},
                        datetime.now()
                    )
                msg = format_daily_report(threat_data, ai_analysis, top_news, intrusion_stats)
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.HTML)

            elif action == "map":
                map_path = await asyncio.to_thread(generate_defense_map)
                with open(map_path, "rb") as f:
                    await context.bot.send_document(
                        chat_id=chat_id, document=f,
                        filename=f"map_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                        caption="🗺️ 台灣國防態勢地圖"
                    )

            elif action == "trend":
                scores   = get_recent_scores(days=1)
                military = scores[-1].military_score if scores else 0
                maritime = scores[-1].maritime_score if scores else 0
                cyber    = scores[-1].cyber_score    if scores else 0
                charts   = await asyncio.to_thread(run_all_charts, military, maritime, cyber)
                for name, path in charts.items():
                    if path and os.path.exists(path):
                        with open(path, "rb") as f:
                            await context.bot.send_photo(chat_id=chat_id, photo=f)

            elif action == "weekly":
                stats, _   = get_intrusion_stats(days=7)
                scores     = get_recent_scores(days=7)
                avg        = (sum(s.overall_score for s in scores) / len(scores)) if scores else 0
                peak       = max(scores, key=lambda s: s.overall_score) if scores else None
                weekly_data = {
                    "week_start":       (datetime.now() - timedelta(days=7)).strftime("%m/%d"),
                    "week_end":         datetime.now().strftime("%m/%d"),
                    "total_intrusions": stats.get("total_incidents", 0),
                    "total_aircraft":   stats.get("total_aircraft", 0),
                    "median_crossings": stats.get("median_line_crossings", 0),
                    "avg_threat":       round(avg, 2),
                    "peak_day":         peak.date.strftime("%m/%d") if peak else "N/A",
                    "peak_score":       peak.overall_score if peak else 0,
                }
                ai_weekly = generate_weekly_report(weekly_data) if check_ollama_available() else ""
                msg       = format_weekly_report(weekly_data, ai_weekly)
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.HTML)

    except Exception as e:
        await query.edit_message_text(f"❌ 發生錯誤：{e}")


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

        from scrapers.satellite import get_latest_analysis
        from database.db import get_cog_war_news
        threat_data["satellite_analysis"] = get_latest_analysis()
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
            ai_analysis = generate_daily_report(
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


async def push_alerts(bot: Bot):
    """掃描並推送即時高威脅警報"""
    alerts = get_unalerted_high_threat_news(threshold=THREAT_ALERT_THRESHOLD)
    for news in alerts:
        try:
            ai_alert = ""
            if check_ollama_available():
                ai_alert = generate_alert_message(
                    news.title, news.content or "", news.threat_score or 0
                )
            msg = format_alert_message(
                news.title, news.url or "",
                news.threat_score or 0, ai_alert
            )
            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=msg,
                parse_mode=ParseMode.HTML   # 改用 HTML
            )
            mark_news_alerted(news.id)
            print(f"[BOT] 警報推送：{news.title[:40]}")
            await asyncio.sleep(2)
        except Exception as e:
            print(f"[BOT ERROR] push_alerts: {e}")


# ==============================
# Bot 啟動
# ==============================

def build_app():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("lang",      cmd_lang))
    app.add_handler(CommandHandler("panel",     cmd_panel))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("anomaly",   cmd_anomaly))   # 新增
    app.add_handler(CommandHandler("summary",   cmd_summary))
    app.add_handler(CommandHandler("history",   cmd_history))
    app.add_handler(CommandHandler("today",     cmd_today))
    app.add_handler(CommandHandler("map",       cmd_map))
    app.add_handler(CommandHandler("trend",     cmd_trend))
    app.add_handler(CommandHandler("cable",     cmd_cable))
    app.add_handler(CommandHandler("vessel",    cmd_vessel))
    app.add_handler(CommandHandler("satellite", cmd_satellite))
    app.add_handler(CommandHandler("weekly",    cmd_weekly))
    app.add_handler(CommandHandler("refresh",   cmd_refresh))
    app.add_handler(CallbackQueryHandler(handle_callback))

    async def post_init(application):
        await application.bot.set_my_commands([
            ("panel",     "🛡️ 開啟控制面板"),
            ("summary",   "⚡ 今日快速摘要"),
            ("status",    "📊 威脅指數 + 活躍異常"),
            ("anomaly",   "⚠️ 異常偵測歷史"),
            ("today",     "📋 今日完整報告"),
            ("history",   "📈 歷史威脅趨勢"),
            ("satellite", "🛰️ 衛星影像分析"),
            ("cable",     "🔌 海底電纜狀態"),
            ("vessel",    "🚢 可疑船隻"),
            ("map",       "🗺️ 態勢地圖"),
            ("trend",     "📉 趨勢圖表"),
            ("weekly",    "📅 本週週報"),
            ("refresh",   "🔄 手動更新資料"),
            ("lang",      "🌐 切換語言"),
            ("help",      "❓ 指令說明"),
        ])

    app.post_init = post_init
    return app


if __name__ == "__main__":
    print("[BOT] 啟動 Telegram Bot...")
    app = build_app()
    app.run_polling(allowed_updates=["message", "callback_query"])