# 檔案名稱：analyzer/anomaly_detector.py
# 功能說明：各 scraper 獨立異常偵測，規則引擎優先，減少 Ollama 呼叫

import statistics
from datetime import datetime, timedelta
from typing import Optional
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db import (
    get_recent_news, get_intrusion_stats,
    get_all_cable_status, get_cog_war_news,
    insert_anomaly, get_active_anomalies,
    resolve_anomalies_by_type, has_recent_anomaly,
    get_news_by_source, get_news_count_by_source,
    get_anomaly_history,
)

SEV_LOW      = "LOW"
SEV_MEDIUM   = "MEDIUM"
SEV_HIGH     = "HIGH"
SEV_CRITICAL = "CRITICAL"


def _rolling_stats(values: list) -> dict:
    if not values:
        return {"mean": 0.0, "stdev": 0.0, "median": 0.0}
    mean   = statistics.mean(values)
    stdev  = statistics.stdev(values) if len(values) >= 2 else 0.0
    median = statistics.median(values)
    return {"mean": mean, "stdev": stdev, "median": median}


def _news_in_window(start: datetime, end: datetime) -> list:
    from database.db import get_session
    from database.models import NewsEvent
    from sqlalchemy import and_
    session = get_session()
    try:
        return session.query(NewsEvent).filter(
            and_(NewsEvent.fetched_at >= start,
                 NewsEvent.fetched_at < end)
        ).all()
    finally:
        session.close()


def _get_daily_news_counts(source: str, days: int = 14) -> list:
    counts = []
    for i in range(days, 0, -1):
        start = datetime.now() - timedelta(days=i)
        end   = datetime.now() - timedelta(days=i - 1)
        from database.db import get_session
        from database.models import NewsEvent
        from sqlalchemy import func, and_
        session = get_session()
        try:
            c = session.query(func.count(NewsEvent.id)).filter(
                and_(NewsEvent.source == source,
                     NewsEvent.fetched_at >= start,
                     NewsEvent.fetched_at < end)
            ).scalar() or 0
            counts.append(c)
        finally:
            session.close()
    return counts


# ==============================
# 1. 認知作戰（事實查核 + 說法比對）
# ==============================

def check_cog_war_spike() -> Optional[dict]:
    """
    認知作戰（不用 AI，兩種訊號擇一）：
    1. 事實查核機構 24 小時內確認 ≥ 3 則涉兩岸／國防的不實訊息
    2. 對台說法比對：官媒在推 + 台灣端出現量暴增（analyzer/narratives.py）
    """
    SCRAPER = "all"
    ATYPE   = "COG_WAR_SPIKE"
    FC_HIGH = 3
    FC_CRIT = 6

    fc_items = get_cog_war_news(hours=24)
    fc_count = len(fc_items)
    try:
        from analyzer.narratives import scan_narratives
        signals = [n for n in scan_narratives() if n["signal"]]
    except Exception as e:
        print(f"[ANOMALY] 說法比對跳過：{e}")
        signals = []

    if fc_count < FC_HIGH and not signals:
        resolve_anomalies_by_type(SCRAPER, ATYPE)
        return None

    if has_recent_anomaly(SCRAPER, ATYPE, hours=6):
        return None

    severity = SEV_CRITICAL if (fc_count >= FC_CRIT or (fc_count >= FC_HIGH and signals)) else SEV_HIGH
    parts = []
    if fc_count >= FC_HIGH:
        parts.append(f"查核機構 24h 確認 {fc_count} 則涉兩岸/國防不實訊息")
    if signals:
        parts.append("說法升溫：" + "、".join(n["name"] for n in signals[:3]))
    desc = "認知作戰升溫 — " + "；".join(parts)

    lines = ["什麼意思："]
    if fc_count >= FC_HIGH:
        lines.append(f"事實查核機構近 24 小時確認 {fc_count} 則與兩岸、國防相關的不實訊息：")
        for n in fc_items[:3]:
            lines.append(f"• {(n.title or '')[:40]}")
    for n in signals[:3]:
        lines.append(f"「{n['name']}」：官媒近 3 日 {n['cn_3d']} 則，"
                     f"台灣討論 24h {n['tw_24h']} 則（平常日均 {n['tw_baseline']}）")
    lines.append("查核結果來自台灣事實查核中心、MyGoPen；說法熱度為關鍵字統計，不代表個別文章或發文者立場。")
    explanation = "\n".join(lines)

    aid = insert_anomaly(SCRAPER, ATYPE, severity, float(fc_count), 0.0, 0.0, desc)
    return {"id": aid, "type": ATYPE, "severity": severity,
            "desc": desc, "explanation": explanation}


