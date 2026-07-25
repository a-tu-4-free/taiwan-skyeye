# 檔案名稱：bot/alert_engine.py
# 功能說明：即時警報引擎
# 全面改用 parse_mode=HTML，整合 anomaly_detector

import asyncio
from datetime import datetime, timedelta
from telegram import Bot
from telegram.constants import ParseMode
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import TELEGRAM_CHANNEL_ID, THREAT_ALERT_THRESHOLD
from database.db import (
    get_session, get_recent_news,
    get_unalerted_high_threat_news, mark_news_alerted
)

# 即時觸發規則（關鍵字觸發，不需要 Ollama）
INSTANT_TRIGGERS = [
    {
        "id":       "median_line_crossed",
        "keywords": ["逾越中線", "越中線", "穿越中線"],
        "level":    "CRITICAL",
        "title":    "共軍越越海峽中線",
        "icon":     "⚡",
    },
    {
        "id":       "pla_exercise",
        "keywords": ["聯合利劍", "實彈演習", "封鎖演習", "登陸演習"],
        "level":    "CRITICAL",
        "title":    "解放軍宣布軍事演習",
        "icon":     "⚡",
    },
    {
        "id":       "cable_cut",
        "keywords": ["海底電纜", "斷纜", "電纜中斷", "cable cut", "cable severed"],
        "level":    "CRITICAL",
        "title":    "海底電纜異常事件",
        "icon":     "🔌",
    },
    {
        "id":       "ccg_intrusion",
        "keywords": ["中國海警宣稱", "海警侵擾", "海警進入"],
        "level":    "HIGH",
        "title":    "中國海警侵擾事件",
        "icon":     "🔴",
    },
    {
        "id":       "mofa_protest",
        "keywords": ["嚴正抗議", "強烈譴責", "嚴重關切"],
        "level":    "HIGH",
        "title":    "外交部強硬聲明",
        "icon":     "🔴",
    },
    {
        "id":       "gwytb_escalation",
        "keywords": ["不惜一切", "警告台獨", "武力解決"],
        "level":    "HIGH",
        "title":    "國台辦升溫警告",
        "icon":     "🔴",
    },
]

_triggered_today: set = set()

LEVEL_ICON = {
    "CRITICAL": "🚨",
    "HIGH":     "🔴",
    "MEDIUM":   "🟠",
    "LOW":      "🟡",
}


def check_instant_triggers(news_list: list) -> list:
    alerts = []
    today  = datetime.now().strftime("%Y%m%d")
    for news in news_list:
        text = (news.title or "") + " " + (news.content or "")
        for trigger in INSTANT_TRIGGERS:
            key = f"{today}_{trigger['id']}_{news.id}"
            if key in _triggered_today:
                continue
            if any(kw in text for kw in trigger["keywords"]):
                _triggered_today.add(key)
                alerts.append({
                    "level":   trigger["level"],
                    "title":   trigger["title"],
                    "icon":    trigger["icon"],
                    "news":    news,
                    "trigger": trigger["id"],
                })
                break
    return alerts


