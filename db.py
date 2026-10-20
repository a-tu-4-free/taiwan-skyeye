# 檔案名稱：database/db.py
# 功能說明：資料庫 CRUD 操作封裝，提供新增、查詢、更新等常用函式給其他模組呼叫

from datetime import datetime, timedelta
from sqlalchemy import desc, and_, func
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.models import (
    get_session, NewsEvent, IntrusionRecord,
    CableStatus, DailyThreatScore, VesselTracking,
    AnomalyLog
)


# ==============================
# 新聞事件操作
# ==============================

def insert_news(source, title, content, url, published_at, category, keywords_matched):
    """新增一筆新聞事件，若URL已存在則跳過（無URL則用標題去重）"""
    session = get_session()
    try:
        if url:
            # 有 URL：以 URL 去重
            existing = session.query(NewsEvent).filter_by(url=url).first()
        else:
            # 無 URL：以來源+標題去重（避免空字串 url 全部被去重）
            existing = session.query(NewsEvent).filter_by(
                source=source, title=title
            ).first()
        if existing:
            return None  # 已存在，跳過

        news = NewsEvent(
            source=source,
            title=title,
            content=content,
            url=url,
            published_at=published_at,
            category=category,
            keywords_matched=",".join(keywords_matched) if keywords_matched else ""
        )
        session.add(news)
        session.commit()
        return news.id
    except Exception as e:
        session.rollback()
        print(f"[DB ERROR] insert_news: {e}")
        return None
    finally:
        session.close()


def get_recent_news(hours=24, category=None, min_threat_score=0.0):
    """取得最近N小時的新聞，可依分類和威脅分數篩選"""
    session = get_session()
    try:
        cutoff = datetime.now() - timedelta(hours=hours)
        query = session.query(NewsEvent).filter(
            NewsEvent.fetched_at >= cutoff,
            NewsEvent.threat_score >= min_threat_score
        )
        if category:
            query = query.filter(NewsEvent.category == category)
        return query.order_by(desc(NewsEvent.threat_score)).all()
    finally:
        session.close()


def get_unalerted_high_threat_news(threshold=7.0):
    """取得尚未推送警報且威脅分數超過閾值的新聞"""
    session = get_session()
    try:
        return session.query(NewsEvent).filter(
            NewsEvent.threat_score >= threshold,
            NewsEvent.is_alerted == False
        ).order_by(desc(NewsEvent.threat_score)).all()
    finally:
        session.close()


def mark_news_alerted(news_id):
    """標記新聞為已推送警報"""
    session = get_session()
    try:
        news = session.query(NewsEvent).filter_by(id=news_id).first()
        if news:
            news.is_alerted = True
            session.commit()
    except Exception as e:
        session.rollback()
        print(f"[DB ERROR] mark_news_alerted: {e}")
    finally:
        session.close()


def update_news_ai_data(news_id, summary, threat_score):
    """更新新聞的AI摘要和威脅分數"""
    session = get_session()
    try:
        news = session.query(NewsEvent).filter_by(id=news_id).first()
        if news:
            news.ai_summary = summary
            news.threat_score = threat_score
            session.commit()
    except Exception as e:
        session.rollback()
        print(f"[DB ERROR] update_news_ai_data: {e}")
    finally:
        session.close()


# ==============================
# 擾臺紀錄操作
# ==============================

def insert_intrusion(date, aircraft_count, vessel_count, aircraft_types,
                     crossed_median_line, adiz_entry, entry_direction,
                     source_url, raw_text):
    """新增擾臺紀錄"""
    session = get_session()
    try:
        # 檢查同日是否已有紀錄
        existing = session.query(IntrusionRecord).filter(
            func.date(IntrusionRecord.date) == date.date()
        ).first()
        if existing:
            return None

        record = IntrusionRecord(
            date=date,
            aircraft_count=aircraft_count,
            vessel_count=vessel_count,
            aircraft_types=aircraft_types,
            crossed_median_line=crossed_median_line,
            adiz_entry=adiz_entry,
            entry_direction=entry_direction,
            source_url=source_url,
            raw_text=raw_text
        )
        session.add(record)
        session.commit()
        return record.id
    except Exception as e:
        session.rollback()
        print(f"[DB ERROR] insert_intrusion: {e}")
        return None
    finally:
        session.close()


