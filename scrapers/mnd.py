# 檔案名稱：scrapers/mnd.py
# 功能說明：爬取國防部新聞稿，兩階段爬取（列表→內文），解析擾臺資訊存入資料庫

import requests
import re
import time
import json
import urllib3
from bs4 import BeautifulSoup
from datetime import datetime
import sys
import os

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import SOURCES, REQUEST_HEADERS, REQUEST_TIMEOUT, MILITARY_KEYWORDS, ALL_KEYWORDS
from database.db import insert_news, insert_intrusion

# ==============================
# 快取設定
# ==============================
CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "mnd_seen_urls.json")

def load_seen_urls() -> set:
    """載入已爬過的 URL 快取"""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
    except Exception:
        pass
    return set()

def save_seen_urls(seen: set):
    """儲存已爬過的 URL 快取"""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(seen), f, ensure_ascii=False)
    except Exception as e:
        print(f"[MND] 快取儲存失敗：{e}")

# ==============================
# 擾臺相關正規表達式
# ==============================
AIRCRAFT_COUNT_PATTERN = r'各型.*?計\s*(\d+)\s*架次|共機\s*(\d+)\s*架'
VESSEL_COUNT_PATTERN   = r'共艦\s*(\d+)\s*艘'
MEDIAN_LINE_PATTERN    = r'(逾越中線|越.*中線|穿越.*中線)'
ADIZ_PATTERN           = r'(進入.*防空識別區|ADIZ|識別區)'
DIRECTION_PATTERN      = r'(北部|中部|西南|東南|東北|西北|南部|東部).*?空域'

DEEP_FETCH_KEYWORDS = [
    "共機", "共艦", "擾臺", "擾台", "警巡", "聯合戰備",
    "ADIZ", "防空識別區", "越中線", "演習", "解放軍",
]


def parse_roc_date(date_str: str) -> datetime:
    try:
        parts = date_str.strip().split(".")
        if len(parts) == 3:
            return datetime(int(parts[0]) + 1911, int(parts[1]), int(parts[2]))
    except Exception:
        pass
    return datetime.now()


def match_keywords(text):
    return [kw for kw in ALL_KEYWORDS if kw in text]


def categorize_news(keywords):
    from config import MILITARY_KEYWORDS, MARITIME_KEYWORDS, CYBER_KEYWORDS
    mil = sum(1 for kw in keywords if kw in MILITARY_KEYWORDS)
    mar = sum(1 for kw in keywords if kw in MARITIME_KEYWORDS)
    cyb = sum(1 for kw in keywords if kw in CYBER_KEYWORDS)
    if mil >= mar and mil >= cyb:
        return "軍事"
    elif mar >= cyb:
        return "海事"
    return "資安"


def needs_deep_fetch(title):
    return any(kw in title for kw in DEEP_FETCH_KEYWORDS)


def fetch_article_content(url: str) -> tuple:
    try:
        resp = requests.get(
            url, headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT, verify=False
        )
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        content_elem = soup.select_one("div.maincontent")
        content = content_elem.get_text(strip=True, separator="\n") if content_elem else ""
        tag_elems = soup.select("a.keyword-item")
        official_tags = [t.get_text(strip=True) for t in tag_elems]
        return content, official_tags
    except Exception as e:
        print(f"[MND] 內文爬取失敗：{e}")
        return "", []


def parse_intrusion_info(text: str) -> dict:
    info = {
        "aircraft_count":      0,
        "vessel_count":        0,
        "aircraft_types":      "",
        "crossed_median_line": False,
        "adiz_entry":          False,
        "entry_direction":     ""
    }
    ac_match = re.search(AIRCRAFT_COUNT_PATTERN, text)
    if ac_match:
        val = ac_match.group(1) or ac_match.group(2)
        if val:
            info["aircraft_count"] = int(val)
    vs_match = re.search(VESSEL_COUNT_PATTERN, text)
    if vs_match:
        info["vessel_count"] = int(vs_match.group(1))
    type_pattern = r'(殲[-\s]?\d+[A-Z]?|運[-\s]?\d+[A-Z]?|轟[-\s]?\d+[A-Z]?|空警[-\s]?\d+[A-Z]?|直[-\s]?\d+[A-Z]?)'
    found_types = re.findall(type_pattern, text)
    if found_types:
        seen = set()
        types = []
        for t in found_types:
            t_clean = t.replace(" ", "")
            if t_clean not in seen:
                types.append(t_clean)
                seen.add(t_clean)
        info["aircraft_types"] = ", ".join(types)
    if re.search(MEDIAN_LINE_PATTERN, text):
        info["crossed_median_line"] = True
    if re.search(ADIZ_PATTERN, text):
        info["adiz_entry"] = True
    dir_matches = re.findall(DIRECTION_PATTERN, text)
    if dir_matches:
        info["entry_direction"] = "、".join(set(dir_matches))
    return info