async def push_instant_alerts(bot: Bot):
    """推送關鍵字即時觸發警報"""
    try:
        recent = get_recent_news(hours=1)
        cutoff = datetime.now() - timedelta(minutes=15)
        fresh  = [n for n in recent if n.fetched_at and n.fetched_at >= cutoff]
        if not fresh:
            return

        alerts = check_instant_triggers(fresh)
        for alert in alerts:
            try:
                news     = alert["news"]
                title    = (news.title or "")[:60]
                src      = news.source or ""
                now_str  = datetime.now().strftime("%H:%M")
                url_part = f'\n🔗 <a href="{news.url}">查看原文</a>' if news.url else ""

                msg = (
                    f'{alert["icon"]} <b>{alert["title"]}</b>  '
                    f'<code>{now_str}</code>\n'
                    f'{"─" * 28}\n'
                    f'📌 {title}\n'
                    f'來源：<code>{src}</code>'
                    f'{url_part}'
                )

                await bot.send_message(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    text=msg,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
                print(f"[ALERT] 即時：{alert['title']} - {title[:30]}")
                await asyncio.sleep(2)
            except Exception as e:
                print(f"[ALERT ERROR] 推送失敗：{e}")
    except Exception as e:
        print(f"[ALERT ERROR] push_instant_alerts: {e}")


async def push_score_alerts(bot: Bot):
    """推送 AI 評分超過門檻的新聞警報"""
    try:
        from analyzer.ollama_client import generate_alert_message, check_ollama_available
        alerts = get_unalerted_high_threat_news(threshold=THREAT_ALERT_THRESHOLD)

        for news in alerts:
            try:
                score    = news.threat_score or 0
                ai_alert = ""
                if check_ollama_available():
                    ai_alert = generate_alert_message(
                        news.title or "", news.content or "", score
                    )

                header   = ("🚨🚨🚨 <b>緊急警報</b> 🚨🚨🚨"
                            if score >= 9 else "🔴 <b>高度威脅警示</b>")
                title    = (news.title or "")[:60]
                now_str  = datetime.now().strftime("%H:%M")
                url_part = f'\n🔗 <a href="{news.url}">查看原文</a>' if news.url else ""
                ai_part  = f"\n\n🤖 <b>研判：</b>\n<i>{ai_alert[:300]}</i>" if ai_alert else ""

                msg = (
                    f"{header}\n"
                    f'{"─" * 28}\n'
                    f"📌 {title}\n"
                    f"威脅指數：<b>{score:.1f}/10</b>  "
                    f"<code>{now_str}</code>"
                    f"{ai_part}"
                    f"{url_part}"
                )

                await bot.send_message(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    text=msg,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
                mark_news_alerted(news.id)
                print(f"[ALERT] 評分警報：{title[:40]} ({score})")
                await asyncio.sleep(2)
            except Exception as e:
                print(f"[ALERT ERROR] 評分警報：{e}")
    except Exception as e:
        print(f"[ALERT ERROR] push_score_alerts: {e}")


async def push_ptt_hot(bot: Bot, threshold: int = 50):
    """推送 PTT 爆文"""
    try:
        from database.models import NewsEvent
        from sqlalchemy import desc
        session  = get_session()
        cutoff   = datetime.now() - timedelta(hours=1)
        hot_news = session.query(NewsEvent).filter(
            NewsEvent.source.like("ptt_%"),
            NewsEvent.fetched_at >= cutoff,
        ).all()
        session.close()

        import re
        for news in hot_news:
            match = re.search(r'推文:(\d+)', news.content or "")
            if not match or int(match.group(1)) < threshold:
                continue
            key = f"ptt_hot_{news.id}"
            if key in _triggered_today:
                continue
            _triggered_today.add(key)

            push_count = int(match.group(1))
            title      = (news.title or "")[:60]
            url_part   = f'\n🔗 <a href="{news.url}">查看討論</a>' if news.url else ""

            msg = (
                f"🟡 <b>PTT軍武熱議</b>\n"
                f'{"─" * 28}\n'
                f"推文數：<b>{push_count}</b>\n"
                f"📌 {title}"
                f"{url_part}"
            )
            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=msg,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
            print(f"[ALERT] PTT爆文：推{push_count} {title[:30]}")
            await asyncio.sleep(2)
    except Exception as e:
        print(f"[ALERT ERROR] push_ptt_hot: {e}")


# ==============================
# 各 Scraper 圖片通知函式
# ==============================

async def push_mnd_with_card(bot: Bot, intrusion_data: dict):
    """共軍擾台：推送地圖截圖 + 卡片"""
    aircraft = intrusion_data.get("aircraft_count", 0)
    crossed  = intrusion_data.get("crossed_median_line", False)
    types    = intrusion_data.get("aircraft_types", "未知")
    direction = intrusion_data.get("entry_direction", "未知")
    date_str  = intrusion_data.get("date", datetime.now().strftime("%Y-%m-%d"))
    now_str   = datetime.now().strftime("%m/%d %H:%M")

    # 1. 嘗試生成地圖截圖
    map_png = ""
    try:
        from bot.map_notifier import make_mnd_map
        map_png = await asyncio.to_thread(make_mnd_map, intrusion_data)
    except Exception as e:
        print(f"[ALERT] 地圖截圖失敗（非致命）：{e}")

    # 2. 生成卡片
    card_png = ""
    try:
        from bot.card_generator import make_mnd_card
        card_png = await asyncio.to_thread(make_mnd_card, intrusion_data)
    except Exception as e:
        print(f"[ALERT] 卡片生成失敗（非致命）：{e}")

    # 3. 組裝說明文字
    sev_icon = "🚨" if crossed else "🔴"
    caption  = (
        f"{sev_icon} <b>共軍擾台事件</b>  <code>{now_str}</code>\n"
        f"{'─' * 28}\n"
        f"✈️ 共機 <b>{aircraft}</b> 架次  ｜  {direction}方向\n"
        f"機型：{types or '未知'}\n"
        f"越海峽中線：{'<b>⚠️ 是</b>' if crossed else '✅ 否'}\n"
        f"{'─' * 28}\n"
        f"<i>來源：國防部  {date_str}</i>"
    )

    try:
        if map_png and os.path.exists(map_png):
            with open(map_png, "rb") as f:
                await bot.send_photo(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    photo=f, caption=caption,
                    parse_mode=ParseMode.HTML
                )
            os.remove(map_png)
        elif card_png and os.path.exists(card_png):
            with open(card_png, "rb") as f:
                await bot.send_photo(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    photo=f, caption=caption,
                    parse_mode=ParseMode.HTML
                )
        else:
            # 純文字備援
            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=caption, parse_mode=ParseMode.HTML
            )
        print(f"[ALERT] MND 擾台通知推送完成")
    except Exception as e:
        print(f"[ALERT ERROR] push_mnd_with_card: {e}")

    if card_png and os.path.exists(card_png):
        os.remove(card_png)


async def push_cable_with_map(bot: Bot, cable_events: list):
    """電纜異常：推送地圖截圖 + 電纜說明"""
    if not cable_events:
        return

    now_str = datetime.now().strftime("%m/%d %H:%M")

    # 電纜起訖資訊（含 MODA 中文名稱對應）
    CABLE_INFO = {
        "APCN-2":      {"route": "台灣淡水 → 香港 → 日本 → 韓國",     "zh": ["亞太2號", "亞太二號", "APCN2"]},
        "EAC1":        {"route": "台灣八里 → 香港 → 日本",              "zh": ["東亞交匯一號", "EAC1", "EAC-C2C"]},
        "SMW3":        {"route": "台灣頭城/枋山 → 日本 → 歐洲",        "zh": ["法新歐亞三號", "SMW3", "SMW-3"]},
        "APG":         {"route": "台灣頭城 → 香港 → 日本 → 東南亞",    "zh": ["亞太直達", "APG"]},
        "TPE":         {"route": "台灣淡水 → 日本 → 美國",              "zh": ["橫太平洋快速", "TPE"]},
        "NCP":         {"route": "台灣頭城 → 日本 → 美國",              "zh": ["新橫太平洋", "NCP"]},
        "FASTER":      {"route": "台灣淡水 → 日本 → 美國（Google）",    "zh": ["FASTER"]},
        "PLCN":        {"route": "台灣頭城 → 菲律賓 → 美國",            "zh": ["PLCN", "太平洋光纜"]},
        "SJC":         {"route": "台灣枋山 → 越南 → 香港",              "zh": ["東南亞日本", "SJC"]},
        "SJC2":        {"route": "台灣淡水 → 日本 → 東南亞",            "zh": ["東南亞日本二號", "SJC2", "SJC-2"]},
        "HKA":         {"route": "台灣頭城 → 香港 → 東南亞（Meta）",    "zh": ["HKA"]},
        "PCCS":        {"route": "台灣枋山 → 菲律賓",                   "zh": ["PCCS"]},
        "TSE-1":       {"route": "台灣淡水 → 福州（兩岸直連）",         "zh": ["海峽光纜一號", "TSE", "TSE-1"]},
        "FLAG/FEA":    {"route": "台灣 → 菲律賓 → 關島",                "zh": ["FLAG", "FEA"]},
        "TDM2":        {"route": "台灣石門 → 馬祖南竿",                 "zh": ["臺馬二號", "台馬二號", "TDM2", "TDM-2"]},
        "TM3":         {"route": "台灣石門 → 馬祖南竿",                 "zh": ["臺馬三號", "台馬三號", "TM3", "TM-3"]},
        "TDM4":        {"route": "台灣石門 → 馬祖（2026年完工）",       "zh": ["臺馬四號", "台馬四號", "TDM4"]},
        "TPCA":        {"route": "台灣本島 → 澎湖",                     "zh": ["台澎海纜", "臺澎", "TPCA"]},
        "TSE（金廈）": {"route": "金門 → 廈門（兩岸）",                  "zh": ["金廈海纜", "金廈", "Cross Straits"]},
    }

    def get_cable_route(name: str) -> str:
        """模糊比對電纜名稱，回傳路由說明"""
        if name in CABLE_INFO:
            return CABLE_INFO[name]["route"]
        nu = name.upper().replace(" ", "").replace("（", "(").replace("）", ")")
        for key, info in CABLE_INFO.items():
            for alias in info["zh"]:
                au = alias.upper().replace(" ", "")
                if au in nu or nu in au:
                    return info["route"]
            ku = key.replace("-", "").replace(" ", "").upper()
            if ku in nu or nu in ku:
                return info["route"]
        return "台灣周邊海域"

    # 生成地圖
    map_png = ""
    try:
        from bot.map_notifier import make_cable_map
        map_png = await asyncio.to_thread(make_cable_map, cable_events)
    except Exception as e:
        print(f"[ALERT] 電纜地圖失敗：{e}")

    # 生成卡片備援
    card_png = ""
    try:
        from bot.card_generator import make_cable_card
        card_png = await asyncio.to_thread(make_cable_card, cable_events)
    except Exception as e:
        print(f"[ALERT] 電纜卡片失敗：{e}")

    # 說明文字
    has_cut = any(e.get("status") == "中斷" for e in cable_events)
    sev_icon = "🚨" if has_cut else "⚠️"
    lines = [
        f"{sev_icon} <b>海底電纜異常警報</b>  <code>{now_str}</code>",
        "─" * 28,
    ]
    for e in cable_events[:3]:
        name   = e.get("cable_name", "未知")
        status = e.get("status", "異常")
        inc    = e.get("incident_type", "")
        route   = get_cable_route(name)
        st_icon = "🔴" if status == "中斷" else "🟠"
        lines += [
            f"{st_icon} <b>{name}</b>  {status}",
            f"   路由：{route}",
            (f"   類型：{inc}" if inc else ""),
        ]
    lines += ["─" * 28, "<i>來源：MODA / SubTel Forum</i>"]
    caption = "\n".join(l for l in lines if l)

    try:
        img_path = map_png if (map_png and os.path.exists(map_png)) else card_png
        if img_path and os.path.exists(img_path):
            with open(img_path, "rb") as f:
                await bot.send_photo(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    photo=f, caption=caption,
                    parse_mode=ParseMode.HTML
                )
        else:
            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=caption, parse_mode=ParseMode.HTML
            )
        print("[ALERT] 電纜異常通知推送完成")
    except Exception as e:
        print(f"[ALERT ERROR] push_cable_with_map: {e}")
    finally:
        for p in [map_png, card_png]:
            if p and os.path.exists(p):
                os.remove(p)


