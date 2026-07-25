# 檔案名稱：analyzer/trend.py
# 功能說明：生成威脅趨勢圖表（30日折線圖、擾臺統計長條圖、各類威脅雷達圖），輸出PNG供TG推送

import matplotlib
matplotlib.use("Agg")  # 非互動模式，適合背景執行
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patches as mpatches
import numpy as np
from datetime import datetime, timedelta
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database.db import get_recent_scores, get_intrusion_stats
from config import MAP_OUTPUT_PATH

# ==============================
# 字型設定（支援中文）
# ==============================
# Windows 中文字型
FONT_CANDIDATES = [
    "Microsoft JhengHei",   # 微軟正黑體
    "Microsoft YaHei",      # 微軟雅黑
    "DFKai-SB",             # 標楷體
    "SimHei",
]

def setup_chinese_font():
    """設定中文字型"""
    for font_name in FONT_CANDIDATES:
        try:
            font_path = fm.findfont(fm.FontProperties(family=font_name))
            if font_path and "DejaVu" not in font_path:
                plt.rcParams["font.family"] = font_name
                print(f"[TREND] 使用字型：{font_name}")
                return
        except Exception:
            continue
    print("[TREND] 警告：找不到中文字型，可能出現亂碼")

setup_chinese_font()

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ==============================
# 顏色主題（深色軍事風格）
# ==============================
COLORS = {
    "bg":       "#1a1a2e",
    "panel":    "#16213e",
    "military": "#e94560",
    "maritime": "#0f3460",
    "cyber":    "#533483",
    "overall":  "#e2b96f",
    "grid":     "#2d3561",
    "text":     "#c8d8e8",
    "alert":    "#ff6b6b",
}


