# 檔案名稱：scheduler.py
# 功能說明：排程控制器，三級排程 + 動態升頻 + 異常偵測整合

import asyncio
import logging
import sys
import os
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Bot

sys.path.append(os.path.dirname(__file__))
from config import (
    TELEGRAM_CHANNEL_ID,
    SCRAPER_INTERVAL_MINUTES, ALERT_CHECK_INTERVAL_MINUTES,
    DAILY_REPORT_HOUR, DAILY_REPORT_MINUTE
)

logger = logging.getLogger(__name__)

# ==============================
# 通知去重 cache（避免同一事件重複推送）
# ==============================
_notified_cache: dict = {}  # {cache_key: last_notified_datetime}


def _should_notify(cache_key: str, cooldown_hours: float,
                   force_if_escalated: bool = False,
                   new_severity: str = "", old_severity: str = "") -> bool:
    """
    判斷是否應該推送通知
    cooldown_hours: 冷卻時間（小時）
    force_if_escalated: 嚴重度升級時強制推送（用於電纜狀態升級）
    """
    if force_if_escalated and new_severity and old_severity and new_severity != old_severity:
        severity_order = {"正常": 0, "資訊": 0, "障礙": 1, "異常": 1, "維修中": 1, "中斷": 2}
        if severity_order.get(new_severity, 0) > severity_order.get(old_severity, 0):
            _notified_cache[cache_key] = datetime.now()
            return True

    last = _notified_cache.get(cache_key)
    if last is None or (datetime.now() - last).total_seconds() > cooldown_hours * 3600:
        _notified_cache[cache_key] = datetime.now()
        return True
    return False


# ==============================
# 動態升頻狀態追蹤
# 記錄哪些 scraper 目前處於升頻模式，以及何時恢復正常
# ==============================
_escalated_scrapers: dict[str, datetime] = {}   # {scraper_id: 恢復正常時間}
ESCALATION_DURATION_HOURS = 4                    # 升頻持續 4 小時後自動恢復

# 升頻時的間隔（分鐘）
ESCALATED_INTERVAL = 15

# 各 scraper 正常間隔（分鐘）
NORMAL_INTERVALS = {
    "check_alerts":  2,
    "anomaly_check": 5,
    "intl_news":     30,
    "scrape_all":    SCRAPER_INTERVAL_MINUTES,
    "ptt_realtime":  30,    # 原本 5 分鐘，改為 30 分鐘
    "gwytb_check":   60,
    "analyze_news":  60,
    "ais_scrape":    120,
    "thinktank":     120,
    "cable_monitor": 240,   # 與 build_scheduler 一致（4 小時）
}


def is_escalated(scraper_id: str) -> bool:
    """檢查某 scraper 是否處於升頻狀態"""
    if scraper_id not in _escalated_scrapers:
        return False
    if datetime.now() >= _escalated_scrapers[scraper_id]:
        # 時間到，自動解除
        del _escalated_scrapers[scraper_id]
        print(f"[SCHED] ✅ {scraper_id} 升頻解除，恢復正常頻率")
        return False
    return True


def escalate_scraper(scheduler: AsyncIOScheduler, scraper_id: str, reason: str = ""):
    """將指定 scraper 升頻到 15 分鐘，持續 4 小時"""
    if is_escalated(scraper_id):
        return  # 已經在升頻中，不重複設定

    expire_at = datetime.now() + timedelta(hours=ESCALATION_DURATION_HOURS)
    _escalated_scrapers[scraper_id] = expire_at

    try:
        job = scheduler.get_job(scraper_id)
        if job:
            scheduler.reschedule_job(
                scraper_id,
                trigger=IntervalTrigger(minutes=ESCALATED_INTERVAL)
            )
            print(f"[SCHED] 🔴 {scraper_id} 升頻至 {ESCALATED_INTERVAL} 分鐘"
                  f"（原因：{reason}，持續至 {expire_at.strftime('%H:%M')}）")
    except Exception as e:
        logger.error(f"[SCHED] 升頻失敗 {scraper_id}: {e}")


def maybe_restore_normal(scheduler: AsyncIOScheduler, scraper_id: str):
    """檢查並恢復正常頻率（升頻期間結束後呼叫）"""
    if scraper_id in _escalated_scrapers:
        return  # 還在升頻中
    normal = NORMAL_INTERVALS.get(scraper_id)
    if not normal:
        return
    try:
        job = scheduler.get_job(scraper_id)
        if job:
            scheduler.reschedule_job(
                scraper_id,
                trigger=IntervalTrigger(minutes=normal)
            )
    except Exception:
        pass


# ==============================
# 異常偵測任務（核心新增）
# ==============================