# ==============================
# 2. 越海峽中線
# ==============================

HIGH_THREAT_TYPES = ["轟-6", "殲-16", "殲-11"]


def check_median_line_crossing() -> Optional[dict]:
    SCRAPER = "mnd"
    ATYPE   = "MEDIAN_LINE_CROSS"

    stats_1d, records_1d = get_intrusion_stats(days=1)
    stats_2d, _          = get_intrusion_stats(days=2)

    today_cross    = stats_1d.get("median_line_crossings", 0)
    today_aircraft = stats_1d.get("total_aircraft", 0)
    today_adiz     = stats_1d.get("adiz_entries", 0)

    if today_cross == 0:
        resolve_anomalies_by_type(SCRAPER, ATYPE)
        return None

    has_high_threat = False
    for r in records_1d:
        if r.crossed_median_line and r.aircraft_types:
            for ht in HIGH_THREAT_TYPES:
                if ht in (r.aircraft_types or ""):
                    has_high_threat = True
                    break

    consecutive = stats_2d.get("median_line_crossings", 0) >= 2

    if has_high_threat or (today_cross > 0 and today_adiz > 0):
        severity  = SEV_CRITICAL
        type_note = "高威脅機型越線" if has_high_threat else "越線+ADIZ雙重事件"
        desc = (f"緊急：{type_note}，今日越中線 {today_cross} 次，"
                f"共機 {today_aircraft} 架，ADIZ 進入 {today_adiz} 次")
    elif today_cross >= 4 or consecutive:
        severity = SEV_HIGH
        reason   = f"單日 {today_cross} 架次" if today_cross >= 4 else "連續2日越線"
        desc = (f"越海峽中線異常：{reason}，"
                f"共機 {today_aircraft} 架，ADIZ 進入 {today_adiz} 次")
    elif today_cross >= 1:
        severity = SEV_MEDIUM
        desc     = f"越海峽中線：今日 {today_cross} 次，共機 {today_aircraft} 架"
    else:
        return None

    if has_recent_anomaly(SCRAPER, ATYPE, hours=6):
        return None

    month_stats, _ = get_intrusion_stats(days=30)
    monthly_cross  = month_stats.get("median_line_crossings", 0)

    explanation = (
        f"什麼意思：\n"
        f"共軍軍機越過台海中線，進入台灣防衛縱深。\n"
        f"海峽中線是台海雙方長期默契的界線，越線代表刻意挑釁。\n"
        f"本月累計越線 {monthly_cross} 次。"
    )
    if has_high_threat:
        explanation += "\n轟-6/殲-16 等重型機越線，具備對地攻擊或空優作戰能力，威脅等級更高。"

    aid = insert_anomaly(SCRAPER, ATYPE, severity,
                         float(today_cross), 0.0, 100.0, desc)
    return {"id": aid, "type": ATYPE, "severity": severity,
            "desc": desc, "explanation": explanation}


# ==============================
# 3. 共艦異常聚集
# ==============================

