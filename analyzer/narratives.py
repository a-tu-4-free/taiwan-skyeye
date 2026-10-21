# 檔案名稱：analyzer/narratives.py
# 功能說明：認知作戰監測 — 對台說法（敘事）比對，純關鍵字、不用 AI
#   訊號條件（兩個都成立才算）：
#     1. 中共官媒近 3 天有在推這個說法（≥ CN_MIN 則）
#     2. 台灣端（PTT / 新聞）近 24 小時出現量 ≥ TW_MIN，且 ≥ 近 14 日日均 × TW_MULT
#   只回報「說法熱度」，不判定任何一篇文章或任何人

import os
import sys
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db import get_session
from database.models import NewsEvent

CN_MIN  = 2
TW_MIN  = 3
TW_MULT = 2.0

# 中共官媒來源（scrapers/china_media.py 的 SOURCES key）
CN_SOURCES = ["xinhua_world", "people_world", "globaltimes", "chinanews", "cgtn", "gwytb"]
# 台灣討論端
TW_PREFIXES = ("ptt_", "ltn_", "rti")

# 說法清單：zh = 中文關鍵字（台灣端 + 中新社/國台辦），en = 英文官媒用語
NARRATIVES = [
    {"id": "doubt_us",      "name": "疑美論／美國棄台",
     "zh": ["疑美", "棄台", "美國不會出兵", "美國靠不住", "棄子"],
     "en": ["abandon Taiwan", "will not defend Taiwan", "abandoned by the US"]},
    {"id": "us_pawn",       "name": "台灣是美國棋子",
     "zh": ["美國棋子", "棋子", "凱子", "保護費", "軍火商"],
     "en": ["pawn", "chess piece", "arms dealers", "cash cow"]},
    {"id": "weak_military", "name": "國軍不堪一擊",
     "zh": ["不堪一擊", "草莓兵", "一天就投降", "國軍沒戰力"],
     "en": ["no match for the PLA", "collapse within", "Taiwan military weak"]},
    {"id": "peaceful_unif", "name": "和平統一／兩岸一家親",
     "zh": ["兩岸一家親", "和平統一", "祖國統一", "兩岸同胞"],
     "en": ["peaceful reunification", "compatriots", "national reunification"]},
    {"id": "force_unif",    "name": "武統威脅／以武拒統必敗",
     "zh": ["武統", "以武拒統", "解放台灣", "收復台灣"],
     "en": ["reunification by force", "use of force", "reunify by force"]},
    {"id": "separatist",    "name": "台獨挑釁導致緊張",
     "zh": ["台獨挑釁", "倚美謀獨", "台獨分裂", "台獨勢力"],
     "en": ["separatist", "Taiwan independence forces", "secessionist"]},
    {"id": "part_of_china", "name": "台灣是中國一部分",
     "zh": ["中國的一部分", "中國台灣", "台灣地區", "一個中國原則"],
     "en": ["part of China", "Taiwan region", "one-China principle", "China's Taiwan"]},
    {"id": "dpp_authority", "name": "民進黨當局失能",
     "zh": ["民進黨當局", "賴當局", "綠色恐怖", "台灣當局"],
     "en": ["DPP authorities", "Lai authorities", "Taiwan authorities"]},
    {"id": "next_ukraine",  "name": "戰爭恐慌／台灣下一個烏克蘭",
     "zh": ["今日烏克蘭", "下一個烏克蘭", "台海開戰", "戰爭一觸即發"],
     "en": ["next Ukraine", "powder keg", "brink of war"]},
    {"id": "blockade",      "name": "封鎖／斷電斷網恐嚇",
     "zh": ["封鎖台灣", "圍台", "斷電斷網", "斷糧"],
     "en": ["blockade Taiwan", "encircle Taiwan", "seal off"]},
    {"id": "tsmc_hollow",   "name": "掏空台積電／去台化",
     "zh": ["掏空台積電", "美積電", "去台化", "護國神山被搬走"],
     "en": ["hollowing out TSMC", "hollow out Taiwan"]},
    {"id": "isolation",     "name": "國際孤立",
     "zh": ["國際孤立", "邦交歸零", "斷交潮"],
     "en": ["diplomatic isolation", "isolated internationally"]},
    {"id": "econ_lure",     "name": "惠台／融合發展",
     "zh": ["惠台", "融合發展", "對台優惠", "台胞證"],
     "en": ["integrated development", "benefit Taiwan compatriots", "preferential policies"]},
    {"id": "exchange",      "name": "兩岸交流統戰活動",
     "zh": ["海峽論壇", "兩岸青年交流", "台胞", "兩岸交流"],
     "en": ["Straits Forum", "cross-Strait exchanges"]},
    {"id": "election",      "name": "選舉介入敘事",
     "zh": ["戰爭與和平", "投民進黨就是戰爭", "選擇和平"],
     "en": ["war and peace", "choose peace"]},
]


