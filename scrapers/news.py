# 檔案名稱：scrapers/news.py
# 功能說明：聚合多個新聞來源RSS，過濾國防相關新聞並存入資料庫

import requests
import feedparser
from datetime import datetime
import time
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import (
    SOURCES, REQUEST_HEADERS, REQUEST_TIMEOUT,
    ALL_KEYWORDS, MILITARY_KEYWORDS, MARITIME_KEYWORDS, CYBER_KEYWORDS
)
from database.db import insert_news


# ==============================
# RSS 來源清單（已驗證可用）
# ==============================
RSS_SOURCES = {
    "ltn_world": "https://news.ltn.com.tw/rss/world.xml",      # 自由時報國際
}

RSS_SOURCES_EN = {}  # rfa 台海相關版本無法連線，暫時停用

# 英文關鍵字
EN_KEYWORDS = [
    "Taiwan", "PLA", "PLAAF", "PLAN", "ADIZ",
    "China military", "Taiwan strait", "median line",
    "submarine cable", "undersea cable",
    "invasion", "blockade", "drills", "exercises",
    "coast guard", "CCG",
]


def match_keywords(text):
    return [kw for kw in ALL_KEYWORDS if kw in text]


def match_en_keywords(text):
    return [kw for kw in EN_KEYWORDS if kw.lower() in text.lower()]


def categorize(keywords):
    mil = sum(1 for k in keywords if k in MILITARY_KEYWORDS)
    mar = sum(1 for k in keywords if k in MARITIME_KEYWORDS)
    cyb = sum(1 for k in keywords if k in CYBER_KEYWORDS)
    if mil >= mar and mil >= cyb:
        return "軍事"
    elif mar >= cyb:
        return "海事"
    return "資安"


def parse_entry_time(entry):
    try:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            return datetime.fromtimestamp(time.mktime(entry.published_parsed))
    except Exception:
        pass
    return datetime.now()


def fetch_rss_source(source_name, url, is_english=False):
    """爬取單一RSS來源"""
    results = []
    try:
        feed = feedparser.parse(url)
        entries = feed.entries

        if not entries:
            print(f"[NEWS] {source_name}: 無條目或來源無法連線")
            return results

        print(f"[NEWS] {source_name}: 取得 {len(entries)} 筆")
        matched = 0

        for entry in entries:
            title      = entry.get("title", "").strip()
            summary    = entry.get("summary", "").strip()
            url_link   = entry.get("link", "")
            published_at = parse_entry_time(entry)
            text       = title + " " + summary

            if is_english:
                keywords = match_en_keywords(text)
                if not keywords:
                    continue
                category = "軍事"
            else:
                keywords = match_keywords(text)
                if not keywords:
                    continue
                category = categorize(keywords)

            news_id = insert_news(
                source=source_name,
                title=title,
                content=summary,
                url=url_link,
                published_at=published_at,
                category=category,
                keywords_matched=keywords
            )

            if news_id:
                matched += 1
                results.append({
                    "id":       news_id,
                    "title":    title,
                    "source":   source_name,
                    "category": category
                })

        if matched:
            print(f"[NEWS] {source_name}: 新增 {matched} 筆")

    except Exception as e:
        print(f"[NEWS ERROR] {source_name}: {e}")

    return results


def fetch_rti_api():
    """爬取中央廣播電臺 JSON API"""
    results = []
    try:
        resp = requests.get(
            SOURCES["rti_rss"],
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT
        )
        if resp.status_code != 200:
            print(f"[RTI] HTTP {resp.status_code}，跳過")
            return results

        data  = resp.json()
        items = data if isinstance(data, list) else data.get("items", [])
        print(f"[RTI] 取得 {len(items)} 筆")

        for item in items[:30]:
            title    = item.get("title", "").strip()
            summary  = item.get("summary", item.get("description", "")).strip()
            url_link = item.get("url", item.get("link", ""))
            text     = title + " " + summary

            keywords = match_keywords(text)
            if not keywords:
                continue

            category = categorize(keywords)
            news_id  = insert_news(
                source="rti",
                title=title,
                content=summary,
                url=url_link,
                published_at=datetime.now(),
                category=category,
                keywords_matched=keywords
            )
            if news_id:
                results.append({"id": news_id, "title": title})

        if results:
            print(f"[RTI] 新增 {len(results)} 筆")

    except Exception as e:
        print(f"[RTI ERROR]: {e}")

    return results


def run():
    """執行所有新聞爬蟲"""
    print("[NEWS] 開始聚合新聞來源...")
    all_results = []

    for name, url in RSS_SOURCES.items():
        results = fetch_rss_source(name, url, is_english=False)
        all_results.extend(results)
        time.sleep(1)

    for name, url in RSS_SOURCES_EN.items():
        results = fetch_rss_source(name, url, is_english=True)
        all_results.extend(results)
        time.sleep(1)

    rti_results = fetch_rti_api()
    all_results.extend(rti_results)

    print(f"[NEWS] 完成，共新增 {len(all_results)} 筆新聞")
    return all_results


if __name__ == "__main__":
    run()