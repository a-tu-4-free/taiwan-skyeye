# 檔案名稱：scrapers/thinktank.py
# 功能說明：爬取頂級智庫 RSS，兩層過濾後丟給 Ollama 分析，異常推送 TG

import feedparser
import requests
import time
import re
from datetime import datetime
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import REQUEST_HEADERS, REQUEST_TIMEOUT, TELEGRAM_CHANNEL_ID
from database.db import insert_news

# ==============================
# 智庫 RSS 來源
# ==============================
THINKTANK_SOURCES = {
    # 已確認可用
    "aspi":        "https://www.aspi.org.au/rss/feed",
    "dfrlab":      "https://medium.com/feed/dfrlab",
    "euvsdisinfo": "https://euvsdisinfo.eu/feed/",
    # Google News 中繼（無直接 RSS 的智庫）
    "csis_gn":     "https://news.google.com/rss/search?q=CSIS+Taiwan+China&hl=en&gl=US&ceid=US:en",
    "rand_gn":     "https://news.google.com/rss/search?q=RAND+Taiwan+PLA&hl=en&gl=US&ceid=US:en",
    "stratcom_gn": "https://news.google.com/rss/search?q=StratCom+disinformation+Taiwan&hl=en&gl=US&ceid=US:en",
}

# ==============================
# 第一層：台灣/中共相關關鍵字
# （命中才存 DB，否則丟棄）
# ==============================
TAIWAN_CHINA_KEYWORDS = [
    "Taiwan", "PLA", "PLAAF", "PLAN", "PRC",
    "cross-strait", "China military", "Xi Jinping",
    "Indo-Pacific", "South China Sea", "East China Sea",
    "ADIZ", "median line", "Taiwan Strait",
    "Chinese military", "People's Liberation Army",
    "Beijing", "CCP", "Communist Party",
    "gray zone", "cognitive warfare", "disinformation",
    "submarine cable", "critical infrastructure",
]

# ==============================
# 第二層：異常關鍵字
# （命中才丟給 Ollama 分析）
# ==============================
ANOMALY_KEYWORDS = [
    # 軍事升溫
    "invasion", "blockade", "amphibious", "war game",
    "military exercise", "crisis", "escalation",
    "deterrence failure", "coercion", "aggression",
    "preemptive", "first strike", "contingency",
    # 認知作戰
    "cognitive warfare", "disinformation campaign",
    "information operation", "propaganda",
    "influence operation", "fake news", "manipulation",
    # 基礎設施
    "cable cut", "cable severed", "infrastructure attack",
    "cyberattack", "hack", "intrusion",
    # 外交升溫
    "sanctions", "diplomatic crisis", "expel",
    "military alliance", "defense pact",
    # 台灣直接相關
    "Taiwan independence", "reunification by force",
    "PLA drill", "live-fire", "encirclement",
]

# 異常等級判斷（命中越多越高）
def get_anomaly_level(text: str) -> tuple:
    """
    回傳 (等級, 命中關鍵字列表)
    等級：0=正常 1=注意 2=警示 3=緊急
    """
    text_lower = text.lower()
    hits = [kw for kw in ANOMALY_KEYWORDS if kw.lower() in text_lower]
    level = min(len(hits), 3)
    return level, hits


def is_taiwan_china_related(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in TAIWAN_CHINA_KEYWORDS)


def parse_entry_time(entry) -> datetime:
    try:
        import time as t
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            return datetime.fromtimestamp(t.mktime(entry.published_parsed))
    except Exception:
        pass
    return datetime.now()


def fetch_thinktank_source(source_name: str, url: str) -> list:
    """爬取單一智庫來源"""
    results = []
    try:
        feed    = feedparser.parse(url)
        entries = feed.entries

        if not entries:
            print(f"[THINK] {source_name}: 無條目")
            return results

        print(f"[THINK] {source_name}: 取得 {len(entries)} 筆")
        saved = 0
        anomalies = 0

        for entry in entries[:20]:
            title        = entry.get("title", "").strip()
            summary      = entry.get("summary", "").strip()
            url_link     = entry.get("link", "")
            published_at = parse_entry_time(entry)
            text         = title + " " + summary

            # 第一層過濾：台灣/中共相關
            if not is_taiwan_china_related(text):
                continue

            # 第二層：異常等級
            level, hits = get_anomaly_level(text)

            category = "軍事" if level >= 2 else "國際"
            keywords = hits if hits else ["智庫", "台灣"]

            news_id = insert_news(
                source=source_name,
                title=title,
                content=f"[THINK|L{level}] {summary[:300]}",
                url=url_link,
                published_at=published_at,
                category=category,
                keywords_matched=keywords
            )

            if news_id:
                saved += 1
                entry_data = {
                    "id":      news_id,
                    "title":   title,
                    "url":     url_link,
                    "source":  source_name,
                    "level":   level,
                    "hits":    hits,
                    "summary": summary[:200],
                }
                results.append(entry_data)

                if level >= 2:
                    anomalies += 1
                    icon = "🔴" if level == 3 else "🟠"
                    print(f"[THINK] {icon} L{level} [{source_name}] {title[:50]}")
                    print(f"         命中：{', '.join(hits[:3])}")

        if saved:
            print(f"[THINK] {source_name}: 新增 {saved} 筆，異常 {anomalies} 筆")

    except Exception as e:
        print(f"[THINK ERROR] {source_name}: {e}")

    return results


