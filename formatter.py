# 檔案名稱：bot/formatter.py
# 功能說明：將分析結果格式化為 Telegram 訊息

import re
from datetime import datetime
from analyzer.threat_score import get_threat_level_emoji, get_threat_level_text
try:
    from config import WEB_BASE_URL
except ImportError:
    WEB_BASE_URL = "http://127.0.0.1:5000"


# HTML 格式輔助函式
SEP = "─" * 28


def b(text) -> str:
    """HTML 粗體"""
    return f"<b>{text}</b>"


def i(text) -> str:
    """HTML 斜體"""
    return f"<i>{text}</i>"


def format_daily_report(threat_data: dict, ai_analysis: str,
                        top_news: list, intrusion_stats: dict) -> str:
    """格式化每日情勢報告（含新聞摘要，HTML）"""

    overall      = threat_data.get("overall", 0)
    emoji        = get_threat_level_emoji(overall)
    level        = get_threat_level_text(overall)
    trend        = threat_data.get("trend", "→ 持平")

    now          = datetime.now()
    date_str     = now.strftime('%Y年%m月%d日')
    time_str     = now.strftime('%H:%M')
    overall_str  = f"{overall:.1f}"
    military_str = f"{threat_data.get('military', 0):.1f}"
    maritime_str = f"{threat_data.get('maritime', 0):.1f}"
    cyber_str    = f"{threat_data.get('cyber', 0):.1f}"
    aircraft     = intrusion_stats.get('total_aircraft', 0)
    vessels      = intrusion_stats.get('total_vessels', 0)
    median       = '⚠️ 是' if intrusion_stats.get('median_line_crossings', 0) > 0 else '✅ 否'
    adiz         = '⚠️ 入侵' if intrusion_stats.get('adiz_entries', 0) > 0 else '✅ 正常'
    cog_war_news = threat_data.get("cog_war_news", [])

    msg = (
        f"🛡️ {b('台灣國防情勢日報')}\n"
        f"📅 {date_str} {time_str}\n"
        f"{SEP}\n\n"
        f"{emoji} {b(f'威脅指數：{overall_str}/10 [{level}]')}\n"
        f"📈 趨勢：{trend}\n\n"
        f"🔢 {b('分項評分')}\n"
        f"✈️ 軍事威脅：<code>{military_str}</code> 分\n"
        f"🚢 海域威脅：<code>{maritime_str}</code> 分\n"
        f"💻 資安威脅：<code>{cyber_str}</code> 分\n"
        f"{SEP}\n\n"
        f"⚔️ {b('今日擾臺')}\n"
        f"共機：<code>{aircraft}</code> 架次　共艦：<code>{vessels}</code> 艘次\n"
        f"越中線：{median}　ADIZ：{adiz}\n"
        f"{SEP}\n"
    )

    # 認知作戰警示
    if cog_war_news:
        msg += f"\n🧠 {b(f'認知作戰警示 ({len(cog_war_news)}則)')}\n"
        for cw in cog_war_news[:3]:
            title = (cw.title or "")[:45]
            src   = cw.source or ""
            msg  += f"⚠️ {title} <code>{src}</code>\n"
        msg += f"{SEP}\n"

    # 重點新聞（含摘要）
    if top_news:
        msg += f"\n📰 {b('今日重點新聞')}\n"
        for i, news in enumerate(top_news[:5], 1):
            score   = news.get("score", 0)
            icon    = "🔴" if score >= 7 else "🟠" if score >= 4 else "🟡"
            title   = news.get("title", "")[:50]
            summary = news.get("summary", "") or news.get("ai_summary", "")
            source  = news.get("source", "")
            url     = news.get("url", "")

            title_part = f'<a href="{url}">{title}</a>' if url else title
            msg += f"\n{icon} {b(f'{i}. ')}{title_part}\n"

            # 顯示摘要（優先用 AI 摘要，其次用原始 content 截取）
            if summary:
                msg += f"   💬 {summary[:80]}\n"
            elif news.get("content"):
                msg += f"   📄 {news.get('content','')[:80]}\n"

            if source:
                msg += f"   來源：<code>{source}</code>\n"

        msg += f"{SEP}\n"

    # AI分析
    if ai_analysis:
        msg += f"\n🤖 {b('AI情勢研判')}\n{ai_analysis}\n{SEP}\n"

    news_count = threat_data.get('news_count', 0)
    msg += f"\n📊 今日監測新聞：{news_count} 則\n"
    msg += "⚡ 即時摘要：私訊 Bot 輸入 /summary"

    return msg.strip()


