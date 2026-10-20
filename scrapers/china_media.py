# 檔案名稱：scrapers/china_media.py
# 功能說明：監控中共官媒對台措辭，偵測輿論升溫信號

import feedparser
import requests
import time
from datetime import datetime, timedelta
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db import insert_news, get_session

# ==============================
# 可用的中共媒體 RSS 來源
# ==============================
SOURCES = {
    "xinhua_world": {
        "url":   "http://www.xinhuanet.com/english/rss/worldrss.xml",
        "name":  "新華社",
        "weight": 2.0,  # 官方通訊社，權重較高
    },
    "people_world": {
        "url":   "http://en.people.cn/rss/90778.xml",
        "name":  "人民日報",
        "weight": 2.0,
    },
    "globaltimes": {
        "url":   "https://www.globaltimes.cn/rss/outbrain.xml",
        "name":  "環球時報",
        "weight": 1.5,  # 偏激進，但常反映官方立場
    },
    "chinanews": {
        "url":   "http://www.chinanews.com.cn/rss/scroll-news.xml",
        "name":  "中新社",
        "weight": 1.5,
    },
    "cgtn": {
        "url":   "https://www.cgtn.com/subscribe/rss/section/world.xml",
        "name":  "CGTN",
        "weight": 1.5,
    },
}

# ==============================
# 措辭分級關鍵字
# ==============================

# L3 緊急：出現武力/軍事行動字眼
CRITICAL_KEYWORDS = [
    "military exercise", "live fire", "combat ready",
    "strike", "blockade", "amphibious",
    "reunification by force", "military action",
    "war", "conflict", "preemptive",
    "Eastern Theater", "joint operation",
]

# L2 高度警示：強烈外交/政治壓力
HIGH_KEYWORDS = [
    "stern warning", "serious warning", "resolutely oppose",
    "will not tolerate", "necessary measures",
    "cross red line", "provocation", "interference",
    "Taiwan independence", "separatist", "secession",
    "core interest", "sovereignty", "territorial integrity",
    "sanctions", "retaliation",
]

# L1 一般：台灣相關但措辭中性
TAIWAN_KEYWORDS = [
    "taiwan", "strait", "cross-strait", "one china",
    "reunification", "pla", "people's liberation",
]


def _kw_match(text: str, keywords: list) -> list:
    """
    完整字詞比對，避免 warning 被 war 誤觸發
    用空格或標點包住關鍵字
    """
    import re
    hits = []
    for kw in keywords:
        # 用詞邊界 \b 做完整比對
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, text, re.IGNORECASE):
            hits.append(kw)
    return hits


def classify_article(title: str, summary: str) -> tuple:
    """
    分析文章措辭級別
    回傳 (level, matched_keywords)
    level: 0=無關, 1=一般, 2=高度警示, 3=緊急
    """
    text = (title + " " + summary).lower()

    # 先確認台灣相關（用完整字詞）
    if not _kw_match(text, TAIWAN_KEYWORDS):
        return 0, []

    # 判斷級別（由高到低，用完整字詞比對）
    crit_hits = _kw_match(text, CRITICAL_KEYWORDS)
    if crit_hits:
        return 3, crit_hits

    high_hits = _kw_match(text, HIGH_KEYWORDS)
    if high_hits:
        return 2, high_hits

    return 1, _kw_match(text, TAIWAN_KEYWORDS)


def fetch_source(source_id: str, source_info: dict) -> list:
    """抓取單一來源"""
    results = []
    try:
        resp = requests.get(
            source_info["url"],
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 Taiwan Defense Monitor"}
        )
        if resp.status_code != 200:
            print(f"[CMEDIA] {source_info['name']}: HTTP {resp.status_code}")
            return []

        feed    = feedparser.parse(resp.text)
        entries = feed.entries

        if not entries:
            print(f"[CMEDIA] {source_info['name']}: 無條目")
            return []

        saved = 0
        for entry in entries[:30]:
            title    = entry.get("title", "").strip()
            summary  = entry.get("summary", "").strip()
            url_link = entry.get("link", "")

            if not title:
                continue

            level, keywords = classify_article(title, summary)
            if level == 0:
                continue

            # 存入資料庫
            category = "軍事" if level >= 2 else "兩岸"
            content  = f"[CMEDIA|L{level}|{source_info['name']}] {summary[:300]}"

            news_id = insert_news(
                source   = source_id,
                title    = title,
                content  = content,
                url      = url_link,
                published_at = datetime.now(),
                category = category,
                keywords_matched = keywords[:5]
            )

            if news_id:
                saved += 1
                result = {
                    "id":      news_id,
                    "title":   title,
                    "source":  source_info["name"],
                    "level":   level,
                    "keywords": keywords,
                    "weight":  source_info["weight"],
                    "url":     url_link,
                }
                results.append(result)

                if level >= 2:
                    icon = "🔴" if level == 3 else "🟠"
                    print(f"[CMEDIA] {icon} L{level} [{source_info['name']}] {title[:50]}")
                    print(f"         命中：{', '.join(keywords[:3])}")

        if saved:
            print(f"[CMEDIA] {source_info['name']}: 新增 {saved} 筆")

    except Exception as e:
        print(f"[CMEDIA ERROR] {source_info['name']}: {e}")

    return results


