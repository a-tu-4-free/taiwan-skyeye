# 檔案名稱：maps/map_generator.py
# 功能說明：Folium 態勢地圖生成
#   generate_defense_map()     每日 06/18 全量地圖（7日擾臺 + 24h船隻 + 電纜）
#   generate_realtime_map()    網頁嵌入用，6小時滾動視窗，AIS軌跡線
#   generate_snapshot_png()    TG 日報/週報附圖（需 playwright）
#   generate_incident_map()    異常警報局部放大圖

import folium
from folium import plugins
from datetime import datetime, timedelta
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import MAP_CENTER, MAP_ZOOM, MAP_OUTPUT_PATH, CARTO_API_KEY
from database.db import get_session
from database.models import VesselTracking, IntrusionRecord

# ==============================
# 靜態參考資料
# ==============================

TAIWAN_LOCATIONS = {
    "台北":   [25.046, 121.517],
    "高雄":   [22.627, 120.302],
    "金門":   [24.432, 118.317],
    "馬祖":   [26.158, 119.929],
    "東沙島": [20.700, 116.720],
    "太平島": [10.375, 114.364],
    "烏坵":   [24.985, 119.465],
    "彭佳嶼": [25.628, 122.079],
    "蘭嶼":   [22.043, 121.559],
    "綠島":   [22.671, 121.489],
}

# 海底電纜資料統一放在 maps/cable_data.py（登陸站、示意路由、名稱比對）
from maps.cable_data import (
    SUBMARINE_CABLES, match_cable_name, offset_line, locate_fault,
)

# 高威脅機型（MND 地圖標示用）
HIGH_THREAT_TYPES = ["轟-6", "轟6", "H-6", "空警", "KJ-", "運-8", "運-9", "Y-8", "Y-9",
                     "無人機", "TB-001", "BZK", "殲-16", "殲-20", "J-16", "J-20"]

# 台海中線
MEDIAN_LINE_COORDS = [[27.0, 122.0], [23.0, 118.0]]   # 戴維斯線：北 27N/122E ─ 南 23N/118E

ADIZ_COORDS = [
    [27.0, 120.0], [27.0, 124.0], [25.0, 126.0],
    [22.0, 125.5], [20.0, 123.0], [20.0, 120.0],
    [22.0, 118.5], [25.0, 118.5], [27.0, 120.0],
]

DIRECTION_COORDS = {
    "西南": [22.0, 119.5], "西":   [24.0, 119.5],
    "西北": [26.0, 120.0], "東南": [21.5, 123.0],
    "東":   [24.0, 123.5], "東北": [26.0, 123.0],
    "南":   [20.5, 120.5], "北":   [27.0, 122.0],
    "北部": [26.0, 121.5], "中部": [24.5, 119.8], "南部": [22.5, 119.5],
}

# ADS-B 區域代表座標（對應 scrapers/adsb_monitor.py 的 ZONE_LABELS）
ZONE_CENTERS = {
    "台灣海峽":     [24.5, 120.5],
    "宮古水道":     [25.5, 125.0],
    "台灣東部外海":  [23.5, 124.5],
    "南海北部":     [20.0, 117.5],
    "巴士海峽":     [21.0, 121.5],
    "東海":         [27.0, 123.0],
    "台海周邊":     [23.5, 121.5],
}


# ==============================
# 共用工具函式
# ==============================

_match_cable_name = match_cable_name   # 舊名稱相容（其他模組可能還在用）

_SEVERITY = {"中斷": 3, "障礙": 2, "異常": 2, "維修中": 1}