def get_total_pages() -> int:
    """取得國防部新聞總頁數"""
    try:
        resp = requests.get(
            "https://www.mnd.gov.tw/news/pressreleaselist",
            headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT, verify=False
        )
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # 找分頁最後一頁的數字
        page_links = soup.select("a.page-link, ul.pagination a, .pager a")
        max_page = 1
        for link in page_links:
            text = link.get_text(strip=True)
            if text.isdigit():
                max_page = max(max_page, int(text))

        # 備援：找 href 裡的最大頁碼
        if max_page == 1:
            all_links = soup.select("a[href*='pressreleaselist/']")
            for link in all_links:
                href = link.get("href", "")
                match = re.search(r'pressreleaselist/(\d+)', href)
                if match:
                    max_page = max(max_page, int(match.group(1)))

        print(f"[MND] 偵測到總頁數：{max_page}")
        return max_page
    except Exception as e:
        print(f"[MND] 無法取得總頁數，預設11頁：{e}")
        return 11


def fetch_mnd_news_page(page: int, seen_urls: set) -> tuple:
    """
    爬取單頁新聞列表
    回傳 (results, has_new) — has_new=False 代表整頁都爬過了，可以停止
    """
    results = []
    all_seen = True  # 假設整頁都爬過

    url = "https://www.mnd.gov.tw/news/pressreleaselist"
    if page > 1:
        url = f"https://www.mnd.gov.tw/news/pressreleaselist/{page}"

    try:
        resp = requests.get(
            url, headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT, verify=False
        )
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        news_items = soup.select("a.news_list")
        print(f"[MND] 第{page}頁：{len(news_items)} 筆", end="")

        new_count = 0
        skip_count = 0

        for item in news_items:
            title_elem = item.select_one("div.title")
            if not title_elem:
                continue
            title = title_elem.get_text(strip=True)
            if not title:
                continue

            href = item.get("href", "")
            if href.startswith("http"):
                article_url = href
            elif href.startswith("/"):
                article_url = f"https://www.mnd.gov.tw{href}"
            else:
                article_url = f"https://www.mnd.gov.tw/{href}"

            # ── 快取檢查：爬過的跳過 ──
            if article_url in seen_urls:
                skip_count += 1
                continue

            all_seen = False  # 有新的文章
            seen_urls.add(article_url)

            content_elem = item.select_one("p.content")
            summary = content_elem.get_text(strip=True) if content_elem else ""

            date_elem = item.select_one("div.date span.en")
            published_at = parse_roc_date(date_elem.get_text()) if date_elem else datetime.now()

            keywords = match_keywords(title + summary)
            if not keywords:
                continue

            category = categorize_news(keywords)
            full_content = summary
            official_tags = []

            if needs_deep_fetch(title):
                print(f"\n[MND] 🔍 深度爬取：{title[:40]}")
                full_content, official_tags = fetch_article_content(article_url)
                time.sleep(0.5)
                extra_kw = match_keywords(full_content)
                keywords = list(set(keywords + extra_kw))

            news_id = insert_news(
                source="mnd",
                title=title,
                content=full_content or summary,
                url=article_url,
                published_at=published_at,
                category=category,
                keywords_matched=keywords
            )

            if news_id:
                new_count += 1
                results.append({
                    "id": news_id, "title": title,
                    "url": article_url, "category": category,
                })
                print(f"[MND] ✅ {title[:45]}")

                full_text = title + " " + full_content
                if any(kw in full_text for kw in ["共機", "共艦", "架次", "警巡"]):
                    intrusion = parse_intrusion_info(full_text)
                    if intrusion["aircraft_count"] > 0 or intrusion["vessel_count"] > 0:
                        insert_intrusion(
                            date=published_at,
                            aircraft_count=intrusion["aircraft_count"],
                            vessel_count=intrusion["vessel_count"],
                            aircraft_types=intrusion["aircraft_types"],
                            crossed_median_line=intrusion["crossed_median_line"],
                            adiz_entry=intrusion["adiz_entry"],
                            entry_direction=intrusion["entry_direction"],
                            source_url=article_url,
                            raw_text=full_text[:500]
                        )
                        print(f"[MND] 📊 擾臺：機{intrusion['aircraft_count']}架 "
                              f"艦{intrusion['vessel_count']}艘 "
                              f"機型:{intrusion['aircraft_types']} "
                              f"方向:{intrusion['entry_direction']}")

        print(f"  → 新增:{new_count} 跳過:{skip_count}")

    except Exception as e:
        print(f"\n[MND ERROR] 第{page}頁：{e}")

    # all_seen=True 代表整頁都是舊資料，可以停止繼續往後翻
    return results, not all_seen


def run(fetch_history=False):
    """
    執行國防部爬蟲
    fetch_history=True：爬全部頁（首次建立歷史資料用）
    fetch_history=False：爬到遇見舊資料為止（日常排程用）
    """
    print("[MND] 開始爬取國防部新聞...")
    seen_urls = load_seen_urls()
    print(f"[MND] 快取已有 {len(seen_urls)} 筆爬過的 URL")

    if fetch_history:
        total_pages = get_total_pages()
        pages = range(1, total_pages + 1)
    else:
        pages = range(1, 100)  # 日常模式：遇到全舊頁就停

    results = []
    for page in pages:
        page_results, has_new = fetch_mnd_news_page(page, seen_urls)
        results.extend(page_results)

        if not fetch_history and not has_new:
            print(f"[MND] 第{page}頁全為舊資料，停止翻頁")
            break

        time.sleep(0.8)  # 避免打太快

    save_seen_urls(seen_urls)
    print(f"[MND] 完成，新增 {len(results)} 筆，快取更新至 {len(seen_urls)} 筆")
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", action="store_true", help="爬取所有歷史頁")
    args = parser.parse_args()
    run(fetch_history=args.history)