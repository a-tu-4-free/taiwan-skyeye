# 檔案名稱：maps/cable_data.py
# 功能說明：海底電纜「單一資料來源」
#   - 登陸站、示意路由（全程走海面，不穿越陸地）
#   - MODA 名稱比對（match_cable_name）
#   - 故障點推估（locate_fault）
# map_generator / map_notifier / alert_engine / card_generator / cable_monitor 共用
#
# 登陸站對照（submarinenetworks.com Taiwan stations）：
#   淡水：APCN-2、SJC2、TPE、FASTER、C2C、TSE-1（+ 臺馬二/三號）
#   八里：EAC1
#   頭城：APG、NCP、PLCN、E2A、FNAL/RNAL
# 路由為「示意」：登陸站正確、走向正確、避開陸地，非實際海纜鋪設座標。

import math
import re

# ==============================
# 登陸點 / 參考地點 [lat, lon]
# ==============================
TAMSUI   = [25.188, 121.415]   # 淡水沙崙
PALI     = [25.155, 121.385]   # 新北八里
TOUCHENG = [24.858, 121.830]   # 宜蘭頭城
NANGAN   = [26.155, 119.935]   # 馬祖南竿
DONGYIN  = [26.365, 120.490]   # 馬祖東引
KINMEN   = [24.420, 118.410]   # 金門
MAGONG   = [23.565, 119.575]   # 澎湖馬公
BUDAI    = [23.375, 120.140]   # 嘉義布袋
TAINAN   = [23.000, 120.130]   # 台南（示意）
HK       = [22.215, 114.215]   # 香港舂坎角
FUZHOU   = [25.950, 119.690]   # 福州長樂
XIAMEN   = [24.470, 118.190]   # 廈門
SHANGHAI = [31.550, 121.950]   # 上海崇明
JAPAN    = [34.900, 139.900]   # 日本房總（千倉/丸山）
US_EDGE  = [33.500, 151.000]   # 往美國（超出地圖右緣）

# ==============================
# 共用海上航路（waypoints）
# ==============================
_TAMSUI_N   = [TAMSUI, [25.36, 121.30], [25.52, 121.55], [25.36, 122.00]]   # 淡水 → 繞北海岸（避開富貴角、花瓶嶼）
_PALI_N     = [PALI,   [25.27, 121.25], [25.52, 121.55], [25.36, 122.00]]
_TOUCHENG_E = [TOUCHENG, [24.93, 122.08]]                                     # 由龜山島北側出海
_TOUCHENG_S = [TOUCHENG, [24.78, 122.08]]                                     # 由龜山島南側出海

_NE_TO_JAPAN = [[25.90, 122.80], [26.80, 124.60], [28.60, 128.90],
                [31.00, 133.80], [33.50, 138.50], [33.50, 140.20],   # 三宅島/八丈島之間
                [34.50, 140.40], JAPAN]
# 頭城往東北：先往東再北上，避開釣魚台列嶼
_TOUCHENG_NE = [[25.30, 123.00], [25.40, 124.00], [26.40, 125.20]]
_JAPAN_TO_US = [[34.20, 145.00], US_EDGE]
_TO_SHANGHAI = [[27.20, 122.40], [29.50, 123.30], [31.10, 123.00], SHANGHAI]  # 避開舟山群島

_STRAIT_TO_HK = [[25.00, 120.75], [24.30, 119.95], [23.75, 119.10],
                 [22.95, 117.60], [22.30, 115.60], [22.10, 114.55], [22.16, 114.30], HK]
_TOUCHENG_S_TO_HK = [[23.60, 121.95], [22.50, 121.90], [21.90, 121.85],   # 蘭嶼東側
                     [21.40, 121.20], [21.20, 120.60], [21.40, 118.60],
                     [22.00, 116.00], [22.10, 114.55], [22.16, 114.30], HK]


def _tamsui_strait():
    return [TAMSUI, [25.33, 121.32]] + _STRAIT_TO_HK


def _pali_strait():
    return [PALI, [25.25, 121.27]] + _STRAIT_TO_HK