async def task_anomaly_check(bot: Bot, scheduler: AsyncIOScheduler):
    """
    【5分鐘】異常偵測引擎
    跑所有 detector，有新異常時：
    1. 推 TG 警報
    2. 將相關 scraper 升頻
    """
    try:
        from analyzer.anomaly_detector import run_all_detectors, get_current_anomaly_summary
        from database.db import mark_anomaly_notified

        new_anomalies = run_all_detectors()

        for anomaly in new_anomalies:
            severity = anomaly.get("severity", "")
            desc     = anomaly.get("desc", "")
            aid      = anomaly.get("id")

            # MEDIUM 以上才推 TG，加 scheduler 層冷卻保護
            if severity in ("MEDIUM", "HIGH", "CRITICAL"):
                cache_key = f"anomaly_{anomaly.get('type', '')}"
                cooldown  = 2.0 if severity == "CRITICAL" else 4.0 if severity == "HIGH" else 8.0
                if _should_notify(cache_key, cooldown_hours=cooldown):
                    await _push_anomaly_alert(bot, anomaly)
                    if aid:
                        mark_anomaly_notified(aid)
                else:
                    print(f"[SCHED] 異常通知冷卻中：{anomaly.get('type','')}，跳過")

            # HIGH / CRITICAL 才升頻
            if severity in ("HIGH", "CRITICAL"):
                scraper = anomaly.get("type", "").lower()
                # 對應 anomaly_type → scheduler job_id
                SCRAPER_MAP = {
                    "median_line_cross": "scrape_all",
                    "aircraft_surge":    "scrape_all",
                    "vessel_cluster":    "ais_scrape",
                    "cable_incident":    "cable_monitor",
                    "ptt_surge":         "ptt_realtime",
                    "intl_coverage_spike": "intl_news",
                    "gwytb_escalation":  "gwytb_check",
                    "cog_war_spike":     "analyze_news",
                }
                job_id = SCRAPER_MAP.get(anomaly.get("type", "").lower())
                if job_id:
                    escalate_scraper(scheduler, job_id, reason=desc[:40])

        # 定期檢查升頻是否到期，恢復正常
        for scraper_id in list(_escalated_scrapers.keys()):
            is_escalated(scraper_id)          # 內部會自動清除過期的
            maybe_restore_normal(scheduler, scraper_id)

    except Exception as e:
        logger.error(f"[SCHED ERROR] 異常偵測: {e}")


async def _push_anomaly_alert(bot: Bot, anomaly: dict):
    """
    推送異常警報到 TG
    使用新格式：有白話說明 + 依類型附對應圖片
    """
    from telegram.constants import ParseMode
    from bot.formatter import format_anomaly_alert

    severity = anomaly.get("severity", "MEDIUM")
    atype    = anomaly.get("type", "")
    msg      = format_anomaly_alert(anomaly)

    # 依異常類型附對應圖片
    try:
        if atype == "MEDIAN_LINE_CROSS":
            from database.db import get_intrusion_stats
            from bot.alert_engine import push_mnd_with_card
            _, records = get_intrusion_stats(days=1)
            if records:
                r = records[0]
                await push_mnd_with_card(bot, {
                    "aircraft_count":      r.aircraft_count,
                    "vessel_count":        r.vessel_count,
                    "aircraft_types":      r.aircraft_types or "",
                    "crossed_median_line": r.crossed_median_line,
                    "adiz_entry":          r.adiz_entry,
                    "entry_direction":     r.entry_direction or "",
                    "date":                r.date.strftime("%Y-%m-%d"),
                    "raw_text":            r.raw_text or "",
                })
                return

        elif atype == "CABLE_INCIDENT":
            # task_cable_monitor 剛推過電纜警報（1 小時內）就不重複推
            recent_cable_push = any(
                k.startswith("cable_") and not k.startswith("cable_status_")
                and isinstance(t, datetime) and (datetime.now() - t).total_seconds() < 3600
                for k, t in _notified_cache.items()
            )
            if recent_cable_push:
                print("[SCHED] 電纜異常已由電纜監控推送，略過重複通知")
                return
            from database.db import get_all_cable_status
            from bot.alert_engine import push_cable_with_map
            cables = [{"cable_name": c.cable_name, "status": c.status,
                       "incident_type": c.incident_type}
                      for c in get_all_cable_status()
                      if c.status in ("中斷", "異常", "障礙")]
            if cables:
                await push_cable_with_map(bot, cables)
                return

        elif atype == "VESSEL_CLUSTER":
            from scrapers.ais import get_suspicious_vessels_summary
            from bot.alert_engine import push_ais_with_map
            vessels = get_suspicious_vessels_summary()
            if vessels:
                await push_ais_with_map(bot, vessels)
                return

    except Exception as e:
        logger.warning(f"[SCHED] 附圖失敗，改用純文字：{e}")

    # 純文字推送（附圖失敗的備援）
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=msg,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"[SCHED] 警報推送失敗: {e}")


# ==============================
# 既有排程任務（整理版）
# ==============================

async def task_check_alerts(bot: Bot):
    """【2分鐘】即時警報檢查（高威脅新聞推送）"""
    try:
        from bot.alert_engine import run_all_alerts
        await run_all_alerts(bot)
    except Exception as e:
        logger.error(f"[SCHED ERROR] 警報: {e}")


async def task_ptt_realtime(bot: Bot = None):
    """【30分鐘】PTT 軍武版監控（爆文 6 小時冷卻）"""
    print(f"[SCHED] {datetime.now().strftime('%H:%M')} PTT 掃描...")
    try:
        from scrapers.ptt import run as ptt_run, get_hot_articles
        results = await asyncio.to_thread(ptt_run)
        if bot and results:
            hot     = get_hot_articles(results, top_n=5)
            hot_100 = [a for a in hot if a.get("push_count", 0) >= 100]
            if hot_100 and _should_notify("ptt_hot", cooldown_hours=6):
                from bot.alert_engine import push_ptt_with_card
                await push_ptt_with_card(bot, hot_100)
    except Exception as e:
        logger.error(f"[SCHED ERROR] PTT: {e}")