def check_vessel_cluster() -> Optional[dict]:
    SCRAPER         = "ais"
    ATYPE           = "VESSEL_CLUSTER"
    WARN_THRESHOLD  = 8
    CARRIER_KEYWORD = ["遼寧", "山東", "福建", "航母"]

    from database.db import get_session
    from database.models import VesselTracking
    session = get_session()
    try:
        cutoff  = datetime.now() - timedelta(hours=6)
        vessels = session.query(VesselTracking).filter(
            VesselTracking.recorded_at >= cutoff,
            VesselTracking.is_suspicious == True
        ).all()
    finally:
        session.close()

    count = len(vessels)
    if count == 0:
        resolve_anomalies_by_type(SCRAPER, ATYPE)
        return None

    carrier_present = any(
        any(kw in (v.vessel_name or "") for kw in CARRIER_KEYWORD)
        for v in vessels
    )
    east_count = sum(1 for v in vessels if (v.longitude or 0) > 122)
    west_count = sum(1 for v in vessels if (v.longitude or 0) < 120)
    flanking   = east_count >= 2 and west_count >= 2

    if carrier_present or flanking:
        severity = SEV_CRITICAL
        reason   = "航母戰鬥群" if carrier_present else "東西雙側包夾態勢"
        desc = (f"緊急：{reason}，可疑船隻 {count} 艘，"
                f"東側 {east_count} 艘，西側 {west_count} 艘")
    elif count >= WARN_THRESHOLD:
        severity = SEV_HIGH
        desc = (f"共艦異常聚集：可疑船隻 {count} 艘（閾值 {WARN_THRESHOLD}），"
                f"東側 {east_count}，西側 {west_count}")
    elif count >= 5:
        severity = SEV_MEDIUM
        desc     = f"共艦動態：可疑船隻 {count} 艘，持續監控中"
    else:
        return None

    if has_recent_anomaly(SCRAPER, ATYPE, hours=3):
        return None

    explanation = f"什麼意思：\n台灣周邊海域出現 {count} 艘中國籍可疑船隻。\n"
    if carrier_present:
        explanation += "偵測到航母戰鬥群特徵，解放軍海軍具備遠洋作戰能力。\n"
    if flanking:
        explanation += (
            f"東側 {east_count} 艘、西側 {west_count} 艘，\n"
            f"形成東西夾擊態勢，為封鎖演習的典型部署模式。"
        )
    else:
        explanation += "持續追蹤船隻動向，關注是否形成集結態勢。"

    aid = insert_anomaly(SCRAPER, ATYPE, severity,
                         float(count), 5.0,
                         ((count - 5) / 5) * 100, desc)
    return {"id": aid, "type": ATYPE, "severity": severity,
            "desc": desc, "explanation": explanation}


# ==============================
# 4. 共機大規模擾台
# ==============================

def check_aircraft_surge() -> Optional[dict]:
    SCRAPER        = "mnd"
    ATYPE          = "AIRCRAFT_SURGE"
    MED_THRESHOLD  = 15
    HIGH_THRESHOLD = 25
    CRIT_THRESHOLD = 40

    stats, _ = get_intrusion_stats(days=1)
    count    = stats.get("total_aircraft", 0)

    history = []
    for i in range(14, 0, -1):
        s, _ = get_intrusion_stats(days=i)
        history.append(float(s.get("total_aircraft", 0)))
    stats_h  = _rolling_stats(history)
    baseline = stats_h["mean"]
    dev_pct  = ((count - baseline) / max(baseline, 1)) * 100

    if count >= CRIT_THRESHOLD:
        severity = SEV_CRITICAL
        desc = (f"緊急：共機 {count} 架次擾台（閾值 {CRIT_THRESHOLD}），"
                f"14日均值 {baseline:.1f} 架，偏離 +{dev_pct:.0f}%")
    elif count >= HIGH_THRESHOLD:
        severity = SEV_HIGH
        desc = (f"共機大規模擾台：{count} 架次，"
                f"14日均值 {baseline:.1f}，偏離 +{dev_pct:.0f}%")
    elif count >= MED_THRESHOLD:
        severity = SEV_MEDIUM
        dev_str2 = f"+{dev_pct:.0f}%" if dev_pct > 0 else f"{dev_pct:.0f}%"
        desc     = f"共機擾台：今日 {count} 架次，14日均值 {baseline:.1f} 架（{dev_str2}）"
    else:
        resolve_anomalies_by_type(SCRAPER, ATYPE)
        return None

    if has_recent_anomaly(SCRAPER, ATYPE, hours=8):
        return None

    if dev_pct > 0:
        dev_str = f"比近14天平均（{baseline:.0f}架）高出 {dev_pct:.0f}%"
    elif dev_pct < 0:
        dev_str = f"比近14天平均（{baseline:.0f}架）低 {abs(dev_pct):.0f}%"
    else:
        dev_str = f"與近14天平均（{baseline:.0f}架）相當"

    explanation = f"今日共機 {count} 架次，{dev_str}。\n"
    if count >= CRIT_THRESHOLD:
        explanation += "達到大規模演習規模，需高度警戒。"
    elif count >= HIGH_THRESHOLD:
        explanation += "架次明顯高於常態，與歷史演習前模式相符，建議持續關注。"
    else:
        explanation += "架次偏高，持續監控是否進一步升溫。"

    aid = insert_anomaly(SCRAPER, ATYPE, severity,
                         float(count), baseline, dev_pct, desc)
    return {"id": aid, "type": ATYPE, "severity": severity,
            "desc": desc, "explanation": explanation}


