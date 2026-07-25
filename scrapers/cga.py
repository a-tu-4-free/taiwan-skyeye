# 檔案名稱：scrapers/cga.py
# 功能說明：爬取海巡署新聞稿，追蹤海域異常、中共海警動態、漁船事件、離島周邊狀況

import requests
import feedparser
import urllib3
from bs4 import BeautifulSoup
from datetime import datetime
import time
import sys
import os

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import SOURCES, REQUEST_HEADERS, REQUEST_TIMEOUT, MARITIME_KEYWORDS, ALL_KEYWORDS
from database.db import insert_news

# ==============================
# 海巡相關關鍵字
# ==============================
CGA_HIGH_ALERT_KEYWORDS = [
    "海警", "中國海警", "驅離", "對峙", "包圍", "侵擾",
    "金門", "馬祖", "東引", "烏坵", "東沙", "太平",
    "越界", "越境", "非法捕魚", "扣押", "查扣",
]

CGA_CABLE_KEYWORDS = [
    "海底電纜", "海纜", "電纜", "通訊纜線", "斷纜", "割斷",
]

# 分頁快取
import json
CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cga_seen_urls.json")

def load_seen_urls() -> set:
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
    except Exception:
        pass
    return set()

def save_seen_urls(seen: set):
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(seen), f, ensure_ascii=False)
    except Exception as e:
        print(f"[CGA] 快取儲存失敗：{e}")

def parse_roc_date(date_str: str) -> datetime:
    """民國年轉換：115/05/28 → datetime"""
    try:
        parts = date_str.strip().split("/")
        if len(parts) == 3:
            return datetime(int(parts[0]) + 1911, int(parts[1]), int(parts[2]))
    except Exception:
        pass
    return datetime.now()

def match_keywords(text):
    matched = [kw for kw in ALL_KEYWORDS if kw in text]
    return matched

def is_high_alert(title, content=""):
    text = title + content
    return any(kw in text for kw in CGA_HIGH_ALERT_KEYWORDS)

def is_cable_incident(title, content=""):
    text = title + content
    return any(kw in text for kw in CGA_CABLE_KEYWORDS)

def fetch_cga_page(page=1, seen_urls=None) -> tuple:
    """爬取海巡署單頁新聞，回傳 (results, has_new)"""
    if seen_urls is None:
        seen_urls = set()

    results = []
    all_seen = True

    base = "https://www.cga.gov.tw/GipOpen/wSite/lp?ctNode=650&mp=999"
    url  = base if page == 1 else f"https://www.cga.gov.tw/GipOpen/wSite/lp?ctNode=650&mp=999&nowPage={page}&pagesize=15"

    try:
        resp = requests.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
            verify=False
        )
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # 新結構：<a class="news-list" href="ct?xItem=...">
        news_links = soup.select("a.news-list")
        print(f"[CGA] 第{page}頁：找到 {len(news_links)} 筆", end="")

        new_count  = 0
        skip_count = 0

        for link in news_links:
            # 標題從 span.content 取得
            content_elem = link.select_one("span.content")
            if not content_elem:
                # 備援：用 title 屬性
                title = link.get("title", "").strip()
            else:
                title = content_elem.get_text(strip=True)

            if not title or len(title) < 5:
                continue

            # 日期
            date_elem = link.select_one("span.date")
            published_at = parse_roc_date(date_elem.get_text()) if date_elem else datetime.now()

            # 連結
            href = link.get("href", "")
            if href.startswith("http"):
                article_url = href
            elif href.startswith("/"):
                article_url = f"https://www.cga.gov.tw{href}"
            else:
                article_url = f"https://www.cga.gov.tw/GipOpen/wSite/{href}"

            # 快取檢查
            if article_url in seen_urls:
                skip_count += 1
                continue

            all_seen = False
            seen_urls.add(article_url)

            keywords   = match_keywords(title)
            alert_level = "一般"

            if is_high_alert(title):
                alert_level = "高"
                # 高警示補充關鍵字
                if not keywords:
                    keywords = ["海巡"]

            if is_cable_incident(title):
                keywords.append("海底電纜")
                alert_level = "高"

            if not keywords:
                continue

            category = "海事"
            news_id  = insert_news(
                source="cga",
                title=title,
                content=f"[警示:{alert_level}]",
                url=article_url,
                published_at=published_at,
                category=category,
                keywords_matched=keywords
            )

            if news_id:
                new_count += 1
                results.append({
                    "id":          news_id,
                    "title":       title,
                    "url":         article_url,
                    "alert_level": alert_level,
                })
                icon = "🔴" if alert_level == "高" else "✅"
                print(f"\n[CGA] {icon} [{alert_level}] {title[:45]}")

        print(f"  → 新增:{new_count} 跳過:{skip_count}")

    except Exception as e:
        print(f"\n[CGA ERROR] 第{page}頁：{e}")

    return results, not all_seen


def check_cable_news_from_rss():
    """從中央社RSS過濾電纜相關新聞"""
    results = []
    try:
        feed = feedparser.parse(SOURCES["cna_rss"])
        for entry in feed.entries:
            title   = entry.get("title", "")
            summary = entry.get("summary", "")
            text    = title + summary

            if is_cable_incident(text):
                url      = entry.get("link", "")
                keywords = [kw for kw in CGA_CABLE_KEYWORDS if kw in text]
                news_id  = insert_news(
                    source="cna_cable",
                    title=title,
                    content=summary,
                    url=url,
                    published_at=datetime.now(),
                    category="海事",
                    keywords_matched=keywords
                )
                if news_id:
                    results.append({"id": news_id, "title": title})
                    print(f"[CNA 電纜] 新增：{title[:40]}")
    except Exception as e:
        print(f"[CGA ERROR] cable RSS: {e}")
    return results


def run(fetch_history=False):
    """執行海巡署爬蟲"""
    print("[CGA] 開始爬取海巡署新聞...")
    seen_urls = load_seen_urls()
    print(f"[CGA] 快取已有 {len(seen_urls)} 筆")

    pages   = range(1, 50) if fetch_history else range(1, 100)
    results = []

    for page in pages:
        page_results, has_new = fetch_cga_page(page, seen_urls)
        results.extend(page_results)

        if not fetch_history and not has_new:
            print(f"[CGA] 第{page}頁全為舊資料，停止翻頁")
            break

        time.sleep(0.8)

    save_seen_urls(seen_urls)

    print("[CGA] 檢查電纜相關新聞...")
    cable_results = check_cable_news_from_rss()
    results.extend(cable_results)

    print(f"[CGA] 完成，新增 {len(results)} 筆")
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", action="store_true", help="爬取歷史頁")
    args = parser.parse_args()
    run(fetch_history=args.history)