# 檔案名稱：scrapers/ptt.py
# 功能說明：爬取 PTT 軍武板（Warfare）和八卦板涉台軍事文章，提供即時民間情報來源

import requests
from bs4 import BeautifulSoup
from datetime import datetime
import sys
import os
import re
import time
import random
import time as t

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import REQUEST_HEADERS, REQUEST_TIMEOUT, ALL_KEYWORDS
from database.db import insert_news

# ==============================
# PTT 板設定
# ==============================
PTT_BOARDS = {
    "Warfare":    "https://www.ptt.cc/bbs/Warfare/index.html",       # 軍武板（主要）
    "Military":   "https://www.ptt.cc/bbs/Military/index.html",      # 軍事板
    "gossiping":  "https://www.ptt.cc/bbs/Gossiping/index.html",     # 八卦板（過濾涉台）
}

# PTT 需要帶這個 cookie 過 18+ 確認
PTT_HEADERS = {
    **REQUEST_HEADERS,
    "Cookie": "over18=1",
    "Referer": "https://www.ptt.cc/",
}

# 高價值關鍵字（PTT 用語）
PTT_MILITARY_KEYWORDS = [
    "共機", "共艦", "解放軍", "PLA", "PLAAF", "PLAN",
    "擾台", "擾臺", "越中線", "ADIZ", "識別區",
    "漢光", "聯合利劍", "演習",
    "台海", "兩岸", "戰備",
    "海警", "灰色地帶",
    "F-16", "幻象", "經國號", "IDF",
    "海底電纜", "斷纜",
    "金門", "馬祖", "澎湖", "東沙", "太平島",
]

# 過濾低品質文章
SKIP_PREFIXES = ["Re:", "Fw:", "[公告]", "[版規]", "[申請]"]

# 最低推文數門檻（避免抓到沒人看的文章）
MIN_PUSH_COUNT = 5


def parse_push_count(text):
    """解析推文數（PTT 顯示 爆/XX/X1 等格式）"""
    if not text:
        return 0
    text = text.strip()
    if text == "爆":
        return 100
    if text.startswith("X"):
        # X1 = -10, X2 = -20
        try:
            return -int(text[1:]) * 10
        except Exception:
            return -10
    try:
        return int(text)
    except Exception:
        return 0


def match_keywords(text):
    """PTT 專用關鍵字匹配"""
    matched = [kw for kw in ALL_KEYWORDS if kw in text]
    matched += [kw for kw in PTT_MILITARY_KEYWORDS if kw in text and kw not in matched]
    return list(set(matched))


def is_relevant(title):
    """判斷文章是否相關"""
    # 跳過特定前綴
    for prefix in SKIP_PREFIXES:
        if title.startswith(prefix):
            return False

    # 必須包含關鍵字
    return bool(match_keywords(title))


def fetch_ptt_board(board_name, board_url, max_pages=2):
    """爬取 PTT 單一板"""
    results = []
    current_url = board_url

    for page in range(max_pages):
        try:
            resp = requests.get(
                current_url,
                headers=PTT_HEADERS,
                timeout=REQUEST_TIMEOUT
            )
            resp.encoding = "utf-8"

            if resp.status_code != 200:
                print(f"[PTT] {board_name}: HTTP {resp.status_code}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")

            # 解析文章列表
            articles = soup.select("div.r-ent")
            print(f"[PTT] {board_name} 第{page+1}頁：{len(articles)} 篇文章")

            for article in articles:
                # 標題
                title_elem = article.select_one("div.title a")
                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)

                # 過濾不相關文章
                if not is_relevant(title):
                    continue

                # 連結
                href = title_elem.get("href", "")
                url = f"https://www.ptt.cc{href}"

                # 推文數
                push_elem = article.select_one("div.nrec span")
                push_count = parse_push_count(push_elem.get_text() if push_elem else "0")

                # 過濾負評文章
                if push_count < MIN_PUSH_COUNT and board_name == "gossiping":
                    continue

                # 作者
                author_elem = article.select_one("div.author")
                author = author_elem.get_text(strip=True) if author_elem else ""

                # 日期
                date_elem = article.select_one("div.date")
                date_str = date_elem.get_text(strip=True) if date_elem else ""
                try:
                    # PTT 日期格式：" 5/28"
                    now = datetime.now()
                    date_parts = date_str.strip().split("/")
                    if len(date_parts) == 2:
                        month, day = int(date_parts[0]), int(date_parts[1])
                        published_at = now.replace(month=month, day=day, hour=0, minute=0, second=0)
                    else:
                        published_at = now
                except Exception:
                    published_at = datetime.now()

                keywords = match_keywords(title)
                category = "軍事"

                content = f"[PTT/{board_name}] 推文:{push_count} 作者:{author}"

                news_id = insert_news(
                    source=f"ptt_{board_name.lower()}",
                    title=title,
                    content=content,
                    url=url,
                    published_at=published_at,
                    category=category,
                    keywords_matched=keywords
                )

                if news_id:
                    results.append({
                        "id": news_id,
                        "title": title,
                        "url": url,
                        "push_count": push_count,
                        "board": board_name,
                    })
                    print(f"[PTT/{board_name}] 推{push_count:3d} | {title[:40]}")

            # 找上一頁連結
            prev_link = soup.select_one("a.btn.wide:-soup-contains('上頁')")
            if not prev_link:
                # 備用選擇器
                nav_links = soup.select("div.btn-group-paging a")
                prev_link = next((a for a in nav_links if "上頁" in a.get_text()), None)

            if prev_link and page < max_pages - 1:
                prev_href = prev_link.get("href", "")
                current_url = f"https://www.ptt.cc{prev_href}"
                time.sleep(random.uniform(1.0, 2.0))
            else:
                break

        except Exception as e:
            print(f"[PTT ERROR] {board_name}: {e}")
            break

    return results


def fetch_ptt_article_content(url):
    """
    爬取 PTT 文章內文
    用於高推文數文章的深度分析
    """
    try:
        resp = requests.get(url, headers=PTT_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        content_elem = soup.select_one("div#main-content")
        if content_elem:
            # 移除推文區塊
            for tag in content_elem.select("div.push"):
                tag.decompose()
            return content_elem.get_text(strip=True, separator="\n")[:500]
    except Exception:
        pass
    return ""


def get_hot_articles(results, top_n=5):
    """取得高推文數文章"""
    return sorted(results, key=lambda x: x["push_count"], reverse=True)[:top_n]


def run():
    """執行 PTT 爬蟲"""
    print("[PTT] 開始爬取 PTT 軍武相關版面...")
    all_results = []

    # 主要板：多爬幾頁
    for i, (board_name, board_url) in enumerate(PTT_BOARDS.items()):
        # 八卦板只爬1頁（量太大）
        max_pages = 1 if board_name == "gossiping" else 2

        # 第一個板也要等，避免被 PTT 偵測為爬蟲
        import random
        wait = random.uniform(2.0, 3.5) if i == 0 else random.uniform(1.5, 2.5)
        time.sleep(wait)

        results = fetch_ptt_board(board_name, board_url, max_pages=max_pages)
        all_results.extend(results)

    # 印出熱門文章
    hot = get_hot_articles(all_results)
    if hot:
        print(f"\n[PTT] 熱門文章 TOP {len(hot)}：")
        for a in hot:
            print(f"  推{a['push_count']:3d} [{a['board']}] {a['title'][:45]}")

    print(f"\n[PTT] 完成，新增 {len(all_results)} 筆")
    return all_results


if __name__ == "__main__":
    results = run()