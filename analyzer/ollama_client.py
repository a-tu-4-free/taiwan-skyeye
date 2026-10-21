# 檔案名稱：analyzer/ollama_client.py
# 功能說明：透過本地 Ollama 執行 AI 分析，使用 /api/generate 端點

import requests
import json
import re
from datetime import datetime
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT


def ollama_generate(prompt: str, system_prompt: str = "", max_retries: int = 3) -> str:
    """
    呼叫本地 Ollama /api/generate 端點
    比 /api/chat 相容性更好
    """
    url = f"{OLLAMA_BASE_URL}/api/generate"

    # 把 system prompt 和 user prompt 合併
    full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt

    payload = {
        "model":  OLLAMA_MODEL,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 1024,
        }
    }

    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "").strip()
        except requests.exceptions.ConnectionError:
            if attempt == 0:
                print("[OLLAMA] 無法連線，請確認 Ollama 已啟動（ollama serve）")
            return ""
        except requests.exceptions.Timeout:
            # 逾時重試只會再等一輪，直接放棄（可在 .env 調高 OLLAMA_TIMEOUT）
            print(f"[OLLAMA] 逾時（>{OLLAMA_TIMEOUT}s），跳過；硬體較慢可調高 OLLAMA_TIMEOUT")
            return ""
        except Exception as e:
            print(f"[OLLAMA ERROR] 第{attempt+1}次嘗試失敗: {e}")

    return ""


# 向下相容舊程式碼
ollama_chat = ollama_generate


def check_ollama_available() -> bool:
    """檢查 Ollama 是否在線"""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        models = resp.json().get("models", [])
        model_names = [m["name"] for m in models]
        print(f"[OLLAMA] 可用模型：{model_names}")
        # 完整名稱比對：只裝 gemma3:4b 但設定 gemma3:12b 時不能誤判為可用
        want = OLLAMA_MODEL if ":" in OLLAMA_MODEL else f"{OLLAMA_MODEL}:latest"
        ok   = want in model_names
        if not ok and model_names:
            print(f"[OLLAMA] ⚠️ 找不到模型 {want}，請執行：ollama pull {want}")
        return ok
    except Exception:
        return False


# ==============================
# 規則前置過濾引擎
# 目的：用純規則快速估分，只有分數夠高才進 Ollama
# 省下約 70% 的 AI 呼叫
# ==============================

# 來源權重：可信度高的來源給基礎加分
SOURCE_WEIGHT = {
    "mnd":        2.0,   # 國防部：官方，直接軍事資訊
    "cga":        1.5,   # 海巡署：海域執法
    "gwytb":      1.5,   # 國台辦：對台政治施壓
    "intl_news":  1.2,   # 國際媒體：西方觀點
    "gov_tw":     1.0,   # 外交部：外交動態
    "ptt":        0.8,   # PTT：民間，需交叉驗證
    "news":       0.8,   # 一般新聞
    "satellite":  1.0,   # 衛星：已經過 Gemini 分析
    "ltn_world":  0.5,   # 自由時報國際版：含中東/歐洲新聞，基礎分降低
    "war_zone":   0.5,   # The War Zone：全球軍事，非台海專屬
    "ptt_military": 0.7, # PTT 軍武板
}

# 非台海地區關鍵字：出現這些字代表新聞跟台灣無關，分數打折
NON_TAIWAN_REGIONS = [
    # 中東
    "伊朗", "以色列", "加薩", "哈瑪斯", "葉門", "胡塞",
    "沙烏地", "科威特", "伊拉克", "敘利亞", "黎巴嫩",
    "波斯灣", "紅海", "荷莫茲",
    # 東歐
    "烏克蘭", "俄羅斯", "莫斯科", "聖彼得堡", "克里姆林",
    "烏俄", "北約東擴", "波羅的海艦隊", "基輔",
    # 其他
    "北韓核武", "阿富汗", "緬甸內戰",
]