def _match(n: dict, text: str) -> bool:
    low = text.lower()
    return any(k in text for k in n["zh"]) or any(k.lower() in low for k in n["en"])


def _texts(sources_filter, start: datetime, end: datetime) -> list:
    session = get_session()
    try:
        rows = session.query(NewsEvent.source, NewsEvent.title, NewsEvent.content).filter(
            NewsEvent.fetched_at >= start, NewsEvent.fetched_at < end
        ).all()
    finally:
        session.close()
    return [f"{t or ''} {(c or '')[:400]}" for s, t, c in rows if sources_filter(s or "")]


def _is_cn(s: str) -> bool:
    return s in CN_SOURCES


def _is_tw(s: str) -> bool:
    return s.startswith(TW_PREFIXES)


def scan_narratives() -> list:
    """
    回傳每個說法的統計：
    [{id, name, cn_3d, tw_24h, tw_baseline, signal}]，依 tw_24h 由高到低
    """
    now   = datetime.now()
    cn_3d = _texts(_is_cn, now - timedelta(days=3), now)
    tw_1d = _texts(_is_tw, now - timedelta(hours=24), now)
    tw_hist = [_texts(_is_tw, now - timedelta(days=i + 1), now - timedelta(days=i))
               for i in range(1, 15)]

    out = []
    for n in NARRATIVES:
        cn   = sum(1 for t in cn_3d if _match(n, t))
        tw   = sum(1 for t in tw_1d if _match(n, t))
        hist = [sum(1 for t in day if _match(n, t)) for day in tw_hist]
        base = sum(hist) / len(hist) if hist else 0.0
        signal = cn >= CN_MIN and tw >= TW_MIN and tw >= max(base, 0.5) * TW_MULT
        out.append({"id": n["id"], "name": n["name"], "cn_3d": cn, "tw_24h": tw,
                    "tw_baseline": round(base, 1), "signal": signal})
    out.sort(key=lambda x: (-x["signal"], -x["tw_24h"], -x["cn_3d"]))
    return out


def weekly_narrative_summary() -> list:
    """週報用：近 7 天各說法在官媒 / 台灣端的出現次數（只列有出現的）"""
    now = datetime.now()
    cn  = _texts(_is_cn, now - timedelta(days=7), now)
    tw  = _texts(_is_tw, now - timedelta(days=7), now)
    res = []
    for n in NARRATIVES:
        c = sum(1 for t in cn if _match(n, t))
        w = sum(1 for t in tw if _match(n, t))
        if c or w:
            res.append({"name": n["name"], "cn_7d": c, "tw_7d": w})
    res.sort(key=lambda x: -(x["cn_7d"] + x["tw_7d"]))
    return res


if __name__ == "__main__":
    for r in scan_narratives():
        flag = "🚨" if r["signal"] else "  "
        print(f"{flag} {r['name']:<16} 官媒3日:{r['cn_3d']:>3}  台灣24h:{r['tw_24h']:>3}  日均:{r['tw_baseline']}")