# ==============================
# 電纜清單
# segments：可多段（例如一條往日本、一條往香港）
# codes：括號內英文代碼（正規化後完全比對）
# zh：中文名稱關鍵字（子字串比對，長的優先）
# ==============================
SUBMARINE_CABLES = [
    # ── 淡水 ─────────────────────────────────────
    {"name": "APCN-2", "landing": "淡水", "intl": True,
     "route": "淡水 → 上海崇明 / 香港 → 日韓・東南亞", "len": "19000km",
     "codes": ["APCN2", "APCN-2"], "zh": ["亞太網路二號", "亞太2號", "亞太二號"],
     "segments": [_TAMSUI_N[:3] + _TO_SHANGHAI, _tamsui_strait()]},
    {"name": "SJC2", "landing": "淡水", "intl": True,
     "route": "淡水 → 日本 / 香港 → 東南亞", "len": "10500km",
     "codes": ["SJC2"], "zh": ["東南亞日本二號"],
     "segments": [_TAMSUI_N + _NE_TO_JAPAN, _tamsui_strait()]},
    {"name": "TPE", "landing": "淡水", "intl": True,
     "route": "淡水 → 上海 / 日本 → 美國", "len": "17700km",
     "codes": ["TPE"], "zh": ["橫太平洋快速"],
     "segments": [_TAMSUI_N + _NE_TO_JAPAN + _JAPAN_TO_US, _TAMSUI_N[:3] + _TO_SHANGHAI]},
    {"name": "FASTER", "landing": "淡水", "intl": True,
     "route": "淡水 → 日本 → 美國（Google）", "len": "11600km",
     "codes": ["FASTER"], "zh": [],
     "segments": [_TAMSUI_N + _NE_TO_JAPAN + _JAPAN_TO_US]},
    {"name": "C2C", "landing": "淡水", "intl": True,
     "route": "淡水 → 日本 / 香港", "len": "17000km",
     "codes": ["C2C"], "zh": [],
     "segments": [_TAMSUI_N + _NE_TO_JAPAN, _tamsui_strait()]},
    {"name": "TSE-1", "landing": "淡水", "intl": True,
     "route": "淡水 → 福州長樂（兩岸直連）", "len": "270km",
     "codes": ["TSE1", "TSE"], "zh": ["海峽光纜一號", "海峽光纜"],
     "segments": [[TAMSUI, [25.33, 121.32], [25.60, 120.60], [25.90, 120.00], FUZHOU]]},
    # ── 八里 ─────────────────────────────────────
    {"name": "EAC1", "landing": "八里", "intl": True,
     "route": "八里 → 日韓 / 香港 → 東南亞", "len": "36000km",
     "codes": ["EAC1", "EAC", "EACC2C"], "zh": ["東亞交匯一號", "東亞交匯"],
     "segments": [_PALI_N + _NE_TO_JAPAN, _pali_strait()]},
    # ── 頭城 ─────────────────────────────────────
    {"name": "APG", "landing": "頭城", "intl": True,
     "route": "頭城 → 日本 / 香港 → 東南亞", "len": "10400km",
     "codes": ["APG"], "zh": ["亞太直達"],
     "segments": [_TOUCHENG_E + _TOUCHENG_NE + _NE_TO_JAPAN[2:],
                  _TOUCHENG_S + _TOUCHENG_S_TO_HK]},
    {"name": "NCP", "landing": "頭城", "intl": True,
     "route": "頭城 → 上海 / 日本 → 美國", "len": "13600km",
     "codes": ["NCP"], "zh": ["新橫太平洋"],
     "segments": [_TOUCHENG_E + _TOUCHENG_NE + _NE_TO_JAPAN[2:] + _JAPAN_TO_US,
                  _TOUCHENG_E + [[25.40, 122.70], [27.50, 123.20]] + _TO_SHANGHAI[1:]]},
    {"name": "PLCN", "landing": "頭城", "intl": True,
     "route": "頭城 → 美國（Google/Meta）", "len": "12900km",
     "codes": ["PLCN"], "zh": ["太平洋光纜"],
     "segments": [_TOUCHENG_S + [[24.20, 122.40], [22.50, 126.00], [20.50, 134.00], [19.50, 151.00]]]},
    {"name": "E2A", "landing": "頭城", "intl": True,
     "route": "頭城 → 日韓 → 美國", "len": "12500km",
     "codes": ["E2A"], "zh": [],
     "segments": [_TOUCHENG_E + _TOUCHENG_NE + _NE_TO_JAPAN[2:] + _JAPAN_TO_US]},
    {"name": "FNAL/RNAL", "landing": "頭城", "intl": True,
     "route": "頭城 → 日韓 / 香港", "len": "9800km",
     "codes": ["FNAL", "RNAL", "FLAG"], "zh": [],
     "segments": [_TOUCHENG_E + _TOUCHENG_NE + _NE_TO_JAPAN[2:],
                  _TOUCHENG_S + _TOUCHENG_S_TO_HK]},
    # ── 國內海纜 ─────────────────────────────────
    {"name": "TDM2", "landing": "淡水", "intl": False,
     "route": "淡水 → 東引 → 南竿", "len": "233km",
     "codes": ["TDM2"], "zh": ["臺馬二號", "台馬二號"],
     "segments": [[TAMSUI, [25.33, 121.32], [25.85, 120.95], DONGYIN, [26.25, 120.15], NANGAN]]},
    {"name": "TM3", "landing": "淡水", "intl": False,
     "route": "淡水 → 南竿", "len": "233km",
     "codes": ["TM3", "TDM3"], "zh": ["臺馬三號", "台馬三號"],
     "segments": [[TAMSUI, [25.33, 121.30], [25.70, 120.65], [26.12, 120.15], NANGAN]]},
    {"name": "臺澎海纜", "landing": "布袋", "intl": False,
     "route": "嘉義布袋 → 澎湖馬公", "len": "80km",
     "codes": ["TPCA", "TP2", "TP3"], "zh": ["臺澎", "台澎"],
     "segments": [[BUDAI, [23.42, 119.90], MAGONG]]},
    {"name": "臺金海纜", "landing": "台南", "intl": False,
     "route": "台灣本島 → 金門", "len": "200km",
     "codes": ["TKC", "TK2", "TK3"], "zh": ["臺金", "台金"],
     "segments": [[TAINAN, [22.95, 119.40], [23.50, 118.75], [24.15, 118.50], KINMEN]]},
    {"name": "澎金海纜", "landing": "馬公", "intl": False,
     "route": "澎湖馬公 → 金門", "len": "140km",
     "codes": [], "zh": ["澎金"],
     "segments": [[MAGONG, [23.75, 119.20], [24.20, 118.65], KINMEN]]},
    {"name": "金廈海纜", "landing": "金門", "intl": False,
     "route": "金門 → 廈門（兩岸）", "len": "21km",
     "codes": ["CSCN"], "zh": ["金廈", "廈金"],
     "segments": [[[24.47, 118.31], [24.465, 118.24], XIAMEN]]},
]

