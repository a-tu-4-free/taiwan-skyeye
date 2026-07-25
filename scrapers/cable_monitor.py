# 檔案名稱：scrapers/cable_monitor.py
# 功能說明：監控台灣海底電纜狀態，來源包含 MODA、中華電信、SubmarineNetworks

import requests
import feedparser
import urllib3
from bs4 import BeautifulSoup
from datetime import datetime
import time
import sys
import os
import re

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import REQUEST_HEADERS, REQUEST_TIMEOUT
from database.db import get_session
from database.models import CableStatus

# ==============================
# 來源設定
# ==============================
MODA_FAULT_URL      = "https://moda.gov.tw/major-policies/subseacable/fault/1749"
CHT_NEWS_URL        = "https://www.cht.com.tw/zh-tw/home/cht/news"
SUBTEL_RSS          = "https://subtelforum.com/feed/"
SUBMARINENETWORKS_TW = "https://www.submarinenetworks.com/en/systems/trans-pacific"

# 電纜事件關鍵字
CABLE_KEYWORDS = [
    "海底電纜", "海纜", "斷纜", "電纜中斷", "電纜故障",
    "submarine cable", "cable fault", "cable cut", "cable break",
    "undersea cable", "Taiwan cable",
]

# 高警示關鍵字（疑似人為破壞）
SABOTAGE_KEYWORDS = [
    "疑似破壞", "人為切斷", "錨害", "拖網", "不明船隻",
    "suspected", "sabotage", "anchor damage", "deliberate",
]


def parse_roc_date(date_str: str) -> datetime:
    """民國年轉換"""
    try:
        date_str = date_str.strip().replace("年", "/").replace("月", "/").replace("日", "")
        parts    = [p for p in re.split(r'[/\-]', date_str) if p.strip()]
        if len(parts) == 3 and int(parts[0]) < 200:
            return datetime(int(parts[0]) + 1911, int(parts[1]), int(parts[2]))
        elif len(parts) == 3:
            return datetime(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        pass
    return datetime.now()


def save_cable_event(cable_name: str, status: str, incident_type: str,
                     location_desc: str, reported_at: datetime,
                     source: str, notes: str) -> bool:
    """儲存電纜事件到資料庫"""
    session = get_session()
    try:
        # 檢查是否已存在相同事件（同電纜同日期）
        existing = session.query(CableStatus).filter(
            CableStatus.cable_name == cable_name,
            CableStatus.reported_at >= reported_at.replace(hour=0, minute=0, second=0),
        ).first()

        if existing:
            return False

        event = CableStatus(
            cable_name    = cable_name,
            status        = status,
            incident_type = incident_type,
            location_desc = location_desc,
            reported_at   = reported_at,
            source        = source,
            notes         = notes,
        )
        session.add(event)
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"[CABLE ERROR] 儲存失敗：{e}")
        return False
    finally:
        session.close()


def fetch_moda_faults() -> list:
    """爬取數位發展部海纜障礙公告"""
    results = []
    try:
        resp = requests.get(
            MODA_FAULT_URL,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
            verify=False
        )
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # MODA 表格結構
        table = soup.select_one("table")
        if not table:
            print("[CABLE] MODA：找不到表格")
            return results

        rows = table.select("tbody tr")
        print(f"[CABLE] MODA：找到 {len(rows)} 筆障礙記錄")

        for row in rows:
            cols = row.select("td")
            if len(cols) < 4:
                continue

            # 欄位：障礙發生日期 | 電纜名稱 | 障礙情形 | 預計修復日期 | 替代路由
            date_text   = cols[0].get_text(strip=True)
            cable_name  = cols[1].get_text(strip=True) if len(cols) > 1 else "未知"
            incident    = cols[2].get_text(strip=True) if len(cols) > 2 else ""
            repair_date = cols[3].get_text(strip=True) if len(cols) > 3 else ""
            alt_route   = cols[4].get_text(strip=True) if len(cols) > 4 else ""

            # 嘗試取公告連結
            link_elem   = row.select_one("a")
            detail_url  = ""
            if link_elem:
                href = link_elem.get("href", "")
                detail_url = f"https://moda.gov.tw{href}" if href.startswith("/") else href

            reported_at = parse_roc_date(date_text)

            # 判斷狀態
            if "修復" in incident or "恢復" in incident:
                status = "已修復"
            elif "中斷" in incident or "故障" in incident:
                status = "中斷"
            else:
                status = "障礙"

            # 判斷是否疑似人為
            incident_type = "不明原因"
            if any(kw in incident for kw in ["錨害", "拖網"]):
                incident_type = "錨害"
            elif any(kw in incident for kw in ["疑似", "人為"]):
                incident_type = "疑似人為"
            elif "自然" in incident or "地震" in incident:
                incident_type = "自然災害"

            notes = f"預計修復：{repair_date} | 替代路由：{alt_route}"
            if detail_url:
                notes += f" | 公告：{detail_url}"

            saved = save_cable_event(
                cable_name    = cable_name or "台灣海纜",
                status        = status,
                incident_type = incident_type,
                location_desc = "",
                reported_at   = reported_at,
                source        = "MODA",
                notes         = notes
            )

            if saved:
                results.append({
                    "cable":    cable_name,
                    "status":   status,
                    "incident": incident,
                    "date":     date_text,
                    "source":   "MODA",
                })
                sabotage = any(kw in incident for kw in SABOTAGE_KEYWORDS)
                icon = "🔴" if sabotage else "🟠"
                print(f"[CABLE] {icon} MODA：{cable_name} - {incident[:40]}")

    except Exception as e:
        print(f"[CABLE ERROR] MODA：{e}")

    return results


