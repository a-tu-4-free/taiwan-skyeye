# 檔案名稱：scrapers/adsb_monitor.py
# 功能說明：透過 OpenSky Network 追蹤台海周邊軍用/偵察機
# 資料來源：OpenSky Network（免費，無需 API Key）

import requests
from datetime import datetime, timedelta
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db import get_session, insert_news

# ==============================
# 監控範圍
# ==============================
WATCH_BBOX = {
    "lamin": 18.0, "lomin": 115.0,
    "lamax": 28.0, "lomax": 127.0,
}

# ==============================
# 軍用機識別規則
# ==============================

# 美軍偵察/特種任務 callsign 前綴
US_MIL_CALLSIGNS = [
    "RCH", "REACH", "JAKE", "MANGO", "SPAR", "FORTE",
    "OLIVE", "POGO", "COLT", "ROCKY", "HOMER", "VALOR",
    "KNIFE", "BLUE", "MAGMA", "TOPXX",
]

# 各國軍用機特徵
MIL_PATTERNS = {
    "美軍偵察機": {
        "callsigns":     US_MIL_CALLSIGNS,
        "icao_prefix":   ["ae"],       # 美軍 ICAO 24-bit 通常 AE 開頭
        "threat_level":  "監控",
        "note":          "美軍在台海周邊偵察，代表關注台海情勢",
    },
    "中共解放軍": {
        # 注意：CSH 是中國南方航空（民航），不在此列
        # 中共軍機通常不廣播 callsign，主要靠 ICAO 前綴判斷
        "callsigns":     ["PLAAF", "PLAN", "CAF"],
        "icao_prefix":   ["78"],       # 中國 ICAO 78 開頭
        "threat_level":  "警示",
        "note":          "中共軍機在台海周邊活動",
    },
    "日本自衛隊": {
        "callsigns":     ["JASDF", "JGSDF", "JMSDF", "JDF"],
        "icao_prefix":   ["86"],
        "threat_level":  "監控",
        "note":          "日本自衛隊在台海周邊偵察",
    },
}

# 重點區域定義
ZONE_LABELS = {
    "台灣海峽":     lambda lat, lon: 22.0 <= lat <= 27.0 and 119.0 <= lon <= 122.5,
    "宮古水道":     lambda lat, lon: 24.0 <= lat <= 27.0 and 123.5 <= lon <= 127.0,
    "台灣東部外海":  lambda lat, lon: 22.0 <= lat <= 26.0 and 122.5 <= lon <= 127.0,
    "南海北部":     lambda lat, lon: 18.0 <= lat <= 22.5 and 115.0 <= lon <= 121.0,
    "巴士海峽":     lambda lat, lon: 20.0 <= lat <= 22.5 and 120.0 <= lon <= 123.5,
    "東海":         lambda lat, lon: 26.0 <= lat <= 28.0 and 120.0 <= lon <= 127.0,
}


def get_zone(lat, lon) -> str:
    if lat is None or lon is None:
        return "台海周邊"
    for name, check in ZONE_LABELS.items():
        if check(lat, lon):
            return name
    return "台海周邊"


def classify_aircraft(icao24: str, callsign: str) -> dict:
    """
    判斷飛機類型
    回傳 {category, threat_level, note} 或 None（民航機）
    """
    cs   = (callsign or "").upper().strip()
    icao = (icao24 or "").lower()

    for category, rules in MIL_PATTERNS.items():
        # Callsign 比對
        if any(cs.startswith(p) for p in rules["callsigns"]):
            return {
                "category":     category,
                "threat_level": rules["threat_level"],
                "note":         rules["note"],
            }
        # ICAO 前綴比對
        if any(icao.startswith(p) for p in rules["icao_prefix"]):
            # callsign 是已知民航 → 排除
            if cs and _is_known_civilian(cs):
                continue
            # callsign 不明（UNKNOWN/空白）+ ICAO 是中國前綴 → 保守標記
            # callsign 明確是軍用 → 標記
            return {
                "category":     category,
                "threat_level": rules["threat_level"],
                "note":         rules["note"],
            }

    # 高空偵察特徵（15,000m 以上且非已知民航）
    return None


def _is_known_civilian(callsign: str) -> bool:
    """
    判斷是否為已知民航飛機
    特別處理 CSH（中國南方航空）：
    - 民航格式：CSH + 3位以上純數字（如 CSH866, CSH6100）
    - 非民航：CSH + 字母或短數字（如 CSH001, CSH1）
    """
    cs = callsign.upper().strip()
    if not cs:
        return False

    # CSH 特別處理
    if cs.startswith("CSH"):
        suffix = cs[3:]
        # 民航班次：純數字且3位以上
        if suffix.isdigit() and len(suffix) >= 3:
            return True
        return False  # 其他格式可能是軍用

    civilian_prefix = [
        # 台灣民航
        "CAL", "EVA", "MDA", "TTW", "TPC",
        # 中國民航（CSS=四川，CES=東方，CSN=南方，CDG=大新華，CXA=廈門）
        "CSS", "CES", "CSN", "CDG", "CCA", "CXA",
        # 日本
        "JAL", "ANA", "JJP", "JJA", "APJ",
        # 韓國
        "KAL", "AAR", "JNA", "ABL", "TWB",
        # 東南亞
        "SIA", "TGW", "AXM", "MAS", "GAR", "PTA",
        "VJC", "HVN", "TBA", "TVJ", "XAX", "CEB",
        # 其他
        "UAE", "CPA", "ESR", "ACA", "BAW",
        "HKE", "CRK", "HGB", "AHK",  # 香港：快運、香港航空、大灣區、港龍
        "CHH", "DKH", "CSZ", "CXA", "CGW", "CQH", "CHB", "CBJ", "CSC",  # 中國民航：海南/吉祥/深圳/廈門/首都/九元等
    ]
    return any(cs.startswith(p) for p in civilian_prefix)