async def push_satellite_with_image(bot: Bot, area_name: str,
                                     threat_level: float, summary: str,
                                     image_path: str = ""):
    """衛星分析：直接附上衛星圖 + Gemini 分析結果"""
    from bot.card_generator import make_satellite_caption
    caption = make_satellite_caption(area_name, threat_level, summary)

    try:
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                await bot.send_photo(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    photo=f, caption=caption,
                    parse_mode=ParseMode.HTML
                )
        else:
            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=caption, parse_mode=ParseMode.HTML
            )
        print(f"[ALERT] 衛星分析通知推送完成：{area_name}")
    except Exception as e:
        print(f"[ALERT ERROR] push_satellite: {e}")


async def push_ais_with_map(bot: Bot, suspicious_vessels: list):
    """AIS可疑船隻：推送地圖 + 說明"""
    if not suspicious_vessels:
        return

    now_str = datetime.now().strftime("%m/%d %H:%M")
    count   = len(suspicious_vessels)

    map_png = card_png = ""
    try:
        from bot.map_notifier import make_ais_map
        map_png = await asyncio.to_thread(make_ais_map, suspicious_vessels)
    except Exception as e:
        print(f"[ALERT] AIS地圖失敗：{e}")
    try:
        from bot.card_generator import make_ais_card
        card_png = await asyncio.to_thread(make_ais_card, suspicious_vessels)
    except Exception as e:
        print(f"[ALERT] AIS卡片失敗：{e}")

    lines = [
        f"⚓ <b>可疑船隻警報（{count}艘）</b>  <code>{now_str}</code>",
        "─" * 28,
    ]
    for v in suspicious_vessels[:4]:
        lines.append(
            f"▸ <b>{v.get('name','未知')}</b>  {v.get('flag','')}  "
            f"｜  {v.get('zone','')}\n"
            f"   原因：{v.get('reason','')[:40]}"
        )
    lines += ["─" * 28, "<i>來源：AISStream WebSocket</i>"]
    caption = "\n".join(lines)

    try:
        img_path = map_png if (map_png and os.path.exists(map_png)) else card_png
        if img_path and os.path.exists(img_path):
            with open(img_path, "rb") as f:
                await bot.send_photo(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    photo=f, caption=caption,
                    parse_mode=ParseMode.HTML
                )
        else:
            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=caption, parse_mode=ParseMode.HTML
            )
        print("[ALERT] AIS 船隻通知推送完成")
    except Exception as e:
        print(f"[ALERT ERROR] push_ais: {e}")
    finally:
        for p in [map_png, card_png]:
            if p and os.path.exists(p):
                os.remove(p)