def get_intrusion_stats(days=30):
    """取得近N天擾臺統計"""
    session = get_session()
    try:
        cutoff = datetime.now() - timedelta(days=days)
        records = session.query(IntrusionRecord).filter(
            IntrusionRecord.date >= cutoff
        ).all()

        stats = {
            "total_incidents": len(records),
            "total_aircraft": sum(r.aircraft_count for r in records),
            "total_vessels": sum(r.vessel_count for r in records),
            "median_line_crossings": sum(1 for r in records if r.crossed_median_line),
            "adiz_entries": sum(1 for r in records if r.adiz_entry),
        }
        return stats, records
    finally:
        session.close()


# ==============================
# 威脅評分操作
# ==============================

def upsert_daily_score(date, military, maritime, cyber, news_count,
                       intrusion_count, ai_analysis):
    """新增或更新當日威脅評分"""
    session = get_session()
    try:
        overall = round((military * 0.5 + maritime * 0.3 + cyber * 0.2), 2)

        existing = session.query(DailyThreatScore).filter(
            func.date(DailyThreatScore.date) == date.date()
        ).first()

        if existing:
            existing.overall_score = overall
            existing.military_score = military
            existing.maritime_score = maritime
            existing.cyber_score = cyber
            existing.news_count = news_count
            existing.intrusion_count = intrusion_count
            existing.ai_analysis = ai_analysis
        else:
            score = DailyThreatScore(
                date=date,
                overall_score=overall,
                military_score=military,
                maritime_score=maritime,
                cyber_score=cyber,
                news_count=news_count,
                intrusion_count=intrusion_count,
                ai_analysis=ai_analysis
            )
            session.add(score)
        session.commit()
        return overall
    except Exception as e:
        session.rollback()
        print(f"[DB ERROR] upsert_daily_score: {e}")
        return 0.0
    finally:
        session.close()


def get_recent_scores(days=7):
    """取得近N天威脅評分"""
    session = get_session()
    try:
        cutoff = datetime.now() - timedelta(days=days)
        return session.query(DailyThreatScore).filter(
            DailyThreatScore.date >= cutoff
        ).order_by(DailyThreatScore.date).all()
    finally:
        session.close()


# ==============================
# 電纜狀態操作
# ==============================

def upsert_cable_status(cable_name, status, incident_type=None,
                        location_desc=None, reported_at=None, source=None, notes=None):
    """
    新增電纜狀態紀錄（每次都 INSERT，保留歷史）
    查詢時用 get_all_cable_status() 的 GROUP BY MAX 取最新
    """
    session = get_session()
    try:
        cable = CableStatus(
            cable_name=cable_name,
            status=status,
            incident_type=incident_type,
            location_desc=location_desc,
            reported_at=reported_at or datetime.now(),
            source=source,
            notes=notes
        )
        session.add(cable)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"[DB ERROR] upsert_cable_status: {e}")
    finally:
        session.close()


