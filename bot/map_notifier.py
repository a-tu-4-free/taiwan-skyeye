# 檔案名稱：bot/map_notifier.py
# 功能說明：用 playwright 截圖 Folium 地圖，生成各 scraper 的地圖通知圖片

import os
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "map_shots")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _screenshot_html(html_path: str, output_path: str,
                     width: int = 1200, height: int = 750,
                     wait_ms: int = 2500) -> str:
    """用 playwright 截圖 HTML 地圖"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page    = browser.new_page(viewport={"width": width, "height": height})
            page.goto(f"file:///{html_path.replace(os.sep, '/')}")
            page.wait_for_timeout(wait_ms)
            page.screenshot(path=output_path, full_page=False)
            browser.close()
        return output_path
    except ImportError:
        print("[MAP_NOTIFIER] playwright 未安裝，跳過截圖")
        return ""
    except Exception as e:
        print(f"[MAP_NOTIFIER ERROR] 截圖失敗：{e}")
        return ""


# ==============================
# MND 共軍繞台路線地圖
# ==============================
def make_mnd_map(intrusion_data: dict) -> str:
    """
    生成共軍繞台路線局部地圖截圖
    intrusion_data: {entry_direction, aircraft_count, aircraft_types,
                     crossed_median_line, adiz_entry}
    """
    import folium
    from maps.map_generator import (
        _add_base_layers, _finalize_map,
        DIRECTION_COORDS, HIGH_THREAT_TYPES
    )

    aircraft  = intrusion_data.get("aircraft_count", 0)
    types     = intrusion_data.get("aircraft_types", "")
    crossed   = intrusion_data.get("crossed_median_line", False)
    direction = intrusion_data.get("entry_direction", "西南")
    date_str  = intrusion_data.get("date", datetime.now().strftime("%Y-%m-%d"))

    # 根據主要方向決定地圖中心
    dir_key  = direction.split("、")[0] if "、" in direction else direction
    dir_coord = DIRECTION_COORDS.get(dir_key, [23.5, 120.5])
    center   = [
        (dir_coord[0] + 24.0) / 2,
        (dir_coord[1] + 120.8) / 2
    ]

    m      = folium.Map(location=center, zoom_start=7,
                        tiles="CartoDB dark_matter", prefer_canvas=True)
    layers = _add_base_layers(m)

    # 標記入侵事件
    color = "#ff0000" if crossed else "#ff8800"
    size  = min(8 + aircraft // 4, 22)
    popup_html = (
        f"<b>{'🔴 越中線！' if crossed else '🟠'} {date_str}</b><br>"
        f"方向：{direction}<br>架次：{aircraft}<br>機型：{types or '未知'}"
    )
    folium.CircleMarker(
        location=dir_coord, radius=size,
        color=color, fill=True, fill_color=color, fill_opacity=0.7,
        popup=folium.Popup(popup_html, max_width=200),
        tooltip=f"✈️ {direction} | {aircraft}架"
    ).add_to(layers["intrusion"])

    # 有越中線：畫入侵箭頭
    if crossed:
        folium.PolyLine(
            locations=[dir_coord, [24.1, 120.7]],
            color="#ff0000", weight=3, opacity=0.8,
            dash_array="8 4", tooltip="越中線入侵路徑"
        ).add_to(layers["intrusion"])

    # 高威脅機型圖示
    if any(ht in (types or "") for ht in HIGH_THREAT_TYPES):
        folium.Marker(
            location=[dir_coord[0] + 0.3, dir_coord[1]],
            icon=folium.DivIcon(
                html=f'<div style="color:#ff4444;font-size:13px;'
                     f'font-weight:bold;text-shadow:0 0 4px #ff0000;'
                     f'white-space:nowrap;">⚡ {types[:20]}</div>',
                icon_size=(160, 20), icon_anchor=(0, 10)
            )
        ).add_to(layers["intrusion"])

    _finalize_map(m, layers,
                  title=f"共軍擾台 {date_str}",
                  window_desc=f"{aircraft}架次 | {'越中線' if crossed else 'ADIZ'}")

    ts       = datetime.now().strftime("%Y%m%d_%H%M")
    html_path = os.path.join(OUTPUT_DIR, f"mnd_{ts}.html")
    png_path  = os.path.join(OUTPUT_DIR, f"mnd_{ts}.png")
    m.save(html_path)

    result = _screenshot_html(html_path, png_path)
    if result:
        os.remove(html_path)  # 截完刪 HTML
    return result


# ==============================
# 電纜異常地圖（highlight 異常電纜）
# ==============================
def make_cable_map(cable_events: list) -> str:
    """
    生成電纜異常地圖截圖
    cable_events: [{cable_name, status, incident_type}]
    """
    import folium
    from maps.map_generator import _add_base_layers, _finalize_map, SUBMARINE_CABLES

    # 把異常電纜名稱建成 set，方便查詢
    anomaly_names = {e.get("cable_name", "") for e in cable_events}
    anomaly_map   = {e.get("cable_name", ""): e for e in cable_events}

    # 以台灣為中心，zoom 稍寬
    m      = folium.Map(location=[23.5, 122.5], zoom_start=5,
                        tiles="CartoDB dark_matter", prefer_canvas=True)
    layers = _add_base_layers(m)

    # 在 _add_base_layers 已畫電纜，這裡額外 highlight 異常電纜
    for cable in SUBMARINE_CABLES:
        name = cable["name"]
        if name not in anomaly_names:
            continue
        event  = anomaly_map[name]
        status = event.get("status", "異常")
        color  = "#ff2222" if status == "中斷" else "#ff8800"

        # 畫粗發光線條覆蓋在原來的電纜上
        folium.PolyLine(
            locations=cable["coords"],
            color=color, weight=6, opacity=0.9,
            tooltip=f"🚨 {name} — {status}"
        ).add_to(layers["cable"])

        # 中點警示 marker
        mid = cable["coords"][len(cable["coords"]) // 2]
        folium.Marker(
            location=mid,
            icon=folium.DivIcon(
                html=f'<div style="font-size:20px;text-shadow:0 0 8px {color};">'
                     f'{"⚡" if status=="中斷" else "⚠️"}</div>',
                icon_size=(24, 24), icon_anchor=(12, 12)
            ),
            tooltip=f"{name}：{status}"
        ).add_to(layers["cable"])

    _finalize_map(m, layers,
                  title=f"電纜異常警報",
                  window_desc=f"{len(cable_events)} 條異常  {datetime.now().strftime('%H:%M')}")

    ts        = datetime.now().strftime("%Y%m%d_%H%M")
    html_path = os.path.join(OUTPUT_DIR, f"cable_{ts}.html")
    png_path  = os.path.join(OUTPUT_DIR, f"cable_{ts}.png")
    m.save(html_path)

    result = _screenshot_html(html_path, png_path)
    if result:
        os.remove(html_path)
    return result


# ==============================
# AIS 可疑船隻地圖
# ==============================
def make_ais_map(suspicious_vessels: list) -> str:
    """
    生成可疑船隻位置地圖截圖
    suspicious_vessels: [{name, lat, lon, flag, reason, zone}]
    """
    import folium
    from maps.map_generator import _add_base_layers, _finalize_map

    m      = folium.Map(location=[23.5, 121.5], zoom_start=6,
                        tiles="CartoDB dark_matter", prefer_canvas=True)
    layers = _add_base_layers(m)

    for v in suspicious_vessels:
        lat  = v.get("lat")
        lon  = v.get("lon")
        if not lat or not lon:
            continue
        name   = v.get("name", "未知")
        flag   = v.get("flag", "")
        reason = v.get("reason", "")

        is_carrier = any(kw in name for kw in ["遼寧", "山東", "福建", "航母"])
        color  = "#ff2222" if is_carrier else "#ff8800"
        size   = 10 if is_carrier else 7

        popup = f"<b>🚢 {name}</b><br>旗：{flag}<br>原因：{reason}"
        folium.CircleMarker(
            location=[lat, lon], radius=size,
            color=color, fill=True, fill_color=color, fill_opacity=0.85,
            popup=folium.Popup(popup, max_width=180),
            tooltip=f"🚢 {name}"
        ).add_to(layers["vessel"])

    _finalize_map(m, layers,
                  title=f"可疑船隻警報",
                  window_desc=f"{len(suspicious_vessels)} 艘  {datetime.now().strftime('%H:%M')}")

    ts        = datetime.now().strftime("%Y%m%d_%H%M")
    html_path = os.path.join(OUTPUT_DIR, f"ais_{ts}.html")
    png_path  = os.path.join(OUTPUT_DIR, f"ais_{ts}.png")
    m.save(html_path)

    result = _screenshot_html(html_path, png_path)
    if result:
        os.remove(html_path)
    return result


# ==============================
# CGA 海域事件地圖
# ==============================
def make_cga_map(incidents: list) -> str:
    """
    生成海巡事件地圖截圖
    incidents: [{title, url, alert_level}]
    """
    import folium
    from maps.map_generator import _add_base_layers, _finalize_map

    # 關鍵地點座標對應
    ISLAND_COORDS = {
        "金門": [24.43, 118.32], "馬祖": [26.16, 119.93],
        "東沙": [20.70, 116.72], "太平": [10.38, 114.36],
        "澎湖": [23.57, 119.58], "烏坵": [24.99, 119.47],
    }

    m      = folium.Map(location=[23.5, 120.5], zoom_start=6,
                        tiles="CartoDB dark_matter", prefer_canvas=True)
    layers = _add_base_layers(m)

    for inc in incidents:
        title = inc.get("title", "")
        level = inc.get("alert_level", "一般")
        color = "#ff2222" if level == "高" else "#ff8800"

        # 根據標題判斷事件位置
        for island, coords in ISLAND_COORDS.items():
            if island in title:
                popup = f"<b>{'🔴' if level=='高' else '🟠'} {title[:50]}</b>"
                folium.CircleMarker(
                    location=coords, radius=9,
                    color=color, fill=True, fill_color=color, fill_opacity=0.75,
                    popup=folium.Popup(popup, max_width=200),
                    tooltip=f"海巡：{island}"
                ).add_to(layers["intrusion"])
                break

    _finalize_map(m, layers,
                  title="海巡署事件地圖",
                  window_desc=datetime.now().strftime("%Y-%m-%d %H:%M"))

    ts        = datetime.now().strftime("%Y%m%d_%H%M")
    html_path = os.path.join(OUTPUT_DIR, f"cga_{ts}.html")
    png_path  = os.path.join(OUTPUT_DIR, f"cga_{ts}.png")
    m.save(html_path)

    result = _screenshot_html(html_path, png_path)
    if result:
        os.remove(html_path)
    return result


# ==============================
# ADS-B 軍機動態地圖
# ==============================
def make_adsb_map(aircraft_list: list) -> str:
    """
    生成軍機位置地圖截圖
    aircraft_list: [{callsign, category, lat, lon, alt_m, heading, zone, threat_level}]
    """
    import folium
    from maps.map_generator import _add_base_layers, _finalize_map

    m      = folium.Map(location=[23.5, 121.5], zoom_start=6,
                        tiles="CartoDB dark_matter", prefer_canvas=True)
    layers = _add_base_layers(m)

    # 依類別決定顏色
    CATEGORY_COLOR = {
        "中共解放軍": "#ff2222",
        "美軍偵察機": "#3399ff",
        "日本自衛隊": "#ffcc00",
    }

    for ac in aircraft_list:
        lat = ac.get("lat")
        lon = ac.get("lon")
        if not lat or not lon:
            continue

        callsign = ac.get("callsign") or "不明"
        category = ac.get("category", "")
        alt_m    = ac.get("alt_m", 0)
        heading  = ac.get("heading", 0)
        zone     = ac.get("zone", "")
        color    = CATEGORY_COLOR.get(category, "#ff8800")

        # 用旋轉的飛機符號表示航向
        icon_html = (
            f'<div style="font-size:22px; '
            f'transform: rotate({heading}deg); '
            f'color:{color}; text-shadow: 0 0 4px #000;">✈</div>'
        )

        popup = (
            f"<b>✈ {callsign}</b><br>"
            f"類別：{category}<br>"
            f"區域：{zone}<br>"
            f"高度：{alt_m:.0f}m<br>"
            f"航向：{heading:.0f}°"
        )

        folium.Marker(
            location=[lat, lon],
            icon=folium.DivIcon(html=icon_html, icon_size=(28, 28), icon_anchor=(14, 14)),
            popup=folium.Popup(popup, max_width=200),
            tooltip=f"✈ {callsign} ({category})"
        ).add_to(layers["vessel"])

        # 在飛機旁標註 callsign
        folium.Marker(
            location=[lat, lon],
            icon=folium.DivIcon(
                html=(f'<div style="font-size:11px; color:{color}; '
                      f'text-shadow:0 0 3px #000; margin-top:18px; '
                      f'white-space:nowrap;">{callsign}</div>'),
                icon_size=(80, 16), icon_anchor=(0, 0)
            ),
        ).add_to(layers["vessel"])

    cats = set(a.get("category", "") for a in aircraft_list)
    title = "軍機動態警報"
    if "中共解放軍" in cats:
        title = "⚠️ 中共解放軍動態"
    elif "美軍偵察機" in cats:
        title = "美軍偵察機動態"

    _finalize_map(m, layers,
                  title=title,
                  window_desc=f"{len(aircraft_list)} 架  {datetime.now().strftime('%H:%M')}")

    ts        = datetime.now().strftime("%Y%m%d_%H%M")
    html_path = os.path.join(OUTPUT_DIR, f"adsb_{ts}.html")
    png_path  = os.path.join(OUTPUT_DIR, f"adsb_{ts}.png")
    m.save(html_path)

    result = _screenshot_html(html_path, png_path)
    if result:
        os.remove(html_path)
    return result
