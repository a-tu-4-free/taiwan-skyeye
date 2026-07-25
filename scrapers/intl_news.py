# 檔案名稱：scrapers/intl_news.py
# 功能說明：爬取國際英文軍事媒體（USNI News、The War Zone、BBC Asia）

import feedparser
import requests
from datetime import datetime
import time
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import REQUEST_HEADERS, REQUEST_TIMEOUT
from database.db import insert_news

# ==============================
# 英文來源
# ==============================
INTL_SOURCES = {
    "usni":      "https://news.usni.org/feed",
    "war_zone":  "https://www.thedrive.com/the-war-zone/feed",
    "defense_news": "https://www.defensenews.com/arc/outboundfeeds/rss/",
    "bbc_asia":  "https://feeds.bbci.co.uk/news/world/asia/rss.xml",
}

# 台海相關英文關鍵字
TW_EN_KEYWORDS = [
    "Taiwan", "PLA", "PLAAF", "PLAN", "ADIZ",
    "Taiwan Strait", "median line", "cross-strait",
    "China military", "Chinese military", "People's Liberation Army",
    "submarine cable", "undersea cable",
    "invasion", "blockade", "amphibious",
    "coast guard", "CCG", "Senkaku", "South China Sea",
    "Indo-Pacific", "semiconductor", "chip war",
    "Xi Jinping", "reunification", "deterrence",
    "F-16", "F-35", "carrier", "destroyer",
]

# 高優先級關鍵字（立即警報）
HIGH_PRIORITY_EN = [
    "invasion", "blockade", "amphibious assault",
    "live fire", "exercise near Taiwan", "Taiwan crisis",
    "submarine cable cut", "cable severed",
]


def match_en_keywords(text: str) -> list:
    text_lower = text.lower()
    return [kw for kw in TW_EN_KEYWORDS if kw.lower() in text_lower]


def is_high_priority(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in HIGH_PRIORITY_EN)


def parse_entry_time(entry) -> datetime:
    try:
        import time as t
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            return datetime.fromtimestamp(t.mktime(entry.published_parsed))
    except Exception:
        pass
    return datetime.now()


def fetch_intl_source(source_name: str, url: str) -> list:
    results = []
    try:
        feed    = feedparser.parse(url)
        entries = feed.entries

        if not entries:
            print(f"[INTL] {source_name}: 無條目")
            return results

        print(f"[INTL] {source_name}: 取得 {len(entries)} 筆")
        matched = 0

        for entry in entries:
            title        = entry.get("title", "").strip()
            summary      = entry.get("summary", "").strip()
            url_link     = entry.get("link", "")
            published_at = parse_entry_time(entry)
            text         = title + " " + summary

            keywords = match_en_keywords(text)
            if not keywords:
                continue

            priority = is_high_priority(text)
            category = "軍事"
            content  = f"[EN][{'HIGH' if priority else 'normal'}] {summary[:300]}"

            news_id = insert_news(
                source=source_name,
                title=title,
                content=content,
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
                    "priority": priority,
                    "keywords": keywords,
                })
                if priority:
                    print(f"[INTL] 🔴 HIGH: {title[:50]}")

        if matched:
            print(f"[INTL] {source_name}: 新增 {matched} 筆")

    except Exception as e:
        print(f"[INTL ERROR] {source_name}: {e}")

    return results


def run() -> list:
    print("[INTL] 開始爬取國際軍事媒體...")
    all_results = []

    for name, url in INTL_SOURCES.items():
        results = fetch_intl_source(name, url)
        all_results.extend(results)
        time.sleep(1)

    high_priority = [r for r in all_results if r.get("priority")]
    if high_priority:
        print(f"[INTL] ⚠️  高優先級新聞：{len(high_priority)} 筆")

    print(f"[INTL] 完成，新增 {len(all_results)} 筆")
    return all_results


if __name__ == "__main__":
    run()