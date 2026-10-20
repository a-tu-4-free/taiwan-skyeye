# 檔案名稱：bot/i18n.py
# 功能說明：多語言支援（繁體中文/簡體中文/英文）
# 設定儲存在記憶體，Bot 重啟後重置為預設語言

from datetime import datetime

# ==============================
# 翻譯字典
# ==============================
TRANSLATIONS = {
    "zh-TW": {
        # 通用
        "threat_index":    "台灣國防威脅指數",
        "daily_report":    "台灣國防情勢日報",
        "morning_brief":   "台海今日概況",
        "weekly_report":   "台灣國防情勢週報",
        "cable_status":    "台灣海底電纜狀態",
        "vessel_alert":    "可疑船隻警報",
        "anomaly_alert":   "情勢異常警報",
        # 威脅等級
        "level_calm":      "平穩",
        "level_normal":    "正常",
        "level_elevated":  "偏高",
        "level_high":      "高度警示",
        "level_critical":  "緊急",
        # 擾台
        "intrusion":       "擾台",
        "aircraft":        "共機",
        "vessel":          "共艦",
        "median_cross":    "越中線",
        "adiz_entry":      "進入ADIZ",
        # 台海
        "taiwan_strait":   "台海",
        "status_calm":     "平穩",
        "status_tense":    "偏高",
        "status_critical": "高度緊張",
        # 源頭
        "source_mnd":      "國防部",
        "source_cga":      "海巡署",
        "source_ptt":      "PTT",
        "source_intl":     "國際媒體",
        # 行動
        "see_details":     "/status 詳情",
        "see_map":         "/map 地圖",
        "see_report":      "/today 日報",
        # 通知
        "urgent":          "緊急警示",
        "high":            "高度警示",
        "medium":          "一般警示",
        "low":             "低度關注",
        "no_anomaly":      "目前無活躍異常",
        # 衛星
        "satellite":       "衛星影像",
        "sat_no_data":     "今日尚無衛星資料",
        # 其他
        "updated":         "更新",
        "source":          "來源",
        "loading":         "載入中...",
    },
    "zh-CN": {
        # 通用
        "threat_index":    "台湾国防威胁指数",
        "daily_report":    "台湾国防形势日报",
        "morning_brief":   "台海今日概况",
        "weekly_report":   "台湾国防形势周报",
        "cable_status":    "台湾海底电缆状态",
        "vessel_alert":    "可疑船只警报",
        "anomaly_alert":   "形势异常警报",
        # 威脅等級
        "level_calm":      "平稳",
        "level_normal":    "正常",
        "level_elevated":  "偏高",
        "level_high":      "高度警示",
        "level_critical":  "紧急",
        # 擾台
        "intrusion":       "扰台",
        "aircraft":        "共机",
        "vessel":          "共舰",
        "median_cross":    "越中线",
        "adiz_entry":      "进入ADIZ",
        # 台海
        "taiwan_strait":   "台海",
        "status_calm":     "平稳",
        "status_tense":    "偏高",
        "status_critical": "高度紧张",
        # 源頭
        "source_mnd":      "国防部",
        "source_cga":      "海巡署",
        "source_ptt":      "PTT",
        "source_intl":     "国际媒体",
        # 行動
        "see_details":     "/status 详情",
        "see_map":         "/map 地图",
        "see_report":      "/today 日报",
        # 通知
        "urgent":          "紧急警示",
        "high":            "高度警示",
        "medium":          "一般警示",
        "low":             "低度关注",
        "no_anomaly":      "目前无活跃异常",
        # 衛星
        "satellite":       "卫星图像",
        "sat_no_data":     "今日暂无卫星资料",
        # 其他
        "updated":         "更新",
        "source":          "来源",
        "loading":         "加载中...",
    },
    "en": {
        # General
        "threat_index":    "Taiwan Defense Threat Index",
        "daily_report":    "Taiwan Defense Situation Report",
        "morning_brief":   "Taiwan Strait Daily Brief",
        "weekly_report":   "Taiwan Defense Weekly Report",
        "cable_status":    "Submarine Cable Status",
        "vessel_alert":    "Suspicious Vessel Alert",
        "anomaly_alert":   "Situation Anomaly Alert",
        # Threat levels
        "level_calm":      "Calm",
        "level_normal":    "Normal",
        "level_elevated":  "Elevated",
        "level_high":      "High Alert",
        "level_critical":  "Critical",
        # Intrusion
        "intrusion":       "Intrusion",
        "aircraft":        "PLA Aircraft",
        "vessel":          "PLA Vessel",
        "median_cross":    "Median Line Crossed",
        "adiz_entry":      "ADIZ Entry",
        # Strait
        "taiwan_strait":   "Taiwan Strait",
        "status_calm":     "Calm",
        "status_tense":    "Elevated",
        "status_critical": "High Tension",
        # Sources
        "source_mnd":      "MND",
        "source_cga":      "CGA",
        "source_ptt":      "PTT",
        "source_intl":     "International Media",
        # Actions
        "see_details":     "/status Details",
        "see_map":         "/map Map",
        "see_report":      "/today Report",
        # Notifications
        "urgent":          "URGENT",
        "high":            "HIGH ALERT",
        "medium":          "ADVISORY",
        "low":             "MONITOR",
        "no_anomaly":      "No active anomalies",
        # Satellite
        "satellite":       "Satellite Imagery",
        "sat_no_data":     "No satellite data today",
        # Other
        "updated":         "Updated",
        "source":          "Source",
        "loading":         "Loading...",
    },
}

# ==============================
# 使用者語言偏好（記憶體，重啟重置）
# ==============================
_user_lang: dict[int, str] = {}   # {user_id: "zh-TW"/"zh-CN"/"en"}

SUPPORTED_LANGS = list(TRANSLATIONS.keys())
DEFAULT_LANG    = "zh-TW"

LANG_DISPLAY = {
    "zh-TW": "繁體中文",
    "zh-CN": "简体中文",
    "en":    "English",
}


def get_user_lang(user_id: int) -> str:
    return _user_lang.get(user_id, DEFAULT_LANG)


def set_user_lang(user_id: int, lang: str) -> bool:
    if lang in SUPPORTED_LANGS:
        _user_lang[user_id] = lang
        return True
    return False


def t(key: str, user_id: int = 0, lang: str = "") -> str:
    """
    取得翻譯字串
    優先使用 user_id 的設定，其次 lang 參數，最後預設繁中
    """
    effective_lang = lang or get_user_lang(user_id) or DEFAULT_LANG
    return TRANSLATIONS.get(effective_lang, TRANSLATIONS[DEFAULT_LANG]).get(key, key)