async def push_adsb_with_map(bot: Bot, aircraft_list: list, category: str):
    """ADS-B 軍機動態：推送地圖 + 說明"""
    if not aircraft_list:
        return

    now_str = datetime.now().strftime("%m/%d %H:%M")
    count   = len(aircraft_list)
    icon    = "⚠️" if category == "中共解放軍" else "👁"
    sev     = "高度警示" if category == "中共解放軍" else "監控通報"

    map_png = ""
    try:
        from bot.map_notifier import make_adsb_map
        map_png = await asyncio.to_thread(make_adsb_map, aircraft_list)
    except Exception as e:
        print(f"[ALERT] ADS-B地圖失敗：{e}")

    lines = [
        f"{icon} <b>{category}動態</b>  <code>{now_str}</code>",
        "─" * 28,
        f"偵測到 <b>{count}</b> 架{category}在台海周邊",
        "",
    ]
    for ac in aircraft_list[:4]:
        cs   = ac.get("callsign") or ""
        # 中共軍機通常關閉 ADS-B 識別，callsign 不廣播是正常現象
        cs_display = f"<code>{cs}</code>" if cs else "<code>─</code>（未廣播）"
        alt  = f"{ac.get('alt_m', 0):.0f}m"
        hdg  = f"{ac.get('heading', 0):.0f}°"
        zone = ac.get("zone", "台海周邊")
        lines.append(f"  ✈ {cs_display} {zone}  {alt}  航向{hdg}")

    lines += [
        "",
        "─" * 28,
        f"<i>來源：OpenSky Network  ｜  {sev}</i>",
        "<i>⚠️ 中共軍機通常不廣播識別碼，識別依 ICAO 前綴判斷</i>",
    ]
    caption = "\n".join(lines)

    try:
        if map_png and os.path.exists(map_png):
            with open(map_png, "rb") as f:
                await bot.send_photo(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    photo=f, caption=caption,
                    parse_mode=ParseMode.HTML
                )
        else:
            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=caption, parse_mode=ParseMode.HTML
            )
        print(f"[ALERT] ADS-B {category} 通知推送完成")
    except Exception as e:
        print(f"[ALERT ERROR] push_adsb: {e}")
    finally:
        if map_png and os.path.exists(map_png):
            os.remove(map_png)


