# 檔案名稱：scrapers/cable_monitor.py
# 功能說明：監控台灣海底電纜狀態，來源包含 MODA、中華電信、SubmarineNetworks

import requests
import feedparser
import urllib3
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
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
    """
    儲存電纜事件到資料庫
    去重條件：同電纜 + 同一天 + 同狀態（同一天先障礙後斷纜仍會記錄）
    """
    session = get_session()
    try:
        day_start = reported_at.replace(hour=0, minute=0, second=0, microsecond=0)
        existing = session.query(CableStatus).filter(
            CableStatus.cable_name == cable_name,
            CableStatus.status     == status,
            CableStatus.reported_at >= day_start,
            CableStatus.reported_at <  day_start + timedelta(days=1),
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


def _cleanup_legacy_moda_rows():
    """
    舊版解析把欄位對錯（序號當日期、日期當障礙情形），寫入大量錯誤紀錄：
      notes 以「預計修復：」開頭、reported_at = 爬取當天、狀態全是「障礙」
    新版 notes 以「障礙情形：」開頭，這裡一次性刪掉舊格式（重複執行無副作用）
    """
    session = get_session()
    try:
        n = session.query(CableStatus).filter(
            CableStatus.source == "MODA",
            CableStatus.notes.like("預計修復：%"),
        ).delete(synchronize_session=False)
        session.commit()
        if n:
            print(f"[CABLE] 清除舊版錯誤解析紀錄 {n} 筆")
    except Exception as e:
        session.rollback()
        print(f"[CABLE ERROR] 清理舊紀錄失敗：{e}")
    finally:
        session.close()


def _classify_incident(text: str) -> tuple:
    """障礙情形 → (status, incident_type)"""
    if any(kw in text for kw in ["修復完成", "已修復", "已恢復"]):
        status = "已修復"
    elif any(kw in text for kw in ["斷纜", "中斷", "斷裂"]):
        status = "中斷"
    else:
        status = "障礙"          # 部分芯線受損、電力異常等

    if any(kw in text for kw in ["錨害", "拖錨", "下錨"]):
        incident_type = "錨害"
    elif "拖網" in text:
        incident_type = "拖網"
    elif any(kw in text for kw in ["疑似", "人為"]):
        incident_type = "疑似人為"
    elif "自然" in text or "地震" in text:
        incident_type = "自然災害"
    else:
        incident_type = "不明原因"
    return status, incident_type


_ROC_DATE_RE = re.compile(r"^\d{2,4}\s*[/年.-]\s*\d{1,2}\s*[/月.-]\s*\d{1,2}")


def _parse_moda_rows(table) -> list:
    """
    MODA 障礙表欄位：序號 | 海纜名稱 | 障礙發生日期 | 障礙情形 | 替代路由 | 預計修復日期
    同一條電纜多筆障礙時，序號/名稱用 rowspan 合併 → 後續列只剩 4 欄
    因此一律「從右邊對齊」取欄位，名稱缺少時沿用上一列
    """
    rows = []
    last_name = ""
    for tr in table.select("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.select("td")]
        if len(cells) < 4:
            continue                      # 表頭（th）或空列
        date_text, situation, alt_route, repair = cells[-4:]
        if not _ROC_DATE_RE.match(date_text):
            continue                      # 不是資料列
        if len(cells) >= 5 and cells[-5]:
            last_name = cells[-5]
        if not last_name:
            continue
        rows.append({
            "cable_name": last_name, "date": date_text, "situation": situation,
            "alt_route": alt_route, "repair": repair,
        })
    return rows


def _mark_repaired(current_names: set) -> list:
    """
    MODA 表只列「未修復」的障礙；之前有障礙、現在從表上消失的電纜 → 寫入「已修復」
    （名稱用 match_cable_name 正規化，避免 MODA 改字造成誤判）
    """
    from sqlalchemy import desc
    from maps.cable_data import match_cable_name
    current_keys = {match_cable_name(n) or n for n in current_names}

    session  = get_session()
    repaired = []
    try:
        cutoff = datetime.now() - timedelta(days=400)
        events = session.query(CableStatus).filter(
            CableStatus.source == "MODA",
            CableStatus.reported_at >= cutoff,
        ).order_by(desc(CableStatus.reported_at), desc(CableStatus.id)).all()
        latest = {}
        for e in events:
            key = match_cable_name(e.cable_name) or e.cable_name
            latest.setdefault(key, e)
    finally:
        session.close()

    for key, e in latest.items():
        if e.status in ("中斷", "障礙", "異常") and key not in current_keys:
            if save_cable_event(e.cable_name, "已修復", "修復完成", "",
                                datetime.now(), "MODA",
                                "障礙情形：已自 MODA 障礙表移除（視為修復完成）"):
                repaired.append({"cable_name": e.cable_name, "cable": e.cable_name,
                                 "status": "已修復", "source": "MODA"})
                print(f"[CABLE] ✅ MODA：{e.cable_name} 已修復")
    return repaired


def fetch_moda_faults() -> list:
    """爬取數位發展部海纜障礙公告（只回傳「新增」的事件）"""
    results = []
    _cleanup_legacy_moda_rows()
    try:
        resp = requests.get(
            MODA_FAULT_URL,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
            verify=False
        )
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        table = soup.select_one("table")
        if not table:
            print("[CABLE] MODA：找不到表格")
            return results

        rows = _parse_moda_rows(table)
        print(f"[CABLE] MODA：找到 {len(rows)} 筆障礙記錄")
        if not rows:
            return results               # 解析不到就不要誤判成「全部已修復」

        for r in rows:
            status, incident_type = _classify_incident(r["situation"])
            reported_at = parse_roc_date(r["date"])
            notes = (f"障礙情形：{r['situation']} | 替代路由：{r['alt_route']}"
                     f" | 預計修復：{r['repair']}")

            saved = save_cable_event(
                cable_name    = r["cable_name"],
                status        = status,
                incident_type = incident_type,
                location_desc = r["situation"][:300],
                reported_at   = reported_at,
                source        = "MODA",
                notes         = notes,
            )
            if saved:
                results.append({
                    "cable_name":    r["cable_name"],
                    "cable":         r["cable_name"],
                    "status":        status,
                    "incident_type": incident_type,
                    "incident":      r["situation"],
                    "date":          r["date"],
                    "source":        "MODA",
                })
                sabotage = any(kw in r["situation"] for kw in SABOTAGE_KEYWORDS)
                icon = "🔴" if sabotage or status == "中斷" else "🟠"
                print(f"[CABLE] {icon} MODA：{r['cable_name']} - {r['situation'][:40]}")

        results.extend(_mark_repaired({r["cable_name"] for r in rows}))

    except Exception as e:
        print(f"[CABLE ERROR] MODA：{e}")

    return results


def fetch_subtel_forum() -> list:
    """爬取 SubTel Forum RSS（英文）"""
    results = []
    try:
        # feedparser 抓網址沒有 timeout，網路卡住會讓整個排程永遠掛住 → 先用 requests 抓
        resp    = requests.get(SUBTEL_RSS, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        feed    = feedparser.parse(resp.content)
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

            status        = "中斷" if re.search(r"\b(cut|severed|fault|break)\b", text.lower()) else "異常"
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
                    "cable_name": "Taiwan Cable",
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