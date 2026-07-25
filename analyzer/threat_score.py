# 檔案名稱：analyzer/threat_score.py
# 功能說明：計算綜合威脅指數，使用相對評分避免資料量虛高

from datetime import datetime, timedelta
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db import (
    get_recent_news, get_intrusion_stats,
    get_recent_scores, upsert_daily_score
)
from config import MILITARY_KEYWORDS, MARITIME_KEYWORDS, CYBER_KEYWORDS

# ==============================
# 機型威脅係數
# ==============================
AIRCRAFT_THREAT_WEIGHT = {
    "轟-6":  3.0,
    "殲-16": 2.0,
    "殲-11": 2.0,
    "殲-10": 1.5,
    "運-8":  1.0,
    "運-9":  1.0,
    "直-9":  1.2,
    "空警":  1.5,
}

MEDIAN_LINE_BONUS = 2.0
ADIZ_ENTRY_BONUS  = 1.0

# 關鍵字威脅加分（每出現一次）
KEYWORD_SCORES = {
    "飛彈": 2.0, "導彈": 2.0, "封鎖": 2.5,
    "演習": 1.5, "軍演": 1.5, "越中線": 2.0,
    "航母": 2.5, "遼寧": 2.0, "山東": 2.0, "福建": 2.5,
    "海警": 1.5, "駭客": 1.5, "網攻": 2.0,
    "DDoS": 1.5, "斷纜": 2.0, "海底電纜": 1.5,
}

# 基準值：正常狀態下每日平均新聞數（初始值，會被歷史資料修正）
BASELINE_MILITARY_NEWS = 5
BASELINE_MARITIME_NEWS = 3
BASELINE_CYBER_NEWS    = 2


def get_historical_baseline(days: int = 30) -> dict:
    """
    計算歷史基準線：過去N天的平均每日新聞數
    用來做相對評分，避免資料量虛高
    """
    try:
        all_news = get_recent_news(hours=days * 24)
        if not all_news or days == 0:
            return {
                "military": BASELINE_MILITARY_NEWS,
                "maritime": BASELINE_MARITIME_NEWS,
                "cyber":    BASELINE_CYBER_NEWS,
            }

        mil_count = len([n for n in all_news if n.category == "軍事"])
        mar_count = len([n for n in all_news if n.category == "海事"])
        cyb_count = len([n for n in all_news if n.category == "資安"])

        return {
            "military": max(mil_count / days, BASELINE_MILITARY_NEWS),
            "maritime": max(mar_count / days, BASELINE_MARITIME_NEWS),
            "cyber":    max(cyb_count / days, BASELINE_CYBER_NEWS),
        }
    except Exception:
        return {
            "military": BASELINE_MILITARY_NEWS,
            "maritime": BASELINE_MARITIME_NEWS,
            "cyber":    BASELINE_CYBER_NEWS,
        }


def get_keyword_score_for_news(news_list: list, dilution: float = 0.3) -> float:
    """
    計算新聞列表的關鍵字威脅加分
    dilution: 稀釋係數，避免大量新聞堆疊
    每個關鍵字只計算第一次出現（去重）
    """
    seen_keywords = set()
    total = 0.0
    for news in news_list:
        keywords = (news.keywords_matched or "").split(",")
        for kw in keywords:
            kw = kw.strip()
            if kw in KEYWORD_SCORES and kw not in seen_keywords:
                seen_keywords.add(kw)
                total += KEYWORD_SCORES[kw] * dilution
    return total


# 台海相關來源：只有這些來源的新聞才計入軍事新聞量
TAIWAN_STRAIT_SOURCES = {"mnd", "cga", "gwytb", "gov_tw", "intl_news"}

# 台海相關關鍵字：非台海來源的新聞必須含這些字才算台海新聞
TAIWAN_STRAIT_KW = [
    "台灣", "台海", "共軍", "共機", "共艦", "解放軍", "中共",
    "兩岸", "海峽", "ADIZ", "防空識別區", "越中線",
    "金門", "馬祖", "南海主權", "東沙", "太平島",
]

# 純非台海關鍵字：出現這些且無台海關鍵字 → 不計入
NON_TAIWAN_KW = [
    "伊朗", "以色列", "烏克蘭", "俄羅斯", "加薩", "哈瑪斯",
    "葉門", "胡塞", "聖彼得堡", "波斯灣", "紅海", "克里姆林",
    "北韓核武", "阿富汗",
]