async def push_gwytb_with_card(bot: Bot, escalations: list):
    """國台辦升溫：推送卡片"""
    if not escalations:
        return
    card_png = ""
    try:
        from bot.card_generator import make_gwytb_card
        card_png = await asyncio.to_thread(make_gwytb_card, escalations)
    except Exception as e:
        print(f"[ALERT] 國台辦卡片失敗：{e}")

    max_int  = max(e.get("intensity", 0) for e in escalations)
    now_str  = datetime.now().strftime("%m/%d %H:%M")
    lines    = [
        f"📢 <b>國台辦措辭升溫</b>  <code>{now_str}</code>",
        "─" * 28,
    ]
    for e in escalations[:3]:
        lines.append(f"▸ {e.get('title','')[:45]}")
        lines.append(f"   升溫強度：{'🔴' * e.get('intensity',0)}")
    lines += ["─" * 28, "<i>來源：gwytb.gov.tw</i>"]
    caption = "\n".join(lines)

    try:
        if card_png and os.path.exists(card_png):
            with open(card_png, "rb") as f:
                await bot.send_photo(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    photo=f, caption=caption,
                    parse_mode=ParseMode.HTML
                )
            os.remove(card_png)
        else:
            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=caption, parse_mode=ParseMode.HTML
            )
    except Exception as e:
        print(f"[ALERT ERROR] push_gwytb: {e}")