def get_cable_realtime_status() -> dict:
    """
    從資料庫取得電纜即時狀態，回傳 {地圖cable_name: status_info}
    - MODA 障礙表只列「目前未修復」的事件，舊事件可能超過一年仍在表上
    - 遇到「已修復」紀錄即停止往前看（代表之前的障礙已排除）
    - 同一條電纜有多筆未修復障礙時，取最嚴重狀態，並保留全部故障描述
    """
    from database.models import CableStatus
    from sqlalchemy import desc
    status_map = {}
    closed     = set()
    session    = get_session()
    try:
        cutoff_moda  = datetime.now() - timedelta(days=400)
        cutoff_other = datetime.now() - timedelta(days=30)
        events = session.query(CableStatus).filter(
            CableStatus.reported_at >= cutoff_moda
        ).order_by(desc(CableStatus.reported_at), desc(CableStatus.id)).all()

        for e in events:
            if e.source != "MODA" and e.reported_at < cutoff_other:
                continue
            map_key = match_cable_name(e.cable_name)
            if not map_key or map_key in closed:
                continue
            info = status_map.get(map_key)
            if e.status in ("已修復", "正常"):
                if info is None:
                    status_map[map_key] = {
                        "status": "已修復", "incident_type": "", "notes": e.notes or "",
                        "reported_at": e.reported_at, "source": e.source or "",
                        "original_name": e.cable_name, "faults": [],
                    }
                closed.add(map_key)
                continue
            if info is None:
                info = status_map[map_key] = {
                    "status": e.status, "incident_type": e.incident_type or "",
                    "notes": e.notes or "", "reported_at": e.reported_at,
                    "source": e.source or "", "original_name": e.cable_name,
                    "faults": [],
                }
            elif _SEVERITY.get(e.status, 0) > _SEVERITY.get(info["status"], 0):
                info["status"] = e.status
            info["faults"].append({
                "status": e.status, "notes": e.notes or "", "reported_at": e.reported_at,
            })
    finally:
        session.close()
    for k, v in status_map.items():
        print(f"[MAP] 電纜狀態：{v['original_name']} → {k} ({v['status']})")
    return status_map


_STATUS_STYLE = {
    "中斷":   ("#ff2222", 4),
    "障礙":   ("#ff8800", 3),
    "異常":   ("#ff8800", 3),
    "維修中": ("#ffcc00", 3),
    "已修復": ("#88ff88", 2),
}
_INTL_COLOR     = "#00e08a"
_DOMESTIC_COLOR = "#33c3ff"


def _draw_cables(layer, status_map: dict, highlight: set = None):
    """
    繪製所有電纜
    - 同一登陸站的電纜做法線偏移，避免全部疊在同一條線上
    - 異常電纜依 MODA 描述推估故障點並標示
    highlight：需要加粗發光的地圖 key（電纜警報圖用）
    """
    import html as _html
    highlight = highlight or set()
    by_landing = {}
    for c in SUBMARINE_CABLES:
        by_landing.setdefault(c["landing"], []).append(c["name"])

    for cable in SUBMARINE_CABLES:
        name   = cable["name"]
        db     = status_map.get(name, {})
        status = db.get("status", "正常")
        color, weight = _STATUS_STYLE.get(
            status, (_INTL_COLOR if cable["intl"] else _DOMESTIC_COLOR, 2))
        if status == "已修復" and db.get("reported_at") and \
                (datetime.now() - db["reported_at"]).days > 7:
            color, weight = (_INTL_COLOR if cable["intl"] else _DOMESTIC_COLOR, 2)
            status = "正常"

        group = by_landing[cable["landing"]]
        d     = 0.03 * (group.index(name) - (len(group) - 1) / 2) if len(group) > 1 else 0

        popup_html = (f"<b>🔌 {name}</b><br>路由：{cable['route']}<br>"
                      f"狀態：<b>{status}</b><br>")
        if db.get("original_name"):
            popup_html += f"MODA 名稱：{_html.escape(db['original_name'])}<br>"
        for f in db.get("faults", [])[:3]:
            dt = f["reported_at"].strftime("%Y-%m-%d") if f["reported_at"] else ""
            popup_html += f"• {dt} {_html.escape(f['notes'][:90])}<br>"
        if db.get("source"):
            popup_html += f"來源：{db['source']}"

        status_icon = ("🔴" if status == "中斷" else
                       "🟠" if status in ("障礙", "異常") else "✅")
        lines = [offset_line(seg, d) for seg in cable["segments"]]

        if name in highlight and status in ("中斷", "障礙", "異常"):
            folium.PolyLine(locations=lines, color=color, weight=weight + 4,
                            opacity=0.25).add_to(layer)

        folium.PolyLine(
            locations=lines,
            color=color, weight=weight, opacity=0.9,
            dash_array=None if cable["intl"] else "6 4",
            tooltip=f"🔌 {name} {status_icon} [{status}]",
            popup=folium.Popup(popup_html, max_width=300),
        ).add_to(layer)

        # 故障點：依「距○○約N公里」推估（參考點在地圖外，如馬來西亞關丹，就不標點，只靠線色＋popup）
        if status in ("中斷", "障礙", "異常"):
            marks = []
            for f in db.get("faults", []):
                loc = locate_fault(name, f["notes"])
                if loc:
                    marks.append((loc[0], loc[1], f["status"], loc[2]))
            for lat, lon, st, desc in marks:
                folium.Marker(
                    location=[lat, lon],
                    icon=folium.DivIcon(
                        html=f'<div style="font-size:16px;text-shadow:0 0 6px {color};">'
                             f'{"⚡" if st == "中斷" else "⚠️"}</div>',
                        icon_size=(20, 20), icon_anchor=(10, 10)
                    ),
                    tooltip=f"{name}：{st}｜{desc}",
                ).add_to(layer)


