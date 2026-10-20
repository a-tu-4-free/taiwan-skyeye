# 檔案名稱：scrapers/satellite.py
# 功能說明：用 Google Maps Static API 抓取中共重點軍事基地衛星影像（每日輪替一處）
#           AI 影像分析已停用（效果不穩定），僅推送原始影像

import requests
import os
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import GOOGLE_MAPS_API_KEY

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