# 台海相關關鍵字：出現這些才算台海新聞（與非台海關鍵字互斥判斷）
TAIWAN_STRAIT_KEYWORDS = [
    "台灣", "台海", "中共", "解放軍", "共軍", "共機", "共艦",
    "兩岸", "國防部", "海峽", "ADIZ", "防空識別區",
    "金門", "馬祖", "太平島", "東沙", "南海主權",
]

# 關鍵字分級：出現即加分，可累計
RULE_KEYWORDS = {
    # 緊急級（每個 +3.0）
    "封鎖":   3.0, "武力犯台": 3.0, "飛彈攻擊": 3.0,
    "登陸":   3.0, "全面演習": 3.0, "戒嚴":    3.0,
    # 高警示（每個 +2.0）
    "越中線": 2.0, "航母":    2.0, "轟-6":    2.0,
    "飛彈":   2.0, "導彈":    2.0, "海底電纜": 2.0,
    "斷纜":   2.0, "軍演":    2.0, "實彈":    2.0,
    "殲-16":  2.0, "055":     2.0,
    # 中等警示（每個 +1.0）
    "擾臺":   1.0, "ADIZ":    1.0, "防空識別區": 1.0,
    "共機":   1.0, "共艦":    1.0, "海警":    1.0,
    "演習":   1.0, "殲-11":   1.0, "驅逐艦":  1.0,
    "潛艦":   1.0, "兩棲":    1.0, "統一":    1.0,
    "網攻":   1.0, "DDoS":    1.0, "駭客":    1.0,
    # 低關注（每個 +0.5）
    "台海":   0.5, "解放軍":  0.5, "國台辦":  0.5,
    "外交部": 0.5, "制裁":    0.5, "警告":    0.5,
}

# 來源特定加分（某些來源出現特定關鍵字額外加分）
SOURCE_KEYWORD_BONUS = {
    "mnd":   {"越中線": 1.5, "轟-6": 1.5, "航母": 1.0},
    "gwytb": {"武力": 2.0, "戰爭": 2.0, "軍事行動": 2.0},
    "cga":   {"扣押": 1.5, "衝突": 1.5, "驅離": 1.0},
}


def rule_based_score(title: str, content: str, source: str = "") -> dict:
    """
    純規則快速評分，不呼叫 AI
    回傳：
      score      : 0.0-10.0 估計分數
      matched_kw : 匹配到的關鍵字列表
      should_ai  : 是否值得送 Ollama 精分
      ai_mode    : "full"（完整分析）/ "light"（輕量摘要）/ "skip"（跳過）
    """
    text  = (title or "") + " " + (content[:300] if content else "")
    score = 0.0

    # 1. 來源基礎分
    score += SOURCE_WEIGHT.get(source, 0.5)

    # 2. 關鍵字累計（每個關鍵字最多計一次，避免堆疊）
    matched_kw = []
    for kw, weight in RULE_KEYWORDS.items():
        if kw in text:
            score += weight
            matched_kw.append(kw)

    # 3. 來源 × 關鍵字 額外加成
    if source in SOURCE_KEYWORD_BONUS:
        for kw, bonus in SOURCE_KEYWORD_BONUS[source].items():
            if kw in text:
                score += bonus

    score = min(round(score, 2), 10.0)

    # 4. 地理相關性過濾
    # 非台海來源（ltn_world/war_zone）出現非台海地區關鍵字時，分數打折
    geo_penalty = 1.0
    if source in ("ltn_world", "war_zone", "ptt_military", "news"):
        has_non_taiwan = any(r in text for r in NON_TAIWAN_REGIONS)
        has_taiwan     = any(t in text for t in TAIWAN_STRAIT_KEYWORDS)
        if has_non_taiwan and not has_taiwan:
            # 純非台海新聞：分數乘以 0.3（大幅降低，不會觸發警報）
            geo_penalty = 0.3
        elif has_non_taiwan and has_taiwan:
            # 混合新聞（如中東+台灣）：輕微降低
            geo_penalty = 0.7

    score = min(round(score * geo_penalty, 2), 10.0)

    # 5. 決定 AI 模式
    # 國台辦來源降低門檻（政治操作即使分數不高也值得摘要）
    light_threshold = 2.0 if source == "gwytb" else 3.0

    if score >= 6.0:
        ai_mode = "full"       # 完整分析
    elif score >= light_threshold:
        ai_mode = "light"      # 只做簡短摘要
    else:
        ai_mode = "skip"       # 不進 Ollama

    return {
        "score":      score,
        "matched_kw": matched_kw,
        "should_ai":  ai_mode != "skip",
        "ai_mode":    ai_mode,
        "geo_penalty": geo_penalty,
    }