async def task_intl_news(bot: Bot = None):
    """【30分鐘】國際軍事媒體 + 台灣官方"""
    print(f"[SCHED] {datetime.now().strftime('%H:%M')} 國際/官方新聞...")
    try:
        from scrapers.intl_news import run as intl_run
        from scrapers.gov_tw import run as gov_run
        intl_results = await asyncio.to_thread(intl_run)
        await asyncio.to_thread(gov_run)

        if bot and intl_results:
            high = [r for r in intl_results if r.get("priority")]
            if not high:
                return

            urgent = [r for r in high if any(
                w in " ".join(r.get("keywords", [])).lower()
                for w in ["invasion", "blockade", "amphibious", "war plan"]
            )]

            if urgent and _should_notify("intl_urgent", cooldown_hours=1):
                from bot.alert_engine import push_intl_with_card
                await push_intl_with_card(bot, urgent)
            elif high and _should_notify("intl_high", cooldown_hours=6):
                from bot.alert_engine import push_intl_with_card
                await push_intl_with_card(bot, high[:3])
    except Exception as e:
        logger.error(f"[SCHED ERROR] 國際/官方: {e}")


async def task_gwytb_check(bot: Bot = None):
    """【60分鐘】國台辦獨立監控"""
    print(f"[SCHED] {datetime.now().strftime('%H:%M')} 國台辦...")
    try:
        from scrapers.gwytb import run as gwytb_run
        results = await asyncio.to_thread(gwytb_run)

        # 有升溫聲明才推卡片
        if bot and results:
            escalations = [r for r in results if r.get("tone") == "escalation"]
            if escalations:
                from bot.alert_engine import push_gwytb_with_card
                await push_gwytb_with_card(bot, escalations)
    except Exception as e:
        logger.error(f"[SCHED ERROR] 國台辦: {e}")


async def task_analyze_news():
    """
    【60分鐘】AI評分 + 批次認知作戰偵測
    改用規則前置過濾 + batch_detect，大幅減少 Ollama 呼叫
    """
    print(f"[SCHED] {datetime.now().strftime('%H:%M')} AI評分+認知作戰...")
    try:
        from database.db import get_recent_news, update_news_ai_data, update_news_cog_war
        from analyzer.ollama_client import (
            analyze_news_threat, batch_detect_cognitive_warfare,
            check_ollama_available, rule_based_score
        )
        recent   = get_recent_news(hours=2)
        unscored = [n for n in recent if (n.threat_score or 0) == 0.0]
        print(f"[SCHED] 待評分：{len(unscored)} 則")

        # 沒有 Ollama 時改用純規則評分，否則 threat_score 永遠是 0、高威脅警報不會觸發
        if not check_ollama_available():
            for news in unscored[:50]:
                rule = rule_based_score(news.title or "", news.content or "", news.source or "")
                update_news_ai_data(news.id, (news.title or "")[:80], rule["score"])
            print(f"[SCHED] Ollama 未啟用，規則評分 {min(len(unscored), 50)} 則")
            return

        ai_called = 0
        skipped   = 0

        for news in unscored[:15]:
            # Ollama 呼叫是同步阻塞的，丟到 thread 才不會卡住 TG Bot 與其他排程
            result = await asyncio.to_thread(
                analyze_news_threat, news.title, news.content or "", news.source or ""
            )
            update_news_ai_data(news.id, result["summary"], result["score"])

            if result.get("ai_used"):
                ai_called += 1
            else:
                skipped += 1

            await asyncio.sleep(1)

        print(f"[SCHED] AI評分完成：AI呼叫 {ai_called} 次，規則跳過 {skipped} 次")

        # 批次認知作戰偵測（單次 Ollama 呼叫取代多次）
        high_score_news = [n for n in recent if (n.threat_score or 0) >= 3.0]
        if high_score_news:
            cog_results = await asyncio.to_thread(batch_detect_cognitive_warfare, high_score_news)
            for news_id, cog in cog_results.items():
                if cog.get("is_cog_war") and cog.get("confidence", 0) >= 75:
                    update_news_cog_war(
                        news_id,
                        cog["is_cog_war"],
                        cog["confidence"],
                        cog.get("indicators", [])
                    )

    except Exception as e:
        logger.error(f"[SCHED ERROR] AI評分: {e}")


