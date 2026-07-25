# 檔案名稱：scrapers/ais.py
# 功能說明：透過 AISStream WebSocket 追蹤台灣周邊可疑船隻

import asyncio
import json
import websockets
from datetime import datetime
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import REQUEST_HEADERS, REQUEST_TIMEOUT, AISSTREAM_API_KEY
from database.db import get_session
from database.models import VesselTracking

# ==============================
# 監控區域（台灣周邊大範圍）
# ==============================
WATCH_BBOX = [[18.0, 118.0], [27.0, 126.0]]  # [南緯,西經], [北緯,東經]

ZONE_LABELS = {
    "台灣海峽":    lambda lat, lon: 22.0 <= lat <= 26.5 and 119.0 <= lon <= 122.5,
    "台灣東部外海": lambda lat, lon: 22.0 <= lat <= 26.0 and 122.5 <= lon <= 125.0,
    "南海北部":    lambda lat, lon: 18.0 <= lat <= 22.5 and 114.0 <= lon <= 121.0,
    "巴士海峽":    lambda lat, lon: 20.0 <= lat <= 22.5 and 120.0 <= lon <= 123.5,
}

# ==============================
# 可疑船隻判斷條件
# ==============================
SUSPICIOUS_FLAGS        = ["China", "CN", "CHN", "中國"]
SUSPICIOUS_VESSEL_TYPES = ["Coast Guard", "海警", "Naval", "Warship", "Government", "Patrol", "Military"]
CHINA_MMSI_PREFIXES     = ["412", "413"]


def get_zone(lat, lon) -> str:
    for name, check in ZONE_LABELS.items():
        if check(lat, lon):
            return name
    return "台灣周邊"


def is_suspicious(vessel: dict) -> tuple:
    reasons = []
    flag   = vessel.get("flag", "") or vessel.get("CountryName", "")
    vtype  = vessel.get("type", "") or vessel.get("ShipType", "")
    mmsi   = str(vessel.get("mmsi", "") or vessel.get("MMSI", ""))
    name   = vessel.get("name", "") or vessel.get("ShipName", "")

    if any(f in flag for f in SUSPICIOUS_FLAGS):
        reasons.append("中國籍")
    if any(t in vtype for t in SUSPICIOUS_VESSEL_TYPES):
        reasons.append(f"船型:{vtype}")
    if any(mmsi.startswith(p) for p in CHINA_MMSI_PREFIXES):
        reasons.append("中國MMSI")
    if "CCG" in name.upper() or "海警" in name:
        reasons.append("海警船")

    return (len(reasons) > 0, " | ".join(reasons))


def save_vessel(v: dict, zone: str, suspicious: bool, reason: str):
    """儲存船隻資料到資料庫"""
    session = get_session()
    try:
        vessel = VesselTracking(
            mmsi          = str(v.get("mmsi") or v.get("MMSI", "")),
            vessel_name   = v.get("name") or v.get("ShipName", "未知"),
            vessel_type   = v.get("type") or v.get("ShipType", ""),
            flag          = v.get("flag") or v.get("CountryName", ""),
            latitude      = float(v.get("lat") or v.get("Latitude", 0)),
            longitude     = float(v.get("lon") or v.get("Longitude", 0)),
            speed         = float(v.get("speed") or v.get("Sog", 0)),
            heading       = float(v.get("heading") or v.get("Cog", 0)),
            status        = str(v.get("status") or v.get("NavigationalStatus", "")),
            is_suspicious = suspicious,
            suspicion_reason = reason,
            recorded_at   = datetime.now()
        )
        session.add(vessel)
        session.commit()
    except Exception as e:
        session.rollback()
    finally:
        session.close()


