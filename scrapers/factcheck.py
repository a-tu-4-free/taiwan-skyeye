# 檔案名稱：scrapers/factcheck.py
# 功能說明：認知作戰監測 — 事實查核機構（人工查核，精準度高，不用 AI）
#   MyGoPen      RSS（標題開頭帶判定標籤，如【錯誤】【誤導】）
#   台灣事實查核中心 TFC  查核報告列表頁
# 只保留與兩岸 / 國防 / 選舉相關的查核結果，存入 news_events：
#   source = factcheck_mygopen / factcheck_tfc，category = "認知作戰"
#   content 開頭 [FACTCHECK|判定|機構]

import calendar
import re
import sys
import os
import time
from datetime import datetime

import feedparser
import requests
from bs4 import BeautifulSoup

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import REQUEST_HEADERS, REQUEST_TIMEOUT
from database.db import insert_news

MYGOPEN_RSS = "https://www.mygopen.com/feeds/posts/default?alt=rss"
TFC_LIST    = "https://tfc-taiwan.org.tw/fact-check-reports-all/"

# MyGoPen 判定標籤：只收「不實」類，【正確】【事實釐清】不收
FALSE_VERDICTS = ["錯誤", "誤導", "易誤解", "詐騙", "假影片", "假圖片", "謠言", "部分錯誤", "合成", "AI生成"]

# 相關性：兩岸 / 國防 / 對台 / 選舉（認知作戰最常見的目標）
RELEVANT_KEYWORDS = [
    "中國", "中共", "大陸", "對岸", "北京", "習近平", "國台辦", "統戰", "統一", "武統",
    "解放軍", "共軍", "共機", "共艦", "海警", "台海", "兩岸", "台獨",
    "國軍", "國防", "國防部", "軍人", "軍隊", "兵役", "徵兵", "後備", "漢光", "演習",
    "飛彈", "潛艦", "軍購", "美軍", "美國", "AIT", "戰爭", "開戰", "封鎖", "疑美",
    "賴清德", "總統府", "選舉", "民調", "罷免", "立委", "海底電纜", "海纜",
]
# 明顯無關的主題（健康、詐騙投資等），即使出現「中國」也排除
EXCLUDE_KEYWORDS = ["保健", "疫苗", "癌", "飲食", "食物", "減肥", "投資詐騙", "中藥", "偏方"]


def _is_relevant(text: str) -> list:
    if any(kw in text for kw in EXCLUDE_KEYWORDS):
        return []
    return [kw for kw in RELEVANT_KEYWORDS if kw in text]


def _get(url: str) -> requests.Response:
    time.sleep(1.5)   # 禮貌延遲
    return requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)


# ==============================
# MyGoPen
# ==============================
def fetch_mygopen() -> list:
    results = []
    try:
        feed = feedparser.parse(_get(MYGOPEN_RSS).content)
        for e in feed.entries[:40]:
            title = (e.get("title") or "").strip()
            m = re.match(r"^【([^】]{1,8})】", title)
            if not m:
                continue
            verdict = m.group(1)
            if not any(v in verdict for v in FALSE_VERDICTS):
                continue
            tags    = " ".join(t.get("term", "") for t in e.get("tags", []))
            summary = BeautifulSoup(e.get("summary", ""), "html.parser").get_text(" ", strip=True)[:300]
            hits    = _is_relevant(title + " " + tags + " " + summary[:150])
            if not hits:
                continue
            published = datetime.now()
            if e.get("published_parsed"):
                published = datetime.fromtimestamp(calendar.timegm(e.published_parsed))  # RSS 時間為 UTC
            results.append({
                "org": "MyGoPen", "source": "factcheck_mygopen", "verdict": verdict,
                "title": title, "url": e.get("link", ""), "summary": summary,
                "published_at": published, "keywords": hits,
            })
    except Exception as e:
        print(f"[FACTCHECK ERROR] MyGoPen：{e}")
    return results


# ==============================
# 台灣事實查核中心（TFC）
# ==============================
def fetch_tfc() -> list:
    """
    查核報告列表頁：每張卡片含 /fact-check-reports/<slug>/ 連結、
    分類 /fact-check-report-type/<type>/、「發佈日期：YYYY-MM-DD」
    TFC 只發佈「已查核」的報告（多數為錯誤 / 部分錯誤），判定標為「查核報告」
    """
    results = []
    try:
        soup = BeautifulSoup(_get(TFC_LIST).text, "html.parser")
        seen = set()
        for a in soup.select('a[href*="/fact-check-reports/"]'):
            url   = a.get("href", "").split("?")[0]
            title = a.get_text(" ", strip=True)
            if url in seen or len(title) < 8 or url.rstrip("/").endswith("fact-check-reports"):
                continue
            seen.add(url)

            # 往上找卡片容器，取分類與日期
            card = a
            for _ in range(5):
                if card.parent is None:
                    break
                card = card.parent
                if card.select_one('a[href*="/fact-check-report-type/"]') or "發佈日期" in card.get_text():
                    break
            card_text = card.get_text(" ", strip=True)
            cat_a     = card.select_one('a[href*="/fact-check-report-type/"]')
            category  = cat_a.get_text(strip=True) if cat_a else ""
            dm        = re.search(r"發佈日期[:：]\s*(\d{4}-\d{2}-\d{2})", card_text)
            published = datetime.strptime(dm.group(1), "%Y-%m-%d") if dm else datetime.now()

            hits = _is_relevant(title + " " + category)
            if not hits:
                continue
            results.append({
                "org": "台灣事實查核中心", "source": "factcheck_tfc", "verdict": "查核報告",
                "title": title, "url": url, "summary": category,
                "published_at": published, "keywords": hits,
            })
    except Exception as e:
        print(f"[FACTCHECK ERROR] TFC：{e}")
    return results


def run() -> list:
    """抓取查核結果，回傳「新增」的相關項目"""
    print("[FACTCHECK] 開始抓取事實查核機構...")
    new_items = []
    for item in fetch_mygopen() + fetch_tfc():
        nid = insert_news(
            source       = item["source"],
            title        = item["title"],
            content      = f"[FACTCHECK|{item['verdict']}|{item['org']}] {item['summary']}",
            url          = item["url"],
            published_at = item["published_at"],
            category     = "認知作戰",
            keywords_matched = item["keywords"][:5],
        )
        if nid:
            new_items.append(item)
            print(f"[FACTCHECK] 🧠 {item['org']}：{item['title'][:50]}")
    print(f"[FACTCHECK] 完成，新增 {len(new_items)} 則相關查核")
    return new_items


if __name__ == "__main__":
    run()