def format_weekly_report(weekly_data: dict, ai_weekly: str) -> str:
    """格式化週報（HTML）"""
    week_start = weekly_data.get('week_start', '')
    week_end   = weekly_data.get('week_end', '')
    intrusions = weekly_data.get('total_intrusions', 0)
    aircraft   = weekly_data.get('total_aircraft', 0)
    median     = weekly_data.get('median_crossings', 0)
    avg_threat = f"{weekly_data.get('avg_threat', 0):.1f}"
    peak_day   = weekly_data.get('peak_day', 'N/A')
    peak_score = f"{weekly_data.get('peak_score', 0):.1f}"

    msg = (
        f"📋 {b('台灣國防情勢週報')}\n"
        f"📅 {week_start} ～ {week_end}\n"
        f"{SEP}\n\n"
        f"📊 {b('本週統計')}\n"
        f"擾臺次數：<code>{intrusions}</code> 次\n"
        f"共機架次：<code>{aircraft}</code> 架次\n"
        f"越中線：<code>{median}</code> 次\n"
        f"平均威脅指數：<code>{avg_threat}/10</code>\n"
        f"最高威脅日：<code>{peak_day}</code>（{peak_score}分）\n"
        f"{SEP}\n\n"
        f"🤖 {b('週報分析：')}\n{ai_weekly}\n"
        f"{SEP}\n"
        f"📈 /history 查看威脅指數歷史"
    )
    return msg.strip()


def format_threat_card(threat_data: dict) -> str:
    """格式化威脅指數卡片（HTML）"""
    overall  = threat_data.get("overall", 0)
    military = threat_data.get('military', 0)
    maritime = threat_data.get('maritime', 0)
    cyber    = threat_data.get('cyber', 0)

    emoji   = get_threat_level_emoji(overall)
    bar_str = "█" * int(overall) + "░" * (10 - int(overall))

    overall_str = f"{overall:.1f}"
    level_str   = get_threat_level_text(overall)
    trend_str   = threat_data.get('trend', '→ 持平')
    mil_str     = f"{military:.1f}"
    mar_str     = f"{maritime:.1f}"
    cyb_str     = f"{cyber:.1f}"
    news_str    = threat_data.get('news_count', 0)
    now_str     = datetime.now().strftime('%Y-%m-%d %H:%M')

    mil_bar = "█" * int(military) + "░" * (10 - int(military))
    mar_bar = "█" * int(maritime) + "░" * (10 - int(maritime))
    cyb_bar = "█" * int(cyber)   + "░" * (10 - int(cyber))

    msg = (
        f"🛡️ {b('台灣國防威脅指數')}\n"
        f"⏱️ {now_str}\n"
        f"{SEP}\n\n"
        f"{emoji} <code>[{bar_str}]</code> {b(f'{overall_str}/10')}\n"
        f"等級：{b(level_str)}\n"
        f"趨勢：{trend_str}\n\n"
        f"軍事 <code>{mil_bar}</code> {mil_str}\n"
        f"海域 <code>{mar_bar}</code> {mar_str}\n"
        f"資安 <code>{cyb_bar}</code> {cyb_str}\n"
        f"{SEP}\n"
        f"今日監測：{news_str} 則新聞"
    )
    return msg.strip()


def format_cable_status(cables: list) -> str:
    """格式化海底電纜狀態（含詳細資訊，HTML）"""
    msg  = f"🔌 {b('台灣海底電纜狀態')}\n"
    msg += f"{SEP}\n"

    status_icon = {
        "正常":   "✅",
        "異常":   "⚠️",
        "障礙":   "🟠",
        "中斷":   "🔴",
        "已修復": "🔧",
        "維修中": "🔧",
    }

    if not cables:
        msg += "✅ 目前無電纜異常紀錄\n"
    else:
        for c in cables:
            icon     = status_icon.get(c.status, "❓")
            name     = c.cable_name
            status   = c.status
            incident = c.incident_type or ""
            source   = c.source or ""
            msg     += f"\n{icon} {b(name)}\n"
            msg     += f"   狀態：{status}"
            if incident:
                msg += f" ｜ 類型：{incident}"
            if source:
                msg += f" ｜ 來源：<code>{source}</code>"
            msg     += "\n"

            if c.reported_at:
                date_str = c.reported_at.strftime('%Y-%m-%d')
                msg     += f"   發生：{date_str}\n"

            if c.notes:
                import re
                clean_notes = re.sub(r'<[^>]+>', '', c.notes)
                msg += f"   備註：{clean_notes[:80]}\n"

    msg += f"\n{SEP}\n"
    msg += f"更新：{datetime.now().strftime('%H:%M')}"
    return msg