def _make_scrape_task(bot: Bot):
    """建立完整爬蟲任務（閉包，帶 bot 參數）"""
    async def _task():
        print(f"[SCHED] {datetime.now().strftime('%H:%M')} 完整爬蟲...")
        summary = {"mnd": 0, "cga": 0, "ptt": 0, "intl": 0}
        try:
            from scrapers.mnd import run as mnd_run
            from scrapers.cga import run as cga_run
            from scrapers.news import run as news_run
            from scrapers.gwytb import run as gwytb_run
            from scrapers.ptt import run as ptt_run
            from scrapers.intl_news import run as intl_run
            from scrapers.gov_tw import run as gov_run

            mnd_results = await asyncio.to_thread(mnd_run)
            summary["mnd"] = len(mnd_results) if mnd_results else 0
            # MND 有新的擾台紀錄時推送卡片
            if mnd_results and bot:
                from database.db import get_intrusion_stats
                from database.models import IntrusionRecord
                from database.db import get_session
                from datetime import timedelta
                sess = get_session()
                try:
                    cutoff   = datetime.now() - timedelta(hours=2)
                    latest   = sess.query(IntrusionRecord).filter(
                        IntrusionRecord.date >= cutoff
                    ).order_by(IntrusionRecord.date.desc()).first()
                    if latest and latest.aircraft_count > 0:
                        from bot.alert_engine import push_mnd_with_card
                        asyncio.create_task(push_mnd_with_card(bot, {
                            "aircraft_count":      latest.aircraft_count,
                            "vessel_count":        latest.vessel_count,
                            "aircraft_types":      latest.aircraft_types or "",
                            "crossed_median_line": latest.crossed_median_line,
                            "adiz_entry":          latest.adiz_entry,
                            "entry_direction":     latest.entry_direction or "",
                            "date":                latest.date.strftime("%Y-%m-%d"),
                            "raw_text":            latest.raw_text or "",
                        }))
                finally:
                    sess.close()
            r = mnd_results
            r = await asyncio.to_thread(cga_run);  summary["cga"]  = len(r) if r else 0
            await asyncio.to_thread(news_run)
            await asyncio.to_thread(gwytb_run)
            r = await asyncio.to_thread(ptt_run);  summary["ptt"]  = len(r) if r else 0
            r = await asyncio.to_thread(intl_run); summary["intl"] = len(r) if r else 0
            await asyncio.to_thread(gov_run)
            print(f"[SCHED] 完整爬蟲完成 MND:{summary['mnd']} CGA:{summary['cga']} "
                  f"PTT:{summary['ptt']} INTL:{summary['intl']}")
        except Exception as e:
            logger.error(f"[SCHED ERROR] 爬蟲: {e}")

        # 只印 log，不推 TG（避免無關緊要的例行資訊打擾訂閱者）
        total_new = sum(summary.values())
        if total_new > 0:
            print(f"[SCHED] 例行掃描新資料：MND:{summary['mnd']} CGA:{summary['cga']} "
                  f"PTT:{summary['ptt']} INTL:{summary['intl']}")

    return _task


async def task_adsb_monitor(bot: Bot = None):
    """【30分鐘】ADS-B 軍機監控（白天頻率較高）"""
    from datetime import datetime
    hour = datetime.now().hour
    # 夜間（01:00-06:00）降低頻率，軍機活動少
    if 1 <= hour <= 6:
        print("[SCHED] 夜間模式，跳過 ADS-B 掃描")
        return
    try:
        from scrapers.adsb_monitor import run as adsb_run
        from bot.alert_engine import push_adsb_with_map
        results = await asyncio.to_thread(adsb_run)
        if bot and results:
            # 有軍機才推通知，4小時冷卻（避免同一批軍機重複推）
            us_mil  = [r for r in results if r.get("category") == "美軍偵察機"]
            pla_mil = [r for r in results if r.get("category") == "中共解放軍"]
            if pla_mil and _should_notify("adsb_pla", cooldown_hours=4):
                await push_adsb_with_map(bot, pla_mil, "中共解放軍")
            elif us_mil and _should_notify("adsb_us", cooldown_hours=6):
                await push_adsb_with_map(bot, us_mil, "美軍偵察機")
    except Exception as e:
        logger.error(f"[SCHED ERROR] ADS-B: {e}")


async def task_ais_scrape(bot: Bot = None):
    """【2小時】AIS船隻追蹤 + 民船徵用偵測"""
    try:
        from scrapers.ais import run as ais_run
        results = await asyncio.to_thread(ais_run)

        # 可疑軍艦通知（至少3艘）
        if bot and results and len(results) >= 3:
            from bot.alert_engine import push_ais_with_map
            await push_ais_with_map(bot, results)

        # 民船徵用偵測（每次 AIS 掃描後順帶分析）
        try:
            from scrapers.ais import get_requisition_summary
            summary = await asyncio.to_thread(get_requisition_summary)

            if bot and summary["bases_with_anomaly"] > 0:
                max_level = summary["max_level"]
                cooldown  = 4.0 if max_level == "CRITICAL" else 12.0
                if _should_notify("ais_requisition", cooldown_hours=cooldown):
                    await _push_requisition_alert(bot, summary)
        except Exception as e:
            logger.warning(f"[SCHED] 民船偵測失敗（非致命）：{e}")

    except Exception as e:
        logger.error(f"[SCHED ERROR] AIS: {e}")


