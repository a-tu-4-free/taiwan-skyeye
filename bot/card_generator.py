# 檔案名稱：bot/card_generator.py
# 功能說明：用 matplotlib 生成各 scraper 的靜態通知卡片（不依賴瀏覽器）

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import matplotlib.patheffects as pe
import matplotlib.font_manager as fm
import numpy as np
from datetime import datetime
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

# ==============================
# 中文字型設定
# ==============================
def _setup_chinese_font():
    """設定中文字型，優先使用 Microsoft JhengHei"""
    candidates = [
        "Microsoft JhengHei",   # Windows 正黑體
        "Microsoft YaHei",      # 微軟雅黑
        "PingFang TC",          # macOS 繁中
        "Noto Sans CJK TC",     # Linux
        "SimHei",               # 中易黑體
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    for font in candidates:
        if font in available:
            matplotlib.rcParams['font.family'] = font
            matplotlib.rcParams['axes.unicode_minus'] = False
            print(f"[CARD] 使用字型：{font}")
            return font

    # 找不到預設字型，嘗試找系統中的 .ttc/.ttf
    import glob
    patterns = [
        "C:/Windows/Fonts/msjh*.ttc",
        "C:/Windows/Fonts/msyh*.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/**/NotoSansCJK*.ttf",
    ]
    for pattern in patterns:
        files = glob.glob(pattern, recursive=True)
        if files:
            try:
                fm.fontManager.addfont(files[0])
                prop = fm.FontProperties(fname=files[0])
                matplotlib.rcParams['font.family'] = prop.get_name()
                matplotlib.rcParams['axes.unicode_minus'] = False
                print(f"[CARD] 載入字型檔：{files[0]}")
                return prop.get_name()
            except Exception:
                pass

    print("[CARD] ⚠️  找不到中文字型，文字可能顯示為方塊")
    return None

_FONT_NAME = _setup_chinese_font()

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cards")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 設計 token
BG_DARK    = "#060d18"
BG_CARD    = "#0a1525"
BG_ACCENT  = "#0f2035"
C_BORDER   = "#1e3a5f"
C_TEXT     = "#c8d8e8"
C_TEXT_DIM = "#4a7a9b"
C_GOLD     = "#f5c842"
C_RED      = "#f44336"
C_ORANGE   = "#ff9800"
C_YELLOW   = "#ffc107"
C_GREEN    = "#4caf50"
C_BLUE     = "#4488ff"
C_TEAL     = "#00bcd4"

SEV_COLOR  = {"CRITICAL": C_RED, "HIGH": C_ORANGE, "MEDIUM": C_YELLOW, "LOW": C_GREEN}

def _setup_fig(w=8, h=5):
    fig, ax = plt.subplots(figsize=(w, h))
    fig.patch.set_facecolor(BG_DARK)
    ax.set_facecolor(BG_DARK)
    ax.axis('off')
    return fig, ax

def _save(fig, name: str) -> str:
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(OUTPUT_DIR, f"{name}_{ts}.png")
    fig.savefig(path, dpi=150, bbox_inches='tight',
                facecolor=BG_DARK, edgecolor='none')
    plt.close(fig)
    return path

def _header(ax, title: str, subtitle: str, sev: str = "HIGH",
            y_start: float = 0.93):
    color = SEV_COLOR.get(sev, C_ORANGE)
    ax.text(0.04, y_start, title, transform=ax.transAxes,
            fontsize=15, fontweight='bold', color=color,
            path_effects=[pe.withStroke(linewidth=3, foreground=BG_DARK)])
    ax.text(0.04, y_start - 0.09, subtitle, transform=ax.transAxes,
            fontsize=9, color=C_TEXT_DIM)
    ax.axhline(y=y_start - 0.13, xmin=0.04, xmax=0.96,
               color=C_BORDER, linewidth=0.8)
    return y_start - 0.18

def _row(ax, label: str, value: str, y: float,
         label_color=None, value_color=None):
    ax.text(0.04, y, label, transform=ax.transAxes,
            fontsize=9, color=label_color or C_TEXT_DIM)
    ax.text(0.38, y, value, transform=ax.transAxes,
            fontsize=9, color=value_color or C_TEXT,
            fontweight='bold')
    return y - 0.09

def _footer(ax, source: str, update_time: str = None):
    t = update_time or datetime.now().strftime("%Y-%m-%d %H:%M")
    ax.axhline(y=0.10, xmin=0.04, xmax=0.96, color=C_BORDER, linewidth=0.5)
    ax.text(0.04, 0.05, f"來源：{source}", transform=ax.transAxes,
            fontsize=8, color=C_TEXT_DIM)
    ax.text(0.96, 0.05, t, transform=ax.transAxes,
            fontsize=8, color=C_TEXT_DIM, ha='right')

# ==============================
# MND 擾台卡片
# ==============================
# ==============================
# MND 卡片輔助函式
# ==============================

DIRECTION_DESC = {
    "北部":  "台灣北部空域",
    "中部":  "台灣中部空域及海峽中線附近",
    "南部":  "台灣南部及巴士海峽",
    "西南":  "西南ADIZ及南海方向",
    "西北":  "西北ADIZ及福建外海",
    "東南":  "東南外海及巴士海峽",
    "東北":  "東北外海及宮古水道",
    "東部":  "台灣東部外海",
    "西":    "台灣海峽中段",
}

def make_mnd_card(intrusion_data: dict) -> str:
    """
    共軍擾台通知卡片
    intrusion_data: {aircraft_count, vessel_count, aircraft_types,
                     crossed_median_line, adiz_entry, entry_direction,
                     date}
    """
    aircraft   = intrusion_data.get("aircraft_count", 0)
    vessels    = intrusion_data.get("vessel_count", 0)
    types      = intrusion_data.get("aircraft_types", "未知")
    crossed    = intrusion_data.get("crossed_median_line", False)
    adiz       = intrusion_data.get("adiz_entry", False)
    direction  = intrusion_data.get("entry_direction", "未知")
    date_str   = intrusion_data.get("date", datetime.now().strftime("%Y-%m-%d"))

    sev = "CRITICAL" if crossed else "HIGH" if aircraft >= 15 else "MEDIUM"

    fig, ax = _setup_fig(8, 5.5)

    title    = "[緊急] 共軍擾台事件" if crossed else "[警示] 共軍進入ADIZ"
    subtitle = f"{date_str}  ｜  即時警報"
    y = _header(ax, title, subtitle, sev)

    y = _row(ax, "共機架次", f"{aircraft} 架次", y,
             value_color=C_RED if aircraft >= 20 else C_ORANGE)
    y = _row(ax, "機型",     types or "未知", y)
    y = _row(ax, "共艦",     f"{vessels} 艘" if vessels else "無", y)
    y = _row(ax, "進入方向", direction, y)
    y = _row(ax, "越海峽中線",
             "[是]" if crossed else "[否]", y,
             value_color=C_RED if crossed else C_GREEN)
    y = _row(ax, "ADIZ入侵",
             "[是]" if adiz else "[否]", y,
             value_color=C_ORANGE if adiz else C_GREEN)

    # 嚴重度指示燈
    sev_color = SEV_COLOR.get(sev, C_ORANGE)
    circle = plt.Circle((0.88, 0.82), 0.06, color=sev_color,
                         alpha=0.9, transform=ax.transAxes)
    ax.add_patch(circle)
    sev_text = {"CRITICAL": "緊急", "HIGH": "高", "MEDIUM": "中"}.get(sev, "")
    ax.text(0.88, 0.82, sev_text, transform=ax.transAxes,
            fontsize=8, color='white', ha='center', va='center', fontweight='bold')

    _footer(ax, "國防部 mnd.gov.tw")
    return _save(fig, "mnd_intrusion")


# ==============================
# 電纜異常卡片
# ==============================
def _get_cable_info(name: str) -> dict:
    """電纜路由/長度（統一由 maps/cable_data.py 提供）"""
    from maps.cable_data import get_cable_info
    return get_cable_info(name)

def make_cable_card(cable_events: list) -> str:
    """
    電纜異常通知卡片
    cable_events: [{cable_name, status, incident_type, notes, reported_at}]
    """
    if not cable_events:
        return ""

    fig, ax = _setup_fig(8, max(4.5, 3 + len(cable_events) * 1.2))

    has_critical = any(e.get("status") == "中斷" for e in cable_events)
    sev   = "CRITICAL" if has_critical else "HIGH"
    title = "[緊急] 海底電纜中斷" if has_critical else "[警示] 海底電纜異常"
    y     = _header(ax, title,
                    f"偵測到 {len(cable_events)} 條電纜異常  ｜  {datetime.now().strftime('%H:%M')}",
                    sev)

    for event in cable_events[:4]:
        name   = event.get("cable_name") or event.get("cable") or "未知"
        status = event.get("status", "異常")
        inc    = event.get("incident_type", "")
        info   = _get_cable_info(name)
        route  = info.get("route", "台灣周邊海域")
        cap    = info.get("len", "")

        st_color = C_RED if status == "中斷" else C_ORANGE
        ax.text(0.04, y, f"▐ {name}", transform=ax.transAxes,
                fontsize=10, fontweight='bold', color=st_color)
        ax.text(0.04, y - 0.07, f"  {route}", transform=ax.transAxes,
                fontsize=8, color=C_TEXT_DIM)
        status_txt = f"{status}" + (f"  ｜  {inc}" if inc else "") + \
                     (f"  ｜  全長 {cap}" if cap and cap != "N/A" else "")
        ax.text(0.04, y - 0.14, f"  狀態：{status_txt}", transform=ax.transAxes,
                fontsize=8, color=st_color)
        y -= 0.22

    _footer(ax, "數位發展部 MODA")
    return _save(fig, "cable_alert")


# ==============================
# 衛星分析卡片（純文字，附原始衛星圖）
# ==============================
def make_satellite_caption(area_name: str, threat_level: float = 0,
                           summary: str = "") -> str:
    """
    衛星通知的 caption 文字
    只顯示區域和時間，不附 AI 分析
    （衛星圖解析度有限，AI 分析可能過度推斷，由訂閱者自行判斷）
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    caption  = (
        f"📡 <b>衛星影像監測</b>  {date_str}\n"
        f"{'─' * 28}\n"
        f"🎯 監測區域：<b>{area_name}</b>\n\n"
        f"<i>來源：Google Maps 衛星圖層\n"
        f"每日輪流掃描各重點基地</i>"
    )
    return caption


# ==============================
# 國台辦措辭升溫卡片
# ==============================
def make_gwytb_card(escalations: list) -> str:
    """
    國台辦升溫通知卡片
    escalations: [{title, tone, intensity, url}]
    """
    if not escalations:
        return ""

    fig, ax = _setup_fig(8, 5)

    max_intensity = max(e.get("intensity", 0) for e in escalations)
    sev   = "CRITICAL" if max_intensity >= 3 else "HIGH"
    y     = _header(ax, "[警示] 國台辦措辭升溫",
                    f"偵測到 {len(escalations)} 篇升溫聲明  ｜  {datetime.now().strftime('%H:%M')}",
                    sev)

    for e in escalations[:3]:
        title     = e.get("title", "")[:40]
        intensity = e.get("intensity", 0)
        color     = C_RED if intensity >= 3 else C_ORANGE if intensity >= 2 else C_YELLOW
        bar_w     = min(intensity / 5, 1.0) * 0.5

        ax.text(0.04, y, f"▸ {title}", transform=ax.transAxes,
                fontsize=9, color=C_TEXT)
        ax.barh(y - 0.07, bar_w, left=0.04, height=0.04,
                color=color, alpha=0.7, transform=ax.transAxes)
        ax.text(0.04 + bar_w + 0.01, y - 0.065, f"強度 {intensity}",
                transform=ax.transAxes, fontsize=8, color=color, va='center')
        y -= 0.18

    # 升溫關鍵字
    all_hits = []
    for e in escalations:
        all_hits.extend(e.get("hits", []))
    if all_hits:
        from collections import Counter
        top_kw = [kw for kw, _ in Counter(all_hits).most_common(5)]
        ax.text(0.04, y, "偵測關鍵字：" + "  ".join(top_kw),
                transform=ax.transAxes, fontsize=8, color=C_TEXT_DIM)

    _footer(ax, "國台辦 gwytb.gov.tw")
    return _save(fig, "gwytb_escalation")


# ==============================
# PTT 熱議卡片
# ==============================
def make_ptt_card(hot_articles: list) -> str:
    """
    PTT 軍武熱議通知卡片
    hot_articles: [{title, push_count, board, url}]
    """
    if not hot_articles:
        return ""

    fig, ax = _setup_fig(8, 5)

    max_push = max(a.get("push_count", 0) for a in hot_articles)
    sev      = "HIGH" if max_push >= 100 else "MEDIUM"
    y        = _header(ax, "[熱議] PTT 軍武板",
                       f"本時段最高 {max_push} 推  ｜  {datetime.now().strftime('%H:%M')}",
                       sev)

    for article in hot_articles[:4]:
        title      = article.get("title", "")[:38]
        push_count = article.get("push_count", 0)
        board      = article.get("board", "")
        bar_w      = min(push_count / max(max_push, 1), 1.0) * 0.55
        color      = C_RED if push_count >= 100 else C_ORANGE if push_count >= 50 else C_YELLOW

        ax.text(0.04, y, f"[{board}] {title}", transform=ax.transAxes,
                fontsize=8.5, color=C_TEXT)
        ax.barh(y - 0.07, bar_w, left=0.04, height=0.038,
                color=color, alpha=0.6, transform=ax.transAxes)
        push_txt = "爆" if push_count >= 100 else str(push_count)
        ax.text(0.04 + bar_w + 0.01, y - 0.065, f"推 {push_txt}",
                transform=ax.transAxes, fontsize=8, color=color, va='center')
        y -= 0.17

    _footer(ax, "PTT Warfare / Military")
    return _save(fig, "ptt_hot")


# ==============================
# 智庫異常卡片
# ==============================
def make_thinktank_card(anomaly_entries: list) -> str:
    """
    智庫異常通知卡片
    anomaly_entries: [{title, source, level, hits, summary}]
    """
    if not anomaly_entries:
        return ""

    fig, ax = _setup_fig(8, 5.5)

    max_level = max(e.get("level", 0) for e in anomaly_entries)
    sev       = "CRITICAL" if max_level >= 3 else "HIGH"
    y         = _header(ax, "[分析] 智庫台灣安全",
                        f"{len(anomaly_entries)} 篇高度相關報告  ｜  {datetime.now().strftime('%H:%M')}",
                        sev)

    for entry in anomaly_entries[:3]:
        level  = entry.get("level", 0)
        source = entry.get("source", "")
        title  = entry.get("title", "")[:42]
        hits   = entry.get("hits", [])[:3]
        color  = C_RED if level >= 3 else C_ORANGE

        ax.text(0.04, y, f"L{level} [{source}]", transform=ax.transAxes,
                fontsize=8, color=color, fontweight='bold')
        ax.text(0.04, y - 0.08, title, transform=ax.transAxes,
                fontsize=9, color=C_TEXT)
        if hits:
            ax.text(0.04, y - 0.15, "命中：" + " | ".join(hits),
                    transform=ax.transAxes, fontsize=7.5, color=C_TEXT_DIM)
        y -= 0.22

    _footer(ax, "ASPI / DFRLab / CSIS / RAND")
    return _save(fig, "thinktank_alert")


# ==============================
# 國際媒體高優先卡片
# ==============================
def make_intl_card(high_priority_news: list) -> str:
    """
    國際媒體高優先通知卡片
    high_priority_news: [{title, source, keywords, url}]
    """
    if not high_priority_news:
        return ""

    fig, ax = _setup_fig(8, 5)

    y = _header(ax, "[緊報] 國際媒體台海",
                f"{len(high_priority_news)} 篇高優先報導  ｜  {datetime.now().strftime('%H:%M')}",
                "HIGH")

    for news in high_priority_news[:4]:
        source   = news.get("source", "")
        title    = news.get("title", "")[:45]
        keywords = news.get("keywords", [])[:3]

        ax.text(0.04, y, f"[{source.upper()}]", transform=ax.transAxes,
                fontsize=8, color=C_TEAL, fontweight='bold')
        ax.text(0.04, y - 0.08, title, transform=ax.transAxes,
                fontsize=9, color=C_TEXT)
        if keywords:
            ax.text(0.04, y - 0.15, "  ".join(keywords),
                    transform=ax.transAxes, fontsize=7.5, color=C_TEXT_DIM)
        y -= 0.20

    _footer(ax, "USNI News / War Zone / BBC / DefenseNews")
    return _save(fig, "intl_alert")


# ==============================
# AIS 可疑船隻卡片
# ==============================
def make_ais_card(suspicious_vessels: list) -> str:
    """
    可疑船隻通知卡片
    suspicious_vessels: [{name, flag, reason, zone, lat, lon}]
    """
    if not suspicious_vessels:
        return ""

    fig, ax = _setup_fig(8, 5.5)

    has_carrier = any("航母" in v.get("reason", "") or "遼寧" in v.get("name", "") or
                      "山東" in v.get("name", "") for v in suspicious_vessels)
    sev = "CRITICAL" if has_carrier else "HIGH" if len(suspicious_vessels) >= 5 else "MEDIUM"

    y = _header(ax, f"[警報] 可疑船隻 {len(suspicious_vessels)} 艘",
                f"台灣周邊海域  ｜  {datetime.now().strftime('%H:%M')}",
                sev)

    # 區域分組統計
    from collections import Counter
    zones = Counter(v.get("zone", "台灣周邊") for v in suspicious_vessels)
    zone_txt = "  ".join(f"{z}:{c}" for z, c in zones.most_common(4))
    ax.text(0.04, y, f"分佈：{zone_txt}", transform=ax.transAxes,
            fontsize=8.5, color=C_TEXT_DIM)
    y -= 0.12

    for v in suspicious_vessels[:4]:
        name   = v.get("name", "未知")[:20]
        flag   = v.get("flag", "")
        reason = v.get("reason", "")[:30]
        zone   = v.get("zone", "")

        ax.text(0.04, y, f"▸ {name}", transform=ax.transAxes,
                fontsize=9, color=C_TEXT, fontweight='bold')
        ax.text(0.04, y - 0.08, f"  {flag}  ｜  {zone}  ｜  {reason}",
                transform=ax.transAxes, fontsize=8, color=C_TEXT_DIM)
        y -= 0.16

    _footer(ax, "AISStream WebSocket")
    return _save(fig, "ais_alert")


# ==============================
# 威脅指數日報卡片（取代純文字進度條）
# ==============================
def make_threat_card(threat_data: dict) -> str:
    """
    每日威脅指數視覺卡片
    threat_data: {overall, military, maritime, cyber, trend,
                  news_count, intrusion_count, anomaly_count}
    """
    fig, ax = _setup_fig(8, 5.0)

    overall  = threat_data.get("overall", 0)
    military = threat_data.get("military", 0)
    maritime = threat_data.get("maritime", 0)
    cyber    = threat_data.get("cyber", 0)
    trend    = threat_data.get("trend", "→ 持平")
    anomaly  = threat_data.get("anomaly_count", 0)
    date_str = datetime.now().strftime("%Y-%m-%d")

    sev   = ("CRITICAL" if overall >= 8 else "HIGH" if overall >= 6
             else "MEDIUM" if overall >= 4 else "LOW")
    color = SEV_COLOR.get(sev, C_ORANGE)
    level_text = {"CRITICAL": "緊急", "HIGH": "高", "MEDIUM": "中", "LOW": "低"}.get(sev, "")

    # 標頭（移除 emoji，改用文字）
    ax.text(0.04, 0.93, f"台灣國防威脅指數  {date_str}",
            transform=ax.transAxes, fontsize=14, fontweight='bold', color=color,
            path_effects=[pe.withStroke(linewidth=3, foreground=BG_DARK)])
    ax.text(0.04, 0.84, f"趨勢：{trend}  |  活躍異常：{anomaly} 個",
            transform=ax.transAxes, fontsize=9, color=C_TEXT_DIM)
    ax.axhline(y=0.80, xmin=0.04, xmax=0.96, color=C_BORDER, linewidth=0.8)

    # 左側：大數字區塊（獨立在左側 0.04~0.38）
    ax.text(0.21, 0.60, f"{overall:.1f}",
            transform=ax.transAxes, fontsize=44, fontweight='bold',
            color=color, ha='center', va='center',
            path_effects=[pe.withStroke(linewidth=4, foreground=BG_DARK)])
    ax.text(0.21, 0.42, "/ 10",
            transform=ax.transAxes, fontsize=13, color=C_TEXT_DIM,
            ha='center', va='center')
    ax.text(0.21, 0.33, f"[ {level_text} ]",
            transform=ax.transAxes, fontsize=11, color=color,
            ha='center', va='center', fontweight='bold')

    # 垂直分隔線
    ax.axvline(x=0.38, ymin=0.15, ymax=0.78, color=C_BORDER, linewidth=0.8)

    # 右側：三維分項條形（0.42~0.96）
    def right_bar(label, score, y_pos):
        ratio = min(score / 10.0, 1.0)
        c     = C_RED if ratio >= 0.7 else C_ORANGE if ratio >= 0.4 else C_GREEN
        # 標籤（在條形左側，垂直置中）
        ax.text(0.42, y_pos + 0.035, label,
                transform=ax.transAxes, fontsize=8.5, color=C_TEXT_DIM, va='center')
        # 背景條（標籤右側開始）
        ax.barh(y_pos, 0.36, left=0.56, height=0.07,
                color=BG_ACCENT, transform=ax.transAxes)
        # 填充條
        ax.barh(y_pos, 0.36 * ratio, left=0.56, height=0.07,
                color=c, alpha=0.85, transform=ax.transAxes)
        # 數值（最右側）
        ax.text(0.94, y_pos + 0.035, f"{score:.1f}",
                transform=ax.transAxes, fontsize=9, color=c,
                fontweight='bold', va='center', ha='right')

    right_bar("軍事威脅", military, 0.55)
    right_bar("海域威脅", maritime, 0.40)
    right_bar("資安威脅", cyber,    0.25)

    _footer(ax, "Taiwan Defense Bot")
    return _save(fig, "threat_daily")


if __name__ == "__main__":
    # 測試所有卡片
    print("測試 MND 卡片...")
    p = make_mnd_card({
        "aircraft_count": 21, "vessel_count": 0,
        "aircraft_types": "殲-16, 運-8",
        "crossed_median_line": True, "adiz_entry": True,
        "entry_direction": "西南、東南", "date": "2026-06-04"
    })
    print(f"✅ {p}")

    print("測試威脅卡片...")
    p = make_threat_card({
        "overall": 6.1, "military": 6.1, "maritime": 0.8, "cyber": 1.5,
        "trend": "↑↑ 顯著上升", "anomaly_count": 4
    })
    print(f"✅ {p}")