CABLES_BY_NAME = {c["name"]: c for c in SUBMARINE_CABLES}


# ==============================
# 名稱比對
# ==============================
def _norm(s: str) -> str:
    return re.sub(r"[\s\-_/（）()]", "", (s or "").upper())


_CODE_INDEX = {}
for _c in SUBMARINE_CABLES:
    _CODE_INDEX[_norm(_c["name"])] = _c["name"]
    for _code in _c["codes"]:
        _CODE_INDEX[_norm(_code)] = _c["name"]

# 中文關鍵字：長的先比，避免「東南亞日本」吃掉「東南亞日本二號」
_ZH_INDEX = sorted(
    [(zh, c["name"]) for c in SUBMARINE_CABLES for zh in c["zh"]],
    key=lambda x: -len(x[0])
)


def match_cable_name(db_name: str) -> str:
    """
    MODA / DB 電纜名稱 → 地圖 key，找不到回傳 ""
    1. 括號內代碼精確比對：「臺馬二號海纜 ( TDM2 )」→ TDM2
    2. 整串名稱就是代碼：「APG」
    3. 中文關鍵字子字串比對（長字優先）
    """
    if not db_name:
        return ""
    for code in re.findall(r"[（(]\s*([A-Za-z0-9\-/ ]+?)\s*[)）]", db_name):
        key = _CODE_INDEX.get(_norm(code))
        if key:
            return key
    key = _CODE_INDEX.get(_norm(db_name))
    if key:
        return key
    for zh, name in _ZH_INDEX:
        if zh in db_name:
            return name
    # 英文代碼出現在字串中（以非英數字元分隔）
    for code in re.findall(r"[A-Za-z][A-Za-z0-9\-]*", db_name):
        key = _CODE_INDEX.get(_norm(code))
        if key:
            return key
    return ""