async def push_thinktank_with_card(bot: Bot, anomaly_entries: list):
    """智庫異常：推送卡片 + Ollama 分析"""
    if not anomaly_entries:
        return
    card_png = ""
    try:
        from bot.card_generator import make_thinktank_card
        card_png = await asyncio.to_thread(make_thinktank_card, anomaly_entries)
    except Exception as e:
        print(f"[ALERT] 智庫卡片失敗：{e}")

    now_str = datetime.now().strftime("%m/%d %H:%M")
    top     = anomaly_entries[0]
    url_part2 = f'<a href="{top.get("url","")}">{top.get("source","")}</a>' if top.get("url") else top.get("source","")
    tags_str  = "　".join(f"#{h}" for h in top.get("hits", [])[:3])
    caption   = (
        f"🔬 <b>智庫台灣安全分析</b>  <code>{now_str}</code>\n"
        f"{'─' * 28}\n"
        f"<b>{top.get('title','')[:65]}</b>\n"
        f"來源：{url_part2}\n"
        f"{tags_str}\n"
        f"{'─' * 28}\n"
        f"<i>ASPI / DFRLab / CSIS / RAND</i>"
    )

    try:
        if card_png and os.path.exists(card_png):
            with open(card_png, "rb") as f:
                await bot.send_photo(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    photo=f, caption=caption,
                    parse_mode=ParseMode.HTML
                )
            os.remove(card_png)
        else:
            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=caption, parse_mode=ParseMode.HTML
            )
    except Exception as e:
        print(f"[ALERT ERROR] push_thinktank: {e}")