async def _push_requisition_alert(bot, summary: dict):
    """推送民船徵用異常通知"""
    from telegram.constants import ParseMode
    now_str   = datetime.now().strftime("%m/%d %H:%M")
    max_level = summary["max_level"]
    icon      = "🚨" if max_level == "CRITICAL" else "⚠️"
    sev       = "緊急" if max_level == "CRITICAL" else "警示"

    lines = [
        f"{icon} <b>解放軍基地附近民船異常聚集</b>  <code>{now_str}</code>",
        f"{'─' * 28}",
        f"偵測到 <b>{summary['bases_with_anomaly']}</b> 個基地異常  {sev}",
        "",
    ]
    for base, info in summary["details"].items():
        lines += [
            f"📍 <b>{base}</b>  {info['count']} 艘  [{info['level']}]",
            f"  船隻：" + "、".join(
                v["name"] or "不明" for v in info["vessels"][:3]
            ),
            "",
        ]
    lines += [
        f"{'─' * 28}",
        "<i>解放軍兩棲登陸需徵用大量民船，基地附近民船大量聚集是重要前兆指標</i>",
    ]
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text="\n".join(lines),
            parse_mode=ParseMode.HTML
        )
        print(f"[SCHED] 民船徵用通知推送完成")
    except Exception as e:
        print(f"[SCHED] 民船推送失敗：{e}")


async def task_china_media(bot=None):
    """【每2小時】中共官媒輿論監控"""
    print(f"[SCHED] {datetime.now().strftime('%H:%M')} 中共官媒掃描...")
    try:
        from scrapers.china_media import run as cmedia_run, get_rhetoric_score
        results = await asyncio.to_thread(cmedia_run)
        if bot and results:
            l3    = [r for r in results if r["level"] == 3]
            high  = [r for r in results if r["level"] >= 2]
            score = get_rhetoric_score(results)
            if l3 and _should_notify("cmedia_critical", cooldown_hours=2):
                await _push_cmedia_alert(bot, l3, score, level=3)
            elif high and _should_notify("cmedia_high", cooldown_hours=6):
                await _push_cmedia_alert(bot, high, score, level=2)
    except Exception as e:
        logger.error(f"[SCHED ERROR] 中共官媒: {e}")


async def _push_cmedia_alert(bot, articles: list, score: float, level: int):
    """推送中共官媒輿論升溫通知"""
    from telegram.constants import ParseMode
    now_str = datetime.now().strftime("%m/%d %H:%M")
    icon    = "🚨" if level == 3 else "🟠"
    sev     = "緊急警示" if level == 3 else "高度警示"
    lines   = [
        f"{icon} <b>中共官媒對台措辭升溫</b>  <code>{now_str}</code>",
        f"{'─' * 28}",
        f"措辭強度：<b>{score:.1f}/10</b>  {sev}", "",
    ]
    for a in articles[:3]:
        lines += [
            f"📰 [{a['source']}]",
            f"  {a['title'][:55]}",
            f"  命中：{', '.join(a['keywords'][:2])}", "",
        ]
    lines += [
        f"{'─' * 28}",
        "<i>中共官媒措辭升溫常出現於軍事行動前的輿論準備期</i>",
    ]
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text="\n".join(lines),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        print(f"[SCHED] 中共官媒推送失敗：{e}")


async def task_thinktank(bot=None):
    """【每2小時】智庫監控"""
    print(f"[SCHED] {datetime.now().strftime('%H:%M')} 智庫掃描...")
    try:
        from scrapers.thinktank import run_with_notify
        await run_with_notify(bot)
    except Exception as e:
        logger.error(f"[SCHED ERROR] 智庫: {e}")


async def task_cable_monitor(bot: Bot = None):
    """【每4小時】海底電纜監控（只推 MODA 新增的障礙；同電纜 24h 冷卻，升級為中斷立即推）"""
    try:
        from scrapers.cable_monitor import run as cable_run
        results = await asyncio.to_thread(cable_run)

        if bot and results:
            to_notify = []
            for r in results:
                name   = r.get("cable_name", r.get("cable", "unknown"))
                status = r.get("status", "")
                if status not in ("中斷", "異常", "障礙"):
                    continue
                cache_key  = f"cable_{name}"
                old_status = _notified_cache.get(f"cable_status_{name}", "")
                if _should_notify(cache_key, cooldown_hours=24,
                                  force_if_escalated=True,
                                  new_severity=status,
                                  old_severity=old_status):
                    _notified_cache[f"cable_status_{name}"] = status
                    to_notify.append(r)

            if to_notify:
                from bot.alert_engine import push_cable_with_map
                await push_cable_with_map(bot, to_notify)
                print(f"[SCHED] 電纜通知推送：{len(to_notify)} 條")
            else:
                print(f"[SCHED] 電纜：有異常但冷卻中，不推送")
    except Exception as e:
        logger.error(f"[SCHED ERROR] 電纜監控: {e}")


async def task_oil_monitor(bot: Bot = None):
    """【每月1日】中國石油消耗指標更新"""
    print(f"[SCHED] {datetime.now().strftime('%m/%d')} 石油指標更新...")
    try:
        from scrapers.oil_monitor import run as oil_run
        result = await asyncio.to_thread(oil_run)
        if result:
            analysis = result["analysis"]
            level    = analysis["level"]
            # 只有 HIGH 以上才推通知
            if bot and level in ("HIGH", "CRITICAL"):
                from telegram.constants import ParseMode
                icon = "🚨" if level == "CRITICAL" else "🟠"
                msg  = (
                    f"{icon} <b>中國石油消耗指標異常</b>\n"
                    f"────────────────────────────\n"
                    f"{analysis['latest_year']} 年：<b>{analysis['latest_twh']:.0f} TWh</b>\n"
                    f"年增長：<b>{analysis['yoy_change_pct']:+.1f}%</b>\n"
                    f"5年平均增速：{analysis['avg_yoy_5yr']:+.1f}%\n\n"
                    f"{analysis['note']}\n"
                    f"────────────────────────────\n"
                    f"<i>石油消耗激增可能代表戰略儲備行為</i>"
                )
                await bot.send_message(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    text=msg, parse_mode=ParseMode.HTML
                )
    except Exception as e:
        logger.error(f"[SCHED ERROR] 石油指標: {e}")