# ==============================
# 新聞威脅評分
# ==============================

THREAT_SCORE_SYSTEM = """你是台灣國防情資分析專家。
根據新聞標題和摘要，給出威脅評分（0.0-10.0）和簡短分析。
評分標準：
0-2：一般動態，無直接威脅
3-4：值得關注，有潛在影響
5-6：中等警示，需持續追蹤
7-8：高度警示，具體威脅行動
9-10：緊急狀態，直接軍事威脅或攻擊

只回傳 JSON 格式，不要其他文字：
{"score": 數字, "summary": "50字內繁體中文摘要", "reason": "評分理由"}"""


def analyze_news_threat(title: str, content: str, source: str = "") -> dict:
    """
    分析單則新聞的威脅評分
    流程：規則快速估分 → 分數夠高才進 Ollama 精分
    """
    # Step 1：規則引擎快速估分
    rule = rule_based_score(title, content, source)

    # Step 2：分數太低直接跳過 Ollama
    if rule["ai_mode"] == "skip":
        return {
            "score":    rule["score"],
            "summary":  title[:80],
            "reason":   f"規則過濾（{','.join(rule['matched_kw']) or '無關鍵字'}）",
            "ai_used":  False,
            "rule_kw":  rule["matched_kw"],
        }

    # Step 3：輕量模式（score 3-6）只要簡短摘要，縮短 prompt 省資源
    if rule["ai_mode"] == "light":
        light_system = """你是台灣國防新聞編輯。
用繁體中文寫一句話摘要（30字內）和威脅評分。
只回傳 JSON：{"score": 數字, "summary": "摘要"}"""
        prompt   = f"標題：{title}"
        response = ollama_generate(prompt, light_system)
        try:
            clean  = re.sub(r'```json|```', '', response).strip()
            result = json.loads(clean)
            ai_score = float(result.get("score", rule["score"]))
            # 規則分和 AI 分取平均，避免 AI 過高或過低
            final_score = round((rule["score"] + ai_score) / 2, 2)
            return {
                "score":   min(final_score, 10.0),
                "summary": result.get("summary", title[:50]),
                "reason":  f"輕量分析（規則:{rule['score']} AI:{ai_score}）",
                "ai_used": True,
                "rule_kw": rule["matched_kw"],
            }
        except Exception:
            return {
                "score":   rule["score"],
                "summary": title[:80],
                "reason":  "輕量分析解析失敗，使用規則分",
                "ai_used": False,
                "rule_kw": rule["matched_kw"],
            }

    # Step 4：完整分析（score >= 6.0）
    prompt   = f"新聞標題：{title}\n內文摘要：{content[:500] if content else '無'}"
    response = ollama_generate(prompt, THREAT_SCORE_SYSTEM)
    try:
        clean  = re.sub(r'```json|```', '', response).strip()
        result = json.loads(clean)
        return {
            "score":   float(result.get("score", rule["score"])),
            "summary": result.get("summary", ""),
            "reason":  result.get("reason", ""),
            "ai_used": True,
            "rule_kw": rule["matched_kw"],
        }
    except json.JSONDecodeError:
        score_match   = re.search(r'"score"\s*:\s*(\d+\.?\d*)', response)
        summary_match = re.search(r'"summary"\s*:\s*"([^"]+)"', response)
        return {
            "score":   float(score_match.group(1)) if score_match else rule["score"],
            "summary": summary_match.group(1) if summary_match else title[:50],
            "reason":  "解析異常，部分使用規則分",
            "ai_used": True,
            "rule_kw": rule["matched_kw"],
        }