async def push_ptt_with_card(bot: Bot, hot_articles: list):
    """PTT 熱議：推送卡片"""
    if not hot_articles:
        return
    card_png = ""
    try:
        from bot.card_generator import make_ptt_card
        card_png = await asyncio.to_thread(make_ptt_card, hot_articles)
    except Exception as e:
        print(f"[ALERT] PTT卡片失敗：{e}")

    now_str = datetime.now().strftime("%m/%d %H:%M")
    top     = hot_articles[0]
    caption = (
        f"💬 <b>PTT 軍武板熱議</b>  <code>{now_str}</code>\n"
        f"{'─' * 28}\n"
        f"🔥 推文 <b>{top.get('push_count','')}</b>  [{top.get('board','')}]\n"
        f"{top.get('title','')[:60]}\n"
        f"{'─' * 28}\n"
        f"<i>來源：PTT Warfare / Military</i>"
    )

    try:
        if card_png and os.path.exists(card_png):
            with open(card_png, "rb") as f:
                await bot.send_photo(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    photo=f, caption=caption,
                    parse_mode=ParseMode.HTML
                )
            os.remove(card_png)
        else:
            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=caption, parse_mode=ParseMode.HTML
            )
    except Exception as e:
        print(f"[ALERT ERROR] push_ptt: {e}")


async def push_intl_with_card(bot: Bot, high_priority_news: list):
    """國際媒體高優先：推送卡片"""
    if not high_priority_news:
        return
    card_png = ""
    try:
        from bot.card_generator import make_intl_card
        card_png = await asyncio.to_thread(make_intl_card, high_priority_news)
    except Exception as e:
        print(f"[ALERT] 國際媒體卡片失敗：{e}")

    now_str  = datetime.now().strftime("%m/%d %H:%M")
    top      = high_priority_news[0]
    url_part = f'\n🔗 <a href="{top.get("url","")}">{top.get("source","").upper()}</a>' if top.get("url") else f'\n來源：{top.get("source","").upper()}'
    kw_str   = "　".join(f"#{k}" for k in top.get("keywords", [])[:3])
    caption  = (
        f"🌐 <b>國際媒體台海緊急報導</b>  <code>{now_str}</code>\n"
        f"{'─' * 28}\n"
        f"<b>{top.get('title','')[:65]}</b>\n"
        f"{kw_str}"
        f"{url_part}\n"
        f"{'─' * 28}\n"
        f"<i>USNI / The War Zone / BBC / DefenseNews</i>"
    )

    try:
        if card_png and os.path.exists(card_png):
            with open(card_png, "rb") as f:
                await bot.send_photo(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    photo=f, caption=caption,
                    parse_mode=ParseMode.HTML
                )
            os.remove(card_png)
        else:
            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=caption, parse_mode=ParseMode.HTML
            )
    except Exception as e:
        print(f"[ALERT ERROR] push_intl: {e}")