def is_taiwan_relevant(news) -> bool:
    """判斷一則新聞是否與台海直接相關"""
    # 官方台海來源，直接算
    if (news.source or "") in TAIWAN_STRAIT_SOURCES:
        return True
    text = (news.title or "") + (news.content or "")[:200]
    has_taiwan = any(kw in text for kw in TAIWAN_STRAIT_KW)
    has_non_tw = any(kw in text for kw in NON_TAIWAN_KW)
    # 有台海關鍵字：算；純非台海：不算
    if has_taiwan:
        return True
    if has_non_tw:
        return False
    # 兩者都沒有：PTT/一般新聞給一半機率（保守處理）
    return (news.source or "") in {"ptt", "ptt_military"}


def calculate_military_score(intrusion_stats: dict, today_news: list,
                              baseline: dict) -> float:
    """
    計算軍事威脅分數（0-10）
    使用相對評分：今日 vs 歷史基準
    只計算台海相關新聞，過濾中東/烏俄等無關新聞
    """
    score = 0.0

    # 1. 擾臺飛機數量（每10架+1分，最多+3）
    aircraft = intrusion_stats.get("total_aircraft", 0)
    score += min(aircraft / 10, 3.0)

    # 2. 越中線（+2分，高優先）
    if intrusion_stats.get("median_line_crossings", 0) > 0:
        score += MEDIAN_LINE_BONUS

    # 3. ADIZ進入（+1分）
    if intrusion_stats.get("adiz_entries", 0) > 0:
        score += ADIZ_ENTRY_BONUS

    # 4. 相對新聞量（只計台海相關新聞）
    mil_news     = [n for n in today_news if n.category == "軍事"]
    tw_mil_news  = [n for n in mil_news if is_taiwan_relevant(n)]
    baseline_mil = baseline.get("military", BASELINE_MILITARY_NEWS)
    excess       = max(0, len(tw_mil_news) - baseline_mil)
    score       += min(excess * 0.3, 2.0)

    filtered_out = len(mil_news) - len(tw_mil_news)
    if filtered_out > 0:
        print(f"[THREAT] 過濾非台海軍事新聞 {filtered_out} 筆"
              f"（台海相關 {len(tw_mil_news)}/{len(mil_news)} 筆）")

    # 5. 關鍵字加分（只用台海相關新聞）
    score += min(get_keyword_score_for_news(tw_mil_news, dilution=0.4), 2.0)

    return min(round(score, 2), 10.0)


def calculate_maritime_score(today_news: list, baseline: dict) -> float:
    """計算海域威脅分數（0-10）"""
    score = 0.0

    mar_news     = [n for n in today_news if n.category == "海事"]
    baseline_mar = baseline.get("maritime", BASELINE_MARITIME_NEWS)
    excess       = max(0, len(mar_news) - baseline_mar)
    score       += min(excess * 0.4, 2.5)

    score += min(get_keyword_score_for_news(mar_news, dilution=0.5), 2.5)

    # 電纜事件額外加分
    cable_news = [n for n in mar_news
                  if any(kw in (n.title or "") for kw in ["電纜", "斷纜", "海纜"])]
    score += len(cable_news) * 1.0

    return min(round(score, 2), 10.0)


def calculate_cyber_score(today_news: list, baseline: dict) -> float:
    """計算資安威脅分數（0-10）"""
    score = 0.0

    cyb_news     = [n for n in today_news if n.category == "資安"]
    baseline_cyb = baseline.get("cyber", BASELINE_CYBER_NEWS)
    excess       = max(0, len(cyb_news) - baseline_cyb)
    score       += min(excess * 0.5, 2.5)

    score += min(get_keyword_score_for_news(cyb_news, dilution=0.6), 2.5)

    return min(round(score, 2), 10.0)


def calculate_trend(scores_7d: list) -> str:
    """計算7日威脅趨勢"""
    if len(scores_7d) < 2:
        return "→ 資料不足"

    recent_avg = sum(s.overall_score for s in scores_7d[-3:]) / min(3, len(scores_7d))
    older_avg  = sum(s.overall_score for s in scores_7d[:-3]) / max(1, len(scores_7d) - 3)
    diff       = recent_avg - older_avg

    if diff > 1.0:
        return "↑↑ 顯著上升"
    elif diff > 0.3:
        return "↑ 上升"
    elif diff < -1.0:
        return "↓↓ 顯著下降"
    elif diff < -0.3:
        return "↓ 下降"
    else:
        return "→ 持平"