async def task_morning_brief(bot: Bot):
    """【每日08:00】晨間概況推送（取代舊的例行掃描推送）"""
    print(f"[SCHED] 推送晨間概況...")
    try:
        from analyzer.threat_score import run_daily_scoring
        from analyzer.anomaly_detector import get_current_anomaly_summary
        from database.db import get_intrusion_stats
        from bot.formatter import format_morning_brief
        from telegram.constants import ParseMode

        threat_data        = run_daily_scoring()
        anomaly_summary    = get_current_anomaly_summary()
        intrusion_stats, _ = get_intrusion_stats(days=1)

        msg = format_morning_brief(threat_data, anomaly_summary, intrusion_stats)
        sent = await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=msg,
            parse_mode=ParseMode.HTML
        )

        # PIN 這條訊息（讓新訂閱者一進頻道就看到現況）
        try:
            await bot.pin_chat_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                message_id=sent.message_id,
                disable_notification=True
            )
        except Exception:
            pass  # 沒有 PIN 權限時靜默跳過

        print("[SCHED] 晨間概況推送完成")
    except Exception as e:
        logger.error(f"[SCHED ERROR] 晨報: {e}")


async def task_satellite(bot: Bot = None):
    """【每日08:00】衛星影像分析"""
    try:
        from scrapers.satellite import run as sat_run, CACHE_DIR
        results = await asyncio.to_thread(sat_run)

        # 分析完後推送衛星圖（附上今日快取的衛星影像）
        if bot and results:
            for r in results:
                if r.get("summary") not in ("API限制，稍後重試", "分析失敗", "無影像資料"):
                    import os
                    from datetime import datetime
                    area_name = r.get("area", "")
                    img_path  = os.path.join(
                        CACHE_DIR,
                        f"{area_name}_{datetime.now().strftime('%Y%m%d')}.png"
                    )
                    from bot.alert_engine import push_satellite_with_image
                    await push_satellite_with_image(
                        bot,
                        area_name      = area_name,
                        threat_level   = r.get("threat_level", 0),
                        summary        = r.get("summary", ""),
                        image_path     = img_path
                    )
    except Exception as e:
        logger.error(f"[SCHED ERROR] 衛星: {e}")


async def task_daily_scoring():
    """【每日19:00】威脅評分計算"""
    print(f"[SCHED] 計算威脅評分...")
    try:
        from analyzer.threat_score import run_daily_scoring
        result = run_daily_scoring()
        print(f"[SCHED] 今日評分：{result['overall']:.1f}")
    except Exception as e:
        logger.error(f"[SCHED ERROR] 評分: {e}")


async def task_daily_report(bot: Bot):
    """【每日20:00】每日報告推送 + 當日地圖快照"""
    print(f"[SCHED] 推送每日報告...")
    try:
        from bot.telegram_bot import push_daily_report
        await push_daily_report(bot)
    except Exception as e:
        logger.error(f"[SCHED ERROR] 日報: {e}")
    # 附上當日地圖截圖（playwright 未安裝時靜默跳過）
    try:
        from bot.alert_engine import push_daily_snapshot
        await push_daily_snapshot(bot)
    except Exception as e:
        logger.warning(f"[SCHED] 日報截圖跳過: {e}")


async def task_update_map():
    """【每日06:00/18:00】每日全量地圖更新"""
    try:
        from maps.map_generator import generate_defense_map
        await asyncio.to_thread(generate_defense_map)
        print("[SCHED] 全量地圖更新完成")
    except Exception as e:
        logger.error(f"[SCHED ERROR] 地圖: {e}")


async def task_realtime_map():
    """【每30分鐘】網頁嵌入用即時地圖（6小時滾動視窗）"""
    try:
        from maps.map_generator import generate_realtime_map
        await asyncio.to_thread(generate_realtime_map)
    except Exception as e:
        logger.error(f"[SCHED ERROR] 即時地圖: {e}")