def make_base_map(location, zoom_start: int) -> folium.Map:
    """
    建立底圖
    CARTO 自 2026 起要求 API key（否則圖磚出現「API KEY REQUIRED」浮水印）
    - .env 有 CARTO_API_KEY → 用 CARTO Dark Matter
    - 沒有 → 改用免 key 的 Esri Dark Gray Canvas
    """
    m = folium.Map(location=location, zoom_start=zoom_start,
                   tiles=None, prefer_canvas=True)
    if CARTO_API_KEY:
        folium.TileLayer(
            tiles="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
                  f"?key={CARTO_API_KEY}",
            attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> '
                 '&copy; <a href="https://carto.com/attributions">CARTO</a>',
            name="CARTO Dark", subdomains="abcd", max_zoom=19, control=False,
        ).add_to(m)
    else:
        esri = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/{}/MapServer/tile/{{z}}/{{y}}/{{x}}"
        folium.TileLayer(
            tiles=esri.format("World_Dark_Gray_Base"),
            attr="Esri, HERE, Garmin, &copy; OpenStreetMap contributors",
            name="Esri Dark Gray", max_zoom=16, control=False,
        ).add_to(m)
        folium.TileLayer(
            tiles=esri.format("World_Dark_Gray_Reference"),
            attr="Esri", name="Labels", max_zoom=16,
            overlay=True, control=False,
        ).add_to(m)
    return m