def plot_threat_trend_30d() -> str:
    """生成30日威脅趨勢折線圖"""
    scores = get_recent_scores(days=30)

    if not scores:
        print("[TREND] 無足夠資料生成趨勢圖")
        return ""

    dates = [s.date.strftime("%m/%d") for s in scores]
    overall = [s.overall_score for s in scores]
    military = [s.military_score for s in scores]
    maritime = [s.maritime_score for s in scores]
    cyber = [s.cyber_score for s in scores]

    fig, ax = plt.subplots(figsize=(14, 6), facecolor=COLORS["bg"])
    ax.set_facecolor(COLORS["panel"])

    x = range(len(dates))

    # 繪製各線條
    ax.plot(x, overall,  color=COLORS["overall"],  linewidth=2.5, label="整體威脅", marker="o", markersize=4, zorder=5)
    ax.plot(x, military, color=COLORS["military"], linewidth=1.5, label="軍事",     linestyle="--", alpha=0.8)
    ax.plot(x, maritime, color="#4fc3f7",           linewidth=1.5, label="海域",     linestyle="--", alpha=0.8)
    ax.plot(x, cyber,    color=COLORS["cyber"],     linewidth=1.5, label="資安",     linestyle="--", alpha=0.8)

    # 警戒線
    ax.axhline(y=7, color=COLORS["alert"], linestyle=":", linewidth=1.5, alpha=0.7, label="高警戒(7)")
    ax.axhline(y=4, color="#ffd166",       linestyle=":", linewidth=1.0, alpha=0.5, label="注意(4)")

    # 填充區域
    ax.fill_between(x, overall, alpha=0.15, color=COLORS["overall"])

    # 刻度與標籤
    step = max(1, len(dates) // 10)
    ax.set_xticks(list(range(0, len(dates), step)))
    ax.set_xticklabels([dates[i] for i in range(0, len(dates), step)],
                       color=COLORS["text"], fontsize=10, rotation=30)
    ax.set_yticks(range(0, 11, 2))
    ax.set_yticklabels([str(i) for i in range(0, 11, 2)], color=COLORS["text"])
    ax.set_ylim(0, 10.5)

    # 格線
    ax.grid(True, color=COLORS["grid"], linewidth=0.5, alpha=0.7)
    ax.spines[:].set_color(COLORS["grid"])

    # 標題與標籤
    ax.set_title("台灣國防威脅趨勢 — 近30日",
                 color=COLORS["text"], fontsize=16, fontweight="bold", pad=15)
    ax.set_xlabel("日期", color=COLORS["text"], fontsize=11)
    ax.set_ylabel("威脅指數 (0-10)", color=COLORS["text"], fontsize=11)

    legend = ax.legend(loc="upper left", facecolor=COLORS["panel"],
                       edgecolor=COLORS["grid"], labelcolor=COLORS["text"])

    # 最新值標注
    if overall:
        ax.annotate(f"現在：{overall[-1]:.1f}",
                    xy=(len(dates)-1, overall[-1]),
                    xytext=(-40, 15), textcoords="offset points",
                    color=COLORS["overall"], fontsize=11, fontweight="bold",
                    arrowprops=dict(arrowstyle="->", color=COLORS["overall"]))

    # 時間戳
    fig.text(0.99, 0.01, f"更新：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
             color=COLORS["grid"], fontsize=8, ha="right")

    plt.tight_layout()
    output_path = os.path.join(OUTPUT_DIR, "threat_trend_30d.png")
    plt.savefig(output_path, dpi=150, bbox_inches="tight",
                facecolor=COLORS["bg"], edgecolor="none")
    plt.close()
    print(f"[TREND] 趨勢圖已儲存：{output_path}")
    return output_path


def plot_intrusion_monthly() -> str:
    """生成近12個月擾臺統計長條圖"""
    stats, records = get_intrusion_stats(days=365)

    if not records:
        print("[TREND] 無擾臺資料")
        return ""

    # 按月統計
    monthly = {}
    for r in records:
        key = r.date.strftime("%Y-%m")
        if key not in monthly:
            monthly[key] = {"aircraft": 0, "vessels": 0, "crossings": 0}
        monthly[key]["aircraft"] += r.aircraft_count
        monthly[key]["vessels"] += r.vessel_count
        if r.crossed_median_line:
            monthly[key]["crossings"] += 1

    months = sorted(monthly.keys())[-12:]
    aircraft_data = [monthly[m]["aircraft"] for m in months]
    vessels_data  = [monthly[m]["vessels"]  for m in months]
    crossings_data = [monthly[m]["crossings"] for m in months]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9), facecolor=COLORS["bg"])

    x = np.arange(len(months))
    width = 0.35

    # 上圖：機艦數量
    ax1.set_facecolor(COLORS["panel"])
    bars1 = ax1.bar(x - width/2, aircraft_data, width, label="共機（架次）",
                    color=COLORS["military"], alpha=0.85, zorder=3)
    bars2 = ax1.bar(x + width/2, vessels_data,  width, label="共艦（艘次）",
                    color="#4fc3f7",              alpha=0.85, zorder=3)

    ax1.set_xticks(x)
    ax1.set_xticklabels(months, color=COLORS["text"], fontsize=9, rotation=30)
    ax1.set_ylabel("次數", color=COLORS["text"])
    ax1.set_title("共軍擾臺統計 — 近12個月", color=COLORS["text"],
                  fontsize=14, fontweight="bold", pad=10)
    ax1.legend(facecolor=COLORS["panel"], edgecolor=COLORS["grid"], labelcolor=COLORS["text"])
    ax1.grid(True, color=COLORS["grid"], linewidth=0.5, alpha=0.7, axis="y")
    ax1.spines[:].set_color(COLORS["grid"])
    ax1.tick_params(colors=COLORS["text"])

    # 長條數值標籤
    for bar in bars1:
        h = bar.get_height()
        if h > 0:
            ax1.text(bar.get_x() + bar.get_width()/2, h + 0.3, str(int(h)),
                     ha="center", va="bottom", color=COLORS["text"], fontsize=8)

    # 下圖：越中線次數
    ax2.set_facecolor(COLORS["panel"])
    ax2.bar(x, crossings_data, color=COLORS["alert"], alpha=0.85, label="越中線次數", zorder=3)
    ax2.set_xticks(x)
    ax2.set_xticklabels(months, color=COLORS["text"], fontsize=9, rotation=30)
    ax2.set_ylabel("次數", color=COLORS["text"])
    ax2.set_title("越中線事件統計", color=COLORS["text"], fontsize=13, pad=10)
    ax2.grid(True, color=COLORS["grid"], linewidth=0.5, alpha=0.7, axis="y")
    ax2.spines[:].set_color(COLORS["grid"])
    ax2.tick_params(colors=COLORS["text"])

    plt.tight_layout(pad=2.0)
    output_path = os.path.join(OUTPUT_DIR, "intrusion_monthly.png")
    plt.savefig(output_path, dpi=150, bbox_inches="tight",
                facecolor=COLORS["bg"], edgecolor="none")
    plt.close()
    print(f"[TREND] 月統計圖已儲存：{output_path}")
    return output_path