def get_all_cable_status(days: int = 400):
    """
    取得電纜狀態：每條電纜只取最新一筆，去除重複
    days: MODA 紀錄看近 N 天（MODA 障礙表上的事件可能超過一年仍未修復，
          修復後 cable_monitor 會補一筆「已修復」成為最新紀錄）
    非 MODA 來源（新聞 RSS）只保留 30 天
    """
    session = get_session()
    try:
        from sqlalchemy import desc, func
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=days)

        # 每條電纜只取最新一筆
        subq = session.query(
            CableStatus.cable_name,
            func.max(CableStatus.reported_at).label("latest")
        ).filter(
            CableStatus.reported_at >= cutoff
        ).group_by(CableStatus.cable_name).subquery()

        results = session.query(CableStatus).join(
            subq,
            (CableStatus.cable_name == subq.c.cable_name) &
            (CableStatus.reported_at == subq.c.latest)
        ).order_by(desc(CableStatus.reported_at)).all()

        # 過濾掉非電纜名稱的描述（如「距越南峴港約226公里處斷纜」）
        KNOWN_CABLES = {
            "APCN-2", "EAC1", "EAC-C2C", "SMW3", "APG", "TPE", "NCP",
            "FASTER", "PLCN", "SJC", "SJC2", "HKA", "PCCS", "TSE-1",
            "C2C", "E2A", "FNAL", "RNAL",
            "FLAG/FEA", "TDM2", "TM3", "TDM4", "TPCA", "TPCE", "TKC",
            "Taiwan Cable",
            # 中文名稱
            "臺馬二號", "台馬二號", "臺馬三號", "台馬三號", "臺馬四號",
            "亞太直達", "東亞交匯一號", "法新歐亞三號", "台澎海纜", "金廈海纜",
        }

        def is_known_cable(name: str) -> bool:
            """判斷是否為已知電纜名稱（排除地理描述）"""
            if not name:
                return False
            # 包含已知關鍵字
            for known in KNOWN_CABLES:
                if known.upper() in name.upper():
                    return True
            # 排除純地理描述（含「公里」「距」「處」等字）
            geo_keywords = ["公里", "距", "處斷纜", "附近", "km", "nautical"]
            if any(kw in name for kw in geo_keywords):
                return False
            return True

        news_cutoff = datetime.now() - timedelta(days=30)
        results  = [r for r in results
                    if r.source == "MODA" or (r.reported_at and r.reported_at >= news_cutoff)]
        filtered = [r for r in results if is_known_cable(r.cable_name)]
        unknown  = [r for r in results if not is_known_cable(r.cable_name)]

        if unknown:
            print(f"[DB] 過濾掉 {len(unknown)} 筆地理描述型電纜紀錄：")
            for u in unknown[:3]:
                print(f"     {u.cable_name[:50]}")

        return filtered
    finally:
        session.close()
# ==============================
# 認知作戰
# ==============================

def update_news_cog_war(news_id: int, is_cog_war: bool, confidence: int, indicators: list):
    """更新新聞的認知作戰偵測結果"""
    session = get_session()
    try:
        news = session.query(NewsEvent).filter_by(id=news_id).first()
        if news:
            cog_note = f"[COG_WAR:{is_cog_war}|{confidence}%|{'|'.join(indicators[:3])}]"
            if news.content and "[COG_WAR:" not in news.content:
                news.content = news.content + " " + cog_note
            elif not news.content:
                news.content = cog_note
            session.commit()
    except Exception as e:
        session.rollback()
    finally:
        session.close()


def get_cog_war_news(hours: int = 24) -> list:
    """取得近N小時疑似認知作戰的新聞"""
    session = get_session()
    try:
        cutoff = datetime.now() - timedelta(hours=hours)
        return session.query(NewsEvent).filter(
            NewsEvent.fetched_at >= cutoff,
            NewsEvent.content.like("%[COG_WAR:True%")
        ).order_by(desc(NewsEvent.fetched_at)).all()
    finally:
        session.close()
        

# ==============================
# 異常偵測紀錄操作
# ==============================

def insert_anomaly(scraper: str, anomaly_type: str, severity: str,
                    current_value: float, baseline_value: float,
                    deviation_pct: float, description: str) -> int:
    """
    新增一筆異常紀錄
    回傳新紀錄的 id
    """
    session = get_session()
    try:
        anomaly = AnomalyLog(
            scraper        = scraper,
            anomaly_type   = anomaly_type,
            severity       = severity,
            current_value  = current_value,
            baseline_value = baseline_value,
            deviation_pct  = deviation_pct,
            description    = description,
            detected_at    = datetime.now(),
            is_notified    = False,
        )
        session.add(anomaly)
        session.commit()
        return anomaly.id
    except Exception as e:
        session.rollback()
        print(f"[DB ERROR] insert_anomaly: {e}")
        return 0
    finally:
        session.close()
 
 