# ==============================
# 5. PTT 軍武板異常
# ==============================

def check_ptt_surge() -> Optional[dict]:
    SCRAPER        = "ptt"
    ATYPE          = "PTT_SURGE"
    WARN_MULT      = 1.8
    CRIT_MULT      = 2.5
    PANIC_KEYWORDS = ["動員", "封鎖", "攻台", "開戰", "備戰", "疏散"]
    PANIC_THRESH   = 5

    history     = _get_daily_news_counts("ptt", days=7)
    today_count = get_news_count_by_source("ptt", hours=24)

    if not history or sum(history) == 0:
        return None

    stats    = _rolling_stats([float(c) for c in history])
    baseline = stats["mean"]
    if baseline == 0:
        return None

    dev_pct    = ((today_count - baseline) / baseline) * 100
    today_news = get_news_by_source("ptt", hours=24)
    panic_count = sum(
        1 for n in today_news
        if any(kw in (n.title or "") + (n.content or "") for kw in PANIC_KEYWORDS)
    )

    if today_count >= baseline * CRIT_MULT or panic_count >= PANIC_THRESH:
        severity = SEV_CRITICAL
        reason   = f"高危關鍵字 {panic_count} 篇" if panic_count >= PANIC_THRESH else f"發文量 {today_count} 篇"
        desc = (f"PTT 軍武板異常：{reason}，"
                f"7日均值 {baseline:.1f}，偏離 +{dev_pct:.0f}%")
    elif today_count >= baseline * WARN_MULT:
        severity = SEV_HIGH
        desc = (f"PTT 軍武板發文激增：今日 {today_count} 篇，"
                f"7日均值 {baseline:.1f}，偏離 +{dev_pct:.0f}%")
    else:
        resolve_anomalies_by_type(SCRAPER, ATYPE)
        return None

    if has_recent_anomaly(SCRAPER, ATYPE, hours=4):
        return None

    explanation = (
        f"什麼意思：\n"
        f"PTT 軍武板今日發文 {today_count} 篇，比7日均值（{baseline:.0f}篇）{'高出 ' + str(int(dev_pct)) + '%' if dev_pct > 0 else '相當'}。\n"
    )
    if panic_count >= PANIC_THRESH:
        explanation += f"其中 {panic_count} 篇含有「{PANIC_KEYWORDS[0]}」等高度緊張字眼，民間情緒明顯升溫。"
    else:
        explanation += "民間對台海情勢討論熱度偏高，反映社會關注程度上升。"

    aid = insert_anomaly(SCRAPER, ATYPE, severity,
                         float(today_count), baseline, dev_pct, desc)
    return {"id": aid, "type": ATYPE, "severity": severity,
            "desc": desc, "explanation": explanation}


# ==============================
# 6. 國際媒體集中報導
# ==============================

def check_intl_coverage_spike() -> Optional[dict]:
    SCRAPER          = "intl_news"
    ATYPE            = "INTL_COVERAGE_SPIKE"
    WARN_COUNT       = 3
    ESCALATION_WORDS = ["contingency", "deployment", "mobiliz", "strike group",
                        "combat ready", "evacuation", "war plan"]

    today_news = get_news_by_source("intl_news", hours=24)
    count      = len(today_news)

    if count < WARN_COUNT:
        resolve_anomalies_by_type(SCRAPER, ATYPE)
        return None

    escalation_hits = [
        n for n in today_news
        if any(w in (n.title or "").lower() + (n.content or "").lower()
               for w in ESCALATION_WORDS)
    ]

    history  = _get_daily_news_counts("intl_news", days=7)
    stats    = _rolling_stats([float(c) for c in history]) if history else {"mean": 1.0}
    baseline = max(stats["mean"], 1.0)
    dev_pct  = ((count - baseline) / baseline) * 100

    if escalation_hits:
        severity       = SEV_CRITICAL
        keywords_found = set(
            w for n in escalation_hits
            for w in ESCALATION_WORDS
            if w in (n.title or "").lower() + (n.content or "").lower()
        )
        desc = (f"緊急：國際媒體出現軍事行動字眼 {list(keywords_found)[:3]}，"
                f"今日報導 {count} 篇")
    elif count >= WARN_COUNT:
        severity = SEV_HIGH
        desc = (f"國際媒體集中報導台海：今日 {count} 篇，"
                f"7日均值 {baseline:.1f}，偏離 +{dev_pct:.0f}%")
    else:
        return None

    if has_recent_anomaly(SCRAPER, ATYPE, hours=6):
        return None

    explanation = (
        f"什麼意思：\n"
        f"今日 {count} 篇國際主流媒體同時報導台海，比7日均值高出 {dev_pct:.0f}%。\n"
    )
    if escalation_hits:
        kw_list      = list(keywords_found)[:2]
        explanation += (
            f"出現「{'、'.join(kw_list)}」等軍事行動字眼，\n"
            f"顯示西方政府或軍事機構已開始公開討論台海應變計畫。"
        )
    else:
        explanation += "國際輿論對台海的關注度異常升高，通常先於政治或軍事局勢升溫。"

    aid = insert_anomaly(SCRAPER, ATYPE, severity,
                         float(count), baseline, dev_pct, desc)
    return {"id": aid, "type": ATYPE, "severity": severity,
            "desc": desc, "explanation": explanation}