def get_cable_info(db_name: str) -> dict:
    """回傳 {name, route, len}，找不到給預設值"""
    key = match_cable_name(db_name)
    if key:
        c = CABLES_BY_NAME[key]
        return {"name": key, "route": c["route"], "len": c["len"]}
    return {"name": db_name, "route": "台灣周邊海域", "len": "N/A"}


# ==============================
# 幾何工具
# ==============================
def _haversine_km(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 6371 * 2 * math.asin(math.sqrt(h))


def offset_line(coords: list, d: float) -> list:
    """
    整條線往法線方向平移 d 度（第一點＝登陸站不動，第二點起漸進）
    讓同走廊的多條電纜分開顯示，不會全部疊成一條
    """
    if not d or len(coords) < 2:
        return coords
    out = [coords[0]]
    n = len(coords)
    for i in range(1, n):
        p0 = coords[i - 1]
        p1 = coords[i + 1] if i + 1 < n else coords[i]
        dy, dx = p1[0] - p0[0], p1[1] - p0[1]     # dy=Δlat, dx=Δlon
        L = math.hypot(dx, dy) or 1.0
        k = d if i > 1 else d * 0.4               # 靠岸段偏移較小
        out.append([coords[i][0] + (dx / L) * k,  # 法線方向平移
                    coords[i][1] - (dy / L) * k])
    return out


def _walk(coords: list, km: float):
    """沿折線從起點走 km 公里，回傳座標"""
    remain = km
    for a, b in zip(coords, coords[1:]):
        seg = _haversine_km(a, b)
        if seg >= remain and seg > 0:
            t = remain / seg
            return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
        remain -= seg
    return coords[-1]


_REF_PLACES = {
    "沙崙": TAMSUI, "淡水": TAMSUI, "八里": PALI, "頭城": TOUCHENG,
    "南竿": NANGAN, "東引": DONGYIN, "金門": KINMEN, "馬公": MAGONG,
    "澎湖": MAGONG, "布袋": BUDAI, "舂坎角": HK, "香港": HK,
    "福州": FUZHOU, "長樂": FUZHOU, "廈門": XIAMEN, "崇明": SHANGHAI,
    "上海": SHANGHAI,
}

_FAULT_RE = re.compile(r"距(.{1,12}?)約?\s*([\d.]+)\s*公里")


def locate_fault(cable_name: str, text: str):
    """
    從 MODA 障礙描述推估故障點
    例：「距淡水沙崙約58公里處斷纜」→ 沿電纜從淡水走 58km
    回傳 (lat, lon, 說明) 或 None（參考點不在地圖範圍內）
    """
    cable = CABLES_BY_NAME.get(cable_name)
    if not cable or not text:
        return None
    m = _FAULT_RE.search(text)
    if not m:
        return None
    place, km = m.group(1), float(m.group(2))
    ref = next((v for k, v in _REF_PLACES.items() if k in place), None)
    if ref is None:
        return None
    # 找最接近參考點的頂點（可能是端點或中繼點，如東引），沿較長的一側走
    best = None
    for seg in cable["segments"]:
        for i, p in enumerate(seg):
            dist = _haversine_km(p, ref)
            for coords in (seg[i:], seg[i::-1]):
                if len(coords) < 2:
                    continue
                length = sum(_haversine_km(a, b) for a, b in zip(coords, coords[1:]))
                cand = (round(dist), -length, coords)
                if best is None or cand[:2] < best[:2]:
                    best = cand
    if best is None or best[0] > 60:
        return None
    pt = _walk(best[2], km)
    return pt[0], pt[1], f"距{place}約{km:g}公里（推估）"