async def push_routine_status(bot: Bot, scrape_summary: dict):
    """
    例行掃描狀態推送
    只有有新資料時才推（scheduler 已在上層判斷，此處直接推）
    """
    try:
        from analyzer.threat_score import run_daily_scoring
        from analyzer.anomaly_detector import get_current_anomaly_summary

        threat  = run_daily_scoring()
        overall = threat.get("overall", 0)
        anomaly = get_current_anomaly_summary()

        status_icon = "🔴" if overall >= 8 else "🟠" if overall >= 5 else "🟢"
        sea_status  = "緊張" if overall >= 8 else "偏高" if overall >= 5 else "平穩"

        total  = sum(scrape_summary.values())
        now    = datetime.now().strftime("%H:%M")

        # 異常摘要（有異常才顯示）
        anomaly_part = ""
        if anomaly.get("count", 0) > 0:
            max_sev  = anomaly.get("max_severity", "LOW")
            sev_icon = {"LOW": "⚪", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}.get(max_sev, "⚪")
            top_item = anomaly["items"][0]
            anomaly_part = (
                f'\n{"─" * 28}\n'
                f'{sev_icon} <b>活躍異常：{anomaly["count"]} 個</b>\n'
                f'<i>{top_item["desc"][:60]}</i>'
            )

        # 取近2小時高分新聞作摘要連結
        from database.db import get_recent_news
        top_news = sorted(
            get_recent_news(hours=2, min_threat_score=3.0),
            key=lambda n: n.threat_score or 0, reverse=True
        )[:3]
        news_lines = ""
        for n in top_news:
            icon_n = "🔴" if (n.threat_score or 0) >= 7 else "🟠" if (n.threat_score or 0) >= 5 else "🟡"
            title  = (n.title or "")[:45]
            if n.url:
                news_lines += f'\n{icon_n} <a href="{n.url}">{title}</a>'
            else:
                news_lines += f"\n{icon_n} {title}"

        msg = (
            f"{status_icon} <b>台灣國防情勢 — 例行更新</b>\n"
            f'{"─" * 28}\n'
            f"⏰ {now}｜新增 <b>{total}</b> 筆\n"
            f"🏛️ 國防部 {scrape_summary.get('mnd', 0)} ｜ "
            f"🚢 海巡 {scrape_summary.get('cga', 0)} ｜ "
            f"💬 PTT {scrape_summary.get('ptt', 0)} ｜ "
            f"🌐 國際 {scrape_summary.get('intl', 0)}\n"
            f"🛡️ 威脅指數：<code>{overall:.1f}/10</code>  {sea_status}"
            f"{anomaly_part}"
            + (f"\n\n📰 <b>近期重點</b>{news_lines}" if news_lines else "")
            + f'\n{"─" * 28}\n/status 詳情　/today 日報'
        )

        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=msg,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        print("[ALERT] 例行狀態推送完成")
    except Exception as e:
        print(f"[ALERT ERROR] push_routine_status: {e}")


async def push_daily_snapshot(bot: Bot):
    """
    推送當日地圖快照圖片（日報附圖）
    playwright 未安裝時靜默跳過
    """
    try:
        from maps.map_generator import generate_snapshot_png
        png_path = generate_snapshot_png(days=1)
        if not png_path or not os.path.exists(png_path):
            return

        now_str = datetime.now().strftime("%Y-%m-%d")
        caption = f"🗺️ <b>今日態勢地圖</b>  {now_str}"

        with open(png_path, "rb") as f:
            await bot.send_photo(
                chat_id=TELEGRAM_CHANNEL_ID,
                photo=f,
                caption=caption,
                parse_mode=ParseMode.HTML
            )
        print("[ALERT] 當日地圖快照推送完成")
    except Exception as e:
        print(f"[ALERT ERROR] push_daily_snapshot: {e}")


async def push_weekly_snapshot(bot: Bot):
    """推送 7 日熱力地圖快照（週報附圖）"""
    try:
        from maps.map_generator import generate_snapshot_png
        png_path = generate_snapshot_png(days=7)
        if not png_path or not os.path.exists(png_path):
            return

        start = (datetime.now() - __import__("datetime").timedelta(days=7)).strftime("%m/%d")
        end   = datetime.now().strftime("%m/%d")
        caption = f"🗺️ <b>本週態勢地圖</b>  {start}～{end}"

        with open(png_path, "rb") as f:
            await bot.send_photo(
                chat_id=TELEGRAM_CHANNEL_ID,
                photo=f,
                caption=caption,
                parse_mode=ParseMode.HTML
            )
        print("[ALERT] 週報地圖快照推送完成")
    except Exception as e:
        print(f"[ALERT ERROR] push_weekly_snapshot: {e}")


async def run_all_alerts(bot: Bot):
    """排程呼叫入口"""
    await push_instant_alerts(bot)
    await push_score_alerts(bot)
    await push_ptt_hot(bot, threshold=50)