async def analyze_and_notify(anomaly_entries: list, bot=None):
    """
    對異常文章進行 Ollama 分析並推送 TG
    使用新版卡片格式 + HTML
    """
    if not anomaly_entries or not bot:
        return

    from analyzer.ollama_client import ollama_generate, check_ollama_available

    # 先推卡片（不依賴 Ollama）
    try:
        from bot.alert_engine import push_thinktank_with_card
        await push_thinktank_with_card(bot, anomaly_entries)
    except Exception as e:
        print(f"[THINK] 卡片推送失敗：{e}")

    # Ollama 分析（可用時補充深度研判）
    if not check_ollama_available():
        print("[THINK] Ollama 不可用，跳過深度分析")
        return

    sorted_entries = sorted(anomaly_entries, key=lambda x: x["level"], reverse=True)
    to_analyze     = [e for e in sorted_entries if e["level"] >= 3][:1]  # 只分析 L3 最高級

    for entry in to_analyze:
        try:
            print(f"[THINK] Ollama 深度分析：{entry['title'][:40]}")

            prompt = f"""你是台灣國防情報分析師，分析以下智庫報告對台灣安全的影響。

來源：{entry['source']}
標題：{entry['title']}
摘要：{entry['summary']}
命中關鍵字：{', '.join(entry['hits'])}

請用繁體中文回答（150字內，純文字）：
1. 核心訊息
2. 對台灣安全的影響
3. 威脅評估（低/中/高/緊急）"""

            analysis = ollama_generate(prompt)
            if not analysis:
                continue

            from telegram.constants import ParseMode
            now_str = datetime.now().strftime("%m/%d %H:%M")
            sep = "─" * 28
            msg = (
                f"🤖 <b>智庫深度研判</b>  <code>{now_str}</code>\n"
                f"{sep}\n"
                f"<b>{entry['title'][:55]}</b>\n\n"
                f"<i>{analysis[:400]}</i>\n"
                f"{sep}\n"
                f"來源：{entry['source']}"
            )
            if entry.get("url"):
                msg += f"\n<a href=\"{entry['url']}\">查看原文</a>"

            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=msg,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
            print(f"[THINK] Ollama 研判推送完成：{entry['title'][:40]}")

            import asyncio
            await asyncio.sleep(3)

        except Exception as e:
            print(f"[THINK ERROR] 深度分析失敗：{e}")


def run() -> list:
    """執行智庫爬蟲（同步版，供排程呼叫）"""
    print("[THINK] 開始爬取智庫資訊...")
    all_results = []

    for name, url in THINKTANK_SOURCES.items():
        results = fetch_thinktank_source(name, url)
        all_results.extend(results)
        time.sleep(1.5)

    anomalies = [r for r in all_results if r["level"] >= 2]
    print(f"[THINK] 完成，新增 {len(all_results)} 筆，異常 {len(anomalies)} 筆")

    return all_results


async def run_with_notify(bot=None) -> list:
    """執行智庫爬蟲 + 異常通知（非同步版）"""
    import asyncio
    results   = await asyncio.to_thread(run)
    anomalies = [r for r in results if r["level"] >= 2]

    if anomalies and bot:
        await analyze_and_notify(anomalies, bot)

    return results


if __name__ == "__main__":
    results   = run()
    anomalies = [r for r in results if r["level"] >= 2]
    print(f"\n{'='*50}")
    print(f"異常文章（L2+）：{len(anomalies)} 篇")
    for r in anomalies:
        print(f"  L{r['level']} [{r['source']}] {r['title'][:50]}")
        print(f"       命中：{r['hits'][:3]}")