def format_vessel_alert(vessels: list) -> str:
    """格式化可疑船隻警報（HTML）"""
    if not vessels:
        return ""

    count = len(vessels)
    msg   = f"🚢 {b(f'可疑船隻警報 ({count}艘)')}\n"
    msg  += f"{SEP}\n"

    for v in vessels[:5]:
        name   = v.get('name', '未知')
        flag   = v.get('flag', '?')
        vtype  = v.get('type', '?')
        reason = v.get('reason', '?')
        lat    = f"{v.get('lat', 0):.2f}"
        lon    = f"{v.get('lon', 0):.2f}"
        msg   += (
            f"⚠️ {b(name)}\n"
            f"   旗：{flag} ｜ 型：{vtype}\n"
            f"   原因：{reason}\n"
            f"   位置：{lat}N, {lon}E\n\n"
        )

    return msg.strip()


def format_anomaly_summary(anomaly_summary: dict) -> str:
    """
    格式化目前活躍異常摘要（供 /status 等指令使用）
    anomaly_summary: {count, max_severity, items: [{desc, severity, type}, ...]}
    """
    count   = anomaly_summary.get("count", 0)
    max_sev = anomaly_summary.get("max_severity", "LOW")
    items   = anomaly_summary.get("items", [])

    if count == 0:
        return f"✅ {b('目前無活躍異常')}"

    sev_icon = {"CRITICAL": "🚨", "HIGH": "🔴",
                "MEDIUM": "🟠", "LOW": "🟡"}.get(max_sev, "🟡")

    lines = [f"{sev_icon} {b('活躍異常')}：{count} 個"]
    for item in items[:5]:
        item_sev  = item.get("severity", "LOW")
        item_icon = {"CRITICAL": "🚨", "HIGH": "🔴",
                      "MEDIUM": "🟠", "LOW": "🟡"}.get(item_sev, "🟡")
        desc = item.get("desc", "")[:50]
        lines.append(f"  {item_icon} {desc}")

    if count > 5:
        lines.append(f"  ...及其他 {count - 5} 個")

    return "\n".join(lines)


def format_anomaly_alert(anomaly: dict) -> str:
    """
    格式化單筆異常通知
    設計原則：
    1. 第一行說清楚發生什麼
    2. 第二層說明為什麼重要
    3. 底部簡短行動提示
    """
    severity    = anomaly.get("severity", "MEDIUM")
    desc        = anomaly.get("desc", "")
    explanation = anomaly.get("explanation", "")
    atype       = anomaly.get("type", "")
    now_str     = datetime.now().strftime("%m/%d %H:%M")

    sev_icon = {"CRITICAL": "🚨", "HIGH": "🔴", "MEDIUM": "🟠", "LOW": "🟡"}.get(severity, "🟡")
    sev_text = {"CRITICAL": "緊急警示", "HIGH": "高度警示",
                "MEDIUM":   "一般警示", "LOW":  "低度關注"}.get(severity, "警示")

    type_title = {
        "COG_WAR_SPIKE":        "認知作戰比例異常",
        "MEDIAN_LINE_CROSS":    "共軍越越海峽中線",
        "VESSEL_CLUSTER":       "共艦異常聚集",
        "AIRCRAFT_SURGE":       "共機大規模擾台",
        "PTT_SURGE":            "PTT 軍武板熱議異常",
        "INTL_COVERAGE_SPIKE":  "國際媒體集中報導台海",
        "CABLE_INCIDENT":       "海底電纜異常",
        "GWYTB_ESCALATION":     "國台辦措辭升溫",
    }.get(atype, "情勢異常")

    lines = [
        f"{sev_icon} <b>{type_title}</b>",
        f"<code>{now_str}</code>  {sev_text}",
        SEP,
        "",
        desc,
    ]

    if explanation:
        lines += ["", explanation]

    lines += ["", SEP]

    action = {
        "COG_WAR_SPIKE":       "/anomaly 查看異常詳情",
        "MEDIAN_LINE_CROSS":   "/summary 查看今日摘要",
        "VESSEL_CLUSTER":      "/vessel 查看可疑船隻清單",
        "AIRCRAFT_SURGE":      "/summary 查看今日摘要",
        "PTT_SURGE":           "/anomaly 查看異常詳情",
        "INTL_COVERAGE_SPIKE": "/anomaly 查看異常詳情",
        "CABLE_INCIDENT":      "/cable 查看電纜狀態",
        "GWYTB_ESCALATION":    "/anomaly 查看異常詳情",
    }.get(atype, "/status 查看完整狀態")

    lines.append(f"<i>{action}</i>")
    return "\n".join(lines)


