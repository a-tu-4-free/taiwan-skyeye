# 檔案名稱：scrapers/oil_monitor.py
# 功能說明：監控中國石油消耗/進口趨勢，作為武力集結背景指標
# 資料來源：Our World in Data（引用 BP Statistical Review）
# 更新頻率：月頻數據，每月1日更新一次即可

import requests
import csv
import io
from datetime import datetime, timedelta
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db import insert_news, get_session

# ==============================
# 資料來源
# ==============================
OWID_OIL_URL = (
    "https://ourworldindata.org/grapher/oil-consumption-by-country.csv"
    "?tab=chart&country=CHN"
)

# 門檻動態計算（在 analyze_trend 內用近10年均值計算）
# 不使用固定值，避免隨著中國整體能源消耗成長而誤報


def fetch_china_oil_data() -> list:
    """
    從 Our World in Data 抓取中國石油消耗數據
    回傳 [{year, consumption_twh}] 按年份排序
    """
    try:
        resp = requests.get(OWID_OIL_URL, timeout=20,
                           headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            print(f"[OIL] HTTP {resp.status_code}")
            return []

        reader = csv.DictReader(io.StringIO(resp.text))
        data   = []
        for row in reader:
            if row.get("Code") != "CHN":
                continue
            try:
                year  = int(row["Year"])
                value = float(row.get("Oil", 0) or 0)
                if value > 0:
                    data.append({"year": year, "consumption_twh": value})
            except (ValueError, KeyError):
                continue

        data.sort(key=lambda x: x["year"])
        return data

    except Exception as e:
        print(f"[OIL ERROR] 抓取失敗：{e}")
        return []


def analyze_trend(data: list) -> dict:
    """
    分析石油消耗趨勢
    判斷邏輯：
    - 不看絕對值（會隨中國整體成長而增加）
    - 看「年增速是否異常加快」或「單年激增」
    - 激增才是備戰信號，正常成長不是
    """
    if len(data) < 3:
        return {"status": "資料不足", "level": "UNKNOWN"}

    latest    = data[-1]
    prev_year = data[-2]
    recent_5  = data[-5:] if len(data) >= 5 else data
    recent_10 = data[-10:] if len(data) >= 10 else data

    # 年增長率
    yoy_change = ((latest["consumption_twh"] - prev_year["consumption_twh"])
                  / prev_year["consumption_twh"] * 100)

    # 5年均值
    avg_5yr = sum(d["consumption_twh"] for d in recent_5) / len(recent_5)

    # 10年均值（長期趨勢基準）
    avg_10yr = sum(d["consumption_twh"] for d in recent_10) / len(recent_10)

    # 近5年平均年增速
    if len(recent_5) >= 2:
        avg_yoy = ((recent_5[-1]["consumption_twh"] - recent_5[0]["consumption_twh"])
                   / recent_5[0]["consumption_twh"] / (len(recent_5)-1) * 100)
    else:
        avg_yoy = 0

    # 相對5年均值的偏差
    deviation_pct = (latest["consumption_twh"] - avg_5yr) / avg_5yr * 100

    # 判斷異常：重點看「年增速是否突然加快」
    # 正常年增約 2-4%，超過 8% 才值得關注
    if yoy_change >= 12:
        level = "CRITICAL"
        note  = (f"石油消耗年增 {yoy_change:.1f}%，"
                 f"遠超近5年平均增速（{avg_yoy:.1f}%），"
                 f"疑似大規模戰略儲備")
    elif yoy_change >= 8:
        level = "HIGH"
        note  = (f"石油消耗年增 {yoy_change:.1f}%，"
                 f"明顯高於近5年平均增速（{avg_yoy:.1f}%）")
    elif yoy_change >= 5:
        level = "MEDIUM"
        note  = f"石油消耗年增 {yoy_change:.1f}%，增速略高於正常"
    elif yoy_change < -5:
        level = "LOW"
        note  = f"石油消耗年減 {abs(yoy_change):.1f}%，可能反映經濟放緩"
    else:
        level = "NORMAL"
        note  = f"石油消耗正常，年增 {yoy_change:.1f}%（近5年平均 {avg_yoy:.1f}%）"

    return {
        "latest_year":    latest["year"],
        "latest_twh":     latest["consumption_twh"],
        "yoy_change_pct": round(yoy_change, 1),
        "avg_5yr_twh":    round(avg_5yr, 1),
        "avg_10yr_twh":   round(avg_10yr, 1),
        "avg_yoy_5yr":    round(avg_yoy, 1),
        "deviation_pct":  round(deviation_pct, 1),
        "level":          level,
        "note":           note,
    }


def run() -> dict:
    """
    執行石油監控
    回傳分析結果
    """
    print("[OIL] 抓取中國石油消耗數據...")

    data = fetch_china_oil_data()
    if not data:
        print("[OIL] 無法取得數據")
        return {}

    print(f"[OIL] 取得 {len(data)} 年數據（{data[0]['year']}-{data[-1]['year']}）")

    analysis = analyze_trend(data)
    latest   = data[-1]

    print(f"[OIL] {latest['year']} 年消耗：{latest['consumption_twh']:.0f} TWh")
    print(f"[OIL] 年增長：{analysis['yoy_change_pct']:+.1f}%")
    print(f"[OIL] 級別：{analysis['level']}  {analysis['note']}")

    # 存入資料庫（月頻，避免重複）
    title   = f"【石油指標】中國 {latest['year']} 年石油消耗：{latest['consumption_twh']:.0f} TWh"
    content = (
        f"[OIL|{analysis['level']}] "
        f"年增 {analysis['yoy_change_pct']:+.1f}%，"
        f"5年均值 {analysis['avg_5yr_twh']:.0f} TWh，"
        f"偏差 {analysis['deviation_pct']:+.1f}%。"
        f"{analysis['note']}"
    )
    insert_news(
        source       = "oil_monitor",
        title        = title,
        content      = content,
        url          = OWID_OIL_URL,
        published_at = datetime.now(),
        category     = "軍事",
        keywords_matched = ["石油", "能源", "中國", "戰略儲備"]
    )

    return {
        "data":     data,
        "analysis": analysis,
    }


def get_oil_indicator() -> dict:
    """
    取得最新石油指標（供威脅評分和日報使用）
    """
    from database.models import NewsEvent
    session = get_session()
    try:
        cutoff = datetime.now() - timedelta(days=40)  # 最近一個月的記錄
        item   = session.query(NewsEvent).filter(
            NewsEvent.source == "oil_monitor",
            NewsEvent.published_at >= cutoff
        ).order_by(NewsEvent.published_at.desc()).first()

        if not item:
            return {"level": "UNKNOWN", "note": "無最新數據"}

        # 從 content 解析 level
        content = item.content or ""
        level   = "NORMAL"
        for l in ["CRITICAL", "HIGH", "MEDIUM"]:
            if f"|{l}|" in content:
                level = l
                break

        return {
            "level":   level,
            "title":   item.title,
            "content": content,
            "updated": item.published_at.strftime("%Y-%m"),
        }
    finally:
        session.close()


if __name__ == "__main__":
    result = run()
    if result:
        analysis = result["analysis"]
        data     = result["data"]
        print(f"\n{'='*55}")
        print(f"中國石油消耗趨勢（最近5年）")
        print(f"{'='*55}")
        for d in data[-5:]:
            bar = "█" * int(d["consumption_twh"] / 500)
            print(f"  {d['year']}：{d['consumption_twh']:8.0f} TWh  {bar}")
        print(f"\n分析：{analysis['note']}")
        print(f"級別：{analysis['level']}")
