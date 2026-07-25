# 檔案名稱：scrapers/gov_tw.py
# 功能說明：爬取台灣官方來源（外交部聲明、行政院、立法院國防委員會）

import requests
import feedparser
import json
import urllib3
from bs4 import BeautifulSoup
from datetime import datetime
import time
import sys
import os

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import REQUEST_HEADERS, REQUEST_TIMEOUT, ALL_KEYWORDS
from database.db import insert_news

# ==============================
# 外交部 OpenData API
# ==============================
MOFA_SOURCES = {
    "mofa_news":    "https://www.mofa.gov.tw/OpenData.aspx?SN=FB09C9C041E34414",
    "mofa_speech":  "https://www.mofa.gov.tw/OpenData.aspx?SN=E0AB271EE713F7E8",
    "mofa_press":   "https://www.mofa.gov.tw/OpenData.aspx?SN=AF58E98D7F27B8E8",
}

# 行政院 RSS
EY_RSS = "https://www.ey.gov.tw/Page/9277F759E41CCD91/rss"

# 立法院國防外交委員會
LY_DEFENSE_URL = "https://www.ly.gov.tw/Pages/List.aspx?nodeid=153"

# 高警示關鍵字
GOV_HIGH_ALERT = [
    "嚴正抗議", "強烈譴責", "嚴重關切",
    "軍事挑釁", "武力威脅", "片面改變現狀",
    "對台動武", "武統", "封鎖",
]


def match_keywords(text: str) -> list:
    return [kw for kw in ALL_KEYWORDS if kw in text]


def is_high_alert(text: str) -> bool:
    return any(kw in text for kw in GOV_HIGH_ALERT)


def parse_roc_date(date_str: str) -> datetime:
    """民國年轉換"""
    try:
        import re
        # 格式：115/05/28 或 115-05-28
        date_str = date_str.strip().replace("-", "/")
        parts = date_str.split("/")
        if len(parts) == 3 and int(parts[0]) < 200:
            return datetime(int(parts[0]) + 1911, int(parts[1]), int(parts[2]))
    except Exception:
        pass
    return datetime.now()


def fetch_mofa(source_name: str, url: str) -> list:
    """爬取外交部 OpenData JSON"""
    results = []
    try:
        resp = requests.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
            verify=False
        )
        resp.encoding = "utf-8"

        # 嘗試 JSON 解析
        try:
            data  = resp.json()
            items = data if isinstance(data, list) else data.get("data", data.get("items", []))
        except Exception:
            # 備援：XML/RSS 解析
            feed  = feedparser.parse(url)
            items = [{"title": e.get("title",""), "content": e.get("summary",""),
                      "url": e.get("link",""), "date": ""} for e in feed.entries]

        print(f"[GOV] {source_name}: 取得 {len(items)} 筆")

        for item in items[:30]:
            # 欄位名稱可能不同，嘗試多種
            title = (item.get("title") or item.get("Title") or
                     item.get("subject") or "").strip()
            content = (item.get("content") or item.get("Content") or
                       item.get("description") or item.get("body") or "").strip()
            url_link = (item.get("url") or item.get("Url") or
                        item.get("link") or item.get("Link") or "").strip()
            date_str = (item.get("date") or item.get("Date") or
                        item.get("publishDate") or "").strip()

            if not title:
                continue

            published_at = parse_roc_date(date_str) if date_str else datetime.now()
            text         = title + " " + content
            keywords     = match_keywords(text)
            alert        = is_high_alert(text)

            if not keywords and not alert:
                continue

            if alert and not keywords:
                keywords = ["外交", "聲明"]

            news_id = insert_news(
                source=source_name,
                title=title,
                content=content[:500] if content else f"[{'高警示' if alert else '一般'}]",
                url=url_link,
                published_at=published_at,
                category="軍事" if alert else "外交",
                keywords_matched=keywords
            )

            if news_id:
                results.append({
                    "id":    news_id,
                    "title": title,
                    "alert": alert,
                })
                icon = "🔴" if alert else "✅"
                print(f"[GOV] {icon} {title[:45]}")

    except Exception as e:
        print(f"[GOV ERROR] {source_name}: {e}")

    return results


def fetch_ey_rss() -> list:
    """爬取行政院 RSS"""
    results = []
    try:
        feed    = feedparser.parse(EY_RSS)
        entries = feed.entries

        if not entries:
            print("[GOV] 行政院RSS: 無條目")
            return results

        print(f"[GOV] 行政院RSS: 取得 {len(entries)} 筆")

        for entry in entries:
            title    = entry.get("title", "").strip()
            summary  = entry.get("summary", "").strip()
            url_link = entry.get("link", "")
            text     = title + " " + summary

            keywords = match_keywords(text)
            if not keywords:
                continue

            news_id = insert_news(
                source="ey_gov",
                title=title,
                content=summary[:300],
                url=url_link,
                published_at=datetime.now(),
                category="軍事",
                keywords_matched=keywords
            )
            if news_id:
                results.append({"id": news_id, "title": title})
                print(f"[GOV] ✅ 行政院：{title[:45]}")

    except Exception as e:
        print(f"[GOV ERROR] 行政院RSS: {e}")

    return results


def fetch_ly_defense() -> list:
    """爬取立法院國防外交委員會"""
    results = []
    try:
        resp = requests.get(
            LY_DEFENSE_URL,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
            verify=False
        )
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # 立法院列表結構
        items = soup.select("ul.list li, .news-list li, table.list tr")
        print(f"[GOV] 立法院國防委員會: 找到 {len(items)} 筆")

        for item in items[:20]:
            link = item.select_one("a")
            if not link:
                continue

            title = link.get_text(strip=True)
            if not title or len(title) < 5:
                continue

            href = link.get("href", "")
            if href.startswith("http"):
                url_link = href
            elif href.startswith("/"):
                url_link = f"https://www.ly.gov.tw{href}"
            else:
                continue

            keywords = match_keywords(title)
            if not keywords:
                continue

            news_id = insert_news(
                source="ly_defense",
                title=title,
                content="",
                url=url_link,
                published_at=datetime.now(),
                category="軍事",
                keywords_matched=keywords
            )
            if news_id:
                results.append({"id": news_id, "title": title})
                print(f"[GOV] ✅ 立法院：{title[:45]}")

    except Exception as e:
        print(f"[GOV ERROR] 立法院: {e}")

    return results


def run() -> list:
    """執行台灣官方來源爬蟲"""
    print("[GOV] 開始爬取台灣官方來源...")
    all_results = []

    # 外交部三個來源
    for name, url in MOFA_SOURCES.items():
        results = fetch_mofa(name, url)
        all_results.extend(results)
        time.sleep(1)

    # 行政院
    ey_results = fetch_ey_rss()
    all_results.extend(ey_results)
    time.sleep(1)

    # 立法院國防委員會
    ly_results = fetch_ly_defense()
    all_results.extend(ly_results)

    print(f"[GOV] 完成，新增 {len(all_results)} 筆")
    return all_results


if __name__ == "__main__":
    run()