def format_morning_brief(threat_data: dict, anomaly_summary: dict,
                         intrusion_stats: dict) -> str:
    """每日 08:00 晨報，讓訂閱者 10 秒內掌握台海現況"""
    overall  = threat_data.get("overall", 0)
    trend    = threat_data.get("trend", "→ 持平")
    military = threat_data.get("military", 0)
    maritime = threat_data.get("maritime", 0)

    aircraft = intrusion_stats.get("total_aircraft", 0)
    crossed  = intrusion_stats.get("median_line_crossings", 0)
    vessels  = intrusion_stats.get("total_vessels", 0)

    anomaly_count = anomaly_summary.get("count", 0)
    max_sev       = anomaly_summary.get("max_severity", "LOW")

    sev_icon = "🔴" if overall >= 8 else "🟠" if overall >= 6 else "🟡" if overall >= 4 else "🟢"
    status   = "高度緊張" if overall >= 8 else "偏高" if overall >= 6 else "正常" if overall >= 4 else "平穩"

    date_str = datetime.now().strftime("%m月%d日")

    lines = [
        f"🛡 <b>台海今日概況</b>  {date_str}",
        SEP,
        "",
        f"{sev_icon} 威脅指數  <b>{overall:.1f}/10</b>  {trend}",
        f"整體態勢：{status}",
        "",
        f"<b>昨日擾台</b>",
    ]

    if aircraft > 0:
        cross_txt = "  ⚠️ 越中線" if crossed > 0 else ""
        lines.append(f"✈️ 共機 <b>{aircraft}</b> 架次{cross_txt}")
    else:
        lines.append("✈️ 共機：無")

    if vessels > 0:
        lines.append(f"🚢 共艦 <b>{vessels}</b> 艘次")

    lines += [""]
    lines += [
        f"<b>分項</b>",
        f"軍事 {military:.1f}  ｜  海域 {maritime:.1f}  ｜  資安 {threat_data.get('cyber',0):.1f}",
        "",
    ]

    if anomaly_count > 0:
        sev_icon2 = {"CRITICAL":"🚨","HIGH":"🔴","MEDIUM":"🟠","LOW":"🟡"}.get(max_sev,"🟡")
        lines += [f"<b>活躍異常</b>  {sev_icon2} {anomaly_count} 個"]
        for item in anomaly_summary.get("items", [])[:3]:
            lines.append(f"  • {item['desc'][:45]}")
    else:
        lines.append("✅ 目前無活躍異常")

    lines += [
        "",
        SEP,
        "<i>/summary 快速摘要  /anomaly 異常詳情</i>",
    ]
    return "\n".join(lines)


def format_project_intro() -> str:
    """
    /start 指令與頻道介紹訊息
    給新加入的訂閱者了解這個專案在做什麼
    """
    sep = "─" * 28
    return (
        f"🛡️ {b('SkyEye 台灣國防情勢監控')}\n"
        f"{sep}\n\n"
        f"這是一個{b('民間自發、非營利')}的公民科普專案，"
        f"整合台灣官方公告、國際媒體、衛星影像、"
        f"船舶與飛航追蹤等多項{b('公開資料來源')}，"
        f"用白話文說明台海周邊的軍事與安全動態。\n\n"

        f"📡 {b('監測項目')}\n"
        f"• 共機/共艦擾台動態\n"
        f"• 軍機追蹤（ADS-B）\n"
        f"• 海底電纜狀態（數位部公告）\n"
        f"• 衛星影像（重點軍事基地）\n"
        f"• 中共官媒輿論升溫偵測\n"
        f"• 民船徵用前兆偵測\n"
        f"• 國台辦/國際媒體/智庫動態\n\n"

        f"📬 {b('推送方式')}\n"
        f"• 每日 08:00 晨報、20:00 日報\n"
        f"• 明顯異常時即時通知（含說明＋圖片）\n"
        f"• 例行活動不打擾，避免通知疲勞\n\n"

        f"⚠️ {b('重要提醒')}\n"
        f"本頻道內容{b('不構成')}軍事、政治、投資建議，"
        f"亦不代表官方立場。正式資訊請以"
        f"國防部、海巡署、數位部公告為準。\n\n"

        f"完整說明與資料來源：\n"
        f"🔗 {WEB_BASE_URL}/about\n\n"
        f"{sep}\n"
        f"💬 {b('如何使用指令？')}\n"
        f"頻道為單向廣播，無法輸入指令。\n"
        f"請直接私訊 @taiwandefence_bot，即可使用 /summary、/status、/cable 等查詢功能。\n\n"
        f"輸入 /help 查看所有指令"
    )


def format_startup_message() -> str:
    """Bot 啟動訊息（系統內部用，HTML 格式）"""
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return (
        f"🟢 {b('SkyEye 已啟動')}\n"
        f"{SEP}\n"
        f"SkyEye v2.0（台灣國防情勢監控）\n"
        f"啟動時間：{now_str}\n\n"
        f"📋 {b('可用指令')}\n"
        f"/summary — 快速摘要\n"
        f"/status — 目前威脅指數\n"
        f"/cable — 電纜狀態\n"
        f"/vessel — 可疑船隻\n"
        f"/help — 指令說明\n"
        f"{SEP}\n"
        f"監控中 🔍"
    )