def _add_base_layers(m: folium.Map, cable_highlight: set = None) -> dict:
    """
    加入共用底圖圖層（ADIZ、中線、電纜、地點）
    回傳 layer dict 供後續使用
    """
    layers = {
        "adiz":        folium.FeatureGroup(name="🛡️ 防空識別區 (ADIZ)", show=True),
        "median":      folium.FeatureGroup(name="⚡ 海峽中線",           show=True),
        "cable":       folium.FeatureGroup(name="🔌 海底電纜",           show=True),
        "intrusion":   folium.FeatureGroup(name="✈️ 擾臺事件",          show=True),
        "vessel":      folium.FeatureGroup(name="🚢 可疑船隻",           show=True),
        "locations":   folium.FeatureGroup(name="📍 重要地點",           show=True),
        "aircraft":    folium.FeatureGroup(name="🛩️ 軍機動態 (ADS-B)",  show=True),
        "requisition": folium.FeatureGroup(name="⚓ 民船徵用偵測",       show=False),
    }

    # ADIZ
    folium.Polygon(
        locations=ADIZ_COORDS,
        color="#00aaff", weight=2,
        fill=True, fill_color="#00aaff", fill_opacity=0.05,
        tooltip="台灣防空識別區 (ADIZ)",
    ).add_to(layers["adiz"])

    # 海峽中線
    folium.PolyLine(
        locations=MEDIAN_LINE_COORDS,
        color="#ff6600", weight=3, dash_array="10 5",
        tooltip="海峽中線",
    ).add_to(layers["median"])
    folium.Marker(
        location=[26.75, 121.85],
        icon=folium.DivIcon(
            html='<div style="color:#ff6600;font-size:11px;font-weight:bold;'
                 'white-space:nowrap;text-shadow:1px 1px 2px #000;">海峽中線</div>',
            icon_size=(80, 16), icon_anchor=(0, 8)
        )
    ).add_to(layers["median"])

    # 電纜圖層
    _draw_cables(layers["cable"], get_cable_realtime_status(), highlight=cable_highlight)

    # 重要地點
    for name, coords in TAIWAN_LOCATIONS.items():
        is_front = name in ("金門", "馬祖", "東沙島", "太平島", "烏坵")
        color    = "red" if is_front else "blue"
        folium.CircleMarker(
            location=coords,
            radius=7 if is_front else 5,
            color=color, fill=True, fill_color=color, fill_opacity=0.9,
            tooltip=f"{'⚠️ ' if is_front else ''}📍 {name}",
        ).add_to(layers["locations"])
        folium.Marker(
            location=[coords[0] + 0.15, coords[1]],
            icon=folium.DivIcon(
                html=f'<div style="color:{"#ffaaaa" if is_front else "#aaccff"};'
                     f'font-size:10px;font-weight:bold;white-space:nowrap;'
                     f'text-shadow:1px 1px 2px #000;">{name}</div>',
                icon_size=(60, 14), icon_anchor=(30, 0)
            )
        ).add_to(layers["locations"])

    return layers