async def task_weekly_report(bot: Bot):
    """【每週日21:00】週報推送"""
    print(f"[SCHED] 推送週報...")
    try:
        from database.db import get_intrusion_stats, get_recent_scores
        from analyzer.ollama_client import generate_weekly_report, check_ollama_available
        from bot.formatter import format_weekly_report
        from telegram.constants import ParseMode

        stats, _ = get_intrusion_stats(days=7)
        scores    = get_recent_scores(days=7)
        avg       = (sum(s.overall_score for s in scores) / len(scores)) if scores else 0
        peak      = max(scores, key=lambda s: s.overall_score) if scores else None

        weekly_data = {
            "week_start":       (datetime.now() - timedelta(days=7)).strftime("%m/%d"),
            "week_end":         datetime.now().strftime("%m/%d"),
            "total_intrusions": stats.get("total_incidents", 0),
            "total_aircraft":   stats.get("total_aircraft", 0),
            "median_crossings": stats.get("median_line_crossings", 0),
            "avg_threat":       round(avg, 2),
            "peak_day":         peak.date.strftime("%m/%d") if peak else "N/A",
            "peak_score":       peak.overall_score if peak else 0,
            "key_events":       "詳見每日日報",
        }

        ai_weekly = (await asyncio.to_thread(generate_weekly_report, weekly_data)) if check_ollama_available() else ""
        msg = format_weekly_report(weekly_data, ai_weekly)
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=msg,
            parse_mode=ParseMode.HTML      # 統一改用 HTML，避免 MarkdownV2 跳脫問題
        )
        print("[SCHED] 週報完成")
    except Exception as e:
        logger.error(f"[SCHED ERROR] 週報: {e}")
    # 附上7日地圖快照
    try:
        from bot.alert_engine import push_weekly_snapshot
        await push_weekly_snapshot(bot)
    except Exception as e:
        logger.warning(f"[SCHED] 週報截圖跳過: {e}")


async def task_cleanup():
    """【每週一03:00】清理舊檔案和資料庫"""
    import glob
    cleaned = 0
    cutoff  = datetime.now() - timedelta(days=7)
    base    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    for pattern in ["*.png", "satellite/*.png", "cards/*.png",
                    "map_shots/*.png", "map_shots/*.html"]:
        pattern = os.path.join(base, pattern)
        for f in glob.glob(pattern):
            if os.path.getmtime(f) < cutoff.timestamp():
                os.remove(f)
                cleaned += 1

    try:
        from database.db import get_session
        from database.models import NewsEvent, AnomalyLog
        session = get_session()
        cutoff_db     = datetime.now() - timedelta(days=90)
        cutoff_anomaly = datetime.now() - timedelta(days=30)
        deleted_news   = session.query(NewsEvent).filter(
            NewsEvent.published_at < cutoff_db
        ).delete()
        # 已解除的舊異常紀錄清理（保留 30 天）
        deleted_anomaly = session.query(AnomalyLog).filter(
            AnomalyLog.resolved_at != None,
            AnomalyLog.resolved_at < cutoff_anomaly
        ).delete()
        session.commit()
        session.close()
        print(f"[CLEANUP] 檔案:{cleaned} 舊新聞:{deleted_news} 舊異常:{deleted_anomaly}")
    except Exception as e:
        logger.error(f"[SCHED ERROR] 清理: {e}")


# ==============================
# 排程器建立
# ==============================