def get_threat_level_emoji(score: float) -> str:
    if score >= 8.0:  return "🔴"
    elif score >= 6.0: return "🟠"
    elif score >= 4.0: return "🟡"
    elif score >= 2.0: return "🟢"
    else:              return "⚪"


def get_threat_level_text(score: float) -> str:
    if score >= 8.0:  return "緊急"
    elif score >= 6.0: return "高"
    elif score >= 4.0: return "中"
    elif score >= 2.0: return "低"
    else:              return "平穩"


def run_daily_scoring(ai_analysis: str = "") -> dict:
    """執行每日威脅評分計算（相對評分版）"""
    today = datetime.now()
    print(f"[THREAT] 計算 {today.strftime('%Y-%m-%d')} 威脅評分...")

    # 取得今日資料
    recent_news      = get_recent_news(hours=24)
    intrusion_stats, _ = get_intrusion_stats(days=1)

    # 取得歷史基準線（過去30天平均）
    baseline = get_historical_baseline(days=30)
    print(f"[THREAT] 基準線：軍事{baseline['military']:.1f} "
          f"海事{baseline['maritime']:.1f} 資安{baseline['cyber']:.1f} 筆/日")

    # 計算各類分數
    military = calculate_military_score(intrusion_stats, recent_news, baseline)
    maritime = calculate_maritime_score(recent_news, baseline)
    cyber    = calculate_cyber_score(recent_news, baseline)

    # 綜合分數（加權）
    overall = round(military * 0.5 + maritime * 0.3 + cyber * 0.2, 2)

    # 儲存到資料庫
    upsert_daily_score(
        date=today,
        military=military,
        maritime=maritime,
        cyber=cyber,
        news_count=len(recent_news),
        intrusion_count=intrusion_stats.get("total_incidents", 0),
        ai_analysis=ai_analysis
    )

    # 7日趨勢
    scores_7d = get_recent_scores(days=7)
    trend     = calculate_trend(scores_7d)

    # 整合 anomaly_detector 數據：活躍異常數量、最高嚴重度
    anomaly_count    = 0
    anomaly_max_sev  = None
    anomaly_boost    = 0.0
    try:
        from analyzer.anomaly_detector import get_current_anomaly_summary
        anomaly_summary = get_current_anomaly_summary()
        anomaly_count   = anomaly_summary.get("count", 0)
        anomaly_max_sev = anomaly_summary.get("max_severity")

        # 有 HIGH/CRITICAL 活躍異常時，overall 分數往上修正
        # 避免純規則評分漏抓（如電纜中斷不一定反映在新聞數量上）
        ANOMALY_BOOST = {"LOW": 0.0, "MEDIUM": 0.3, "HIGH": 0.8, "CRITICAL": 1.5}
        anomaly_boost = ANOMALY_BOOST.get(anomaly_max_sev or "LOW", 0.0)
        if anomaly_boost > 0:
            overall = min(round(overall + anomaly_boost, 2), 10.0)
            print(f"[THREAT] 異常加分 +{anomaly_boost}（{anomaly_max_sev}），"
                  f"修正後 overall={overall}")
    except Exception as e:
        print(f"[THREAT] anomaly 整合跳過：{e}")

    result = {
        "date":            today.strftime("%Y-%m-%d"),
        "overall":         overall,
        "military":        military,
        "maritime":        maritime,
        "cyber":           cyber,
        "trend":           trend,
        "news_count":      len(recent_news),
        "intrusion_count": intrusion_stats.get("total_incidents", 0),
        "level_emoji":     get_threat_level_emoji(overall),
        "level_text":      get_threat_level_text(overall),
        "baseline":        baseline,
        "anomaly_count":   anomaly_count,
        "anomaly_max_sev": anomaly_max_sev,
    }

    print(f"[THREAT] 今日評分：整體{overall} 軍事{military} "
          f"海域{maritime} 資安{cyber} 趨勢{trend} 活躍異常{anomaly_count}")
    return result


if __name__ == "__main__":
    result = run_daily_scoring()
    print(f"\n{'='*40}")
    print(f"台灣國防威脅指數 {result['date']}")
    print(f"整體：{result['level_emoji']} {result['overall']}/10 ({result['level_text']})")
    print(f"趨勢：{result['trend']}")
    print(f"基準線：{result['baseline']}")