def plot_threat_radar(military: float, maritime: float, cyber: float,
                      date_str: str = "") -> str:
    """生成今日威脅雷達圖"""
    categories = ["軍事威脅", "海域威脅", "資安威脅", "認知作戰", "整體態勢"]
    # 認知作戰 = cyber * 0.8，整體 = 加權平均
    cognitive = round(cyber * 0.8, 2)
    overall = round(military * 0.5 + maritime * 0.3 + cyber * 0.2, 2)
    values = [military, maritime, cyber, cognitive, overall]

    # 雷達圖需要閉合
    N = len(categories)
    angles = [n / float(N) * 2 * np.pi for n in range(N)]
    angles += angles[:1]
    values_plot = values + values[:1]

    fig, ax = plt.subplots(1, 1, figsize=(8, 8), subplot_kw=dict(polar=True),
                           facecolor=COLORS["bg"])
    ax.set_facecolor(COLORS["panel"])

    # 繪製
    ax.plot(angles, values_plot, color=COLORS["overall"], linewidth=2, zorder=3)
    ax.fill(angles, values_plot, alpha=0.3, color=COLORS["overall"], zorder=2)

    # 刻度
    ax.set_ylim(0, 10)
    ax.set_yticks([2, 4, 6, 8, 10])
    ax.set_yticklabels(["2", "4", "6", "8", "10"], color=COLORS["text"], fontsize=9)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, color=COLORS["text"], fontsize=12, fontweight="bold")

    ax.grid(color=COLORS["grid"], linewidth=0.7)
    ax.spines["polar"].set_color(COLORS["grid"])

    title = f"台灣國防威脅雷達圖"
    if date_str:
        title += f"\n{date_str}"
    ax.set_title(title, color=COLORS["text"], fontsize=14, fontweight="bold",
                 pad=20, y=1.08)

    # 數值標注
    for angle, val, cat in zip(angles[:-1], values, categories):
        ax.annotate(f"{val:.1f}", xy=(angle, val),
                    color=COLORS["overall"], fontsize=11, fontweight="bold",
                    ha="center")

    plt.tight_layout()
    output_path = os.path.join(OUTPUT_DIR, "threat_radar.png")
    plt.savefig(output_path, dpi=150, bbox_inches="tight",
                facecolor=COLORS["bg"], edgecolor="none")
    plt.close()
    print(f"[TREND] 雷達圖已儲存：{output_path}")
    return output_path


def run_all_charts(military=0.0, maritime=0.0, cyber=0.0) -> dict:
    """生成所有圖表，回傳路徑字典"""
    print("[TREND] 開始生成圖表...")
    return {
        "trend_30d":    plot_threat_trend_30d(),
        "intrusion":    plot_intrusion_monthly(),
        "radar":        plot_threat_radar(military, maritime, cyber,
                                          datetime.now().strftime("%Y-%m-%d")),
    }


if __name__ == "__main__":
    charts = run_all_charts(military=6.5, maritime=3.2, cyber=4.1)
    for name, path in charts.items():
        if path:
            print(f"✅ {name}: {path}")