async def stream_vessels(duration_seconds=30) -> list:
    """
    連線 AISStream WebSocket，收資料 duration_seconds 秒後斷線
    回傳可疑船隻清單
    """
    url = "wss://stream.aisstream.io/v0/stream"
    subscribe_msg = {
        "APIKey": AISSTREAM_API_KEY,
        "BoundingBoxes": [WATCH_BBOX],
        "FilterMessageTypes": ["PositionReport"]
    }

    all_suspicious = []
    vessel_count   = 0

    print(f"[AIS] 連線 AISStream，監聽 {duration_seconds} 秒...")

    try:
        async with websockets.connect(url, ping_interval=20) as ws:
            await ws.send(json.dumps(subscribe_msg))
            print("[AIS] 已訂閱台灣周邊海域")

            deadline = asyncio.get_event_loop().time() + duration_seconds

            while asyncio.get_event_loop().time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    msg = json.loads(raw)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break

                # 解析 AISStream 訊息格式
                msg_type = msg.get("MessageType", "")
                if msg_type != "PositionReport":
                    continue

                meta    = msg.get("MetaData", {})
                pos_msg = msg.get("Message", {}).get("PositionReport", {})

                lat  = meta.get("latitude",  pos_msg.get("Latitude",  0))
                lon  = meta.get("longitude", pos_msg.get("Longitude", 0))
                mmsi = str(meta.get("MMSI", ""))
                name = meta.get("ShipName", "").strip()

                vessel = {
                    "mmsi":    mmsi,
                    "name":    name,
                    "lat":     lat,
                    "lon":     lon,
                    "speed":   pos_msg.get("Sog", 0),
                    "heading": pos_msg.get("Cog", 0),
                    "status":  pos_msg.get("NavigationalStatus", ""),
                    "flag":    meta.get("CountryName", ""),
                    "type":    "",  # PositionReport 不含船型，需另查
                }

                # 用 MMSI 前綴判斷中國籍
                susp, reason = is_suspicious(vessel)
                zone = get_zone(lat, lon)
                vessel_count += 1

                save_vessel(vessel, zone, susp, reason)

                if susp:
                    all_suspicious.append({
                        "name":   name,
                        "mmsi":   mmsi,
                        "flag":   vessel["flag"],
                        "reason": reason,
                        "zone":   zone,
                        "lat":    lat,
                        "lon":    lon,
                    })
                    print(f"[AIS] ⚠️  {name} ({mmsi}) - {reason} @ {zone}")

            print(f"[AIS] 收到 {vessel_count} 筆位置報告，其中可疑 {len(all_suspicious)} 艘")

    except websockets.exceptions.InvalidStatusCode as e:
        print(f"[AIS ERROR] 連線被拒（API Key 錯誤？）：{e}")
    except Exception as e:
        print(f"[AIS ERROR] WebSocket 連線失敗：{e}")

    return all_suspicious


def run() -> list:
    """執行 AIS 船隻追蹤（排程友好的同步入口）"""
    print("[AIS] 開始追蹤台灣周邊船隻...")

    if not AISSTREAM_API_KEY or AISSTREAM_API_KEY == "填入你的AISSTREAM_API_KEY":
        print("[AIS] ⚠️  未設定 AISSTREAM_API_KEY，跳過")
        return []

    try:
        results = asyncio.run(stream_vessels(duration_seconds=30))
    except RuntimeError:
        # 已在 event loop 內（被 scheduler 呼叫時）
        loop = asyncio.get_event_loop()
        results = loop.run_until_complete(stream_vessels(duration_seconds=30))

    print(f"[AIS] 完成，發現 {len(results)} 艘可疑船隻")
    return results


def get_suspicious_vessels_summary() -> list:
    """取得最近24小時可疑船隻清單"""
    session = get_session()
    try:
        from sqlalchemy import desc
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(hours=24)
        vessels = session.query(VesselTracking).filter(
            VesselTracking.is_suspicious == True,
            VesselTracking.recorded_at >= cutoff
        ).order_by(desc(VesselTracking.recorded_at)).limit(20).all()

        return [{
            "name":   v.vessel_name,
            "flag":   v.flag,
            "type":   v.vessel_type,
            "lat":    v.latitude,
            "lon":    v.longitude,
            "reason": v.suspicion_reason,
            "time":   v.recorded_at.strftime("%Y-%m-%d %H:%M"),
        } for v in vessels]
    finally:
        session.close()


if __name__ == "__main__":
    results = run()
    for r in results:
        print(f"⚠️  {r['name']} ({r['flag']}) - {r['reason']} @ {r['zone']}")

# ==============================
# 民船徵用偵測（兩棲登陸前兆）
# ==============================

