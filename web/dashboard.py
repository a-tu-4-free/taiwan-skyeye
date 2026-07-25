# 檔案名稱：web/dashboard.py
# 功能說明：TDB Web Dashboard 完整版

from flask import Flask, render_template_string, jsonify, send_from_directory
from datetime import datetime, timedelta
import sys
import os
import glob

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

app = Flask(__name__)

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SkyEye｜台灣國防情勢監控</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0e1a;
            color: #c8d8e8;
            font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif;
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(135deg, #0d1b2a 0%, #1a2744 100%);
            border-bottom: 1px solid #2d4a6b;
            padding: 16px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: sticky;
            top: 0;
            z-index: 100;
        }
        .header h1 { font-size: 20px; color: #7eb8d4; letter-spacing: 2px; }
        .header .subtitle { font-size: 12px; color: #4a7a9b; margin-top: 2px; }
        .header-right { text-align: right; }
        .last-update { font-size: 12px; color: #4a7a9b; }
        .live-dot {
            display: inline-block;
            width: 8px; height: 8px;
            background: #4caf50;
            border-radius: 50%;
            margin-right: 6px;
            animation: pulse 2s infinite;
        }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        .grid-3 { display: grid; grid-template-columns: repeat(3,1fr); gap: 16px; margin-bottom: 16px; }
        .grid-2 { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; margin-bottom: 16px; }
        .grid-full { margin-bottom: 16px; }
        .card {
            background: #0d1b2a;
            border: 1px solid #1e3a5f;
            border-radius: 12px;
            padding: 20px;
        }
        .card-title {
            font-size: 12px; color: #4a7a9b;
            text-transform: uppercase; letter-spacing: 1px;
            margin-bottom: 14px;
        }
        .threat-score { font-size: 52px; font-weight: bold; line-height: 1; }
        .threat-score.calm     { color: #4caf50; }
        .threat-score.low      { color: #8bc34a; }
        .threat-score.medium   { color: #ffc107; }
        .threat-score.high     { color: #ff9800; }
        .threat-score.critical { color: #f44336; }
        .threat-label { font-size: 14px; margin-top: 6px; opacity: 0.7; }
        .trend-badge { display:inline-block; padding:3px 10px; border-radius:4px; font-size:12px; margin-top:10px; }
        .trend-up   { background:#3d1515; color:#f44336; }
        .trend-down { background:#0a3d1f; color:#4caf50; }
        .trend-flat { background:#1e3a5f; color:#7eb8d4; }
        .bar-container { margin: 10px 0; }
        .bar-label { display:flex; justify-content:space-between; font-size:12px; margin-bottom:5px; color:#7eb8d4; }
        .bar-bg { background:#1e3a5f; border-radius:4px; height:8px; overflow:hidden; }
        .bar-fill { height:100%; border-radius:4px; transition:width 1s ease; }
        .bar-military { background: linear-gradient(90deg,#f44336,#ff9800); }
        .bar-maritime { background: linear-gradient(90deg,#2196f3,#00bcd4); }
        .bar-cyber    { background: linear-gradient(90deg,#9c27b0,#e91e63); }
        .intrusion-stats { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
        .stat-item { text-align:center; }
        .stat-value { font-size:36px; font-weight:bold; color:#7eb8d4; }
        .stat-label { font-size:11px; color:#4a7a9b; margin-top:3px; }
        .news-list { list-style:none; }
        .news-item { padding:10px 0; border-bottom:1px solid #1a2f4a; display:flex; align-items:flex-start; gap:10px; }
        .news-item:last-child { border-bottom:none; }
        .news-score { min-width:34px; height:34px; border-radius:6px; display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:bold; flex-shrink:0; }
        .score-high   { background:#3d1515; color:#f44336; }
        .score-medium { background:#3d2a0a; color:#ff9800; }
        .score-low    { background:#1a2f4a; color:#7eb8d4; }
        .news-content { flex:1; min-width:0; }
        .news-title { font-size:13px; color:#c8d8e8; line-height:1.4; }
        .news-title a { color:#7eb8d4; text-decoration:none; }
        .news-title a:hover { text-decoration:underline; }
        .news-summary { font-size:11px; color:#5a8aab; margin-top:3px; line-height:1.4; }
        .news-meta { font-size:11px; color:#3a6a8b; margin-top:2px; }
        .cable-item { display:flex; align-items:center; gap:10px; padding:8px 0; border-bottom:1px solid #1a2f4a; }
        .cable-item:last-child { border-bottom:none; }
        .cable-dot { width:10px; height:10px; border-radius:50%; flex-shrink:0; }
        .cable-dot.normal   { background:#4caf50; }
        .cable-dot.abnormal { background:#ff9800; box-shadow:0 0 4px #ff9800; }
        .cable-dot.cut      { background:#f44336; box-shadow:0 0 8px #f44336; animation:pulse 1s infinite; }
        .cable-name { font-size:13px; flex:1; }
        .cable-status { font-size:11px; color:#4a7a9b; }
        .vessel-item { padding:8px 0; border-bottom:1px solid #1a2f4a; font-size:12px; }
        .vessel-item:last-child { border-bottom:none; }
        .vessel-name { color:#f44336; font-weight:bold; }
        .vessel-detail { color:#5a8aab; margin-top:2px; }
        .satellite-item { padding:10px 0; border-bottom:1px solid #1a2f4a; }
        .satellite-item:last-child { border-bottom:none; }
        .satellite-area { font-size:13px; color:#7eb8d4; font-weight:bold; }
        .satellite-content { font-size:12px; color:#5a8aab; margin-top:4px; line-height:1.5; }
        .satellite-img {
            width:100%; border-radius:6px; margin-top:8px;
            cursor:pointer; border:1px solid #1e3a5f;
            transition:border-color 0.2s;
        }
        .satellite-img:hover { border-color:#7eb8d4; }
        .cog-item { padding:8px 0; border-bottom:1px solid #1a2f4a; font-size:12px; }
        .cog-item:last-child { border-bottom:none; }
        .cog-title a { color:#ffc107; text-decoration:none; font-weight:bold; }
        .cog-title a:hover { text-decoration:underline; }
        .cog-title span { color:#ffc107; font-weight:bold; }
        .cog-source { color:#5a8aab; font-size:11px; margin-top:2px; }
        .alert-banner {
            background:#3d1515; border:1px solid #f44336;
            border-radius:8px; padding:12px 16px;
            margin-bottom:16px; display:none;
            align-items:center; gap:10px;
        }
        .alert-banner.show { display:flex; }
        .map-frame { width:100%; height:550px; border:none; border-radius:8px; background:#0a0e1a; }
        .chart-container { position:relative; height:200px; }
        .footer { text-align:center; padding:20px; color:#2d4a6b; font-size:12px; border-top:1px solid #1e3a5f; margin-top:8px; }
        .empty-msg { color:#3a6a8b; font-size:13px; text-align:center; padding:16px; }
        .tab-bar { display:flex; gap:8px; margin-bottom:12px; }
        .tab-btn {
            padding:6px 14px; border-radius:6px; border:1px solid #1e3a5f;
            background:#0a0e1a; color:#4a7a9b; cursor:pointer; font-size:12px;
            transition:all 0.2s;
        }
        .tab-btn.active { background:#1e3a5f; color:#7eb8d4; border-color:#7eb8d4; }
        @media (max-width:900px) {
            .grid-3 { grid-template-columns:1fr; }
            .grid-2 { grid-template-columns:1fr; }
            .threat-score { font-size:40px; }
        }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>🛡️ SKYEYE</h1>
            <div class="subtitle">台灣國防情勢監控 Taiwan Defence Monitor</div>
        </div>
        <div class="header-right">
            <div><span class="live-dot"></span><span style="font-size:12px;color:#4caf50;">LIVE</span></div>
            <div class="last-update" id="lastUpdate">載入中...</div>
            <div style="margin-top:4px"><a href="/about" style="color:#4a7a9b;font-size:12px;text-decoration:none;">ℹ️ 關於本站</a></div>
        </div>
    </div>

    <div class="container">
        <!-- 高威脅警示 -->
        <div class="alert-banner" id="alertBanner">
            <span style="font-size:20px">🚨</span>
            <span id="alertText" style="font-size:14px;color:#f44336;font-weight:bold;"></span>
        </div>

        <!-- 第一排：威脅指數 + 分項 + 擾臺 -->
        <div class="grid-3">
            <div class="card">
                <div class="card-title">🛡️ 綜合威脅指數</div>
                <div class="threat-score calm" id="overallScore">--</div>
                <div class="threat-label" id="threatLabel">載入中</div>
                <div class="trend-badge trend-flat" id="trendBadge">--</div>
            </div>
            <div class="card">
                <div class="card-title">🔢 分項評分</div>
                <div class="bar-container">
                    <div class="bar-label"><span>✈️ 軍事</span><span id="milScore">--</span></div>
                    <div class="bar-bg"><div class="bar-fill bar-military" id="milBar" style="width:0%"></div></div>
                </div>
                <div class="bar-container">
                    <div class="bar-label"><span>🚢 海域</span><span id="marScore">--</span></div>
                    <div class="bar-bg"><div class="bar-fill bar-maritime" id="marBar" style="width:0%"></div></div>
                </div>
                <div class="bar-container">
                    <div class="bar-label"><span>💻 資安</span><span id="cybScore">--</span></div>
                    <div class="bar-bg"><div class="bar-fill bar-cyber" id="cybBar" style="width:0%"></div></div>
                </div>
            </div>
            <div class="card">
                <div class="card-title">⚔️ 今日擾臺統計</div>
                <div class="intrusion-stats">
                    <div class="stat-item">
                        <div class="stat-value" id="aircraftCount">0</div>
                        <div class="stat-label">共機架次</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value" id="vesselCount">0</div>
                        <div class="stat-label">共艦艘次</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value" id="medianLine" style="font-size:28px">✅</div>
                        <div class="stat-label">越中線</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value" id="adizEntry" style="font-size:28px">✅</div>
                        <div class="stat-label">ADIZ</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 趨勢圖 -->
        <div class="grid-full">
            <div class="card">
                <div class="card-title">📈 30日威脅趨勢</div>
                <div class="chart-container">
                    <canvas id="trendChart"></canvas>
                </div>
            </div>
        </div>

        <!-- 態勢地圖 -->
        <div class="grid-full">
            <div class="card">
                <div class="card-title">🗺️ 台灣周邊態勢地圖</div>
                <iframe src="/map" class="map-frame"></iframe>
            </div>
        </div>

        <!-- 新聞 + 電纜狀態 -->
        <div class="grid-2">
            <div class="card">
                <div class="card-title">📰 今日重點新聞</div>
                <ul class="news-list" id="newsList">
                    <li class="empty-msg">載入中...</li>
                </ul>
            </div>
            <div class="card">
                <div class="card-title">🔌 海底電纜狀態</div>
                <div id="cableList"><div class="empty-msg">載入中...</div></div>
            </div>
        </div>

        <!-- 船隻 + 衛星 + 認知作戰 -->
        <div class="grid-3">
            <div class="card">
                <div class="card-title">🚢 可疑船隻（24h）</div>
                <div id="vesselList"><div class="empty-msg">載入中...</div></div>
            </div>
            <div class="card">
                <div class="card-title">🛰️ 衛星影像分析</div>
                <div id="satelliteList"><div class="empty-msg">載入中...</div></div>
            </div>
            <div class="card">
                <div class="card-title">🧠 認知作戰警示</div>
                <div id="cogWarList"><div class="empty-msg">載入中...</div></div>
            </div>
        </div>

        <!-- 新增指標：ADS-B / 中共官媒 / 民船徵用 / 石油 -->
        <div class="grid-3">
            <div class="card">
                <div class="card-title">✈️ 軍機動態（6h）</div>
                <div id="adsbList"><div class="empty-msg">載入中...</div></div>
            </div>
            <div class="card">
                <div class="card-title">📢 中共官媒輿論（24h）</div>
                <div id="chinaMediaList"><div class="empty-msg">載入中...</div></div>
            </div>
            <div class="card">
                <div class="card-title">🚢 民船徵用偵測</div>
                <div id="requisitionInfo"><div class="empty-msg">載入中...</div></div>
            </div>
        </div>

        <div class="grid-full">
            <div class="card">
                <div class="card-title">🛢️ 中國石油消耗指標（月頻）</div>
                <div id="oilInfo"><div class="empty-msg">載入中...</div></div>
            </div>
        </div>
    </div>

    <div class="footer">
        SkyEye 台灣國防情勢監控 © 2026 ｜ 資料每30分鐘自動更新 ｜ 僅供參考，非官方資訊
    </div>

    <script>
        let trendChartInstance = null;

        function getThreatClass(s) {
            if (s >= 8) return 'critical';
            if (s >= 6) return 'high';
            if (s >= 4) return 'medium';
            if (s >= 2) return 'low';
            return 'calm';
        }
        function getThreatLabel(s) {
            if (s >= 8) return '緊急';
            if (s >= 6) return '高';
            if (s >= 4) return '中';
            if (s >= 2) return '低';
            return '平穩';
        }
        function getTrendClass(t) {
            if (t && t.includes('↑')) return 'trend-up';
            if (t && t.includes('↓')) return 'trend-down';
            return 'trend-flat';
        }

        async function loadDashboard() {
            try {
                const res  = await fetch('/api/dashboard');
                const data = await res.json();
                if (data.error) throw new Error(data.error);

                document.getElementById('lastUpdate').textContent =
                    '更新：' + new Date().toLocaleTimeString('zh-TW');

                // 威脅指數
                const score = data.threat.overall;
                const scoreEl = document.getElementById('overallScore');
                scoreEl.textContent = score.toFixed(1);
                scoreEl.className   = 'threat-score ' + getThreatClass(score);
                document.getElementById('threatLabel').textContent =
                    score.toFixed(1) + '/10 — ' + getThreatLabel(score);
                const trendEl = document.getElementById('trendBadge');
                trendEl.textContent = data.threat.trend;
                trendEl.className   = 'trend-badge ' + getTrendClass(data.threat.trend);

                // 分項
                [['mil','military'],['mar','maritime'],['cyb','cyber']].forEach(([k, key]) => {
                    const v = data.threat[key];
                    document.getElementById(k+'Score').textContent = v.toFixed(1);
                    document.getElementById(k+'Bar').style.width = (v * 10) + '%';
                });

                // 擾臺
                document.getElementById('aircraftCount').textContent = data.intrusion.aircraft;
                document.getElementById('vesselCount').textContent   = data.intrusion.vessels;
                document.getElementById('medianLine').textContent = data.intrusion.median_crossed ? '⚠️' : '✅';
                document.getElementById('adizEntry').textContent  = data.intrusion.adiz_entry    ? '⚠️' : '✅';

                // 高威脅警示
                if (score >= 7) {
                    document.getElementById('alertBanner').classList.add('show');
                    document.getElementById('alertText').textContent =
                        '⚠️ 威脅指數 ' + score.toFixed(1) + '/10 — 請密切關注最新動態';
                }

                // 新聞
                const nl = document.getElementById('newsList');
                nl.innerHTML = '';
                if (!data.news.length) {
                    nl.innerHTML = '<li class="empty-msg">暫無資料</li>';
                } else {
                    data.news.forEach(n => {
                        const sc = n.score >= 7 ? 'score-high' : n.score >= 4 ? 'score-medium' : 'score-low';
                        const li = document.createElement('li');
                        li.className = 'news-item';
                        li.innerHTML = `
                            <div class="news-score ${sc}">${n.score.toFixed(1)}</div>
                            <div class="news-content">
                                <div class="news-title">
                                    ${n.url ?
                                        `<a href="${n.url}" target="_blank">${n.title}</a>` :
                                        n.title}
                                </div>
                                ${n.summary ? `<div class="news-summary">💬 ${n.summary}</div>` : ''}
                                <div class="news-meta">${n.source} · ${n.time}</div>
                            </div>`;
                        nl.appendChild(li);
                    });
                }

                // 電纜（每條只顯示最新一筆）
                const cl = document.getElementById('cableList');
                cl.innerHTML = '';
                if (!data.cables.length) {
                    cl.innerHTML = '<div class="empty-msg" style="color:#4caf50">✅ 無異常紀錄</div>';
                } else {
                    data.cables.forEach(c => {
                        const dotClass = c.status === '中斷' ? 'cut' :
                                        c.status === '正常' ? 'normal' : 'abnormal';
                        const div = document.createElement('div');
                        div.className = 'cable-item';
                        div.innerHTML = `
                            <div class="cable-dot ${dotClass}"></div>
                            <div class="cable-name">${c.name}</div>
                            <div class="cable-status">${c.status}${c.time ? ' · '+c.time : ''}</div>`;
                        cl.appendChild(div);
                    });
                }

                // 船隻
                const vl = document.getElementById('vesselList');
                vl.innerHTML = '';
                if (!data.vessels.length) {
                    vl.innerHTML = '<div class="empty-msg">✅ 無可疑船隻</div>';
                } else {
                    data.vessels.forEach(v => {
                        const div = document.createElement('div');
                        div.className = 'vessel-item';
                        div.innerHTML = `
                            <div class="vessel-name">⚠️ ${v.name}</div>
                            <div class="vessel-detail">
                                旗：${v.flag} ｜ ${v.reason}<br>
                                位置：${v.lat.toFixed(2)}N ${v.lon.toFixed(2)}E
                            </div>`;
                        vl.appendChild(div);
                    });
                }

                // 認知作戰（含連結）
                const cgl = document.getElementById('cogWarList');
                cgl.innerHTML = '';
                if (!data.cog_war.length) {
                    cgl.innerHTML = '<div class="empty-msg">✅ 無警示</div>';
                } else {
                    data.cog_war.forEach(c => {
                        const div = document.createElement('div');
                        div.className = 'cog-item';
                        const titleHtml = c.url
                            ? `<a href="${c.url}" target="_blank">⚠️ ${c.title}</a>`
                            : `<span>⚠️ ${c.title}</span>`;
                        div.innerHTML = `
                            <div class="cog-title">${titleHtml}</div>
                            <div class="cog-source">${c.source}</div>`;
                        cgl.appendChild(div);
                    });
                }

                // ADS-B 軍機動態
                const adl = document.getElementById('adsbList');
                adl.innerHTML = '';
                if (!data.adsb || !data.adsb.length) {
                    adl.innerHTML = '<div class="empty-msg">✅ 目前無偵測到軍機</div>';
                } else {
                    data.adsb.forEach(a => {
                        const div = document.createElement('div');
                        div.className = 'vessel-item';
                        div.innerHTML = `
                            <div class="vessel-name">✈️ ${a.title}</div>
                            <div class="vessel-detail">${a.time} ｜ ${a.content}</div>`;
                        adl.appendChild(div);
                    });
                }

                // 中共官媒輿論
                const cml = document.getElementById('chinaMediaList');
                cml.innerHTML = '';
                if (!data.china_media || !data.china_media.length) {
                    cml.innerHTML = '<div class="empty-msg">✅ 無異常升溫</div>';
                } else {
                    data.china_media.forEach(m => {
                        const div = document.createElement('div');
                        div.className = 'cog-item';
                        const badge = m.level === 'L3' ? '🔴 L3' : '🟠 L2';
                        div.innerHTML = `
                            <div class="cog-title">${badge} ${m.title}</div>
                            <div class="cog-source">${m.source} ｜ ${m.time}</div>`;
                        cml.appendChild(div);
                    });
                }

                // 民船徵用偵測
                const reqEl = document.getElementById('requisitionInfo');
                if (data.requisition && data.requisition.title) {
                    reqEl.innerHTML = `
                        <div class="vessel-item">
                            <div class="vessel-name">⚠️ ${data.requisition.title}</div>
                            <div class="vessel-detail">偵測時間：${data.requisition.time}</div>
                        </div>`;
                } else {
                    reqEl.innerHTML = '<div class="empty-msg">✅ 各基地周邊無異常聚集</div>';
                }

                // 石油消耗指標
                const oilEl = document.getElementById('oilInfo');
                if (data.oil && data.oil.title) {
                    const levelColor = {
                        'CRITICAL': '#ff4444', 'HIGH': '#ff8800',
                        'MEDIUM': '#ffcc00', 'NORMAL': '#4caf50', 'LOW': '#4a7a9b'
                    }[data.oil.level] || '#4a7a9b';
                    oilEl.innerHTML = `
                        <div class="vessel-item">
                            <div class="vessel-name" style="color:${levelColor}">
                                ${data.oil.title}
                            </div>
                            <div class="vessel-detail">
                                級別：${data.oil.level} ｜ 更新：${data.oil.updated}
                                <br><span style="color:#4a7a9b">月頻數據，作為背景參考指標</span>
                            </div>
                        </div>`;
                } else {
                    oilEl.innerHTML = '<div class="empty-msg">尚無資料（每月1日更新）</div>';
                }

            } catch(e) {
                console.error(e);
                document.getElementById('lastUpdate').textContent = '載入失敗：' + e.message;
            }
        }

        async function loadSatelliteImages() {
            try {
                const res    = await fetch('/api/satellite-images');
                const images = await res.json();
                const sl     = document.getElementById('satelliteList');

                if (!images.length) {
                    sl.innerHTML = '<div class="empty-msg">每日08:00自動拍攝分析</div>';
                    return;
                }

                sl.innerHTML = '';
                images.forEach(img => {
                    const div = document.createElement('div');
                    div.className = 'satellite-item';
                    div.innerHTML = `
                        <div class="satellite-area">🛰️ ${img.area}</div>
                        <img src="${img.url}"
                             class="satellite-img"
                             onclick="window.open('${img.url}','_blank')"
                             title="點擊放大查看"
                             loading="lazy">`;
                    sl.appendChild(div);
                });
            } catch(e) {
                document.getElementById('satelliteList').innerHTML =
                    '<div class="empty-msg">衛星影像載入失敗</div>';
            }
        }

        async function loadTrendChart() {
            try {
                const res  = await fetch('/api/history');
                const data = await res.json();
                if (!data.length) return;

                const ctx = document.getElementById('trendChart').getContext('2d');
                if (trendChartInstance) trendChartInstance.destroy();

                trendChartInstance = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: data.map(d => d.date),
                        datasets: [
                            {
                                label: '綜合威脅',
                                data: data.map(d => d.overall),
                                borderColor: '#7eb8d4',
                                backgroundColor: 'rgba(126,184,212,0.1)',
                                tension: 0.4, fill: true, borderWidth: 2,
                            },
                            {
                                label: '軍事',
                                data: data.map(d => d.military),
                                borderColor: '#ff9800',
                                tension: 0.4, fill: false, borderWidth: 1.5,
                                borderDash: [4,4],
                            },
                            {
                                label: '海域',
                                data: data.map(d => d.maritime),
                                borderColor: '#2196f3',
                                tension: 0.4, fill: false, borderWidth: 1.5,
                                borderDash: [4,4],
                            },
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { labels: { color:'#7eb8d4', font:{size:11} } }
                        },
                        scales: {
                            x: { ticks:{color:'#4a7a9b',font:{size:10}}, grid:{color:'#1e3a5f'} },
                            y: { min:0, max:10, ticks:{color:'#4a7a9b',font:{size:10}}, grid:{color:'#1e3a5f'} }
                        }
                    }
                });
            } catch(e) { console.error(e); }
        }

        // 初始載入
        loadDashboard();
        loadSatelliteImages();
        loadTrendChart();

        // 定時更新
        setInterval(loadDashboard, 5 * 60 * 1000);
        setInterval(loadSatelliteImages, 30 * 60 * 1000);
        setInterval(loadTrendChart, 10 * 60 * 1000);
    </script>
</body>
</html>
"""


ABOUT_HTML = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>關於本站｜台灣國防情勢監控 SkyEye</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0e1a;
            color: #c8d8e8;
            font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif;
            line-height: 1.8;
        }
        .header {
            background: linear-gradient(135deg, #0d1b2a 0%, #1a2744 100%);
            border-bottom: 1px solid #2d4a6b;
            padding: 20px 24px;
            position: sticky; top: 0; z-index: 10;
        }
        .header h1 { font-size: 20px; color: #7eb8d4; letter-spacing: 2px; }
        .header a { color: #4a7a9b; font-size: 13px; text-decoration: none; }
        .header a:hover { color: #7eb8d4; }
        .container {
            max-width: 760px;
            margin: 0 auto;
            padding: 24px 20px 60px;
        }
        .lead {
            font-size: 15px;
            color: #a8c8e0;
            border-left: 3px solid #2d6a9f;
            padding: 12px 16px;
            margin-bottom: 28px;
            background: rgba(45,106,159,0.08);
            border-radius: 4px;
        }
        h2 {
            font-size: 17px;
            color: #7eb8d4;
            margin: 32px 0 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid #1e3a5f;
        }
        h3 {
            font-size: 14px;
            color: #9ec5e0;
            margin: 18px 0 8px;
        }
        p, li { font-size: 13.5px; color: #b8cce0; }
        ul { padding-left: 22px; margin-bottom: 8px; }
        li { margin-bottom: 4px; }
        .source-table {
            width: 100%;
            border-collapse: collapse;
            margin: 12px 0 20px;
            font-size: 13px;
        }
        .source-table th, .source-table td {
            border: 1px solid #1e3a5f;
            padding: 8px 10px;
            text-align: left;
        }
        .source-table th {
            background: #14233a;
            color: #7eb8d4;
            font-weight: 600;
        }
        .source-table td { color: #b8cce0; }
        .badge {
            display: inline-block;
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 4px;
            margin-right: 4px;
        }
        .badge-realtime { background: rgba(76,175,80,0.15); color: #4caf50; }
        .badge-hourly   { background: rgba(126,184,212,0.15); color: #7eb8d4; }
        .badge-monthly  { background: rgba(255,165,0,0.15); color: #ffa500; }
        .principle-box {
            background: #0f1d33;
            border: 1px solid #1e3a5f;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 16px;
        }
        .principle-box .num {
            display: inline-block;
            background: #2d6a9f;
            color: #fff;
            width: 22px; height: 22px;
            border-radius: 50%;
            text-align: center;
            font-size: 12px;
            line-height: 22px;
            margin-right: 8px;
        }
        .disclaimer {
            margin-top: 36px;
            padding: 16px;
            border: 1px solid #3a2d1e;
            background: rgba(255,165,0,0.05);
            border-radius: 8px;
            font-size: 12.5px;
            color: #d4a76a;
        }
        .footer {
            text-align: center;
            color: #4a7a9b;
            font-size: 12px;
            padding: 24px;
            border-top: 1px solid #1e3a5f;
        }
        a.inline { color: #7eb8d4; }
        code {
            background: #14233a;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 12px;
            color: #9ec5e0;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🛡️ SkyEye 台灣國防情勢監控</h1>
        <a href="/">← 返回儀表板</a>
    </div>

    <div class="container">
        <div class="lead">
            本站整合台灣官方公告、國際媒體、衛星影像、船舶與飛航追蹤等多項公開資料來源，
            以白話文說明台海周邊的軍事與安全動態，希望幫助更多人理解並關注國防議題。
            本站為民間自發專案，非官方資訊來源。
        </div>

        <h2>📡 監測項目與資料來源</h2>
        <table class="source-table">
            <tr><th>項目</th><th>資料來源</th><th>更新頻率</th></tr>
            <tr><td>共機/共艦擾台</td><td>國防部即時動態</td><td><span class="badge badge-hourly">數小時</span></td></tr>
            <tr><td>軍機追蹤（ADS-B）</td><td>OpenSky Network</td><td><span class="badge badge-realtime">30分鐘</span></td></tr>
            <tr><td>船舶追蹤（AIS）</td><td>AISStream</td><td><span class="badge badge-hourly">2小時</span></td></tr>
            <tr><td>民船徵用偵測</td><td>AIS（兩棲基地周邊分析）</td><td><span class="badge badge-hourly">2小時</span></td></tr>
            <tr><td>海底電纜狀態</td><td>數位部 MODA 公告</td><td><span class="badge badge-hourly">4小時</span></td></tr>
            <tr><td>衛星影像</td><td>Google Maps 衛星圖層</td><td><span class="badge badge-hourly">每日</span></td></tr>
            <tr><td>中共官媒輿論</td><td>新華社／人民日報／環球時報／中新社／CGTN</td><td><span class="badge badge-hourly">2小時</span></td></tr>
            <tr><td>國台辦發言</td><td>國台辦官網</td><td><span class="badge badge-hourly">每小時</span></td></tr>
            <tr><td>國際媒體</td><td>國際軍事媒體 RSS</td><td><span class="badge badge-hourly">30分鐘</span></td></tr>
            <tr><td>智庫分析</td><td>主要國際智庫報告</td><td><span class="badge badge-hourly">2小時</span></td></tr>
            <tr><td>輿論熱度</td><td>PTT 軍武板</td><td><span class="badge badge-hourly">30分鐘</span></td></tr>
            <tr><td>中國石油消耗</td><td>Our World in Data（BP統計）</td><td><span class="badge badge-monthly">每月</span></td></tr>
        </table>

        <h2>🧮 分析方法</h2>
        <h3>威脅指數</h3>
        <p>
            綜合軍事、海域、資安三個面向的當日動態，計算 0-10 分的威脅指數，
            並標示與近期趨勢的相對變化（上升/持平/下降）。指數本身不代表「衝突即將發生」，
            而是反映「相較於平時，當前活動量是否異常」。
        </p>

        <h3>異常偵測</h3>
        <p>系統會比對近期數據與歷史基準，當出現以下情況時標示為異常：</p>
        <ul>
            <li>共機/共艦活動量明顯偏離近期平均</li>
            <li>共軍越過台海中線</li>
            <li>海底電纜出現障礙或中斷公告</li>
            <li>中共官媒對台措辭明顯升溫（強硬用詞、官方警告）</li>
            <li>解放軍兩棲基地周邊出現民船異常聚集</li>
            <li>認知作戰相關內容比例異常升高</li>
        </ul>

        <h3>AI 輔助分析</h3>
        <p>
            部分項目（如軍機動態、官媒措辭、衛星影像）會透過 AI 模型
            （Google Gemini，必要時搭配本地模型）進行初步研判，
            產出簡短的繁體中文說明。AI 分析僅作輔助參考，
            <strong>不作為唯一判斷依據</strong>，且分析時要求模型採取保守立場，
            避免過度推斷。
        </p>

        <h2>📐 判斷原則</h2>

        <div class="principle-box">
            <h3><span class="num">1</span>只呈現「發生了什麼」，避免臆測「為什麼」</h3>
            <p>
                每則通知以「發生的事實＋官方原始說法」為主，
                若提供解讀，會明確標示為「初步研判」並保持保守。
            </p>
        </div>

        <div class="principle-box">
            <h3><span class="num">2</span>多來源交叉比對</h3>
            <p>
                同一事件儘量比對官方公告、媒體報導、開放資料（AIS/ADS-B）
                等多個來源，降低單一來源誤判的機率。
            </p>
        </div>

        <div class="principle-box">
            <h3><span class="num">3</span>降低通知疲勞，聚焦真正異常</h3>
            <p>
                例行性活動（如每日例行巡航）採用低頻摘要（晨報/日報），
                只有明顯偏離常態的事件才會即時推送，並設有冷卻機制避免同一事件反覆通知。
            </p>
        </div>

        <div class="principle-box">
            <h3><span class="num">4</span>衛星影像不附加判讀</h3>
            <p>
                衛星影像可能被偽裝或誤判，本站僅提供影像本身，
                判讀交由讀者自行參考，不附加 AI 解讀文字。
            </p>
        </div>

        <div class="principle-box">
            <h3><span class="num">5</span>承認資料限制</h3>
            <p>
                免費公開資料來源在更新頻率、覆蓋範圍上都有限制
                （例如 AIS 無法追蹤關閉訊號的船舶、衛星影像解析度有限）。
                本站不會宣稱資料完整或即時無誤差。
            </p>
        </div>

        <h2>⚠️ 重要聲明</h2>
        <div class="disclaimer">
            <p>
                本站為<strong>民間自發、非營利</strong>的公民科普專案，
                所有資料均來自<strong>公開來源</strong>，整理方式可能存在誤差或延遲。
            </p>
            <p style="margin-top:8px">
                本站內容<strong>不構成軍事、政治、投資或任何決策建議</strong>，
                亦不代表任何官方立場。如需正式、即時、權威的資訊，
                請以
                <a class="inline" href="https://www.mnd.gov.tw/" target="_blank">國防部</a>、
                <a class="inline" href="https://www.cga.gov.tw/" target="_blank">海巡署</a>、
                <a class="inline" href="https://www.moda.gov.tw/" target="_blank">數位部</a>
                等政府機關公告為準。
            </p>
            <p style="margin-top:8px">
                若發現資料有誤或有改善建議，歡迎透過 Telegram 頻道留言回饋。
            </p>
        </div>
    </div>

    <div class="footer">
        Taiwan Defense Bot © 2026 ｜ SkyEye 台灣國防情勢監控 ｜ 民間自發專案
    </div>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route('/about')
def about():
    return render_template_string(ABOUT_HTML)


@app.route('/map')
def serve_map():
    try:
        from config import MAP_OUTPUT_PATH
        with open(MAP_OUTPUT_PATH, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return "<p style='color:#888;text-align:center;padding:40px;background:#0a0e1a'>地圖尚未生成，請等待排程更新</p>"


@app.route('/satellite-image/<filename>')
def serve_satellite_image(filename):
    cache_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data", "satellite"
    )
    return send_from_directory(cache_dir, filename)


@app.route('/api/satellite-images')
def api_satellite_images():
    cache_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data", "satellite"
    )
    today   = datetime.now().strftime('%Y%m%d')
    images  = []
    pattern = os.path.join(cache_dir, f"*_{today}.png")
    for filepath in glob.glob(pattern):
        filename = os.path.basename(filepath)
        area     = filename.replace(f"_{today}.png", "")
        images.append({
            "area":     area,
            "url":      f"/satellite-image/{filename}",
            "filename": filename,
        })
    return jsonify(images)


@app.route('/api/dashboard')
def api_dashboard():
    try:
        from database.db import get_recent_news, get_intrusion_stats, get_recent_scores, get_session
        from database.models import CableStatus, VesselTracking, NewsEvent
        from sqlalchemy import desc

        # 威脅評分
        scores = get_recent_scores(days=1)
        if scores:
            latest = scores[-1]
            threat = {
                "overall":  latest.overall_score,
                "military": latest.military_score,
                "maritime": latest.maritime_score,
                "cyber":    latest.cyber_score,
                "trend":    "→ 持平",
            }
        else:
            threat = {"overall":0,"military":0,"maritime":0,"cyber":0,"trend":"→ 資料不足"}

        scores_7d = get_recent_scores(days=7)
        if len(scores_7d) >= 2:
            r = sum(s.overall_score for s in scores_7d[-3:]) / min(3, len(scores_7d))
            o = sum(s.overall_score for s in scores_7d[:-3]) / max(1, len(scores_7d)-3)
            d = r - o
            if d > 1.0:    threat["trend"] = "↑↑ 顯著上升"
            elif d > 0.3:  threat["trend"] = "↑ 上升"
            elif d < -1.0: threat["trend"] = "↓↓ 顯著下降"
            elif d < -0.3: threat["trend"] = "↓ 下降"

        # 擾臺
        intrusion_stats, _ = get_intrusion_stats(days=1)
        intrusion = {
            "aircraft":       intrusion_stats.get("total_aircraft", 0),
            "vessels":        intrusion_stats.get("total_vessels", 0),
            "median_crossed": intrusion_stats.get("median_line_crossings", 0) > 0,
            "adiz_entry":     intrusion_stats.get("adiz_entries", 0) > 0,
        }

        # 新聞
        recent_news = get_recent_news(hours=24)
        top_news    = sorted(recent_news, key=lambda n: n.threat_score or 0, reverse=True)[:10]
        news = [{
            "title":   n.title or "",
            "score":   n.threat_score or 0,
            "url":     n.url or "",
            "source":  n.source or "",
            "summary": (n.ai_summary or "")[:80],
            "time":    n.fetched_at.strftime('%H:%M') if n.fetched_at else "",
        } for n in top_news]

        session = get_session()
        try:
            # ── 電纜：每條只取最新一筆（去重）──────────────
            from sqlalchemy import func
            cutoff = datetime.now() - timedelta(days=90)
            subq = session.query(
                CableStatus.cable_name,
                func.max(CableStatus.reported_at).label("latest")
            ).filter(
                CableStatus.reported_at >= cutoff
            ).group_by(CableStatus.cable_name).subquery()

            cables_db = session.query(CableStatus).join(
                subq,
                (CableStatus.cable_name == subq.c.cable_name) &
                (CableStatus.reported_at == subq.c.latest)
            ).order_by(desc(CableStatus.reported_at)).all()

            # 過濾地理描述型名稱（如「距越南峴港約226公里處」）
            def is_cable_name(name):
                geo = ["公里", "距", "處斷纜", "附近", "km"]
                return name and not any(g in name for g in geo)

            cables = [
                {"name": c.cable_name, "status": c.status,
                 "time": c.reported_at.strftime("%m/%d") if c.reported_at else ""}
                for c in cables_db if is_cable_name(c.cable_name)
            ]

            # ── 船隻：可疑軍艦（24小時）──────────────────
            vcutoff    = datetime.now() - timedelta(hours=24)
            vessels_db = session.query(VesselTracking).filter(
                VesselTracking.is_suspicious == True,
                VesselTracking.recorded_at >= vcutoff
            ).order_by(desc(VesselTracking.recorded_at)).limit(10).all()
            vessels = [{
                "name":   v.vessel_name,
                "flag":   v.flag or "",
                "reason": v.suspicion_reason or "",
                "lat":    v.latitude or 0,
                "lon":    v.longitude or 0,
            } for v in vessels_db]

            # ── 認知作戰 ──────────────────────────────────
            cogcutoff = datetime.now() - timedelta(hours=24)
            cog_db    = session.query(NewsEvent).filter(
                NewsEvent.fetched_at >= cogcutoff,
                NewsEvent.content.like("%[COG_WAR:True%")
            ).order_by(desc(NewsEvent.fetched_at)).limit(5).all()
            cog_war = [{
                "title":  (n.title or "")[:60],
                "source": n.source or "",
                "url":    n.url or "",
            } for n in cog_db]

            # ── ADS-B 軍機（最近6小時）────────────────────
            adsb_cutoff = datetime.now() - timedelta(hours=6)
            adsb_db     = session.query(NewsEvent).filter(
                NewsEvent.source == "adsb_monitor",
                NewsEvent.published_at >= adsb_cutoff
            ).order_by(desc(NewsEvent.published_at)).limit(5).all()
            adsb = [{
                "title": (n.title or "")[:60],
                "time":  n.published_at.strftime("%H:%M") if n.published_at else "",
                "content": (n.content or "")[:120],
            } for n in adsb_db]

            # ── 中共官媒輿論（最近24小時）─────────────────
            media_cutoff = datetime.now() - timedelta(hours=24)
            media_db     = session.query(NewsEvent).filter(
                NewsEvent.source.in_(["xinhua_world","people_world",
                                      "globaltimes","chinanews","cgtn"]),
                NewsEvent.published_at >= media_cutoff,
                NewsEvent.content.like("%|L2|%") |
                NewsEvent.content.like("%|L3|%")
            ).order_by(desc(NewsEvent.published_at)).limit(5).all()
            china_media = [{
                "title":  (n.title or "")[:60],
                "source": n.source or "",
                "level":  "L3" if "|L3|" in (n.content or "") else "L2",
                "time":   n.published_at.strftime("%m/%d %H:%M") if n.published_at else "",
            } for n in media_db]

            # ── 石油指標（最近一個月）─────────────────────
            oil_cutoff = datetime.now() - timedelta(days=40)
            oil_db     = session.query(NewsEvent).filter(
                NewsEvent.source == "oil_monitor",
                NewsEvent.published_at >= oil_cutoff
            ).order_by(desc(NewsEvent.published_at)).first()
            oil = {}
            if oil_db:
                c = oil_db.content or ""
                oil = {
                    "title":   oil_db.title or "",
                    "level":   next((l for l in ["CRITICAL","HIGH","MEDIUM","NORMAL"]
                                    if f"|{l}|" in c), "NORMAL"),
                    "updated": oil_db.published_at.strftime("%Y-%m") if oil_db.published_at else "",
                }

            # ── 民船徵用（最近24小時）─────────────────────
            req_cutoff = datetime.now() - timedelta(hours=24)
            req_db     = session.query(NewsEvent).filter(
                NewsEvent.source == "ais_monitor",
                NewsEvent.title.like("%民船%"),
                NewsEvent.published_at >= req_cutoff
            ).order_by(desc(NewsEvent.published_at)).first()
            requisition = {}
            if req_db:
                requisition = {
                    "title":  req_db.title or "",
                    "time":   req_db.published_at.strftime("%H:%M") if req_db.published_at else "",
                }

        finally:
            session.close()

        return jsonify({
            "threat":       threat,
            "intrusion":    intrusion,
            "news":         news,
            "cables":       cables,
            "vessels":      vessels,
            "cog_war":      cog_war,
            "adsb":         adsb,
            "china_media":  china_media,
            "oil":          oil,
            "requisition":  requisition,
            "updated":      datetime.now().isoformat(),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/history')
def api_history():
    try:
        from database.db import get_recent_scores
        scores = get_recent_scores(days=30)
        return jsonify([{
            "date":     s.date.strftime('%m/%d'),
            "overall":  s.overall_score,
            "military": s.military_score,
            "maritime": s.maritime_score,
            "cyber":    s.cyber_score,
        } for s in scores])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def run_dashboard(host='127.0.0.1', port=5000, debug=False):
    print(f"[WEB] Dashboard 啟動：http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, use_reloader=False)


if __name__ == "__main__":
    run_dashboard(debug=True)