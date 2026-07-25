# 檔案名稱：scrapers/gwytb.py
# 功能說明：爬取國台辦新聞稿，追蹤措辭變化與對台政策動向

import requests
from bs4 import BeautifulSoup
from datetime import datetime
import sys
import os
import re
import time

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import REQUEST_HEADERS, REQUEST_TIMEOUT, ALL_KEYWORDS
from database.db import insert_news

# ==============================
# 國台辦新聞來源
# ==============================
GWYTB_URLS = [
    "https://www.gwytb.gov.tw/xwdt/xwfb/",   # 改 https 試試
]

# 備援來源（台灣可連）
BACKUP_URLS = [
    "https://www.xinhuanet.com/tw/",           # 新華社涉台
    "https://tw.people.com.cn/",               # 人民日報台灣頻道
]

# 高警示措辭（措辭升級代表立場強硬化）
ESCALATION_KEYWORDS = [
    "警告", "強烈譴責", "嚴正警告", "不惜一切",
    "軍事行動", "武力", "封鎖", "制裁",
    "獨立意味著戰爭", "分裂", "外部勢力干涉",
]

# 緩和措辭
DEESCALATION_KEYWORDS = [
    "歡迎", "交流", "合作", "融合", "共同發展",
    "對話", "和平", "九二共識",
]

# 固定關鍵字補充（國台辦專用）
GWYTB_KEYWORDS = [
    "台灣", "兩岸", "一個中國", "九二共識",
    "台獨", "分裂", "統一", "解放軍",
    "對台", "涉台", "台海",
]


def analyze_tone(text):
    """
    分析措辭語氣
    回傳：'escalation'（升溫）/ 'deescalation'（緩和）/ 'neutral'（中性）
    """
    esc_count = sum(1 for kw in ESCALATION_KEYWORDS if kw in text)
    desc_count = sum(1 for kw in DEESCALATION_KEYWORDS if kw in text)

    if esc_count > desc_count:
        return "escalation", esc_count
    elif desc_count > esc_count:
        return "deescalation", desc_count
    return "neutral", 0


def match_keywords(text):
    """關鍵字匹配"""
    matched = [kw for kw in ALL_KEYWORDS if kw in text]
    # 補充國台辦專用關鍵字
    matched += [kw for kw in GWYTB_KEYWORDS if kw in text and kw not in matched]
    return list(set(matched))


def fetch_gwytb_page(url, page=1):
    """爬取國台辦單頁新聞列表"""
    results = []
    try:
        # 國台辦分頁參數
        params = {"page": page} if page > 1 else {}

        resp = requests.get(
            url,
            headers={
                **REQUEST_HEADERS,
                "Accept-Language": "zh-TW,zh;q=0.9",
            },
            params=params,
            timeout=REQUEST_TIMEOUT + 5,  # 中國網站多給點時間
        )
        resp.encoding = "utf-8"

        if resp.status_code != 200:
            print(f"[GWYTB] HTTP {resp.status_code}，可能被封鎖或網路問題")
            return results

        soup = BeautifulSoup(resp.text, "html.parser")

        # 嘗試多種選擇器（網站改版保險）
        news_links = (
            soup.select("ul.news_list li a") or
            soup.select(".list_content li a") or
            soup.select("div.list li a") or
            soup.select("td.con a")
        )

        print(f"[GWYTB] 頁面 {page}：找到 {len(news_links)} 筆")

        for link in news_links[:30]:
            title = link.get_text(strip=True)
            if len(title) < 5:
                continue

            href = link.get("href", "")
            if href.startswith("http"):
                article_url = href
            elif href.startswith("/"):
                article_url = f"http://www.gwytb.gov.tw{href}"
            else:
                continue

            keywords = match_keywords(title)
            if not keywords:
                # 國台辦所有新聞都有參考價值，即使沒匹配也記錄
                keywords = ["國台辦"]

            tone, intensity = analyze_tone(title)
            category = "軍事" if tone == "escalation" else "兩岸"

            # 升溫措辭提高威脅評分
            extra_content = f"[語氣:{tone}|強度:{intensity}]"

            news_id = insert_news(
                source="gwytb",
                title=title,
                content=extra_content,
                url=article_url,
                published_at=datetime.now(),
                category=category,
                keywords_matched=keywords
            )

            if news_id:
                results.append({
                    "id": news_id,
                    "title": title,
                    "url": article_url,
                    "tone": tone,
                    "intensity": intensity,
                })
                tone_icon = "🔴" if tone == "escalation" else ("🟢" if tone == "deescalation" else "⚪")
                print(f"[GWYTB] {tone_icon} {title[:40]}")

    except requests.exceptions.ConnectionError:
        print(f"[GWYTB] 無法連線（台灣DNS封鎖，屬正常）")
    except requests.exceptions.Timeout:
        print(f"[GWYTB] 連線逾時（屬正常）")
    except Exception as e:
        print(f"[GWYTB ERROR] {url}: {e}")

    return results


def fetch_gwytb_article(url):
    """爬取國台辦文章內文（用於深度分析）"""
    try:
        resp = requests.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT + 5
        )
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        content_elem = (
            soup.select_one("div.TRS_Editor") or
            soup.select_one("div.content") or
            soup.select_one("div#content") or
            soup.select_one("td.con")
        )
        if content_elem:
            return content_elem.get_text(strip=True, separator="\n")
    except Exception:
        pass
    return ""


def run(fetch_history=False):
    """
    執行國台辦爬蟲
    fetch_history=True 時爬取前3頁歷史資料
    """
    print("[GWYTB] 開始爬取國台辦新聞...")
    all_results = []

    pages = range(1, 4) if fetch_history else [1]

    for url in GWYTB_URLS:
        for page in pages:
            results = fetch_gwytb_page(url, page)
            all_results.extend(results)
            if page > 1:
                time.sleep(2)  # 歷史爬取放慢

        time.sleep(1)

    # 統計措辭分布
    escalations = [r for r in all_results if r["tone"] == "escalation"]
    if escalations:
        print(f"[GWYTB] ⚠️  發現 {len(escalations)} 筆升溫措辭新聞")

    print(f"[GWYTB] 完成，新增 {len(all_results)} 筆")
    return all_results


if __name__ == "__main__":
    # 直接執行時抓歷史資料
    results = run(fetch_history=True)
    for r in results:
        if r["tone"] == "escalation":
            print(f"🔴 {r['title'][:50]} (強度:{r['intensity']})")