def fetch_subtel_forum() -> list:
    """爬取 SubTel Forum RSS（英文）"""
    results = []
    try:
        feed    = feedparser.parse(SUBTEL_RSS)
        entries = feed.entries

        if not entries:
            print("[CABLE] SubTel：無條目")
            return results

        print(f"[CABLE] SubTel：取得 {len(entries)} 筆")

        for entry in entries[:20]:
            title   = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()
            url     = entry.get("link", "")
            text    = title + " " + summary

            # 只要台灣相關電纜新聞
            is_tw    = any(kw in text for kw in ["Taiwan", "台灣"])
            is_cable = any(kw.lower() in text.lower() for kw in
                          ["cable", "submarine", "undersea", "電纜", "海纜"])
            is_not_irrelevant = not any(kw in title for kw in ["Biznet", "Indonesia", "Philippines"])

            if not (is_tw and is_cable and is_not_irrelevant):
                continue

            sabotage = any(kw.lower() in text.lower() for kw in SABOTAGE_KEYWORDS)

            import time as t
            published_at = datetime.now()
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published_at = datetime.fromtimestamp(t.mktime(entry.published_parsed))

            status        = "中斷" if any(kw in text.lower() for kw in ["cut", "fault", "break"]) else "異常"
            incident_type = "疑似人為" if sabotage else "不明原因"

            saved = save_cable_event(
                cable_name    = "Taiwan Cable",
                status        = status,
                incident_type = incident_type,
                location_desc = "",
                reported_at   = published_at,
                source        = "SubTel Forum",
                notes         = f"{summary[:200]} | {url}"
            )

            if saved:
                results.append({
                    "cable":  "Taiwan Cable",
                    "status": status,
                    "title":  title,
                    "source": "SubTel",
                })
                print(f"[CABLE] {'🔴' if sabotage else '🟠'} SubTel：{title[:50]}")

    except Exception as e:
        print(f"[CABLE ERROR] SubTel：{e}")

    return results


def fetch_submarinenetworks() -> list:
    """爬取 SubmarineNetworks 台灣相關頁面"""
    results = []
    try:
        resp = requests.get(
            "https://www.submarinenetworks.com/en/news",
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT
        )
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # 找新聞連結
        news_links = soup.select("article a, .news-item a, h2 a, h3 a")
        print(f"[CABLE] SubmarineNetworks：找到 {len(news_links)} 筆")

        for link in news_links[:30]:
            title = link.get_text(strip=True)
            href  = link.get("href", "")
            if not title or len(title) < 10:
                continue

            # 只要台灣相關
            if not any(kw in title for kw in ["Taiwan", "台灣", "APCN", "SJC", "FLAG", "PCCS"]):
                continue

            url = f"https://www.submarinenetworks.com{href}" if href.startswith("/") else href

            saved = save_cable_event(
                cable_name    = "Taiwan Region Cable",
                status        = "異常" if any(kw.lower() in title.lower() for kw in ["fault", "cut", "break"]) else "資訊",
                incident_type = "新聞報導",
                location_desc = "",
                reported_at   = datetime.now(),
                source        = "SubmarineNetworks",
                notes         = f"{title} | {url}"
            )
            if saved:
                results.append({"title": title, "url": url})
                print(f"[CABLE] 🔵 SubNet：{title[:50]}")

    except Exception as e:
        print(f"[CABLE ERROR] SubmarineNetworks：{e}")

    return results


def get_cable_summary() -> dict:
    """取得電纜狀態摘要"""
    session = get_session()
    try:
        from datetime import timedelta
        from sqlalchemy import desc

        cutoff  = datetime.now() - timedelta(days=30)
        events  = session.query(CableStatus).filter(
            CableStatus.reported_at >= cutoff
        ).order_by(desc(CableStatus.reported_at)).all()

        active  = [e for e in events if e.status in ["中斷", "障礙", "異常"]]
        fixed   = [e for e in events if e.status == "已修復"]
        sabotage = [e for e in events if e.incident_type in ["疑似人為", "錨害"]]

        return {
            "total":    len(events),
            "active":   len(active),
            "fixed":    len(fixed),
            "sabotage": len(sabotage),
            "latest":   events[:5],
        }
    finally:
        session.close()


def run() -> list:
    """執行電纜監控"""
    print("[CABLE] 開始監控海底電纜狀態...")
    all_results = []

    moda    = fetch_moda_faults()
    all_results.extend(moda)
    time.sleep(1)

    subtel  = fetch_subtel_forum()
    all_results.extend(subtel)
    time.sleep(1)

    subnet  = fetch_submarinenetworks()
    all_results.extend(subnet)

    summary = get_cable_summary()
    print(f"[CABLE] 完成，新增 {len(all_results)} 筆")
    print(f"[CABLE] 近30日：總計{summary['total']}筆 "
          f"異常中{summary['active']}筆 "
          f"疑似人為{summary['sabotage']}筆")

    return all_results


if __name__ == "__main__":
    run()