def _add_intrusion_layer(layers: dict, days: int = 7):
    """擾臺事件圖層（按天數範圍）"""
    session = get_session()
    try:
        cutoff    = datetime.now() - timedelta(days=days)
        intrusions = session.query(IntrusionRecord).filter(
            IntrusionRecord.date >= cutoff
        ).all()

        direction_events = {}
        for r in intrusions:
            direction = r.entry_direction or "西南"
            dir_key   = direction.split("、")[0] if "、" in direction else direction
            direction_events.setdefault(dir_key, []).append(r)

        for direction, events in direction_events.items():
            coords         = DIRECTION_COORDS.get(direction, [22.0, 119.0])
            total_aircraft = sum(r.aircraft_count for r in events)
            any_crossed    = any(r.crossed_median_line for r in events)
            latest         = max(events, key=lambda r: r.date)

            color = "#ff0000" if any_crossed else "#ff8800"
            size  = min(8 + total_aircraft // 3, 25)

            popup_html = (
                f"<b>{'🔴 越中線！' if any_crossed else '🟠'} 擾臺事件</b><br>"
                f"方向：{direction}<br>"
                f"最近：{latest.date.strftime('%Y-%m-%d')}<br>"
                f"近{days}天共機：{total_aircraft} 架次<br>"
                f"事件數：{len(events)} 次<br>"
                f"機型：{latest.aircraft_types or '未知'}"
            )
            folium.CircleMarker(
                location=coords, radius=size,
                color=color, fill=True, fill_color=color, fill_opacity=0.6,
                tooltip=f"✈️ {direction} | {days}天內{total_aircraft}架{'⚠️越中線' if any_crossed else ''}",
                popup=folium.Popup(popup_html, max_width=220)
            ).add_to(layers["intrusion"])

            # 越中線用圓點顏色（紅色）已足夠表示，不再畫虛線避免視覺混亂
    finally:
        session.close()


def _add_vessel_layer(layers: dict, hours: int = 24, show_track: bool = False):
    """
    可疑船隻圖層
    show_track=True 時畫出 6 小時內的軌跡線（給即時地圖用）
    """
    session = get_session()
    try:
        cutoff  = datetime.now() - timedelta(hours=hours)
        vessels = session.query(VesselTracking).filter(
            VesselTracking.is_suspicious == True,
            VesselTracking.recorded_at >= cutoff
        ).limit(50).all()

        if not show_track:
            # 一般模式：只畫最新位置
            for v in vessels:
                if not v.latitude or not v.longitude:
                    continue
                popup_html = (
                    f"<b>🚢 {v.vessel_name}</b><br>"
                    f"船旗：{v.flag}<br>船型：{v.vessel_type}<br>"
                    f"速度：{v.speed} 節<br>"
                    f"可疑原因：{v.suspicion_reason}<br>"
                    f"記錄：{v.recorded_at.strftime('%H:%M')}"
                )
                folium.Marker(
                    location=[v.latitude, v.longitude],
                    icon=folium.Icon(color="red", icon="ship", prefix="fa"),
                    tooltip=f"🚢 {v.vessel_name} ({v.flag})",
                    popup=folium.Popup(popup_html, max_width=220)
                ).add_to(layers["vessel"])
        else:
            # 軌跡模式：按 MMSI 分組畫軌跡線
            from collections import defaultdict
            tracks = defaultdict(list)
            for v in sorted(vessels, key=lambda x: x.recorded_at):
                if v.latitude and v.longitude and v.mmsi:
                    tracks[v.mmsi].append(v)

            for mmsi, track_vessels in tracks.items():
                if len(track_vessels) < 2:
                    # 只有一筆：畫點
                    v = track_vessels[0]
                    folium.CircleMarker(
                        location=[v.latitude, v.longitude],
                        radius=6, color="#ff4444",
                        fill=True, fill_color="#ff4444", fill_opacity=0.8,
                        tooltip=f"🚢 {v.vessel_name or mmsi}（{v.flag}）"
                    ).add_to(layers["vessel"])
                else:
                    # 多筆：畫軌跡線 + 最新位置
                    coords = [[v.latitude, v.longitude] for v in track_vessels]
                    latest = track_vessels[-1]

                    # 軌跡線（漸淡效果用 opacity）
                    folium.PolyLine(
                        locations=coords,
                        color="#ff6666", weight=2, opacity=0.6,
                        tooltip=f"🚢 {latest.vessel_name or mmsi} 軌跡"
                    ).add_to(layers["vessel"])

                    # 最新位置（較大的點）
                    popup_html = (
                        f"<b>🚢 {latest.vessel_name}</b><br>"
                        f"船旗：{latest.flag}<br>MMSI：{mmsi}<br>"
                        f"速度：{latest.speed} 節<br>"
                        f"方向：{latest.heading}°<br>"
                        f"原因：{latest.suspicion_reason}<br>"
                        f"最後更新：{latest.recorded_at.strftime('%H:%M')}"
                    )
                    folium.CircleMarker(
                        location=[latest.latitude, latest.longitude],
                        radius=8, color="#ff2222",
                        fill=True, fill_color="#ff2222", fill_opacity=0.9,
                        tooltip=f"🚢 {latest.vessel_name or mmsi}（{latest.flag}）",
                        popup=folium.Popup(popup_html, max_width=220)
                    ).add_to(layers["vessel"])

    finally:
        session.close()


def _finalize_map(m: folium.Map, layers: dict, title: str = "台灣國防態勢地圖",
                  window_desc: str = ""):
    """加入圖層控制、插件、資訊面板，儲存前的最後處理"""
    for layer in layers.values():
        layer.add_to(m)

    folium.LayerControl(collapsed=True, position="topright").add_to(m)
    plugins.Fullscreen(position="topleft").add_to(m)
    plugins.MousePosition(position="bottomright").add_to(m)
    folium.plugins.MeasureControl(position="bottomleft").add_to(m)

    update_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    window_note = f"<br><span style='color:#aaa;font-size:10px;'>{window_desc}</span>" if window_desc else ""

    info_html = f"""
    <div style="position:fixed;bottom:60px;left:10px;z-index:9999;
                background:rgba(20,20,40,0.88);color:#c8d8e8;
                padding:10px 14px;border-radius:8px;
                border:1px solid #2d3561;font-family:monospace;font-size:11px;
                pointer-events:none;">
        <b style="font-size:13px;">🛡️ {title}</b><br>
        更新：{update_time}{window_note}<br>
        <span style="color:#ff6600;">── 海峽中線</span>　
        <span style="color:#ff0000;">● 越中線</span><br>
        <span style="color:#ff8800;">● 擾臺事件</span>　
        <span style="color:#00aaff;">■ ADIZ</span><br>
        <span style="color:#00e08a;">── 國際海纜</span>　
        <span style="color:#33c3ff;">┄┄ 國內海纜</span><br>
        <span style="color:#ff8800;">── 障礙</span>　
        <span style="color:#ff2222;">── 斷纜</span>　
        <span style="color:#888;">（電纜為示意路由）</span>
    </div>
    """
    m.get_root().html.add_child(folium.Element(info_html))


# ==============================
# 主要地圖生成函式
# ==============================

def generate_defense_map() -> str:
    """
    每日全量地圖（06:00 / 18:00 排程）
    - 7 天擾臺事件
    - 24 小時可疑船隻（一般模式）
    - 電纜即時狀態
    """
    print("[MAP] 生成每日全量地圖...")
    m = make_base_map(MAP_CENTER, MAP_ZOOM)
    layers = _add_base_layers(m)
    _add_intrusion_layer(layers, days=7)
    _add_vessel_layer(layers, hours=24, show_track=False)
    _add_adsb_layer(layers, hours=24)
    _add_requisition_layer(layers)
    _finalize_map(m, layers, title="台灣國防態勢地圖", window_desc="7日擾臺 | 24小時船隻/軍機")

    os.makedirs(os.path.dirname(MAP_OUTPUT_PATH), exist_ok=True)
    m.save(MAP_OUTPUT_PATH)
    print(f"[MAP] 全量地圖儲存：{MAP_OUTPUT_PATH}")
    return MAP_OUTPUT_PATH


def generate_realtime_map(output_path: str = None) -> str:
    """
    網頁嵌入用即時地圖（每次開頁面時呼叫，或每 30 分鐘快取）
    - 6 小時滾動視窗
    - AIS 軌跡線（show_track=True）
    - 電纜即時狀態
    """
    print("[MAP] 生成即時地圖（6小時視窗）...")

    if output_path is None:
        base = os.path.dirname(MAP_OUTPUT_PATH)
        output_path = os.path.join(base, "realtime_map.html")

    m = make_base_map(MAP_CENTER, MAP_ZOOM)
    layers = _add_base_layers(m)

    # 即時地圖：只顯示當日擾臺（days=1）+ 6小時船隻軌跡
    _add_intrusion_layer(layers, days=1)
    _add_vessel_layer(layers, hours=6, show_track=True)
    _add_adsb_layer(layers, hours=6)
    _add_requisition_layer(layers)

    window_end   = datetime.now().strftime("%H:%M")
    window_start = (datetime.now() - timedelta(hours=6)).strftime("%H:%M")
    _finalize_map(
        m, layers,
        title="即時態勢地圖",
        window_desc=f"視窗：{window_start}～{window_end}（6小時）"
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    m.save(output_path)
    print(f"[MAP] 即時地圖儲存：{output_path}")
    return output_path


def generate_snapshot_png(output_path: str = None, days: int = 1) -> str:
    """
    生成 PNG 快照供 TG 推送用（需要 playwright）
    days=1  → 當日快照（日報附圖）
    days=7  → 7日累積（週報附圖）
    回傳 PNG 路徑；playwright 未安裝時回傳空字串
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[MAP] playwright 未安裝，跳過截圖（pip install playwright）")
        return ""

    # 先生成對應的 HTML
    base      = os.path.dirname(MAP_OUTPUT_PATH)
    html_path = os.path.join(base, f"snapshot_{days}d.html")
    if output_path is None:
        output_path = os.path.join(base, f"snapshot_{days}d.png")

    # 生成對應 HTML
    m = make_base_map(MAP_CENTER, MAP_ZOOM)
    layers = _add_base_layers(m)
    _add_intrusion_layer(layers, days=days)
    _add_vessel_layer(layers, hours=days * 24, show_track=(days == 1))

    label = f"{'當日' if days == 1 else f'{days}日'}快照"
    _finalize_map(m, layers, title=f"台灣國防態勢 {label}",
                  window_desc=datetime.now().strftime("%Y-%m-%d %H:%M"))

    os.makedirs(os.path.dirname(html_path), exist_ok=True)
    m.save(html_path)

    # playwright 截圖
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page    = browser.new_page(viewport={"width": 1200, "height": 800})
            page.goto(f"file:///{html_path.replace(os.sep, '/')}")
            page.wait_for_timeout(3500)   # 等地圖 tile 載入
            page.screenshot(path=output_path, full_page=False)
            browser.close()
        print(f"[MAP] 截圖完成：{output_path}")
        return output_path
    except Exception as e:
        print(f"[MAP ERROR] 截圖失敗：{e}")
        return ""


def generate_incident_map(center_lat: float, center_lon: float,
                          incident_desc: str,
                          output_path: str = None) -> str:
    """
    異常警報局部放大圖（zoom=8，200 海里範圍）
    center_lat/lon：事件中心座標
    incident_desc：標題說明
    """
    if output_path is None:
        base        = os.path.dirname(MAP_OUTPUT_PATH)
        ts          = datetime.now().strftime("%Y%m%d_%H%M")
        output_path = os.path.join(base, f"incident_{ts}.html")

    m = make_base_map([center_lat, center_lon], 8)
    layers = _add_base_layers(m)
    _add_intrusion_layer(layers, days=1)
    _add_vessel_layer(layers, hours=6, show_track=True)

    # 事件中心標記
    folium.Marker(
        location=[center_lat, center_lon],
        icon=folium.DivIcon(
            html=f'<div style="font-size:28px;text-shadow:0 0 6px red;">🎯</div>',
            icon_size=(32, 32), icon_anchor=(16, 16)
        ),
        tooltip=incident_desc,
        popup=folium.Popup(f"<b>⚠️ {incident_desc}</b>", max_width=250)
    ).add_to(layers["intrusion"])

    _finalize_map(m, layers,
                  title=f"⚠️ {incident_desc[:30]}",
                  window_desc=datetime.now().strftime("%H:%M 即時"))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    m.save(output_path)
    print(f"[MAP] 事件局部地圖：{output_path}")
    return output_path


def run():
    return generate_defense_map()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--realtime",  action="store_true", help="生成即時地圖（6小時視窗）")
    parser.add_argument("--snapshot",  type=int, default=0, help="生成PNG快照（天數：1或7）")
    parser.add_argument("--incident",  action="store_true", help="測試事件局部圖")
    args = parser.parse_args()

    if args.realtime:
        path = generate_realtime_map()
    elif args.snapshot:
        path = generate_snapshot_png(days=args.snapshot)
    elif args.incident:
        path = generate_incident_map(24.5, 120.5, "測試：越中線事件")
    else:
        path = generate_defense_map()

    print(f"✅ 輸出：{path}")
    if path and path.endswith(".html"):
        print(f"瀏覽器開啟：file:///{path.replace(os.sep, '/')}")

def _add_adsb_layer(layers: dict, hours: int = 6):
    """
    ADS-B 軍機動態圖層
    顯示近 N 小時偵測到的中共/美軍/日本軍機位置
    """
    from database.models import NewsEvent
    session = get_session()

    CATEGORY_COLOR = {
        "中共解放軍": "#ff2222",
        "美軍偵察機": "#3399ff",
        "日本自衛隊": "#ffcc00",
    }

    try:
        cutoff = datetime.now() - timedelta(hours=hours)
        items  = session.query(NewsEvent).filter(
            NewsEvent.source == "adsb_monitor",
            NewsEvent.published_at >= cutoff
        ).order_by(NewsEvent.published_at.desc()).limit(20).all()

        import re
        for item in items:
            content_text = item.content or ""
            # content 格式：[類別] callsign @ 區域 高度m 航向X°
            for line in content_text.split("\n"):
                m = re.match(
                    r"\[(.+?)\]\s*(\S*)\s+@\s+(\S+)\s+([\d.]+)m\s+航向([\d.]+)°",
                    line.strip()
                )
                if not m:
                    continue
                category, callsign, zone, alt, heading = m.groups()
                callsign = callsign or "不明"
                color = CATEGORY_COLOR.get(category, "#ff8800")

                # 沒有精確座標，用區域中心點代表性標示
                zone_center = ZONE_CENTERS.get(zone, MAP_CENTER)

                popup_html = (
                    f"<b>✈ {callsign}</b><br>"
                    f"類別：{category}<br>"
                    f"區域：{zone}<br>"
                    f"高度：{alt}m ｜ 航向：{heading}°<br>"
                    f"時間：{item.published_at.strftime('%H:%M') if item.published_at else ''}"
                )
                folium.CircleMarker(
                    location=zone_center,
                    radius=7, color=color,
                    fill=True, fill_color=color, fill_opacity=0.85,
                    tooltip=f"✈ {callsign}（{category}）@ {zone}",
                    popup=folium.Popup(popup_html, max_width=220)
                ).add_to(layers["aircraft"])
    finally:
        session.close()


def _add_requisition_layer(layers: dict):
    """
    民船徵用偵測圖層
    標示解放軍兩棲基地位置，異常聚集時顯示警示圈
    """
    try:
        from scrapers.ais import PLA_AMPHIBIOUS_BASES, check_vessel_requisition
    except ImportError:
        return

    results = {}
    try:
        results = check_vessel_requisition()
    except Exception:
        pass

    for base_name, base_info in PLA_AMPHIBIOUS_BASES.items():
        info  = results.get(base_name)
        count = info["count"] if info else 0
        level = info["level"] if info else "NORMAL"

        color = {
            "CRITICAL": "#ff2222", "HIGH": "#ff8800",
            "MEDIUM":   "#ffcc00", "LOW":  "#4caf50",
        }.get(level, "#4a7a9b")

        popup_html = (
            f"<b>⚓ {base_name}（解放軍兩棲基地）</b><br>"
            f"周邊民船：{count} 艘<br>"
            f"狀態：{level}"
        )
        folium.Circle(
            location=[base_info["lat"], base_info["lon"]],
            radius=base_info["radius_km"] * 1000,
            color=color, weight=1.5,
            fill=True, fill_color=color,
            fill_opacity=0.08 if count == 0 else 0.18,
            tooltip=f"⚓ {base_name}：{count} 艘民船（{level}）",
            popup=folium.Popup(popup_html, max_width=220)
        ).add_to(layers["requisition"])

        folium.Marker(
            location=[base_info["lat"], base_info["lon"]],
            icon=folium.DivIcon(
                html=(f'<div style="font-size:11px;color:{color};'
                      f'text-shadow:0 0 3px #000;white-space:nowrap;">'
                      f'⚓ {base_name}</div>'),
                icon_size=(80, 16), icon_anchor=(40, 8)
            ),
        ).add_to(layers["requisition"])