# 解放軍兩棲基地位置
PLA_AMPHIBIOUS_BASES = {
    "東山島":  {"lat": 23.73, "lon": 117.50, "radius_km": 50},
    "連江":    {"lat": 26.20, "lon": 119.55, "radius_km": 50},
    "湛江":    {"lat": 21.27, "lon": 110.36, "radius_km": 60},
    "廈門":    {"lat": 24.48, "lon": 118.08, "radius_km": 40},
    "寧波":    {"lat": 29.87, "lon": 121.55, "radius_km": 50},
}

# 兩棲登陸可用的民用船型
REQUISITION_VESSEL_TYPES = [
    "Ro-Ro", "RoRo", "Roll", "Ferry", "渡輪",
    "Cargo", "General Cargo", "Bulk",
    "Container", "Heavy Load", "Deck",
    "Passenger", "Cruise",
]

# 民用大型船隻 MMSI 特徵（中國籍）
CHINA_CIVIL_MMSI = ["412", "413"]


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    """計算兩點之間的距離（公里）"""
    import math
    R    = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a    = (math.sin(dlat/2)**2 +
            math.cos(math.radians(lat1)) *
            math.cos(math.radians(lat2)) *
            math.sin(dlon/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def check_vessel_requisition() -> dict:
    """
    從資料庫分析近 24 小時 AIS 資料
    偵測解放軍兩棲基地附近的民船異常聚集
    回傳：{base_name: {count, vessels, anomaly_level}}
    """
    session = get_session()
    try:
        from datetime import timedelta
        from sqlalchemy import and_
        cutoff = datetime.now() - timedelta(hours=24)

        # 抓近24小時所有中國籍船隻
        vessels = session.query(VesselTracking).filter(
            and_(
                VesselTracking.recorded_at >= cutoff,
                VesselTracking.flag.in_(["China", "CN", "CHN", "中國"])
            )
        ).all()

        results = {}

        for base_name, base_info in PLA_AMPHIBIOUS_BASES.items():
            nearby = []
            for v in vessels:
                if not v.latitude or not v.longitude:
                    continue
                dist = _haversine_km(
                    base_info["lat"], base_info["lon"],
                    v.latitude, v.longitude
                )
                if dist > base_info["radius_km"]:
                    continue

                # 判斷是否為可能被徵用的民用船型
                vtype    = (v.vessel_type or "").strip()
                is_civil = any(t.lower() in vtype.lower()
                               for t in REQUISITION_VESSEL_TYPES)
                # 低速或停泊（速度 < 3 節）
                is_slow  = (v.speed or 0) < 3.0

                if is_civil or is_slow:
                    nearby.append({
                        "name":   v.vessel_name,
                        "type":   vtype,
                        "mmsi":   v.mmsi,
                        "speed":  v.speed,
                        "dist_km": round(dist, 1),
                    })

            if nearby:
                # 異常判斷：同一基地附近 >= 5 艘
                count = len(nearby)
                if count >= 10:
                    level = "CRITICAL"
                elif count >= 5:
                    level = "HIGH"
                elif count >= 3:
                    level = "MEDIUM"
                else:
                    level = "LOW"

                results[base_name] = {
                    "count":   count,
                    "vessels": nearby[:10],
                    "level":   level,
                    "base_lat": base_info["lat"],
                    "base_lon": base_info["lon"],
                }
                if level in ("HIGH", "CRITICAL"):
                    print(f"[AIS] ⚠️  {base_name} 附近聚集 {count} 艘民船（{level}）")

        return results
    finally:
        session.close()


def get_requisition_summary() -> dict:
    """
    取得民船徵用偵測摘要（供日報和通知使用）
    """
    results  = check_vessel_requisition()
    high_bases = {
        k: v for k, v in results.items()
        if v["level"] in ("HIGH", "CRITICAL")
    }
    return {
        "total_bases_monitored": len(PLA_AMPHIBIOUS_BASES),
        "bases_with_anomaly":    len(high_bases),
        "details":               high_bases,
        "max_level": max(
            (v["level"] for v in high_bases.values()),
            default="NORMAL",
            key=lambda x: {"NORMAL": 0, "LOW": 1,
                           "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}[x]
        )
    }
