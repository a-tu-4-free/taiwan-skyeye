# 檔案名稱：database/models.py
# 功能說明：SQLite 資料表定義，包含新聞事件、擾臺紀錄、威脅評分、電纜狀態等資料結構

from sqlalchemy import (
    create_engine, Column, Integer, String, Float,
    DateTime, Text, Boolean, Enum
)
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import enum
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import DB_PATH

Base = declarative_base()


# ==============================
# 威脅等級枚舉
# ==============================
class ThreatLevel(enum.Enum):
    LOW = "低"
    MEDIUM = "中"
    HIGH = "高"
    CRITICAL = "緊急"


# ==============================
# 新聞事件表
# ==============================
class NewsEvent(Base):
    __tablename__ = "news_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), nullable=False)         # 來源（mnd/cga/cna等）
    title = Column(String(500), nullable=False)         # 標題
    content = Column(Text)                              # 內文
    url = Column(String(1000))                          # 原始連結
    published_at = Column(DateTime)                     # 發布時間
    fetched_at = Column(DateTime, default=datetime.now) # 抓取時間
    category = Column(String(50))                       # 分類（軍事/海事/資安）
    keywords_matched = Column(Text)                     # 匹配到的關鍵字（逗號分隔）
    threat_score = Column(Float, default=0.0)           # AI評分
    is_alerted = Column(Boolean, default=False)         # 是否已推送警報
    is_included_in_daily = Column(Boolean, default=False) # 是否已收入日報
    ai_summary = Column(Text)                           # AI摘要

    def __repr__(self):
        return f"<NewsEvent {self.source}: {self.title[:30]}>"


# ==============================
# 共軍擾臺紀錄表
# ==============================
class IntrusionRecord(Base):
    __tablename__ = "intrusion_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False)             # 事件日期
    aircraft_count = Column(Integer, default=0)         # 飛機數量
    vessel_count = Column(Integer, default=0)           # 船艦數量
    aircraft_types = Column(String(500))                # 機型（如：殲-16x2, 運-8x1）
    crossed_median_line = Column(Boolean, default=False) # 是否越中線
    adiz_entry = Column(Boolean, default=False)         # 是否進入ADIZ
    entry_direction = Column(String(100))               # 進入方向（西南/東北等）
    entry_coordinates = Column(String(200))             # 進入座標（概略）
    source_url = Column(String(1000))                   # 來源連結
    raw_text = Column(Text)                             # 原始新聞文字
    created_at = Column(DateTime, default=datetime.now)

    def __repr__(self):
        return f"<Intrusion {self.date}: 機{self.aircraft_count} 艦{self.vessel_count}>"


# ==============================
# 海底電纜狀態表
# ==============================
class CableStatus(Base):
    __tablename__ = "cable_status"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cable_name = Column(String(200), nullable=False)    # 電纜名稱
    status = Column(String(50), default="正常")         # 正常/異常/中斷/維修中
    incident_type = Column(String(100))                 # 事件類型（切斷/異常/疑似破壞）
    location_desc = Column(String(300))                 # 位置描述
    reported_at = Column(DateTime)                      # 事件時間
    source = Column(String(200))                        # 消息來源
    notes = Column(Text)                                # 備註
    created_at = Column(DateTime, default=datetime.now)

    def __repr__(self):
        return f"<Cable {self.cable_name}: {self.status}>"


# ==============================
# 每日威脅評分表
# ==============================
class DailyThreatScore(Base):
    __tablename__ = "daily_threat_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False, unique=True) # 日期
    overall_score = Column(Float, default=0.0)          # 綜合威脅指數（0-10）
    military_score = Column(Float, default=0.0)         # 軍事威脅分數
    maritime_score = Column(Float, default=0.0)         # 海域威脅分數
    cyber_score = Column(Float, default=0.0)            # 資安威脅分數
    news_count = Column(Integer, default=0)             # 當日相關新聞數
    intrusion_count = Column(Integer, default=0)        # 擾臺事件數
    ai_analysis = Column(Text)                          # AI分析摘要
    created_at = Column(DateTime, default=datetime.now)

    def __repr__(self):
        return f"<DailyScore {self.date.date()}: {self.overall_score}>"


# ==============================
# 船艦動態表（AIS）
# ==============================
class VesselTracking(Base):
    __tablename__ = "vessel_tracking"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mmsi = Column(String(20))                           # 船舶識別碼
    vessel_name = Column(String(200))                   # 船名
    vessel_type = Column(String(100))                   # 船型
    flag = Column(String(50))                           # 船旗國
    latitude = Column(Float)                            # 緯度
    longitude = Column(Float)                           # 經度
    speed = Column(Float)                               # 速度（節）
    heading = Column(Float)                             # 航向
    status = Column(String(100))                        # 航行狀態
    is_suspicious = Column(Boolean, default=False)      # 是否標記為可疑
    suspicion_reason = Column(String(300))              # 可疑原因
    recorded_at = Column(DateTime, default=datetime.now)

    def __repr__(self):
        return f"<Vessel {self.vessel_name} ({self.flag})>"


# ==============================
# 異常事件紀錄表
# ==============================
class AnomalyLog(Base):
    __tablename__ = "anomaly_logs"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    detected_at    = Column(DateTime, default=datetime.now, nullable=False)  # 偵測時間
    scraper        = Column(String(50),  nullable=False)   # 來源 scraper（mnd/cga/ptt...）
    anomaly_type   = Column(String(100), nullable=False)   # 異常類型（見 AnomalyType）
    severity       = Column(String(20),  nullable=False)   # LOW / MEDIUM / HIGH / CRITICAL
    current_value  = Column(Float)                         # 當下觀測值
    baseline_value = Column(Float)                         # 歷史基準值
    deviation_pct  = Column(Float)                         # 偏離幅度（%）
    description    = Column(Text)                          # 人讀說明（推 TG 用）
    is_notified    = Column(Boolean, default=False)        # 是否已推 TG
    resolved_at    = Column(DateTime, nullable=True)       # 解除時間（NULL = 持續中）
    created_at     = Column(DateTime, default=datetime.now)

    def __repr__(self):
        return f"<AnomalyLog {self.scraper}:{self.anomaly_type} {self.severity} @{self.detected_at:%Y-%m-%d %H:%M}>"

    @property
    def is_active(self):
        return self.resolved_at is None

    @property
    def duration_minutes(self):
        end = self.resolved_at or datetime.now()
        return int((end - self.detected_at).total_seconds() / 60)


# ==============================
# 資料庫初始化
# ==============================
# 單一 engine 實例（避免每次查詢都重建）
_engine       = None
_SessionMaker = None


def init_db():
    """初始化資料庫，建立所有資料表（只需執行一次）"""
    global _engine, _SessionMaker
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    _engine = create_engine(
        f"sqlite:///{DB_PATH}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(_engine)
    _SessionMaker = sessionmaker(bind=_engine)
    return _engine


def get_session():
    """取得資料庫 Session（使用共用 engine）"""
    global _engine, _SessionMaker
    if _engine is None:
        init_db()
    return _SessionMaker()


if __name__ == "__main__":
    init_db()
    print(f"✅ 資料庫初始化完成：{DB_PATH}")