def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Taipei")

    # ── 即時層（2分鐘）─────────────────────────────
    # 高威脅新聞推送（threshold 7.0 以上）
    scheduler.add_job(
        task_check_alerts,
        IntervalTrigger(minutes=2),
        id="check_alerts", name="即時警報檢查",
        args=[bot], max_instances=1, coalesce=True
    )

    # ── 異常偵測層（5分鐘）─────────────────────────
    # 核心新增：跑所有 detector，觸發升頻
    scheduler.add_job(
        task_anomaly_check,
        IntervalTrigger(minutes=5),
        id="anomaly_check", name="異常偵測引擎",
        args=[bot, scheduler], max_instances=1, coalesce=True
    )

    # ── 高頻層（30分鐘）────────────────────────────
    scheduler.add_job(
        task_intl_news,
        IntervalTrigger(minutes=30),         # 從 15 分鐘改為 30 分鐘
        id="intl_news", name="國際軍事媒體",
        args=[bot], max_instances=1, coalesce=True
    )

    # ── 標準層（30-60分鐘）─────────────────────────
    scheduler.add_job(
        task_ptt_realtime,
        IntervalTrigger(minutes=30),         # 從 5 分鐘降到 30 分鐘
        id="ptt_realtime", name="PTT軍武版監控",
        args=[bot], max_instances=1, coalesce=True
    )
    scheduler.add_job(
        _make_scrape_task(bot),
        IntervalTrigger(minutes=SCRAPER_INTERVAL_MINUTES),
        id="scrape_all", name="完整爬蟲",
        max_instances=1, coalesce=True
    )
    scheduler.add_job(
        task_gwytb_check,
        IntervalTrigger(minutes=60),
        id="gwytb_check", name="國台辦監控",
        args=[bot], max_instances=1, coalesce=True
    )
    scheduler.add_job(
        task_analyze_news,
        IntervalTrigger(minutes=60),
        id="analyze_news", name="AI新聞評分",
        max_instances=1, coalesce=True
    )
    scheduler.add_job(
        task_cable_monitor,
        IntervalTrigger(hours=4),             # 電纜狀態變化慢，4小時爬一次
        id="cable_monitor", name="海底電纜監控",
        args=[bot], max_instances=1, coalesce=True
    )

    # ── 低頻層（2小時以上）─────────────────────────
    # ADS-B 軍機監控（每30分鐘，夜間自動跳過）
    scheduler.add_job(
        task_adsb_monitor,
        IntervalTrigger(minutes=30),
        id="adsb_monitor", name="ADS-B軍機監控",
        args=[bot], max_instances=1, coalesce=True
    )
    scheduler.add_job(
        task_ais_scrape,
        IntervalTrigger(hours=2),
        id="ais_scrape", name="AIS船隻追蹤",
        args=[bot], max_instances=1, coalesce=True
    )
    # 中共官媒輿論監控（每2小時）
    scheduler.add_job(
        task_china_media,
        IntervalTrigger(hours=2),
        id="china_media", name="中共官媒監控",
        args=[bot], max_instances=1, coalesce=True
    )
    scheduler.add_job(
        task_thinktank,
        IntervalTrigger(hours=2),
        id="thinktank", name="智庫監控",
        args=[bot], max_instances=1, coalesce=True
    )

    # ── 每日任務 ────────────────────────────────────
    # 石油指標（每月1日 06:00，月頻數據）
    scheduler.add_job(
        task_oil_monitor,
        CronTrigger(day=1, hour=6, minute=0, timezone="Asia/Taipei"),
        id="oil_monitor", name="石油消耗指標",
        args=[bot], max_instances=1, coalesce=True
    )
    # 晨間概況（08:00）
    scheduler.add_job(
        task_morning_brief,
        CronTrigger(hour=8, minute=0, timezone="Asia/Taipei"),
        id="morning_brief", name="晨間概況推送",
        args=[bot]
    )
    # 衛星分析（08:05，晨報之後）
    scheduler.add_job(
        task_satellite,
        CronTrigger(hour=8, minute=5, timezone="Asia/Taipei"),
        id="satellite", name="衛星影像分析",
        args=[bot]
    )
    scheduler.add_job(
        task_update_map,
        CronTrigger(hour=6, minute=0, timezone="Asia/Taipei"),
        id="update_map_am", name="早晨全量地圖"
    )
    scheduler.add_job(
        task_update_map,
        CronTrigger(hour=18, minute=0, timezone="Asia/Taipei"),
        id="update_map_pm", name="傍晚全量地圖"
    )
    # 網頁嵌入用即時地圖（6小時滾動視窗，每30分鐘刷新）
    scheduler.add_job(
        task_realtime_map,
        IntervalTrigger(minutes=30),
        id="realtime_map", name="即時地圖刷新",
        max_instances=1, coalesce=True
    )
    scheduler.add_job(
        task_daily_scoring,
        CronTrigger(hour=19, minute=0, timezone="Asia/Taipei"),
        id="daily_scoring", name="每日威脅評分"
    )
    scheduler.add_job(
        task_daily_report,
        CronTrigger(hour=DAILY_REPORT_HOUR, minute=DAILY_REPORT_MINUTE,
                    timezone="Asia/Taipei"),
        id="daily_report", name="每日報告推送",
        args=[bot]
    )

    # ── 每週任務 ────────────────────────────────────
    scheduler.add_job(
        task_weekly_report,
        CronTrigger(day_of_week="sun", hour=21, minute=0, timezone="Asia/Taipei"),
        id="weekly_report", name="每週週報",
        args=[bot]
    )
    scheduler.add_job(
        task_cleanup,
        CronTrigger(day_of_week="mon", hour=3, minute=0, timezone="Asia/Taipei"),
        id="cleanup", name="每週清理"
    )

    # ── 全域錯誤監聽 ────────────────────────────────
    def job_error_listener(event):
        if event.exception:
            import html
            job_id = event.job_id
            error  = html.escape(str(event.exception)[:200])
            print(f"[SCHED ERROR] Job {job_id}: {error}")
            try:
                from bot.error_notify import notify_admin
                asyncio.get_event_loop().create_task(
                    notify_admin(f"🔴 排程任務失敗\n任務：{job_id}\n錯誤：{error}")
                )
            except Exception:
                pass

    from apscheduler.events import EVENT_JOB_ERROR
    scheduler.add_listener(job_error_listener, EVENT_JOB_ERROR)

    return scheduler


def print_schedule(scheduler: AsyncIOScheduler):
    print("\n" + "="*60)
    print("📅 排程任務清單")
    print("="*60)

    # 分層顯示
    layers = {
        "🔴 即時層":   ["check_alerts"],
        "🟠 偵測層":   ["anomaly_check"],
        "🟡 高頻層":   ["intl_news"],
        "🟢 標準層":   ["ptt_realtime", "scrape_all", "gwytb_check",
                        "analyze_news", "cable_monitor", "adsb_monitor"],
        "⚪ 低頻層":   ["ais_scrape", "china_media", "thinktank"],
        "📅 每日任務": ["morning_brief", "satellite", "update_map_am", "update_map_pm",
                        "realtime_map", "daily_scoring", "daily_report"],
        "🗓️ 每月任務": ["oil_monitor"],
        "📆 每週任務": ["weekly_report", "cleanup"],
    }

    jobs_by_id = {j.id: j for j in scheduler.get_jobs()}
    for layer_name, job_ids in layers.items():
        print(f"\n  {layer_name}")
        for jid in job_ids:
            job = jobs_by_id.get(jid)
            if job:
                next_run = job.next_run_time.strftime("%H:%M") if job.next_run_time else "N/A"
                print(f"    ✅ {job.name:<20} 下次：{next_run}")
    print("="*60 + "\n")