def fetch_aircraft() -> list:
    """從 OpenSky Network 抓取台海周邊飛機"""
    try:
        resp = requests.get(
            "https://opensky-network.org/api/states/all",
            params=WATCH_BBOX,
            timeout=20
        )
        if resp.status_code == 200:
            return resp.json().get("states", [])
        elif resp.status_code == 429:
            print("[ADSB] OpenSky 限速，等待下次排程")
        else:
            print(f"[ADSB] HTTP {resp.status_code}")
    except Exception as e:
        print(f"[ADSB ERROR] {e}")
    return []


def analyze_with_ollama(aircraft_list: list) -> str:
    """
    用 Ollama 分析軍機動態
    輸入：軍機清單
    輸出：簡短分析文字
    """
    if not aircraft_list:
        return ""

    try:
        from config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT

        # 整理軍機資訊給 Ollama
        ac_desc = "\n".join([
            f"- {a['callsign']} ({a['category']}) "
            f"在{a['zone']}，高度{a['alt_m']:.0f}m，航向{a['heading']:.0f}°"
            for a in aircraft_list
        ])

        prompt = (
            f"你是台灣國防情報分析師。\n"
            f"以下是台海周邊偵測到的軍用飛機：\n"
            f"{ac_desc}\n\n"
            f"請用繁體中文分析（100字內）：\n"
            f"1. 這些飛機的任務性質\n"
            f"2. 對台灣的威脅程度（低/中/高）\n"
            f"3. 需要特別關注的事項\n"
            f"判斷保守，避免過度推斷。"
        )

        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model":  OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 200}
            },
            timeout=OLLAMA_TIMEOUT
        )
        if resp.status_code == 200:
            return resp.json().get("response", "")
    except Exception as e:
        print(f"[ADSB] Ollama 失敗（{e.__class__.__name__}），嘗試 Gemini 備援...")
        return _analyze_with_gemini(aircraft_list, prompt)
    return ""


def _analyze_with_gemini(aircraft_list: list, prompt: str) -> str:
    """Gemini 備援分析"""
    try:
        from config import GEMINI_API_KEY, GEMINI_MODEL
        if not GEMINI_API_KEY:
            return ""
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0.3, "maxOutputTokens": 300}},
            timeout=20
        )
        if resp.status_code == 200:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        elif resp.status_code == 429:
            print("[ADSB] Gemini 429，跳過分析")
    except Exception as e2:
        print(f"[ADSB] Gemini 分析也失敗：{e2}")
    return ""


def run() -> list:
    """執行 ADS-B 監控"""
    print(f"[ADSB] {datetime.now().strftime('%H:%M')} 掃描台海周邊軍機...")

    states = fetch_aircraft()
    if not states:
        print("[ADSB] 無資料")
        return []

    print(f"[ADSB] 範圍內飛機：{len(states)} 架")

    military = []
    for s in states:
        if not s or len(s) < 12:
            continue

        icao24   = s[0] or ""
        callsign = (s[1] or "").strip()
        country  = s[2] or ""
        lon      = s[5]
        lat      = s[6]
        alt_m    = s[7]
        velocity = s[9]
        heading  = s[10]

        classification = classify_aircraft(icao24, callsign)
        if not classification:
            continue

        zone = get_zone(lat, lon)
        ac   = {
            "icao24":       icao24,
            "callsign":     callsign,
            "country":      country,
            "lat":          lat,
            "lon":          lon,
            "alt_m":        alt_m or 0,
            "velocity":     velocity or 0,
            "heading":      heading or 0,
            "zone":         zone,
            "category":     classification["category"],
            "threat_level": classification["threat_level"],
            "note":         classification["note"],
            "detected_at":  datetime.now().isoformat(),
        }
        military.append(ac)
        print(f"[ADSB] ⚠️  {callsign} ({classification['category']}) "
              f"@ {zone}  {ac['alt_m']:.0f}m  {ac['heading']:.0f}°")

    if not military:
        print("[ADSB] 無軍用/偵察機")
        return []

    print(f"[ADSB] 偵測到 {len(military)} 架軍用/偵察機")

    # Ollama 分析
    analysis = analyze_with_ollama(military)
    if analysis:
        print(f"[ADSB] Ollama 分析：{analysis[:100]}")

    # 存入資料庫
    threat_cats = [a["category"] for a in military]
    title = f"【ADS-B】台海周邊軍機動態：{len(military)} 架"
    if "中共解放軍" in threat_cats:
        title = f"【ADS-B】⚠️ 偵測中共軍機：{len(military)} 架"
    elif "美軍偵察機" in threat_cats:
        title = f"【ADS-B】美軍偵察機台海周邊：{len(military)} 架"

    content_parts = []
    for a in military:
        content_parts.append(
            f"[{a['category']}] {a['callsign']} "
            f"@ {a['zone']} {a['alt_m']:.0f}m "
            f"航向{a['heading']:.0f}°"
        )
    if analysis:
        content_parts.append(f"\n[分析] {analysis}")

    insert_news(
        source="adsb_monitor",
        title=title,
        content="\n".join(content_parts),
        url="https://opensky-network.org",
        published_at=datetime.now(),
        category="軍事",
        keywords_matched=["偵察機", "軍機", "ADS-B"] + list(set(threat_cats))
    )

    return military


if __name__ == "__main__":
    results = run()
    print(f"\n{'='*55}")
    print(f"偵測結果：{len(results)} 架軍用/偵察機")
    for r in results:
        print(f"  {r['category']:10} {r['callsign']:12} "
              f"{r['zone']:12} {r['alt_m']:.0f}m")