# ==============================
# 7. 海底電纜異常
# ==============================

_last_cable_signature = None   # 上次觸發時的 (電纜, 狀態) 組合


def check_cable_incident() -> Optional[dict]:
    """
    MODA 的障礙常持續數週～一年以上，若每 2 小時重觸發就會一直洗版
    → 只有「異常電纜組合改變」（新增障礙/升級為中斷）才產生新異常；
      組合不變時每 24 小時最多提醒一次
    """
    global _last_cable_signature
    SCRAPER = "cable_monitor"
    ATYPE   = "CABLE_INCIDENT"

    cables          = get_all_cable_status()
    if not cables:
        return None

    critical_cables = [c for c in cables
                       if c.status in ("中斷",) or "破壞" in (c.incident_type or "")]
    warning_cables  = [c for c in cables
                       if c.status in ("障礙", "異常", "維修中")
                       and c not in critical_cables]

    if critical_cables:
        severity = SEV_CRITICAL
        names    = "、".join(c.cable_name for c in critical_cables[:3])
        desc     = f"緊急：海底電纜中斷/疑似破壞 — {names}"
    elif warning_cables:
        severity = SEV_HIGH
        names    = "、".join(c.cable_name for c in warning_cables[:3])
        desc     = f"海底電纜異常：{names}（狀態：{warning_cables[0].status}）"
    else:
        _last_cable_signature = None
        resolve_anomalies_by_type(SCRAPER, ATYPE)
        return None

    signature = tuple(sorted((c.cable_name, c.status) for c in critical_cables + warning_cables))
    recent    = has_recent_anomaly(SCRAPER, ATYPE, hours=24)
    if recent and (_last_cable_signature is None or signature == _last_cable_signature):
        _last_cable_signature = signature      # 重啟後第一次：接續既有狀態，不重推
        return None
    _last_cable_signature = signature

    cable_list  = critical_cables or warning_cables
    cable_names = "、".join(c.cable_name for c in cable_list[:2])
    explanation = f"什麼意思：\n{cable_names} 出現異常。\n"
    if critical_cables:
        explanation += (
            "海底電纜中斷會直接影響台灣對外國際網路頻寬，\n"
            "歷史上曾發生疑似人為破壞案例（2023年馬祖電纜）。\n"
            "需關注是否為協同行動的一部分。"
        )
    else:
        explanation += (
            "電纜處於異常或維修狀態，尚未完全中斷。\n"
            "持續監控是否升級為中斷。"
        )

    count = len(critical_cables) + len(warning_cables)
    aid   = insert_anomaly(SCRAPER, ATYPE, severity,
                           float(count), 0.0, 100.0, desc)
    return {"id": aid, "type": ATYPE, "severity": severity,
            "desc": desc, "explanation": explanation}


# ==============================
# 8. 國台辦措辭升級
# ==============================

GWYTB_CRIT_WORDS = ["武力", "戰爭", "軍事行動", "不惜一切", "絕不退讓", "武統", "必要措施"]
GWYTB_HIGH_WORDS = ["嚴重警告", "強烈譴責", "保留權利", "主權不容挑戰",
                    "嚴正交涉", "嚴重關切", "干涉內政"]