# ==============================
# 每日威脅分析報告
# ==============================

DAILY_REPORT_SYSTEM = """你是台灣國防情勢分析師，使用繁體中文，風格專業但易讀。
根據提供的當日情資，生成結構化分析報告。
包含：整體評估、重點事件、趨勢研判、注意事項。
字數控制在400字內，適合Telegram推送。
重要：純文字輸出，不要使用任何 Markdown 符號（# * ** ## 等）。"""


def generate_daily_report(news_summaries: list, intrusion_stats: dict,
                          threat_scores: dict, date: datetime) -> str:
    """生成每日情勢分析報告"""
    news_text = "\n".join([
        f"- {n.get('title', '')} (威脅:{n.get('score', 0):.1f})"
        for n in news_summaries[:10]
    ])

    prompt = f"""
日期：{date.strftime('%Y年%m月%d日')}

【今日擾臺統計】
共機：{intrusion_stats.get('total_aircraft', 0)} 架
共艦：{intrusion_stats.get('total_vessels', 0)} 艘
越中線：{'是' if intrusion_stats.get('crossed_median_line') else '否'}
ADIZ入侵：{'是' if intrusion_stats.get('adiz_entry') else '否'}

【威脅評分】
軍事：{threat_scores.get('military', 0):.1f}/10
海域：{threat_scores.get('maritime', 0):.1f}/10
資安：{threat_scores.get('cyber', 0):.1f}/10

【今日重點新聞】
{news_text if news_text else '無重大事件'}

請生成今日台灣國防情勢分析報告：
"""
    return ollama_generate(prompt, DAILY_REPORT_SYSTEM)


# ==============================
# 即時警報分析
# ==============================

ALERT_SYSTEM = """你是台灣緊急情報分析官。
收到高威脅新聞，請用繁體中文生成簡短即時警報（150字內）。
格式：【事件】→【影響評估】→【建議關注】
語氣：專業、客觀、不煽情。
重要：純文字輸出，不要使用任何 Markdown 符號。"""


def generate_alert_message(title: str, content: str, score: float) -> str:
    """生成即時警報訊息"""
    prompt = f"威脅評分：{score:.1f}/10\n標題：{title}\n內容：{content[:300]}"
    return ollama_generate(prompt, ALERT_SYSTEM)


# ==============================
# 週報趨勢分析
# ==============================

WEEKLY_SYSTEM = """你是台灣國防情勢週報分析師，使用繁體中文。
根據一週數據分析趨勢，提供深度研判。
包含：本週總結、對比上週、威脅趨勢、值得警惕的模式。
字數500字內。
重要：純文字輸出，不要使用任何 Markdown 符號。"""


def generate_weekly_report(weekly_data: dict) -> str:
    """生成週報分析"""
    prompt = f"""
本週（{weekly_data.get('week_start')} ~ {weekly_data.get('week_end')}）台灣國防情勢：

擾臺事件：{weekly_data.get('total_intrusions', 0)} 次
共機架次：{weekly_data.get('total_aircraft', 0)} 架次
越中線：{weekly_data.get('median_crossings', 0)} 次
平均威脅指數：{weekly_data.get('avg_threat', 0):.1f}/10
最高威脅日：{weekly_data.get('peak_day', '無')}（{weekly_data.get('peak_score', 0):.1f}分）

請生成本週台灣國防情勢週報：
"""
    return ollama_generate(prompt, WEEKLY_SYSTEM)


if __name__ == "__main__":
    print("[OLLAMA] 檢查連線狀態...")
    if check_ollama_available():
        print("[OLLAMA] ✅ 連線正常，測試分析...")
        test = analyze_news_threat(
            "共機14架次擾臺，殲-16越越海峽中線",
            "國防部今日公布，共軍14架次軍機進入我防空識別區，其中4架殲-16越越海峽中線"
        )
        print(f"威脅評分：{test['score']}")
        print(f"摘要：{test['summary']}")
    else:
        print(f"[OLLAMA] ❌ 請先執行：ollama pull {OLLAMA_MODEL}")