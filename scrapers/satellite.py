# 檔案名稱：scrapers/satellite.py
# 功能說明：用 Google Maps Static API 抓取衛星影像，Gemini AI 分析中共重點軍事基地

import requests
import base64
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import GEMINI_API_KEY, GOOGLE_MAPS_API_KEY
from database.db import insert_news

# ==============================
# 重點監控區域
# bbox: [lon_min, lat_min, lon_max, lat_max]
# ==============================
WATCH_AREAS = [
    {
        "name":     "福建龍田機場",
        "desc":     "共軍殲擊機主要前線基地，監控停機坪飛機數量變化",
        "bbox":     [119.42, 25.58, 119.58, 25.72],
        "priority": "high",
    },
    {
        "name":     "廈門翔安機場",
        "desc":     "軍民兩用，監控共軍機隊異常集結",
        "bbox":     [118.12, 24.42, 118.28, 24.58],
        "priority": "high",
    },
    {
        "name":     "東山島兩棲基地",
        "desc":     "解放軍兩棲登陸演習重要基地，監控艦艇集結",
        "bbox":     [117.45, 23.70, 117.58, 23.82],
        "priority": "high",
    },
    {
        "name":     "寧德三都澳潛艦基地",
        "desc":     "解放軍潛艦基地，監控出入港動態",
        "bbox":     [119.88, 26.72, 120.02, 26.88],
        "priority": "medium",
    },
    {
        "name":     "泉州晉江機場",
        "desc":     "共軍前線備用基地",
        "bbox":     [118.58, 24.78, 118.72, 24.92],
        "priority": "medium",
    },
    {
        "name":     "海南三亞航母基地",
        "desc":     "解放軍航母母港，監控航母在港狀態",
        "bbox":     [109.52, 18.18, 109.68, 18.32],
        "priority": "low",
    },
]

CACHE_DIR   = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "satellite")
GEMINI_URL  = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent"


# ==============================
# Google Maps Static API 抓圖
# ==============================

def fetch_google_satellite(bbox: list) -> bytes:
    """
    用 Google Maps Static API 抓取衛星圖
    bbox: [lon_min, lat_min, lon_max, lat_max]
    """
    if not GOOGLE_MAPS_API_KEY or GOOGLE_MAPS_API_KEY in ("", "填入你的Google Maps API Key"):
        print("[SAT] ⚠️  未設定 GOOGLE_MAPS_API_KEY")
        return b""

    lat = (bbox[1] + bbox[3]) / 2
    lon = (bbox[0] + bbox[2]) / 2

    url = (
        f"https://maps.googleapis.com/maps/api/staticmap"
        f"?center={lat},{lon}"
        f"&zoom=14"
        f"&size=640x640"
        f"&scale=2"
        f"&maptype=satellite"
        f"&key={GOOGLE_MAPS_API_KEY}"
    )

    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200:
            size = len(resp.content)
            if size < 5120:
                print(f"[SAT] Google Maps 回傳過小（{size} bytes），API Key 可能無效")
                return b""
            print(f"[SAT] Google Maps 衛星圖取得成功（{size//1024} KB）")
            return resp.content
        else:
            print(f"[SAT] Google Maps 失敗：HTTP {resp.status_code}")
            print(f"[SAT] 回應：{resp.text[:200]}")
            return b""
    except Exception as e:
        print(f"[SAT ERROR] Google Maps: {e}")
        return b""


# ==============================
# 快取管理
# ==============================

def should_fetch_today(area_name: str) -> bool:
    """同一區域同一天只抓一次"""
    today    = datetime.now().strftime("%Y%m%d")
    filepath = os.path.join(CACHE_DIR, f"{area_name}_{today}.png")
    if not os.path.exists(filepath):
        return True
    size = os.path.getsize(filepath)
    if size < 10240:
        print(f"[SAT] 快取過小（{size} bytes），重新抓取")
        os.remove(filepath)
        return True
    return False