def get_rhetoric_score(results: list) -> float:
    """
    計算當前中共媒體對台措辭強度分數（0-10）
    基礎分：L2/L3 的最高級別決定
    加成：多來源同時出現才加分
    """
    if not results:
        return 0.0

    l3 = [r for r in results if r["level"] == 3]
    l2 = [r for r in results if r["level"] == 2]
    l1 = [r for r in results if r["level"] == 1]

    # 基礎分（以最高級別決定）
    if l3:
        base = 7.0 + min(len(l3) * 0.5, 2.0)   # L3：7-9分
    elif l2:
        base = 4.0 + min(len(l2) * 0.5, 2.0)   # L2：4-6分
    elif l1:
        base = min(len(l1) * 0.3, 3.0)          # L1：最高3分
    else:
        return 0.0

    # 多來源加成（同一議題被多家媒體報導）
    sources_with_high = len(set(
        r["source"] for r in results if r["level"] >= 2
    ))
    if sources_with_high >= 3:
        base = min(base + 1.0, 10.0)
    elif sources_with_high >= 2:
        base = min(base + 0.5, 10.0)

    return round(base, 1)


def analyze_with_ollama(high_articles: list) -> str:
    """用 Ollama 分析高級別文章"""
    if not high_articles:
        return ""
    try:
        from config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT
        articles_text = "\n".join([
            f"- [{a['source']}] {a['title']}"
            for a in high_articles[:5]
        ])
        prompt = (
            f"你是台灣國防情報分析師。\n"
            f"以下是中共官媒最新對台強硬報導：\n"
            f"{articles_text}\n\n"
            f"請用繁體中文分析（100字內）：\n"
            f"1. 措辭升溫的程度\n"
            f"2. 可能的政治意圖\n"
            f"3. 台灣需要注意的事項\n"
            f"判斷保守，避免過度推斷。"
        )
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model":   OLLAMA_MODEL,
                "prompt":  prompt,
                "stream":  False,
                "options": {"temperature": 0.3, "num_predict": 200}
            },
            timeout=OLLAMA_TIMEOUT
        )
        if resp.status_code == 200:
            return resp.json().get("response", "")
    except Exception as e:
        print(f"[CMEDIA] Ollama 分析失敗：{e}")

    # Gemini 備援
    try:
        from config import GEMINI_API_KEY, GEMINI_MODEL
        if not GEMINI_API_KEY:
            return ""
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 300}
            },
            timeout=20
        )
        if resp.status_code == 200:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"[CMEDIA] Gemini 備援也失敗：{e}")

    return ""


def run() -> list:
    """執行中共媒體監控"""
    print(f"[CMEDIA] {datetime.now().strftime('%H:%M')} 掃描中共官媒...")

    all_results = []
    for source_id, source_info in SOURCES.items():
        results = fetch_source(source_id, source_info)
        all_results.extend(results)
        time.sleep(1)

    # 統計
    by_level = {1: 0, 2: 0, 3: 0}
    for r in all_results:
        by_level[r["level"]] = by_level.get(r["level"], 0) + 1

    score = get_rhetoric_score(all_results)
    print(f"[CMEDIA] 完成：L1={by_level[1]} L2={by_level[2]} L3={by_level[3]}")
    print(f"[CMEDIA] 措辭強度分數：{score:.1f}/10")

    # 高級別才做 Ollama 分析
    high = [r for r in all_results if r["level"] >= 2]
    analysis = ""
    if high:
        analysis = analyze_with_ollama(high)
        if analysis:
            print(f"[CMEDIA] 分析：{analysis[:100]}")

    return all_results


if __name__ == "__main__":
    results = run()
    high = [r for r in results if r["level"] >= 2]
    print(f"\n{'='*55}")
    print(f"高級別文章：{len(high)} 篇")
    for r in high:
        print(f"  L{r['level']} [{r['source']}] {r['title'][:50]}")