def has_recent_anomaly(scraper: str, anomaly_type: str, hours: int = 4) -> bool:
    """
    檢查是否在近 N 小時內已有同類型（未解除）的異常紀錄
    用於避免重複觸發同一個異常
    """
    session = get_session()
    try:
        cutoff = datetime.now() - timedelta(hours=hours)
        exists = session.query(AnomalyLog).filter(
            AnomalyLog.scraper == scraper,
            AnomalyLog.anomaly_type == anomaly_type,
            AnomalyLog.detected_at >= cutoff,
            AnomalyLog.resolved_at.is_(None)
        ).first()
        return exists is not None
    finally:
        session.close()
 
 
def resolve_anomalies_by_type(scraper: str, anomaly_type: str):
    """
    將指定類型的所有未解除異常標記為已解除
    （當偵測條件不再符合時呼叫）
    """
    session = get_session()
    try:
        items = session.query(AnomalyLog).filter(
            AnomalyLog.scraper == scraper,
            AnomalyLog.anomaly_type == anomaly_type,
            AnomalyLog.resolved_at.is_(None)
        ).all()
        for item in items:
            item.resolved_at = datetime.now()
        if items:
            session.commit()
    except Exception as e:
        session.rollback()
        print(f"[DB ERROR] resolve_anomalies_by_type: {e}")
    finally:
        session.close()
 
 
def mark_anomaly_notified(anomaly_id: int):
    """標記異常已通知"""
    if not anomaly_id:
        return
    session = get_session()
    try:
        item = session.query(AnomalyLog).filter_by(id=anomaly_id).first()
        if item:
            item.is_notified = True
            session.commit()
    except Exception as e:
        session.rollback()
        print(f"[DB ERROR] mark_anomaly_notified: {e}")
    finally:
        session.close()
 
 
def get_active_anomalies() -> list:
    """
    取得所有目前活躍（未解除）的異常紀錄
    並計算 duration_minutes（從偵測到現在經過的分鐘數）
    """
    session = get_session()
    try:
        items = session.query(AnomalyLog).filter(
            AnomalyLog.resolved_at.is_(None)
        ).order_by(desc(AnomalyLog.detected_at)).all()
 
        return items
    finally:
        session.close()
 
 
def get_anomaly_history(days: int = 7) -> list:
    """取得近 N 天的異常歷史紀錄（含已解除）"""
    session = get_session()
    try:
        cutoff = datetime.now() - timedelta(days=days)
        return session.query(AnomalyLog).filter(
            AnomalyLog.detected_at >= cutoff
        ).order_by(desc(AnomalyLog.detected_at)).all()
    finally:
        session.close()
 
 
# ==============================
# 依來源查詢新聞（anomaly_detector 用）
# ==============================
 
def get_news_by_source(source: str, hours: int = 24) -> list:
    """
    取得指定來源近 N 小時的新聞清單
    source: scraper 名稱（"ptt", "intl_news", "gwytb" 等）
    """
    session = get_session()
    try:
        cutoff = datetime.now() - timedelta(hours=hours)
        return session.query(NewsEvent).filter(
            NewsEvent.source == source,
            NewsEvent.fetched_at >= cutoff
        ).order_by(desc(NewsEvent.fetched_at)).all()
    finally:
        session.close()
 
 
def get_news_count_by_source(source: str, hours: int = 24) -> int:
    """取得指定來源近 N 小時的新聞數量"""
    session = get_session()
    try:
        cutoff = datetime.now() - timedelta(hours=hours)
        return session.query(func.count(NewsEvent.id)).filter(
            NewsEvent.source == source,
            NewsEvent.fetched_at >= cutoff
        ).scalar() or 0
    finally:
        session.close()