def save_image_cache(image_bytes: bytes, area_name: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    filename = f"{area_name}_{datetime.now().strftime('%Y%m%d')}.png"
    filepath = os.path.join(CACHE_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(image_bytes)
    return filepath


def load_cached_image(area_name: str) -> bytes:
    today    = datetime.now().strftime("%Y%m%d")
    filepath = os.path.join(CACHE_DIR, f"{area_name}_{today}.png")
    if os.path.exists(filepath):
        with open(filepath, "rb") as f:
            return f.read()
    return b""


# ==============================
# Gemini 分析
# ==============================

def analyze_with_gemini(image_bytes: bytes, area_name: str, area_desc: str) -> dict:
    """用 Gemini Flash 分析衛星影像"""
    if not image_bytes:
        return {"summary": "無影像資料", "threat_level": 0}

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    prompt = (
        f"你是台灣國防情報分析師，分析中國解放軍基地衛星影像。\n"
        f"分析區域：{area_name}\n區域說明：{area_desc}\n\n"
        f"請分析這張 Google Maps 衛星影像，回報：\n"
        f"1. 可見的軍事設施（跑道、停機坪、港口、艦艇、車輛等）\n"
        f"2. 是否有異常集結或活動跡象\n"
        f"3. 威脅評估（0-10分）\n"
        f"4. 重要觀察事項\n\n"
        f"請用繁體中文回答，格式：\n"
        f"【設施狀況】...\n【異常跡象】...\n【威脅評分】X/10\n【重要觀察】...\n\n"
        f"判斷需保守，避免過度推斷。"
    )

    try:
        payload = {
            "contents": [{"parts": [
                {"inline_data": {"mime_type": "image/png", "data": image_b64}},
                {"text": prompt}
            ]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 500}
        }
        resp = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json=payload, timeout=30
        )
        if resp.status_code == 200:
            text  = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            match = re.search(r'威脅評分[】\]]*\s*(\d+(?:\.\d+)?)/10', text)
            score = float(match.group(1)) if match else 0
            return {"summary": text, "threat_level": score,
                    "area": area_name, "analyzed_at": datetime.now().isoformat()}
        elif resp.status_code == 429:
            print("[SAT] Gemini 429，切換 Ollama 備援...")
            return analyze_with_ollama(image_bytes, area_name, area_desc)
        else:
            print(f"[SAT] Gemini 失敗：HTTP {resp.status_code}")
            return analyze_with_ollama(image_bytes, area_name, area_desc)
    except Exception as e:
        print(f"[SAT ERROR] Gemini: {e}")
        return {"summary": f"分析錯誤：{e}", "threat_level": 0}


def analyze_with_ollama(image_bytes: bytes, area_name: str, area_desc: str) -> dict:
    """Ollama 本地備援分析（llava 視覺模型）"""
    try:
        from config import OLLAMA_BASE_URL

        # 自動選最佳視覺模型
        model = "llava:7b"
        try:
            r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
            models = [m["name"] for m in r.json().get("models", [])]
            for pref in ["llava", "moondream", "bakllava"]:
                match = next((m for m in models if pref in m), None)
                if match:
                    model = match
                    break
        except Exception:
            pass

        print(f"[SAT] Ollama 備援，模型：{model}")
        # 縮小圖片到 512x512，減少 llava 處理時間
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(image_bytes))
            img = img.convert("RGB")  # 統一轉 RGB，解決 palette mode 問題
            img = img.resize((512, 512), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            image_bytes_small = buf.getvalue()
            print(f"[SAT] 圖片縮小：{len(image_bytes)//1024}KB → {len(image_bytes_small)//1024}KB")
        except ImportError:
            image_bytes_small = image_bytes  # PIL 未安裝，直接用原圖
        except Exception as e:
            print(f"[SAT] 圖片縮小失敗：{e}，使用原圖")
            image_bytes_small = image_bytes

        image_b64 = base64.b64encode(image_bytes_small).decode("utf-8")
        prompt = (
            f"分析這張衛星影像，區域：{area_name}（{area_desc}）\n"
            f"用繁體中文回答：\n"
            f"【設施狀況】可見設施\n【威脅評分】X/10\n【重要觀察】簡短說明\n"
            f"判斷保守。"
        )
        payload = {
            "model": model, "prompt": prompt,
            "images": [image_b64], "stream": False,
            "options": {"temperature": 0.3, "num_predict": 300}
        }
        # CPU 跑 llava 很慢，timeout 設 60 秒
        # 超時就跳過，等 Gemini 額度明天重置
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload, timeout=60
        )
        if resp.status_code == 200:
            text  = resp.json().get("response", "")
            match = re.search(r'威脅評分[】\]]*\s*(\d+(?:\.\d+)?)/10', text)
            score = float(match.group(1)) if match else 0
            print(f"[SAT] Ollama 分析完成，威脅：{score}/10")
            return {"summary": text, "threat_level": score,
                    "area": area_name, "source": "ollama"}
    except requests.exceptions.Timeout:
        print("[SAT] Ollama timeout（CPU 跑 llava 太慢），等明天 Gemini 額度重置")
    except Exception as e:
        print(f"[SAT] Ollama 備援失敗：{e}")
    return {"summary": "待 Gemini 分析（明日重置）", "threat_level": 0}


# ==============================
# 主執行函式
# ==============================

def run(priority_only=True) -> list:
    print("[SAT] 開始衛星影像分析（Google Maps）...")

    if not GOOGLE_MAPS_API_KEY or GOOGLE_MAPS_API_KEY in ("", "填入你的Google Maps API Key"):
        print("[SAT] ⚠️  未設定 GOOGLE_MAPS_API_KEY，跳過")
        return []

    all_areas = [a for a in WATCH_AREAS if a["priority"] == "high"] if priority_only else WATCH_AREAS
    day_index = datetime.now().timetuple().tm_yday % len(all_areas)
    area      = all_areas[day_index]
    print(f"[SAT] 今日分析：{area['name']}（第{day_index+1}/{len(all_areas)}輪）")

    if should_fetch_today(area["name"]):
        image_bytes = fetch_google_satellite(area["bbox"])
        if image_bytes:
            save_image_cache(image_bytes, area["name"])
            print(f"[SAT] 影像已儲存：{area['name']}")
        else:
            print(f"[SAT] {area['name']} 無可用影像")
            return []
    else:
        print(f"[SAT] {area['name']} 使用今日快取")
        image_bytes = load_cached_image(area["name"])

    if not image_bytes:
        return []

    # AI 分析已停用（Gemini/Ollama 視覺分析效果不穩定）
    # 只儲存影像，供 TG Bot /satellite 指令顯示原始衛星圖
    print(f"[SAT] {area['name']} 影像取得完成（無AI分析）")

    return [{
        "area":         area["name"],
        "threat_level": 0,
        "summary":      "",   # 不再附 AI 分析文字
        "image_bytes":  image_bytes,
        "priority":     area["priority"],
    }]


def get_latest_analysis() -> list:
    from database.db import get_session
    from database.models import NewsEvent
    session = get_session()
    try:
        cutoff = datetime.now() - timedelta(hours=24)
        items  = session.query(NewsEvent).filter(
            NewsEvent.source == "satellite",
            NewsEvent.published_at >= cutoff
        ).all()
        return [{"title": n.title, "content": n.content} for n in items]
    finally:
        session.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="分析所有區域")
    args    = parser.parse_args()
    results = run(priority_only=not args.all)
    for r in results:
        print(f"\n{'='*50}")
        print(f"📡 {r['area']} | 威脅：{r['threat_level']}/10")
        print(r['summary'])