def check_gwytb_escalation() -> Optional[dict]:
    SCRAPER = "gwytb"
    ATYPE   = "GWYTB_ESCALATION"

    today_news = get_news_by_source("gwytb", hours=48)
    if not today_news:
        return None

    crit_hits = []
    high_hits = []
    for n in today_news:
        text = (n.title or "") + (n.content or "")
        for w in GWYTB_CRIT_WORDS:
            if w in text:
                crit_hits.append(w)
        for w in GWYTB_HIGH_WORDS:
            if w in text:
                high_hits.append(w)

    if crit_hits:
        severity = SEV_CRITICAL
        desc = (f"緊急：國台辦出現武力相關措辭「{'、'.join(set(crit_hits[:3]))}」，"
                f"近48小時 {len(today_news)} 篇聲明")
    elif high_hits:
        severity = SEV_HIGH
        desc = (f"國台辦措辭升級：「{'、'.join(set(high_hits[:3]))}」，"
                f"近48小時 {len(today_news)} 篇聲明")
    else:
        resolve_anomalies_by_type(SCRAPER, ATYPE)
        return None

    if has_recent_anomaly(SCRAPER, ATYPE, hours=12):
        return None

    explanation = "什麼意思：\n國台辦聲明措辭出現升溫跡象。\n"
    if crit_hits:
        explanation += (
            f"出現「{'、'.join(set(crit_hits[:2]))}」等字眼，\n"
            f"代表北京對台政策立場明顯強硬化，\n"
            f"歷史上此類措辭往往先於實際軍事行動出現。"
        )
    else:
        explanation += (
            f"出現「{'、'.join(set(high_hits[:2]))}」等強烈警告措辭，\n"
            f"顯示北京對當前兩岸情勢表達高度不滿。"
        )

    aid = insert_anomaly(SCRAPER, ATYPE, severity,
                         float(len(crit_hits + high_hits)), 0.0, 100.0, desc)
    return {"id": aid, "type": ATYPE, "severity": severity,
            "desc": desc, "explanation": explanation}


# ==============================
# 主執行函式
# ==============================

def run_all_detectors() -> list:
    detectors = [
        ("COG_WAR",  check_cog_war_spike),
        ("MEDIAN",   check_median_line_crossing),
        ("VESSEL",   check_vessel_cluster),
        ("AIRCRAFT", check_aircraft_surge),
        ("PTT",      check_ptt_surge),
        ("INTL",     check_intl_coverage_spike),
        ("CABLE",    check_cable_incident),
        ("GWYTB",    check_gwytb_escalation),
    ]

    new_anomalies = []
    for name, fn in detectors:
        try:
            result = fn()
            if result:
                new_anomalies.append(result)
                print(f"[ANOMALY] {name}: {result['severity']} — {result['desc'][:60]}")
        except Exception as e:
            print(f"[ANOMALY ERROR] {name}: {e}")

    if not new_anomalies:
        print(f"[ANOMALY] {datetime.now().strftime('%H:%M')} 無異常")

    return new_anomalies


def get_current_anomaly_summary() -> dict:
    active         = get_active_anomalies()
    severity_order = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

    if not active:
        return {"count": 0, "max_severity": None,
                "should_escalate": False, "items": []}

    max_sev         = max(active, key=lambda a: severity_order.get(a.severity, 0)).severity
    should_escalate = max_sev in (SEV_HIGH, SEV_CRITICAL)

    return {
        "count":           len(active),
        "max_severity":    max_sev,
        "should_escalate": should_escalate,
        "items": [
            {
                "type":     a.anomaly_type,
                "severity": a.severity,
                "scraper":  a.scraper,
                "desc":     a.description,
                "detected": a.detected_at.strftime("%H:%M"),
                "duration": a.duration_minutes,
            }
            for a in sorted(active,
                            key=lambda a: severity_order.get(a.severity, 0),
                            reverse=True)
        ],
    }


if __name__ == "__main__":
    print("=" * 55)
    print("[ANOMALY] 執行全域異常偵測...")
    print("=" * 55)
    results = run_all_detectors()
    print(f"\n[ANOMALY] 本次偵測到 {len(results)} 個新異常")
    summary = get_current_anomaly_summary()
    print(f"[ANOMALY] 目前活躍異常：{summary['count']} 個")
    for item in summary.get("items", []):
        print(f"  {item['severity']:8} | {item['type']:25} | {item['desc'][:50]}")