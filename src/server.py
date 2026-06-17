import json
import mimetypes
import re
import urllib.parse
import http.server
import socketserver
import threading
from pathlib import Path
from src.archive import ArchiveIndex
from src.rewriter import rewrite_html, rewrite_css
from src.utils import DEFAULT_ARCHIVE, log

# ── Dashboard HTML ────────────────────────────────────────────────────────────
# PERF: Data is loaded via fetch() at runtime instead of embedded in the HTML.
# This means the initial page load is instant regardless of archive size.
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>📼 WebRecorder Archive</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Outfit:wght@600;700;800&display=swap" rel="stylesheet">
<style>
:root {
  --bg-color: #08090f;
  --panel-color: #111422;
  --border-color: rgba(255, 255, 255, 0.08);
  --border-hover: rgba(139, 92, 246, 0.4);
  --text-primary: #f8fafc;
  --text-secondary: #94a3b8;
  --accent-color: #8b5cf6;
  --accent-glow: rgba(139, 92, 246, 0.15);
  --success-color: #10b981;
  --info-color: #0ea5e9;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Inter', system-ui, sans-serif;
  background-color: var(--bg-color);
  color: var(--text-primary);
  min-height: 100vh;
  line-height: 1.5;
}
header {
  background: linear-gradient(180deg, rgba(17, 20, 34, 0.8) 0%, rgba(8, 9, 15, 0) 100%);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border-color);
  padding: 24px 40px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  position: sticky;
  top: 0;
  z-index: 100;
}
.logo-container {
  display: flex;
  align-items: center;
  gap: 12px;
}
.logo-icon {
  font-size: 2.2rem;
  line-height: 1;
}
.logo {
  font-family: 'Outfit', sans-serif;
  font-size: 1.8rem;
  font-weight: 800;
  background: linear-gradient(135deg, #a78bfa 0%, #8b5cf6 50%, #6366f1 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: -0.5px;
}
.logo span {
  font-family: 'Inter', sans-serif;
  color: var(--text-secondary);
  font-size: 0.95rem;
  font-weight: 500;
  margin-left: 8px;
  border: 1px solid var(--border-color);
  padding: 2px 8px;
  border-radius: 99px;
  background: rgba(255, 255, 255, 0.03);
}
.search-bar {
  flex: 1;
  max-width: 600px;
  position: relative;
}
.search-bar input {
  width: 100%;
  padding: 12px 16px 12px 48px;
  border-radius: 12px;
  border: 1px solid var(--border-color);
  background: rgba(17, 20, 34, 0.6);
  color: var(--text-primary);
  font-size: 0.95rem;
  outline: none;
  transition: all 0.25s ease;
  backdrop-filter: blur(8px);
}
.search-bar input:focus {
  border-color: var(--accent-color);
  box-shadow: 0 0 20px var(--accent-glow);
  background: rgba(17, 20, 34, 0.85);
}
.search-bar::before {
  content: "🔍";
  position: absolute;
  left: 16px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 1.1rem;
  opacity: 0.6;
}
main {
  padding: 40px;
  max-width: 1600px;
  margin: 0 auto;
}
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 20px;
  margin-bottom: 40px;
}
.stat {
  background: var(--panel-color);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 24px;
  position: relative;
  overflow: hidden;
  transition: all 0.3s ease;
}
.stat:hover {
  border-color: var(--border-hover);
  transform: translateY(-2px);
}
.stat::after {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  width: 4px;
  height: 100%;
  background: var(--accent-color);
}
.stat.stat-domains::after { background: var(--info-color); }
.stat.stat-assets::after { background: var(--success-color); }

.stat .n {
  font-family: 'Outfit', sans-serif;
  font-size: 2.5rem;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.1;
  margin-bottom: 4px;
}
.stat .l {
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--text-secondary);
  font-weight: 600;
}
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-color);
}
.section-title {
  font-family: 'Outfit', sans-serif;
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 10px;
}
.refresh-btn {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 0.88rem;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: all 0.2s ease;
}
.refresh-btn:hover {
  background: var(--accent-color);
  border-color: var(--accent-color);
  box-shadow: 0 0 15px var(--accent-glow);
}
.snap-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: 24px;
}
.snap-card {
  background: var(--panel-color);
  border: 1px solid var(--border-color);
  border-radius: 18px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  height: 100%;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
}
.snap-card:hover {
  border-color: var(--border-hover);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3), 0 0 20px rgba(139, 92, 246, 0.05);
  transform: translateY(-4px);
}
.snap-header {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  margin-bottom: 16px;
}
.favicon-container {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  overflow: hidden;
}
.favicon-container img {
  width: 24px;
  height: 24px;
  object-fit: contain;
}
.snap-title-group {
  flex: 1;
  min-width: 0;
}
.snap-domain {
  font-size: 0.8rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--accent-color);
  margin-bottom: 2px;
}
.snap-url {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
  word-break: break-all;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: block;
}
.snap-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}
.tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 8px;
  font-size: 0.78rem;
  font-weight: 500;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border-color);
}
.tag.assets-tag { color: var(--success-color); border-color: rgba(16, 185, 129, 0.15); background: rgba(16, 185, 129, 0.03); }
.tag.apis-tag { color: var(--info-color); border-color: rgba(14, 165, 233, 0.15); background: rgba(14, 165, 233, 0.03); }
.tag.id-tag { color: var(--text-secondary); }
.tag.extracted-tag { color: #f59e0b; border-color: rgba(245, 158, 11, 0.15); background: rgba(245, 158, 11, 0.03); }
.tag.extracted-yes { color: var(--success-color); border-color: rgba(16, 185, 129, 0.15); background: rgba(16, 185, 129, 0.03); }
.btn-extract {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
  border: 1px solid rgba(245, 158, 11, 0.2);
}
.btn-extract:hover {
  background: rgba(245, 158, 11, 0.2);
  border-color: rgba(245, 158, 11, 0.4);
  box-shadow: 0 0 12px rgba(245, 158, 11, 0.1);
}
.btn-extract.loading {
  opacity: 0.6;
  pointer-events: none;
}
.btn-view {
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
  border: 1px solid rgba(16, 185, 129, 0.2);
}
.btn-view:hover {
  background: rgba(16, 185, 129, 0.2);
  border-color: rgba(16, 185, 129, 0.4);
  box-shadow: 0 0 12px rgba(16, 185, 129, 0.1);
}
.toast-container {
  position: fixed; bottom: 24px; right: 24px; z-index: 9999;
  display: flex; flex-direction: column; gap: 8px;
}
.toast {
  background: var(--panel-color); border: 1px solid var(--border-color);
  padding: 12px 20px; border-radius: 12px; font-size: 0.88rem;
  backdrop-filter: blur(12px); animation: toastIn 0.3s ease;
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
}
.toast.success { border-color: rgba(16, 185, 129, 0.3); color: #10b981; }
.toast.error { border-color: rgba(239, 68, 68, 0.3); color: #ef4444; }
.toast.info { border-color: rgba(139, 92, 246, 0.3); color: #a78bfa; }
@keyframes toastIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

.snap-footer {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid var(--border-color);
}
.snap-ts {
  font-size: 0.78rem;
  color: var(--text-secondary);
}
.actions {
  display: flex;
  gap: 8px;
}
.btn {
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 0.82rem;
  font-weight: 600;
  text-decoration: none;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s ease;
}
.btn-primary {
  background: var(--accent-color);
  color: white;
}
.btn-primary:hover {
  background: #7c3aed;
  box-shadow: 0 0 12px var(--accent-glow);
}
.btn-secondary {
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
}
.btn-secondary:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: var(--text-secondary);
}
.no-results {
  grid-column: 1 / -1;
  text-align: center;
  padding: 80px 40px;
  background: var(--panel-color);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  color: var(--text-secondary);
}
.no-results .icon {
  font-size: 4rem;
  margin-bottom: 16px;
}
.loading-container {
  grid-column: 1 / -1;
  text-align: center;
  padding: 80px 40px;
}
.spinner {
  display: inline-block;
  width: 40px;
  height: 40px;
  border: 4px solid var(--border-color);
  border-top-color: var(--accent-color);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-bottom: 16px;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<header>
  <div class="logo-container">
    <span class="logo-icon">📼</span>
    <div class="logo">WebRecorder <span>Archive v2.0</span></div>
  </div>
  <div class="search-bar">
    <input type="text" id="q" placeholder="Tìm kiếm snap hoặc domain..." oninput="search(this.value)">
  </div>
</header>
<main>
  <div class="stats" id="stats">
    <div class="stat"><div class="n">-</div><div class="l">Snapshots</div></div>
    <div class="stat stat-domains"><div class="n">-</div><div class="l">Domains</div></div>
    <div class="stat stat-assets"><div class="n">-</div><div class="l">Assets</div></div>
  </div>
  
  <div class="section-header">
    <div class="section-title" id="sec-title">Tất cả snapshots</div>
    <button class="refresh-btn" onclick="loadData()">↻ Refresh</button>
  </div>
  
  <div class="snap-grid" id="grid">
    <div class="loading-container">
      <div class="spinner"></div>
      <div>Đang tải snapshots...</div>
    </div>
  </div>
</main>
<script>
let allSnaps = [];

function renderStats() {
  const domains = new Set(allSnaps.map(s=>s.domain)).size;
  const assets = allSnaps.reduce((a,s)=>a+(s.asset_count||0),0);
  document.getElementById('stats').innerHTML = `
    <div class="stat">
      <div class="n">${allSnaps.length}</div>
      <div class="l">Snapshots</div>
    </div>
    <div class="stat stat-domains">
      <div class="n">${domains}</div>
      <div class="l">Domains</div>
    </div>
    <div class="stat stat-assets">
      <div class="n">${assets}</div>
      <div class="l">Assets</div>
    </div>
  `;
}

function renderCards(snaps) {
  const grid = document.getElementById('grid');
  if (!snaps.length) {
    grid.innerHTML = `
      <div class="no-results">
        <div class="icon">🕸️</div>
        <h2>Không tìm thấy snapshot nào</h2>
        <p style="margin-top: 8px;">Thử nhập từ khóa tìm kiếm khác hoặc chạy WebRecorder để ghi website mới.</p>
      </div>
    `;
    return;
  }
  grid.innerHTML = snaps.map(s => {
    // Generate clean domain name for google favicon resolving API
    const cleanDomain = s.domain.replace(/_/g, ':');
    return `
      <div class="snap-card">
        <div class="snap-header">
          <div class="favicon-container">
            <img src="https://www.google.com/s2/favicons?sz=64&domain=${cleanDomain}" 
                 onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' viewBox=\\'0 0 24 24\\' width=\\'24\\' height=\\'24\\'><rect width=\\'100%\\' height=\\'100%\\' fill=\\'%231b223c\\'/><text x=\\'50%\\' y=\\'50%\\' font-family=\\'sans-serif\\' font-size=\\'12\\' fill=\\'%238b5cf6\\' dominant-baseline=\\'middle\\' text-anchor=\\'middle\\'>${cleanDomain.slice(0,2).toUpperCase()}</text></svg>'"
                 alt="favicon">
          </div>
          <div class="snap-title-group">
            <div class="snap-domain">${cleanDomain}</div>
            <a class="snap-url" href="/__wb/${encodeURIComponent(s.url)}" target="_blank" title="${s.url}">${s.url}</a>
          </div>
        </div>
        <div class="snap-meta">
          <span class="tag assets-tag">📁 ${s.asset_count||0} assets</span>
          <span class="tag apis-tag">🔌 ${s.api_count||0} APIs</span>
          <span class="tag id-tag">📸 ${s.id}</span>
          <span class="tag ${s.has_extracted ? 'extracted-yes' : 'extracted-tag'}">${s.has_extracted ? '✅ Extracted' : '⏳ Not extracted'}</span>
        </div>
        <div class="snap-footer">
          <div class="snap-ts">⏰ ${new Date(s.recorded_at).toLocaleString('vi-VN')}</div>
          <div class="actions">
            <button class="btn btn-extract" onclick="triggerExtract('${s.id}', this)" title="Extract content">🔄 Extract</button>
            <a href="/__view/${s.id}" class="btn btn-view" target="_blank" title="View structured content">📊 View</a>
            <a href="/__wb/${encodeURIComponent(s.url)}" class="btn btn-primary" target="_blank">📼 Replay</a>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function search(q) {
  document.getElementById('sec-title').childNodes[0].textContent = q ? `Kết quả tìm kiếm: "${q}"` : 'Tất cả snapshots';
  if (!q.trim()) { renderCards(allSnaps); return; }
  const ql = q.toLowerCase();
  renderCards(allSnaps.filter(s =>
    s.url.toLowerCase().includes(ql) ||
    s.domain.toLowerCase().includes(ql) ||
    s.id.toLowerCase().includes(ql)
  ).sort((a,b)=>{
    const sa = (a.url.toLowerCase().includes(ql)?10:0)+(a.domain.toLowerCase().includes(ql)?5:0);
    const sb = (b.url.toLowerCase().includes(ql)?10:0)+(b.domain.toLowerCase().includes(ql)?5:0);
    return sb-sa;
  }));
}

async function loadData() {
  try {
    document.getElementById('grid').innerHTML = `
      <div class="loading-container">
        <div class="spinner"></div>
        <div>Đang tải dữ liệu snapshots...</div>
      </div>
    `;
    const res = await fetch('/__archive__/api/snapshots');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    allSnaps = await res.json();
    renderStats();
    const q = document.getElementById('q').value;
    search(q);
  } catch(e) {
    document.getElementById('grid').innerHTML = `
      <div class="no-results">
        <div class="icon">⚠️</div>
        <h2>Lỗi tải dữ liệu</h2>
        <p style="margin-top: 8px; color: #ef4444;">${e.message}</p>
      </div>
    `;
  }
}

async function triggerExtract(snapId, btn) {
  btn.classList.add('loading');
  btn.innerHTML = '⏳ Extracting...';
  try {
    const res = await fetch(`/__archive__/api/extract/${snapId}`, {method: 'POST'});
    const data = await res.json();
    if (res.ok) {
      showToast('✅ Extraction complete for ' + snapId, 'success');
      loadData();
    } else {
      showToast('❌ ' + (data.error || 'Extraction failed'), 'error');
    }
  } catch(e) {
    showToast('❌ Network error: ' + e.message, 'error');
  } finally {
    btn.classList.remove('loading');
    btn.innerHTML = '🔄 Extract';
  }
}

function showToast(msg, type='info') {
  let c = document.getElementById('toasts');
  if (!c) { c = document.createElement('div'); c.id='toasts'; c.className='toast-container'; document.body.appendChild(c); }
  const t = document.createElement('div');
  t.className = 'toast ' + type;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

loadData();
</script>
</body>
</html>
"""

# ── Structured View HTML ─────────────────────────────────────────────────────
VIEW_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>📊 Structured View</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
:root {
  --bg: #08090f; --bg2: #0c0e18; --panel: #111422; --panel2: #161a2e;
  --border: rgba(255,255,255,0.07); --border-h: rgba(139,92,246,0.4);
  --text1: #f1f5f9; --text2: #94a3b8; --text3: #64748b;
  --accent: #8b5cf6; --accent2: #a78bfa; --accent-g: rgba(139,92,246,0.12);
  --green: #10b981; --blue: #0ea5e9; --amber: #f59e0b; --red: #ef4444;
  --radius: 14px; --radius-sm: 8px;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text1);min-height:100vh;line-height:1.6}
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:rgba(139,92,246,0.3);border-radius:3px}

/* ── Header ── */
.view-header{
  background:linear-gradient(180deg,rgba(17,20,34,0.95) 0%,rgba(8,9,15,0.8) 100%);
  backdrop-filter:blur(20px);border-bottom:1px solid var(--border);
  padding:20px 32px;position:sticky;top:0;z-index:100;
}
.header-inner{max-width:1800px;margin:0 auto;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.header-favicon{width:40px;height:40px;border-radius:10px;background:var(--panel2);border:1px solid var(--border);display:flex;align-items:center;justify-content:center;overflow:hidden;flex-shrink:0}
.header-favicon img{width:24px;height:24px;object-fit:contain}
.header-info{flex:1;min-width:0}
.header-title{font-family:'Outfit',sans-serif;font-size:1.3rem;font-weight:700;background:linear-gradient(135deg,#a78bfa,#8b5cf6,#6366f1);-webkit-background-clip:text;-webkit-text-fill-color:transparent;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.header-meta{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:2px}
.header-meta span{font-size:0.8rem;color:var(--text2);display:flex;align-items:center;gap:4px}
.header-actions{display:flex;gap:8px;flex-shrink:0}
.h-btn{padding:8px 14px;border-radius:var(--radius-sm);font-size:0.82rem;font-weight:600;text-decoration:none;cursor:pointer;border:1px solid var(--border);background:rgba(255,255,255,0.03);color:var(--text1);display:inline-flex;align-items:center;gap:6px;transition:all 0.2s}
.h-btn:hover{border-color:var(--border-h);background:var(--accent-g);box-shadow:0 0 15px var(--accent-g)}
.h-btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.h-btn.primary:hover{background:#7c3aed;box-shadow:0 0 20px var(--accent-g)}

/* ── Banner ── */
.banner{max-width:1800px;margin:0 auto;padding:0 32px}
.banner img{width:100%;max-height:280px;object-fit:cover;border-radius:0 0 var(--radius) var(--radius);border:1px solid var(--border);border-top:none}

/* ── Search Bar ── */
.search-wrap{max-width:1800px;margin:16px auto;padding:0 32px}
.search-input{width:100%;padding:12px 16px 12px 44px;border-radius:var(--radius);border:1px solid var(--border);background:var(--panel);color:var(--text1);font-size:0.92rem;outline:none;transition:all 0.25s}
.search-input:focus{border-color:var(--accent);box-shadow:0 0 20px var(--accent-g)}
.search-wrap{position:relative}
.search-wrap::before{content:"🔍";position:absolute;left:46px;top:50%;transform:translateY(-50%);font-size:1rem;opacity:0.5;z-index:1}

/* ── Tabs ── */
.tabs-wrap{max-width:1800px;margin:0 auto;padding:8px 32px 0}
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--border);overflow-x:auto}
.tab{padding:10px 20px;font-size:0.88rem;font-weight:600;color:var(--text3);cursor:pointer;border-bottom:2px solid transparent;transition:all 0.2s;white-space:nowrap;user-select:none}
.tab:hover{color:var(--text2)}
.tab.active{color:var(--accent2);border-bottom-color:var(--accent)}

/* ── Layout ── */
.main-wrap{max-width:1800px;margin:0 auto;padding:16px 32px 40px;display:flex;gap:24px}
.sidebar{width:260px;flex-shrink:0;position:sticky;top:90px;max-height:calc(100vh - 110px);overflow-y:auto}
.sidebar-section{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:16px}
.sidebar-title{font-family:'Outfit',sans-serif;font-size:0.85rem;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--text3);margin-bottom:12px;display:flex;align-items:center;gap:6px}
.toc-list{list-style:none}
.toc-item{padding:6px 10px;font-size:0.82rem;color:var(--text2);border-radius:6px;cursor:pointer;transition:all 0.15s;border-left:2px solid transparent;margin-bottom:2px}
.toc-item:hover{background:rgba(139,92,246,0.08);color:var(--text1);border-left-color:var(--accent)}
.toc-item.active{background:var(--accent-g);color:var(--accent2);border-left-color:var(--accent)}
.toc-item.h3{padding-left:20px;font-size:0.78rem}
.nav-link{display:block;padding:8px 12px;font-size:0.82rem;color:var(--blue);border-radius:6px;text-decoration:none;transition:all 0.15s;word-break:break-all}
.nav-link:hover{background:rgba(14,165,233,0.08)}
.asset-mini{display:flex;align-items:center;gap:8px;padding:6px 8px;font-size:0.78rem;color:var(--text2);border-radius:6px;transition:all 0.15s;cursor:default}
.asset-mini:hover{background:rgba(255,255,255,0.03)}
.asset-mini .dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.asset-mini .name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.asset-mini .size{color:var(--text3);flex-shrink:0}

.content-area{flex:1;min-width:0}
.tab-panel{display:none}
.tab-panel.active{display:block}

/* ── Content Panel ── */
.content-section{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:28px 32px;margin-bottom:20px;transition:border-color 0.3s}
.content-section:hover{border-color:rgba(139,92,246,0.15)}
.content-section h2{font-family:'Outfit',sans-serif;font-size:1.4rem;font-weight:700;margin-bottom:12px;background:linear-gradient(135deg,var(--accent2),var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.content-section h3{font-size:1.1rem;font-weight:600;margin:16px 0 8px;color:var(--text1)}
.content-section p{color:var(--text2);margin-bottom:12px;line-height:1.7}
.content-section ul,.content-section ol{color:var(--text2);margin:0 0 12px 20px}
.content-section li{margin-bottom:4px;line-height:1.6}
.content-section img{max-width:100%;border-radius:var(--radius-sm);border:1px solid var(--border);cursor:pointer;transition:all 0.3s;margin:8px 0}
.content-section img:hover{border-color:var(--border-h);box-shadow:0 8px 30px rgba(0,0,0,0.4)}
.content-section table{width:100%;border-collapse:collapse;margin:12px 0;font-size:0.88rem}
.content-section th{background:var(--panel2);color:var(--text1);padding:10px 14px;text-align:left;font-weight:600;border:1px solid var(--border)}
.content-section td{padding:10px 14px;border:1px solid var(--border);color:var(--text2)}
.content-section pre{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius-sm);padding:16px;overflow-x:auto;font-family:'JetBrains Mono',monospace;font-size:0.85rem;color:var(--accent2);margin:12px 0}
.content-section code{font-family:'JetBrains Mono',monospace;font-size:0.85rem;background:rgba(139,92,246,0.1);padding:2px 6px;border-radius:4px;color:var(--accent2)}
.content-section pre code{background:none;padding:0}
.content-section a{color:var(--blue);text-decoration:none}
.content-section a:hover{text-decoration:underline}
.content-section blockquote{border-left:3px solid var(--accent);padding:12px 20px;margin:12px 0;background:rgba(139,92,246,0.05);border-radius:0 var(--radius-sm) var(--radius-sm) 0;color:var(--text2);font-style:italic}

/* ── Assets Grid ── */
.assets-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px}
.asset-card{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;transition:all 0.3s;cursor:pointer}
.asset-card:hover{border-color:var(--border-h);transform:translateY(-3px);box-shadow:0 8px 25px rgba(0,0,0,0.3)}
.asset-preview{height:140px;background:var(--bg2);display:flex;align-items:center;justify-content:center;overflow:hidden}
.asset-preview img{max-width:100%;max-height:100%;object-fit:contain}
.asset-preview .icon-preview{font-size:3rem;opacity:0.4}
.asset-info{padding:12px}
.asset-name{font-size:0.8rem;font-weight:500;color:var(--text1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.asset-detail{font-size:0.72rem;color:var(--text3);margin-top:4px;display:flex;justify-content:space-between}

/* ── Flow ── */
.flow-container{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:24px;overflow-x:auto}
.flow-container .mermaid{display:flex;justify-content:center}
.flow-timeline{margin-top:24px}
.flow-entry{display:flex;gap:16px;padding:12px 16px;border-left:2px solid var(--border);margin-left:20px;position:relative;transition:all 0.2s}
.flow-entry:hover{background:rgba(139,92,246,0.04);border-left-color:var(--accent)}
.flow-entry::before{content:"";position:absolute;left:-6px;top:16px;width:10px;height:10px;border-radius:50%;background:var(--panel2);border:2px solid var(--accent);z-index:1}
.flow-entry.nav::before{border-color:var(--blue)}
.flow-entry.api::before{border-color:var(--green)}
.flow-type{font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;padding:2px 8px;border-radius:4px;flex-shrink:0;height:fit-content;margin-top:2px}
.flow-type.nav{color:var(--blue);background:rgba(14,165,233,0.1)}
.flow-type.api{color:var(--green);background:rgba(16,185,129,0.1)}
.flow-url{font-size:0.85rem;color:var(--text2);word-break:break-all;flex:1}
.flow-status{font-size:0.78rem;color:var(--text3);flex-shrink:0}

/* ── Raw / Markdown ── */
.raw-frame{width:100%;height:calc(100vh - 200px);border:1px solid var(--border);border-radius:var(--radius);background:var(--bg)}
.md-toolbar{display:flex;gap:8px;margin-bottom:12px}
.md-content{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:32px;max-height:calc(100vh - 240px);overflow-y:auto}
.md-content h1,.md-content h2,.md-content h3{font-family:'Outfit',sans-serif;color:var(--text1);margin:20px 0 8px}
.md-content h1{font-size:1.6rem;font-weight:800}
.md-content h2{font-size:1.3rem;font-weight:700}
.md-content h3{font-size:1.1rem;font-weight:600}
.md-content p{color:var(--text2);line-height:1.7;margin-bottom:12px}
.md-content a{color:var(--blue)}
.md-content img{max-width:100%;border-radius:var(--radius-sm)}
.md-content pre{background:var(--bg2);padding:16px;border-radius:var(--radius-sm);overflow-x:auto;font-family:'JetBrains Mono',monospace;font-size:0.85rem;color:var(--accent2)}
.md-content code{font-family:'JetBrains Mono',monospace;background:rgba(139,92,246,0.1);padding:2px 6px;border-radius:4px;font-size:0.85rem;color:var(--accent2)}
.md-content pre code{background:none;padding:0}
.md-content blockquote{border-left:3px solid var(--accent);padding:8px 16px;margin:12px 0;background:rgba(139,92,246,0.05);color:var(--text2)}
.md-content table{width:100%;border-collapse:collapse;margin:12px 0}
.md-content th{background:var(--panel2);padding:8px 12px;text-align:left;border:1px solid var(--border);font-weight:600}
.md-content td{padding:8px 12px;border:1px solid var(--border);color:var(--text2)}

/* ── Lightbox ── */
.lightbox{position:fixed;inset:0;background:rgba(0,0,0,0.92);backdrop-filter:blur(20px);z-index:9999;display:none;align-items:center;justify-content:center;cursor:zoom-out}
.lightbox.open{display:flex}
.lightbox img{max-width:92vw;max-height:92vh;object-fit:contain;border-radius:var(--radius);box-shadow:0 20px 60px rgba(0,0,0,0.5)}
.lightbox-close{position:absolute;top:20px;right:24px;font-size:1.8rem;color:var(--text2);cursor:pointer;background:rgba(0,0,0,0.5);width:44px;height:44px;border-radius:50%;display:flex;align-items:center;justify-content:center;transition:all 0.2s}
.lightbox-close:hover{color:#fff;background:var(--accent)}

/* ── Loading / Empty ── */
.loading-state{text-align:center;padding:80px 40px}
.spinner{display:inline-block;width:44px;height:44px;border:4px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin 0.8s linear infinite;margin-bottom:16px}
@keyframes spin{to{transform:rotate(360deg)}}
.empty-state{text-align:center;padding:80px 40px;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius)}
.empty-state .icon{font-size:4rem;margin-bottom:16px}
.empty-state h2{font-family:'Outfit',sans-serif;font-size:1.4rem;font-weight:700;margin-bottom:8px}
.empty-state p{color:var(--text2);margin-bottom:20px}
.extract-btn{padding:12px 28px;border-radius:var(--radius-sm);background:var(--accent);color:#fff;font-size:0.95rem;font-weight:600;border:none;cursor:pointer;transition:all 0.2s;display:inline-flex;align-items:center;gap:8px}
.extract-btn:hover{background:#7c3aed;box-shadow:0 0 25px var(--accent-g)}
.extract-btn.loading{opacity:0.6;pointer-events:none}

/* ── Toast ── */
.toast-box{position:fixed;bottom:24px;right:24px;z-index:99999;display:flex;flex-direction:column;gap:8px}
.toast-msg{background:var(--panel);border:1px solid var(--border);padding:12px 20px;border-radius:var(--radius);font-size:0.88rem;backdrop-filter:blur(12px);animation:toastSlide 0.3s ease;box-shadow:0 8px 30px rgba(0,0,0,0.5)}
.toast-msg.success{border-color:rgba(16,185,129,0.3);color:var(--green)}
.toast-msg.error{border-color:rgba(239,68,68,0.3);color:var(--red)}
@keyframes toastSlide{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}

/* ── Responsive ── */
@media(max-width:900px){
  .main-wrap{flex-direction:column}
  .sidebar{width:100%;position:static;max-height:none}
  .view-header{padding:16px 20px}
  .main-wrap,.tabs-wrap,.search-wrap,.banner{padding-left:16px;padding-right:16px}
  .assets-grid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}
}

/* ── Hierarchical Tree View ── */
.tree-nested {
  margin-left: 16px;
  border-left: 1px dashed #4b5563;
  padding-left: 12px;
  margin-bottom: 8px;
}
.tree-nested-list {
  margin-left: 16px;
  border-left: 1px dashed #8b5cf6;
  padding-left: 12px;
  margin-bottom: 8px;
}
.tree-list-item {
  background: rgba(30, 41, 59, 0.5);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 10px;
  border: 1px solid #334155;
}
.tree-key {
  color: #a78bfa;
  font-weight: 600;
  font-family: monospace;
}
.tree-key-dict {
  color: #60a5fa;
  font-weight: 700;
  cursor: pointer;
  font-family: monospace;
}
.tree-key-list {
  color: #34d399;
  font-weight: 700;
  cursor: pointer;
  font-family: monospace;
}
.tree-val {
  color: #e2e8f0;
}
.tree-img-thumb {
  max-width: 90px;
  max-height: 90px;
  border-radius: 6px;
  cursor: pointer;
  vertical-align: middle;
  margin: 4px 8px;
  border: 1px solid #475569;
  transition: transform 0.2s, box-shadow 0.2s;
}
.tree-img-thumb:hover {
  transform: scale(1.08);
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.3);
}
details[open] > summary {
  margin-bottom: 6px;
}
/* ── Collapsible DOM Tree (DevTools style) ── */
.dom-tree-container {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.85rem;
  line-height: 1.6;
  color: var(--text2);
  user-select: text;
}
.dom-line {
  padding-left: 14px;
  margin: 2px 0;
  border-radius: 3px;
  transition: background 0.1s ease;
}
.dom-line:hover {
  background: rgba(255, 255, 255, 0.04);
}
details.dom-details {
  display: block;
  margin: 2px 0;
}
details.dom-details > summary {
  list-style: none;
  position: relative;
  padding-left: 14px;
  outline: none;
  cursor: pointer;
  border-radius: 3px;
  transition: background 0.1s ease;
}
details.dom-details > summary:hover {
  background: rgba(255, 255, 255, 0.04);
}
details.dom-details > summary::-webkit-details-marker {
  display: none;
}
details.dom-details > summary::before {
  content: "▶";
  position: absolute;
  left: 2px;
  top: 1px;
  font-size: 0.65rem;
  color: var(--text3);
  transition: transform 0.15s ease;
}
details.dom-details[open] > summary::before {
  transform: rotate(90deg);
}
.dom-children {
  border-left: 1px dashed rgba(255, 255, 255, 0.08);
  margin-left: 6px;
  padding-left: 8px;
}
.dom-tag {
  color: #f43f5e;
  font-weight: 500;
}
.dom-attr-name {
  color: #fb923c;
}
.dom-attr-val {
  color: #22c55e;
}
.dom-text {
  color: var(--text1);
  font-family: 'Inter', sans-serif;
  font-size: 0.88rem;
  margin: 0 4px;
  background: rgba(255, 255, 255, 0.02);
  padding: 0px 4px;
  border-radius: 3px;
}
.dom-closing {
  padding-left: 14px;
  color: var(--text2);
}
details.dom-details:not([open]) > summary .dom-ellipsis {
  display: inline;
  background: rgba(255, 255, 255, 0.08);
  padding: 0 4px;
  border-radius: 3px;
  font-size: 0.75rem;
  color: var(--accent2);
}
.dom-ellipsis {
  display: none;
}
</style>
</head>
<body>
<!-- Header -->
<div class="view-header">
  <div class="header-inner">
    <div class="header-favicon" id="hdr-favicon"></div>
    <div class="header-info">
      <div class="header-title" id="hdr-title">Loading...</div>
      <div class="header-meta">
        <span id="hdr-domain">🌐 ...</span>
        <span id="hdr-date">📅 ...</span>
        <span id="hdr-id">🔗 ...</span>
      </div>
    </div>
    <div class="header-actions">
      <a href="/__archive__" class="h-btn">← Dashboard</a>
      <button class="h-btn" onclick="downloadJSON()" id="btn-dl-json">📥 JSON</button>
      <button class="h-btn" onclick="downloadMD()" id="btn-dl-md">📥 MD</button>
      <a href="" class="h-btn primary" id="btn-replay" target="_blank">📼 Replay</a>
    </div>
  </div>
</div>

<!-- Banner -->
<div class="banner" id="banner-wrap" style="display:none">
  <img id="banner-img" alt="Banner" onclick="openLightbox(this.src)">
</div>

<!-- Search -->
<div class="search-wrap">
  <input type="text" class="search-input" id="content-search" placeholder="Search within content..." oninput="filterContent(this.value)">
</div>

<!-- Tabs -->
<div class="tabs-wrap">
  <div class="tabs" id="tabs">
    <div class="tab active" data-tab="content">📄 Content</div>
    <div class="tab" data-tab="assets">🖼️ Assets</div>
    <div class="tab" data-tab="flow">🔀 Flow</div>
    <div class="tab" data-tab="raw">🌐 Raw HTML</div>
    <div class="tab" data-tab="markdown">📝 Markdown</div>
    <div class="tab" data-tab="structure">🏗️ Structure MD</div>
  </div>
</div>

<!-- Main Layout -->
<div class="main-wrap">
  <!-- Sidebar -->
  <aside class="sidebar" id="sidebar">
    <div class="sidebar-section">
      <div class="sidebar-title">📑 Table of Contents</div>
      <ul class="toc-list" id="toc-list"></ul>
    </div>
    <div class="sidebar-section" id="sidebar-nav" style="display:none">
      <div class="sidebar-title">🔗 Navigation</div>
      <div id="nav-links"></div>
    </div>
    <div class="sidebar-section" id="sidebar-assets" style="display:none">
      <div class="sidebar-title">📁 Assets <span id="asset-count" style="color:var(--text3)"></span></div>
      <div id="asset-list-mini"></div>
    </div>
  </aside>

  <!-- Content Area -->
  <div class="content-area">
    <!-- Content Tab -->
    <div class="tab-panel active" id="panel-content">
      <div class="loading-state" id="content-loading">
        <div class="spinner"></div>
        <div>Loading extracted content...</div>
      </div>
      <!-- Mode Toggle -->
      <div class="mode-toggle-wrap" style="display: flex; gap: 8px; margin-bottom: 24px; border-bottom: 1px solid var(--border); padding-bottom: 12px;">
        <button class="h-btn active" id="btn-mode-flat" onclick="switchContentMode('flat')">📄 Flat Sections</button>
        <button class="h-btn" id="btn-mode-hierarchical" onclick="switchContentMode('hierarchical')">🌳 Hierarchical Areas</button>
      </div>
      <div id="content-sections"></div>
      <div id="hierarchical-areas-view" style="display: none;"></div>
    </div>

    <!-- Assets Tab -->
    <div class="tab-panel" id="panel-assets">
      <div class="assets-grid" id="assets-grid"></div>
    </div>

    <!-- Flow Tab -->
    <div class="tab-panel" id="panel-flow">
      <div class="flow-container" id="flow-diagram"></div>
      <div class="flow-timeline" id="flow-timeline"></div>
    </div>

    <!-- Raw HTML Tab -->
    <div class="tab-panel" id="panel-raw">
      <iframe class="raw-frame" id="raw-iframe" sandbox="allow-scripts allow-same-origin"></iframe>
    </div>

    <!-- Markdown Tab -->
    <div class="tab-panel" id="panel-markdown">
      <div class="md-toolbar">
        <button class="h-btn" onclick="copyMarkdown()">📋 Copy Markdown</button>
        <button class="h-btn" onclick="downloadMD()">📥 Download .md</button>
      </div>
      <div class="md-content" id="md-rendered"></div>
    </div>

    <!-- Structure Tab -->
    <div class="tab-panel" id="panel-structure">
      <div class="md-toolbar">
        <button class="h-btn" onclick="copyStructureMarkdown()">📋 Copy Structure</button>
        <button class="h-btn" onclick="downloadStructureMD()">📥 Download structure.md</button>
      </div>
      <div class="md-content" id="structure-rendered"></div>
    </div>
  </div>
</div>

<!-- Lightbox -->
<div class="lightbox" id="lightbox" onclick="closeLightbox()">
  <div class="lightbox-close">✕</div>
  <img id="lightbox-img" src="" alt="Preview">
</div>

<!-- Toast Container -->
<div class="toast-box" id="toast-box"></div>

<script>
const SNAP_ID = '{{SNAP_ID}}';
let extractedData = null;
let markdownContent = '';
let structureMarkdownContent = '';
let snapInfo = null;

// ── Init ──
document.addEventListener('DOMContentLoaded', async () => {
  mermaid.initialize({ theme: 'dark', themeVariables: { primaryColor: '#8b5cf6', primaryTextColor: '#f1f5f9', lineColor: '#64748b', primaryBorderColor: '#8b5cf6' }});

  // Tab switching
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById('panel-' + tab.dataset.tab).classList.add('active');
      // Show/hide sidebar based on tab
      const sb = document.getElementById('sidebar');
      sb.style.display = ['content','markdown','structure'].includes(tab.dataset.tab) ? '' : 'none';
      // Load raw iframe on demand
      if (tab.dataset.tab === 'raw' && snapInfo) {
        const iframe = document.getElementById('raw-iframe');
        if (!iframe.src || iframe.src === 'about:blank') {
          iframe.src = '/__wb/' + encodeURIComponent(snapInfo.url);
        }
      }
    });
  });

  await loadSnapInfo();
  await loadExtractedData();
  await loadMarkdown();
  await loadStructureMarkdown();
  await loadAssets();
  await loadFlow();
});

// ── Load snap info ──
async function loadSnapInfo() {
  try {
    const res = await fetch('/__archive__/api/snapshots');
    const snaps = await res.json();
    snapInfo = snaps.find(s => s.id === SNAP_ID);
    if (snapInfo) {
      const cleanDomain = snapInfo.domain.replace(/_/g, ':');
      document.getElementById('hdr-title').textContent = snapInfo.title || snapInfo.url;
      document.getElementById('hdr-domain').innerHTML = '🌐 ' + cleanDomain;
      document.getElementById('hdr-date').innerHTML = '📅 ' + new Date(snapInfo.recorded_at).toLocaleString();
      document.getElementById('hdr-id').innerHTML = '🔗 ' + snapInfo.id;
      document.getElementById('hdr-favicon').innerHTML = `<img src="https://www.google.com/s2/favicons?sz=64&domain=${cleanDomain}" onerror="this.parentElement.innerHTML='📄'" alt="">`;
      document.getElementById('btn-replay').href = '/__wb/' + encodeURIComponent(snapInfo.url);
    }
  } catch(e) { console.error('Failed to load snap info', e); }
}

// ── Load extracted data ──
async function loadExtractedData() {
  const loading = document.getElementById('content-loading');
  const sections = document.getElementById('content-sections');
  try {
    const res = await fetch(`/__archive__/api/extracted/${SNAP_ID}`);
    if (!res.ok) {
      loading.style.display = 'none';
      sections.innerHTML = `
        <div class="empty-state">
          <div class="icon">📊</div>
          <h2>No extracted data yet</h2>
          <p>Content has not been extracted for this snapshot.</p>
          <button class="extract-btn" onclick="triggerExtract(this)">🔄 Extract Now</button>
        </div>`;
      return;
    }
    extractedData = await res.json();
    loading.style.display = 'none';
    renderContent(extractedData);
    renderHierarchicalAreas(extractedData);
    renderTOC(extractedData);
    renderBanner(extractedData);
  } catch(e) {
    loading.style.display = 'none';
    sections.innerHTML = `<div class="empty-state"><div class="icon">⚠️</div><h2>Error loading data</h2><p>${e.message}</p></div>`;
  }
}

let currentContentMode = 'flat';

function switchContentMode(mode) {
  currentContentMode = mode;
  const btnFlat = document.getElementById('btn-mode-flat');
  const btnHier = document.getElementById('btn-mode-hierarchical');
  const flatView = document.getElementById('content-sections');
  const hierView = document.getElementById('hierarchical-areas-view');
  
  if (mode === 'flat') {
    btnFlat.classList.add('active');
    btnHier.classList.remove('active');
    flatView.style.display = 'block';
    hierView.style.display = 'none';
  } else {
    btnFlat.classList.remove('active');
    btnHier.classList.add('active');
    flatView.style.display = 'none';
    hierView.style.display = 'block';
  }
}

function renderTreeRecursive(val) {
  if (val === null || val === undefined) return '<span class="tree-val">null</span>';
  
  if (typeof val === 'object' && !Array.isArray(val)) {
    let html = '<div class="tree-nested">';
    for (const [k, v] of Object.entries(val)) {
      if (v === null || v === undefined) continue;
      
      const isDict = typeof v === 'object' && !Array.isArray(v);
      const isArr = Array.isArray(v);
      
      if (isDict) {
        html += `<details open><summary><span class="tree-key-dict">${escapeHtml(k)}</span></summary>${renderTreeRecursive(v)}</details>`;
      } else if (isArr) {
        html += `<details open><summary><span class="tree-key-list">${escapeHtml(k)} [${v.length}]</span></summary>`;
        html += `<div class="tree-nested-list">`;
        v.forEach(item => {
          html += `<div class="tree-list-item">${renderTreeRecursive(item)}</div>`;
        });
        html += `</div></details>`;
      } else {
        const vStr = String(v);
        if (k.endsWith('_src') || k.endsWith('_local') || k === 'icon_src') {
          let src = vStr;
          if (!src.startsWith('http') && !src.startsWith('data:')) {
            src = `/__asset/${SNAP_ID}/${src}`;
          }
          html += `<div><span class="tree-key">${escapeHtml(k)}</span>: <img class="tree-img-thumb" src="${escapeHtml(src)}" onclick="openLightbox('${escapeHtml(src)}')"> <span class="tree-val">${escapeHtml(vStr)}</span></div>`;
        } else if (k.endsWith('_href') || k === 'href') {
          html += `<div><span class="tree-key">${escapeHtml(k)}</span>: <a href="${escapeHtml(vStr)}" target="_blank" class="tree-val">${escapeHtml(vStr)}</a></div>`;
        } else {
          html += `<div><span class="tree-key">${escapeHtml(k)}</span>: <span class="tree-val">${escapeHtml(vStr)}</span></div>`;
        }
      }
    }
    html += '</div>';
    return html;
  }
  
  if (Array.isArray(val)) {
    let html = '<div class="tree-nested-list">';
    val.forEach(item => {
      html += `<div class="tree-list-item">${renderTreeRecursive(item)}</div>`;
    });
    html += '</div>';
    return html;
  }
  
  return `<span class="tree-val">${escapeHtml(String(val))}</span>`;
}

function renderHierarchicalAreas(data) {
  const container = document.getElementById('hierarchical-areas-view');
  if (!container) return;

  const ha = data.content && data.content.hierarchical_areas ? data.content.hierarchical_areas : null;
  if (!ha) {
    container.innerHTML = '<div class="empty-state"><div class="icon">🌳</div><h2>No hierarchical areas found</h2><p>Try re-extracting this page.</p></div>';
    return;
  }

  // Support both old array format and new dictionary format
  if (typeof ha === 'object' && ha.html !== undefined) {
    const cleanHtml = ha.html || '';
    
    // Render the beautiful tabbed panel
    container.innerHTML = `
      <div class="ha-tabs" style="display:flex; gap:8px; margin-bottom:16px;">
        <button class="h-btn active" id="btn-ha-visual" onclick="toggleHAMode('visual')">👁️ Visual Structure</button>
        <button class="h-btn" id="btn-ha-code" onclick="toggleHAMode('code')">🌳 Interactive HTML Tree</button>
      </div>
      
      <div id="ha-visual-panel">
        <iframe id="ha-iframe" src="/__asset/${SNAP_ID}/hierarchical_areas.html" style="width:100%; height:700px; border:1px solid var(--border); border-radius:var(--radius); background:var(--bg2);" sandbox="allow-same-origin"></iframe>
      </div>
      
      <div id="ha-code-panel" style="display:none;">
        <div class="dom-tree-container" id="ha-dom-tree" style="background:var(--panel2); border:1px solid var(--border); border-radius:var(--radius); padding:20px; max-height:700px; overflow-y:auto; overflow-x:auto; font-family:'JetBrains Mono',monospace; font-size:0.85rem; line-height:1.5; color:var(--text2);">
          Loading interactive HTML tree...
        </div>
      </div>
    `;

    // Add iframe loaded style injection
    const iframe = document.getElementById('ha-iframe');
    if (iframe) {
      iframe.onload = () => {
        try {
          const doc = iframe.contentDocument || iframe.contentWindow.document;
          const style = doc.createElement('style');
          style.innerHTML = `
            body {
              font-family: 'Inter', system-ui, sans-serif;
              color: #f1f5f9;
              background: #08090f;
              padding: 24px;
              line-height: 1.6;
              max-width: 1000px;
              margin: 0 auto;
            }
            h1, h2, h3, h4, h5, h6 {
              font-family: 'Outfit', sans-serif;
              margin-top: 20px;
              margin-bottom: 10px;
              color: #a78bfa;
            }
            p {
              margin-bottom: 12px;
              color: #cbd5e1;
            }
            a {
              color: #38bdf8;
              text-decoration: none;
            }
            a:hover {
              text-decoration: underline;
            }
            img {
              max-width: 150px;
              max-height: 150px;
              object-fit: contain;
              border-radius: 6px;
              margin: 8px 0;
              border: 1px solid rgba(255,255,255,0.1);
              display: block;
            }
            div {
              border: 1px dashed rgba(139, 92, 246, 0.2);
              padding: 10px;
              margin: 8px 0;
              border-radius: 6px;
              background: rgba(139, 92, 246, 0.01);
            }
            ul, ol {
              margin: 8px 0 8px 20px;
              color: #cbd5e1;
            }
            li {
              margin-bottom: 4px;
            }
            table {
              width: 100%;
              border-collapse: collapse;
              margin: 12px 0;
            }
            th, td {
              border: 1px solid rgba(255,255,255,0.1);
              padding: 6px 10px;
              text-align: left;
            }
            th {
              background: #111422;
            }
          `;
          doc.head.appendChild(style);
        } catch (e) {
          console.error("Failed to inject style into iframe: ", e);
        }
      };
    }

    // Parse clean HTML string and build interactive DOM tree view
    try {
      let htmlToParse = cleanHtml.trim();
      if (htmlToParse.toLowerCase().startsWith('<body')) {
        const firstClose = htmlToParse.indexOf('>');
        const lastOpen = htmlToParse.toLowerCase().lastIndexOf('</body');
        if (firstClose !== -1 && lastOpen !== -1) {
          htmlToParse = htmlToParse.substring(firstClose + 1, lastOpen);
        }
      }

      const parser = new DOMParser();
      const doc = parser.parseFromString(htmlToParse, 'text/html');
      const domTree = document.getElementById('ha-dom-tree');
      if (domTree) {
        const topLevelNodes = Array.from(doc.body.childNodes).filter(child => {
          if (child.nodeType === 3) { // Node.TEXT_NODE
            return child.nodeValue.trim().length > 0;
          }
          return child.nodeType === 1; // Node.ELEMENT_NODE
        });
        
        let treeHtml = '';
        if (topLevelNodes.length === 0) {
          treeHtml = '<div class="empty-state">No elements in body</div>';
        } else {
          topLevelNodes.forEach(node => {
            treeHtml += renderDOMTreeRecursive(node);
          });
        }
        domTree.innerHTML = treeHtml;
      }
    } catch (e) {
      console.error("Failed to parse clean HTML for interactive tree: ", e);
      const domTree = document.getElementById('ha-dom-tree');
      if (domTree) {
        domTree.innerHTML = `<span style="color:var(--red)">Failed to render tree: ${escapeHtml(e.message)}</span>`;
      }
    }
    return;
  }

  // Fallback to old array format if present
  if (Array.isArray(ha)) {
    let html = '';
    ha.forEach((area, i) => {
      html += `<div class="content-section" style="margin-bottom: 24px; border-left: 3px solid var(--accent); padding-left: 16px;">`;
      const tag = area.element || 'div';
      const cls = area.class ? ` class="${area.class}"` : '';
      const eid = area.id ? ` id="${area.id}"` : '';
      html += `<div style="font-family: monospace; font-size: 0.85rem; color: var(--text3); margin-bottom: 12px; background: #1e293b; padding: 4px 8px; border-radius: 4px; display: inline-block;">`;
      html += `&lt;${tag}${cls}${eid}&gt;`;
      html += `</div>`;
      html += renderTreeRecursive(area.data);
      html += `</div>`;
    });
    container.innerHTML = html;
  }
}

function renderDOMTreeRecursive(node) {
  if (node.nodeType === Node.TEXT_NODE) {
    const text = node.nodeValue.trim();
    if (!text) return '';
    return `<span class="dom-text">${escapeHtml(text)}</span>`;
  }
  
  if (node.nodeType !== Node.ELEMENT_NODE) {
    return '';
  }

  const tagName = node.tagName.toLowerCase();
  
  // Build attributes string
  let attrsHtml = '';
  for (let i = 0; i < node.attributes.length; i++) {
    const attr = node.attributes[i];
    attrsHtml += ` <span class="dom-attr-name">${escapeHtml(attr.name)}</span>=<span class="dom-attr-val">"${escapeHtml(attr.value)}"</span>`;
  }

  const childNodes = Array.from(node.childNodes).filter(child => {
    if (child.nodeType === Node.TEXT_NODE) {
      return child.nodeValue.trim().length > 0;
    }
    return child.nodeType === Node.ELEMENT_NODE;
  });

  if (childNodes.length === 0) {
    // Self-closing or empty tag
    if (['img', 'br', 'hr', 'input'].includes(tagName)) {
      return `<div class="dom-line">&lt;<span class="dom-tag">${tagName}</span>${attrsHtml}/&gt;</div>`;
    }
    return `<div class="dom-line">&lt;<span class="dom-tag">${tagName}</span>${attrsHtml}&gt;&lt;/<span class="dom-tag">${tagName}</span>&gt;</div>`;
  }

  // If it has only one text child, render it on a single line!
  if (childNodes.length === 1 && childNodes[0].nodeType === Node.TEXT_NODE) {
    const text = childNodes[0].nodeValue.trim();
    return `<div class="dom-line">&lt;<span class="dom-tag">${tagName}</span>${attrsHtml}&gt;<span class="dom-text">${escapeHtml(text)}</span>&lt;/<span class="dom-tag">${tagName}</span>&gt;</div>`;
  }

  // Recursive tree with details/summary (collapsible)
  let childrenHtml = '<div class="dom-children">';
  childNodes.forEach(child => {
    childrenHtml += renderDOMTreeRecursive(child);
  });
  childrenHtml += '</div>';

  return `
    <details class="dom-details" open>
      <summary class="dom-summary">
        &lt;<span class="dom-tag">${tagName}</span>${attrsHtml}&gt;
        <span class="dom-ellipsis">...</span>
      </summary>
      ${childrenHtml}
      <div class="dom-closing">&lt;/<span class="dom-tag">${tagName}</span>&gt;</div>
    </details>
  `;
}

function toggleHAMode(mode) {
  const btnVisual = document.getElementById('btn-ha-visual');
  const btnCode = document.getElementById('btn-ha-code');
  const panelVisual = document.getElementById('ha-visual-panel');
  const panelCode = document.getElementById('ha-code-panel');
  
  if (mode === 'visual') {
    btnVisual.classList.add('active');
    btnCode.classList.remove('active');
    panelVisual.style.display = 'block';
    panelCode.style.display = 'none';
  } else {
    btnVisual.classList.remove('active');
    btnCode.classList.add('active');
    panelVisual.style.display = 'none';
    panelCode.style.display = 'block';
  }
}

function _getSections(data) {
  if (!data) return [];
  if (data.sections && Array.isArray(data.sections)) return data.sections;
  if (data.content) {
    if (Array.isArray(data.content)) return data.content;
    if (data.content.sections && Array.isArray(data.content.sections)) return data.content.sections;
  }
  return [];
}

// ── Render content sections ──
function renderContent(data) {
  const container = document.getElementById('content-sections');
  const contentSections = _getSections(data);
  if (!contentSections.length && data.text) {
    container.innerHTML = `<div class="content-section"><div>${escapeHtml(data.text)}</div></div>`;
    return;
  }
  let html = '';
  contentSections.forEach((sec, i) => {
    html += `<div class="content-section" id="section-${i}">`;
    if (sec.heading || sec.title) {
      html += `<h2>${escapeHtml(sec.heading || sec.title)}</h2>`;
    }
    if (sec.content || sec.text || sec.body) {
      const text = sec.content || sec.text || sec.body;
      if (typeof text === 'string') {
        html += renderTextContent(text);
      } else if (Array.isArray(text)) {
        text.forEach(item => {
          if (typeof item === 'string') html += `<p>${escapeHtml(item)}</p>`;
          else if (item.type === 'image' || item.src) html += renderImage(item);
          else if (item.type === 'table') html += renderTable(item);
          else if (item.type === 'list') html += renderList(item);
          else if (item.type === 'code') html += `<pre><code>${escapeHtml(item.code || item.content || '')}</code></pre>`;
          else if (item.type === 'heading') html += `<h3>${escapeHtml(item.text || item.content || '')}</h3>`;
          else if (item.type === 'blockquote') html += `<blockquote>${escapeHtml(item.text || item.content || '')}</blockquote>`;
          else if (item.text || item.content) html += `<p>${escapeHtml(item.text || item.content)}</p>`;
        });
      }
    }
    if (sec.images && Array.isArray(sec.images)) {
      sec.images.forEach(img => { html += renderImage(img); });
    }
    if (sec.subsections && Array.isArray(sec.subsections)) {
      sec.subsections.forEach(sub => {
        if (sub.heading || sub.title) html += `<h3>${escapeHtml(sub.heading || sub.title)}</h3>`;
        if (sub.content || sub.text) html += renderTextContent(sub.content || sub.text);
      });
    }
    html += `</div>`;
  });
  container.innerHTML = html || '<div class="empty-state"><div class="icon">📭</div><h2>No content sections found</h2></div>';

  // Click handler for images
  container.querySelectorAll('img').forEach(img => {
    img.addEventListener('click', () => openLightbox(img.src));
  });
}

function renderTextContent(text) {
  if (typeof text !== 'string') return '';
  // Simple markdown-like rendering
  return text.split('\n').map(line => {
    line = line.trim();
    if (!line) return '';
    if (line.startsWith('### ')) return `<h3>${escapeHtml(line.slice(4))}</h3>`;
    if (line.startsWith('## ')) return `<h3>${escapeHtml(line.slice(3))}</h3>`;
    if (line.startsWith('# ')) return `<h2>${escapeHtml(line.slice(2))}</h2>`;
    if (line.startsWith('- ') || line.startsWith('* ')) return `<li>${escapeHtml(line.slice(2))}</li>`;
    if (line.startsWith('> ')) return `<blockquote>${escapeHtml(line.slice(2))}</blockquote>`;
    if (line.startsWith('```')) return '';
    return `<p>${escapeHtml(line)}</p>`;
  }).join('');
}

function renderImage(img) {
  let src = img.local_path || img.src || img.url || img;
  if (typeof src === 'string' && !src.startsWith('http') && !src.startsWith('data:')) {
    src = `/__asset/${SNAP_ID}/${src}`;
  }
  const alt = img.alt || img.caption || '';
  return `<img src="${escapeHtml(src)}" alt="${escapeHtml(alt)}" loading="lazy" title="${escapeHtml(alt)}">`;
}

function renderTable(tbl) {
  if (!tbl.rows || !tbl.rows.length) return '';
  let h = '<table>';
  if (tbl.headers) {
    h += '<tr>' + tbl.headers.map(th => `<th>${escapeHtml(th)}</th>`).join('') + '</tr>';
  }
  tbl.rows.forEach(row => {
    const cells = Array.isArray(row) ? row : Object.values(row);
    h += '<tr>' + cells.map(c => `<td>${escapeHtml(String(c))}</td>`).join('') + '</tr>';
  });
  return h + '</table>';
}

function renderList(list) {
  const items = list.items || list.content || [];
  const tag = list.ordered ? 'ol' : 'ul';
  return `<${tag}>${items.map(i => `<li>${escapeHtml(typeof i === 'string' ? i : i.text || '')}</li>`).join('')}</${tag}>`;
}

// ── TOC ──
function renderTOC(data) {
  const toc = document.getElementById('toc-list');
  const sections = _getSections(data);
  if (!sections.length) { toc.innerHTML = '<li class="toc-item" style="color:var(--text3)">No sections</li>'; return; }
  toc.innerHTML = sections.map((sec, i) => {
    const title = sec.heading || sec.title || `Section ${i+1}`;
    let items = `<li class="toc-item" onclick="scrollToSection(${i})">${escapeHtml(title)}</li>`;
    if (sec.subsections) {
      sec.subsections.forEach(sub => {
        if (sub.heading || sub.title) items += `<li class="toc-item h3">${escapeHtml(sub.heading || sub.title)}</li>`;
      });
    }
    return items;
  }).join('');
}

function renderBanner(data) {
  const banner = data.banner || data.og_image || data.featured_image;
  if (banner) {
    let src = banner;
    if (typeof src === 'string' && !src.startsWith('http') && !src.startsWith('data:')) {
      src = `/__asset/${SNAP_ID}/${src}`;
    }
    document.getElementById('banner-img').src = src;
    document.getElementById('banner-wrap').style.display = '';
  }
}

function scrollToSection(i) {
  const el = document.getElementById('section-' + i);
  if (el) { el.scrollIntoView({behavior:'smooth', block:'start'}); }
  // Update active TOC item
  document.querySelectorAll('.toc-item').forEach((t, idx) => {
    t.classList.toggle('active', idx === i);
  });
}

// ── Markdown ──
async function loadMarkdown() {
  try {
    const res = await fetch(`/__archive__/api/content/${SNAP_ID}`);
    if (res.ok) {
      markdownContent = await res.text();
      if (typeof marked !== 'undefined') {
        marked.setOptions({ breaks: true, gfm: true });
        document.getElementById('md-rendered').innerHTML = marked.parse(markdownContent);
      } else {
        document.getElementById('md-rendered').innerHTML = `<pre>${escapeHtml(markdownContent)}</pre>`;
      }
    } else {
      document.getElementById('md-rendered').innerHTML = '<div class="empty-state"><div class="icon">📝</div><h2>No markdown content</h2><p>Extract the snapshot first to generate markdown.</p></div>';
    }
  } catch(e) {
    document.getElementById('md-rendered').innerHTML = `<p style="color:var(--red)">Error: ${e.message}</p>`;
  }
}

async function loadStructureMarkdown() {
  try {
    const res = await fetch(`/__archive__/api/structure/${SNAP_ID}`);
    if (res.ok) {
      structureMarkdownContent = await res.text();
      if (typeof marked !== 'undefined') {
        marked.setOptions({ breaks: true, gfm: true });
        document.getElementById('structure-rendered').innerHTML = marked.parse(structureMarkdownContent);
      } else {
        document.getElementById('structure-rendered').innerHTML = `<pre>${escapeHtml(structureMarkdownContent)}</pre>`;
      }
    } else {
      document.getElementById('structure-rendered').innerHTML = '<div class="empty-state"><div class="icon">🏗️</div><h2>No structure markdown</h2><p>Extract the snapshot first to generate structure markdown.</p></div>';
    }
  } catch(e) {
    document.getElementById('structure-rendered').innerHTML = `<p style="color:var(--red)">Error: ${e.message}</p>`;
  }
}

// ── Assets ──
async function loadAssets() {
  try {
    const res = await fetch(`/__archive__/api/assets/${SNAP_ID}`);
    if (!res.ok) return;
    const assets = await res.json();
    renderAssetsGrid(assets);
    renderAssetsSidebar(assets);
  } catch(e) { console.error('Failed to load assets', e); }
}

function renderAssetsGrid(assets) {
  const grid = document.getElementById('assets-grid');
  if (!assets.length) {
    grid.innerHTML = '<div class="empty-state"><div class="icon">📁</div><h2>No assets found</h2></div>';
    return;
  }
  const imageExts = ['jpg','jpeg','png','gif','webp','svg','ico','bmp','avif'];
  grid.innerHTML = assets.map(a => {
    const ext = (a.name || '').split('.').pop().toLowerCase();
    const isImg = imageExts.includes(ext) || (a.type && a.type.startsWith('image'));
    const src = `/__asset/${SNAP_ID}/${a.path || a.name}`;
    const sizeStr = a.size ? formatSize(a.size) : '';
    return `
      <div class="asset-card" onclick="${isImg ? `openLightbox('${src}')` : ''}">
        <div class="asset-preview">
          ${isImg ? `<img src="${src}" alt="${escapeHtml(a.name)}" loading="lazy">` : `<div class="icon-preview">${getFileIcon(ext)}</div>`}
        </div>
        <div class="asset-info">
          <div class="asset-name" title="${escapeHtml(a.path || a.name)}">${escapeHtml(a.name)}</div>
          <div class="asset-detail"><span>${ext.toUpperCase()}</span><span>${sizeStr}</span></div>
        </div>
      </div>`;
  }).join('');
}

function renderAssetsSidebar(assets) {
  if (!assets.length) return;
  document.getElementById('sidebar-assets').style.display = '';
  document.getElementById('asset-count').textContent = `(${assets.length})`;
  const mini = document.getElementById('asset-list-mini');
  const imageExts = ['jpg','jpeg','png','gif','webp','svg','ico'];
  mini.innerHTML = assets.slice(0, 20).map(a => {
    const ext = (a.name || '').split('.').pop().toLowerCase();
    const color = imageExts.includes(ext) ? 'var(--green)' : ext === 'js' ? 'var(--amber)' : ext === 'css' ? 'var(--blue)' : 'var(--text3)';
    return `<div class="asset-mini"><span class="dot" style="background:${color}"></span><span class="name">${escapeHtml(a.name)}</span><span class="size">${a.size ? formatSize(a.size) : ''}</span></div>`;
  }).join('');
  if (assets.length > 20) mini.innerHTML += `<div class="asset-mini" style="color:var(--text3);justify-content:center">+${assets.length - 20} more</div>`;
}

// ── Flow ──
async function loadFlow() {
  try {
    const res = await fetch(`/__archive__/api/flow/${SNAP_ID}`);
    if (!res.ok) return;
    const flow = await res.json();
    renderFlow(flow);
  } catch(e) { console.error('Failed to load flow', e); }
}

function renderFlow(flow) {
  const entries = flow.navigations || flow.entries || flow || [];
  if (!Array.isArray(entries) || !entries.length) {
    document.getElementById('flow-diagram').innerHTML = '<div class="empty-state"><div class="icon">🔀</div><h2>No flow data</h2></div>';
    return;
  }

  // Build mermaid diagram
  let mmd = 'graph LR\n';
  const nodes = [];
  entries.forEach((e, i) => {
    const label = (e.url || e.path || '').replace(/https?:\/\//, '').slice(0, 40);
    const type = e.type || (e.method ? 'api' : 'nav');
    const cls = type === 'api' ? ':::api' : ':::nav';
    nodes.push(`  N${i}["${label.replace(/"/g, '#quot;')}"]${cls}`);
    if (i > 0) mmd += `  N${i-1} --> N${i}\n`;
  });
  mmd += nodes.join('\n') + '\n';
  mmd += '  classDef nav fill:#0c4a6e,stroke:#0ea5e9,color:#e0f2fe\n';
  mmd += '  classDef api fill:#064e3b,stroke:#10b981,color:#d1fae5\n';

  const diagramEl = document.getElementById('flow-diagram');
  diagramEl.innerHTML = `<div class="mermaid">${mmd}</div>`;
  try { mermaid.run({ nodes: diagramEl.querySelectorAll('.mermaid') }); } catch(e) { console.warn('Mermaid render failed', e); }

  // Timeline
  const timeline = document.getElementById('flow-timeline');
  timeline.innerHTML = '<h3 style="font-family:Outfit;font-weight:700;margin:20px 0 12px;color:var(--text2)">📊 Timeline</h3>' +
    entries.map(e => {
      const type = e.type || (e.method ? 'api' : 'nav');
      const url = e.url || e.path || '';
      const status = e.status || e.statusCode || '';
      const method = e.method || '';
      return `
        <div class="flow-entry ${type}">
          <span class="flow-type ${type}">${method ? method + ' ' : ''}${type.toUpperCase()}</span>
          <span class="flow-url">${escapeHtml(url)}</span>
          ${status ? `<span class="flow-status">${status}</span>` : ''}
        </div>`;
    }).join('');
}

// ── Extract ──
async function triggerExtract(btn) {
  btn.classList.add('loading');
  btn.innerHTML = '⏳ Extracting...';
  try {
    const res = await fetch(`/__archive__/api/extract/${SNAP_ID}`, {method:'POST'});
    const data = await res.json();
    if (res.ok) {
      toast('✅ Extraction complete!', 'success');
      location.reload();
    } else {
      toast('❌ ' + (data.error || 'Failed'), 'error');
      btn.classList.remove('loading');
      btn.innerHTML = '🔄 Extract Now';
    }
  } catch(e) {
    toast('❌ ' + e.message, 'error');
    btn.classList.remove('loading');
    btn.innerHTML = '🔄 Extract Now';
  }
}

// ── Search ──
function filterContent(q) {
  const sections = document.querySelectorAll('.content-section');
  if (!q.trim()) { sections.forEach(s => s.style.display = ''); return; }
  const ql = q.toLowerCase();
  sections.forEach(s => {
    s.style.display = s.textContent.toLowerCase().includes(ql) ? '' : 'none';
  });
}

// ── Downloads ──
function downloadJSON() {
  if (!extractedData) { toast('No data to download', 'error'); return; }
  downloadBlob(JSON.stringify(extractedData, null, 2), `${SNAP_ID}_extracted.json`, 'application/json');
}
function downloadMD() {
  if (!markdownContent) { toast('No markdown to download', 'error'); return; }
  downloadBlob(markdownContent, `${SNAP_ID}_content.md`, 'text/markdown');
}
function copyMarkdown() {
  if (!markdownContent) { toast('No markdown to copy', 'error'); return; }
  navigator.clipboard.writeText(markdownContent).then(() => toast('📋 Copied to clipboard!', 'success'));
}
function downloadStructureMD() {
  if (!structureMarkdownContent) { toast('No structure markdown to download', 'error'); return; }
  downloadBlob(structureMarkdownContent, `${SNAP_ID}_structure.md`, 'text/markdown');
}
function copyStructureMarkdown() {
  if (!structureMarkdownContent) { toast('No structure markdown to copy', 'error'); return; }
  navigator.clipboard.writeText(structureMarkdownContent).then(() => toast('📋 Copied to clipboard!', 'success'));
}
function downloadBlob(content, name, type) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([content], {type}));
  a.download = name; a.click(); URL.revokeObjectURL(a.href);
}

// ── Lightbox ──
function openLightbox(src) {
  document.getElementById('lightbox-img').src = src;
  document.getElementById('lightbox').classList.add('open');
  document.body.style.overflow = 'hidden';
}
function closeLightbox() {
  document.getElementById('lightbox').classList.remove('open');
  document.body.style.overflow = '';
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeLightbox(); });

// ── Utilities ──
function escapeHtml(s) {
  if (typeof s !== 'string') return '';
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes/1024).toFixed(1) + ' KB';
  return (bytes/1048576).toFixed(1) + ' MB';
}
function getFileIcon(ext) {
  const icons = {js:'📜',css:'🎨',html:'🌐',json:'📋',svg:'🎯',woff:'🔤',woff2:'🔤',ttf:'🔤',eot:'🔤',mp4:'🎬',webm:'🎬',mp3:'🎵',pdf:'📄',zip:'📦'};
  return icons[ext] || '📄';
}
function toast(msg, type='info') {
  const box = document.getElementById('toast-box');
  const el = document.createElement('div');
  el.className = 'toast-msg ' + type;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}
</script>
</body>
</html>
"""

def _load_sw_js() -> str:
    """Load sw.js from the root directory."""
    sw_path = Path(__file__).parent.parent / "sw.js"
    if sw_path.exists():
        return sw_path.read_text(encoding="utf-8")
    return "\nself.addEventListener('install', () => self.skipWaiting());\nself.addEventListener('activate', () => self.clients.claim());\n"

SW_JS = _load_sw_js()


class WaybackServer:
    """
    Replay server kiểu Wayback Machine.
    Routes:
      /__archive__          → Dashboard (fast – data loaded via AJAX)
      /__archive__/api/*    → JSON API cho dashboard
      /__wb/<encoded_url>   → Serve snapshot của URL đó
      /__mhtml/<snap_id>    → Serve MHTML snapshot for a recording
      /__view/<snap_id>     → Structured replay UI for a snapshot
      /__asset/<snap_id>/*  → Serve files from snapshot directory

    PERF improvements:
      - ThreadingMixIn: handles concurrent requests (no more blocking)
      - Routes cached in ArchiveIndex: no per-request manifest scanning
    """

    def __init__(self, archive_dir: str = DEFAULT_ARCHIVE, port: int = 8080):
        self.archive = ArchiveIndex(archive_dir)
        self.port = port

    def start(self):
        archive = self.archive
        port = self.port

        class Handler(http.server.BaseHTTPRequestHandler):
            def address_string(self):
                # Avoid slow DNS reverse lookups on every request
                return self.client_address[0]

            def do_POST(self):
                path = self.path
                # ── Extract API (POST only) ────────────────────────
                if path.startswith("/__archive__/api/extract/"):
                    snap_id = path[len("/__archive__/api/extract/"):].split("?")[0]
                    self._api_extract(snap_id)
                    return
                self._handle_with_body()

            def do_PUT(self):
                self._handle_with_body()

            def do_DELETE(self):
                self._handle_with_body()

            def do_PATCH(self):
                self._handle_with_body()

            def _handle_with_body(self):
                # Consume request body if content length is present
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length > 0:
                    try:
                        self.rfile.read(content_length)
                    except Exception:
                        pass
                self.do_GET()

            def do_GET(self):
                path = self.path

                # ── Dashboard ──────────────────────────────────────────
                if path in ("/__archive__", "/__archive__/"):
                    self._dashboard()

                # ── JSON API ───────────────────────────────────────────
                elif path.startswith("/__archive__/api/"):
                    self._api(path[len("/__archive__/api/"):])

                # ── MHTML Snapshot ────────────────────────────────────
                elif path.startswith("/__mhtml/"):
                    snap_id = path[9:].split("?")[0]
                    self._serve_mhtml(snap_id)

                # ── Wayback style: /__wb/<encoded_url> ────────────────
                elif path.startswith("/__wb/"):
                    encoded = path[6:].split("?")[0]
                    try:
                        url = urllib.parse.unquote(encoded)
                        # Strip query params from the decoded URL for tracking
                        base_url = url.split("?")[0]
                    except Exception:
                        self._404(path)
                        return
                    # Anti-Loop Mechanism: Detects A->B->A or self-reload loops
                    import time
                    if not hasattr(self.server, 'nav_history'):
                        self.server.nav_history = {}
                        
                    # Use the base URL for tracking to catch query-param loops
                    client_ip = self.client_address[0]
                    history_key = f"{client_ip}_{base_url}"
                    now = time.time()
                    
                    history = self.server.nav_history.get(history_key, [])
                    history = [t for t in history if now - t < 5]
                    history.append(now)
                    self.server.nav_history[history_key] = history
                    
                    # If more than 4 requests in 5 seconds to the EXACT same base URL, it's a runaway loop
                    if len(history) > 4:
                        log("WARN", f"Blocked infinite redirect/reload loop for {client_ip} at {url}")
                        self._send(204, "text/plain", b"")
                        return

                    self._serve_url(url)

                # ── Structured View ────────────────────────────────
                elif path.startswith("/__view/"):
                    snap_id = path[8:].split("?")[0]
                    self._view_snapshot(snap_id)

                # ── Asset Serving ─────────────────────────────────────
                elif path.startswith("/__asset/"):
                    rest = path[9:]
                    parts = rest.split("/", 1)
                    if len(parts) == 2:
                        self._serve_asset(parts[0], parts[1])
                    else:
                        self._404(path)

                # ── Root → redirect to dashboard ──────────────────────
                elif path in ("/", ""):
                    self.send_response(302)
                    self.send_header("Location", "/__archive__")
                    self.end_headers()

                # ── Service Worker ────────────────────────────────────
                elif path == "/sw.js":
                    self._serve_sw()

                else:
                    # Referer-based fallback routing (leak correction)
                    referer = self.headers.get("Referer")
                    if referer and "/__wb/" in referer:
                        try:
                            idx = referer.find("/__wb/")
                            ref_encoded = referer[idx + 6:].split("?")[0]
                            ref_url = urllib.parse.unquote(ref_encoded)
                            
                            # Resolve requested path relative to the referer URL's origin
                            parsed_ref = urllib.parse.urlparse(ref_url)
                            ref_origin = f"{parsed_ref.scheme}://{parsed_ref.netloc}"

                            # BUG FIX: Handle both absolute paths (/css/style.css) 
                            # and relative paths (../img/logo.png) correctly
                            if path.startswith("/"):
                                resolved_url = urllib.parse.urljoin(ref_origin, path)
                            else:
                                resolved_url = urllib.parse.urljoin(ref_url, path)
                            
                            self._serve_url(resolved_url)
                            return
                        except Exception as e:
                            log("WARN", f"Failed Referer-routing: {path} (Referer: {referer}) -> {e}")
                    
                    self._404(path)

            # ── Helpers ───────────────────────────────────────────────
            def _dashboard(self):
                # PERF: Serve static HTML immediately — no data embedding
                body = DASHBOARD_HTML.encode("utf-8")
                self._send(200, "text/html; charset=utf-8", body,
                           extra_headers={"Cache-Control": "no-cache"})

            def _serve_sw(self):
                body = _load_sw_js().encode("utf-8")
                self._send(200, "application/javascript; charset=utf-8", body,
                           extra_headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


            def _find_snap(self, snap_id: str):
                """Find a snapshot by ID and return (snap_dict, snap_path) or (None, None)."""
                for snap in archive.data["snapshots"]:
                    if snap["id"] == snap_id:
                        return snap, archive.root / snap["path"]
                return None, None

            def _api(self, sub: str):
                if sub == "snapshots":
                    # PERF: Serve from in-memory index, no disk reads
                    snaps_raw = sorted(
                        archive.data["snapshots"],
                        key=lambda x: x.get("recorded_at", ""),
                        reverse=True,
                    )
                    # Augment each snapshot with has_extracted status
                    snaps = []
                    for s in snaps_raw:
                        snap_copy = dict(s)
                        snap_path = archive.root / s["path"]
                        snap_copy["has_extracted"] = (snap_path / "extracted_data.json").exists()
                        snaps.append(snap_copy)
                    body = json.dumps(snaps).encode()
                    self._send(200, "application/json", body,
                               extra_headers={"Cache-Control": "no-store"})

                elif sub.startswith("search?"):
                    q = urllib.parse.parse_qs(sub[7:]).get("q", [""])[0]
                    body = json.dumps(archive.search(q)).encode()
                    self._send(200, "application/json", body)

                # ── Extracted data API ─────────────────────────────────
                elif sub.startswith("extracted/"):
                    snap_id = sub[len("extracted/"):].split("?")[0]
                    snap, snap_path = self._find_snap(snap_id)
                    if not snap:
                        self._send(404, "application/json", json.dumps({"error": "Snapshot not found"}).encode())
                        return
                    extracted_file = snap_path / "extracted_data.json"
                    if not extracted_file.exists():
                        self._send(404, "application/json", json.dumps({"error": "No extracted data"}).encode())
                        return
                    body = extracted_file.read_bytes()
                    self._send(200, "application/json; charset=utf-8", body)

                # ── Content markdown API ───────────────────────────────
                elif sub.startswith("content/"):
                    snap_id = sub[len("content/"):].split("?")[0]
                    snap, snap_path = self._find_snap(snap_id)
                    if not snap:
                        self._send(404, "text/plain", b"Snapshot not found")
                        return
                    md_file = snap_path / "content.md"
                    if not md_file.exists():
                        self._send(404, "text/plain", b"No markdown content")
                        return
                    body = md_file.read_bytes()
                    self._send(200, "text/markdown; charset=utf-8", body)

                # ── Structure markdown API ─────────────────────────────
                elif sub.startswith("structure/"):
                    snap_id = sub[len("structure/"):].split("?")[0]
                    snap, snap_path = self._find_snap(snap_id)
                    if not snap:
                        self._send(404, "text/plain", b"Snapshot not found")
                        return
                    md_file = snap_path / "structure.md"
                    if not md_file.exists():
                        self._send(404, "text/plain", b"No structure markdown")
                        return
                    body = md_file.read_bytes()
                    self._send(200, "text/markdown; charset=utf-8", body)

                # ── Assets list API ────────────────────────────────────
                elif sub.startswith("assets/"):
                    snap_id = sub[len("assets/"):].split("?")[0]
                    snap, snap_path = self._find_snap(snap_id)
                    if not snap:
                        self._send(404, "application/json", json.dumps({"error": "Snapshot not found"}).encode())
                        return
                    assets_dir = snap_path / "assets"
                    assets = []
                    if assets_dir.exists():
                        for f in assets_dir.rglob("*"):
                            if f.is_file():
                                rel = f.relative_to(snap_path)
                                ct, _ = mimetypes.guess_type(str(f))
                                assets.append({
                                    "name": f.name,
                                    "path": str(rel).replace("\\", "/"),
                                    "size": f.stat().st_size,
                                    "type": ct or "application/octet-stream",
                                })
                    body = json.dumps(assets).encode()
                    self._send(200, "application/json", body)

                # ── Flow/navigation data API ──────────────────────────
                elif sub.startswith("flow/"):
                    snap_id = sub[len("flow/"):].split("?")[0]
                    snap, snap_path = self._find_snap(snap_id)
                    if not snap:
                        self._send(404, "application/json", json.dumps({"error": "Snapshot not found"}).encode())
                        return
                    # Try flow.json first, fall back to building from manifest
                    flow_data = {"navigations": [], "api_calls": []}
                    flow_file = snap_path / "flow.json"
                    if flow_file.exists():
                        try:
                            flow_data = json.loads(flow_file.read_text(encoding="utf-8"))
                        except Exception:
                            pass
                    else:
                        # Build flow from manifest and api_responses
                        manifest_file = snap_path / "manifest.json"
                        if manifest_file.exists():
                            try:
                                mf = json.loads(manifest_file.read_text(encoding="utf-8"))
                                # Add navigation entry
                                flow_data["navigations"].append({
                                    "type": "nav",
                                    "url": snap.get("url", ""),
                                    "status": 200,
                                })
                                # Add API calls from manifest
                                for api in mf.get("api_responses", []):
                                    flow_data["navigations"].append({
                                        "type": "api",
                                        "url": api.get("url", ""),
                                        "method": api.get("method", "GET"),
                                        "status": api.get("response", {}).get("status", 200),
                                    })
                            except Exception:
                                pass
                    body = json.dumps(flow_data).encode()
                    self._send(200, "application/json", body)

                # ── Extract trigger (also handled via do_POST) ────────
                elif sub.startswith("extract/"):
                    snap_id = sub[len("extract/"):].split("?")[0]
                    self._api_extract(snap_id)

                else:
                    self._404(sub)

            def _api_extract(self, snap_id: str):
                """Trigger content extraction for a snapshot."""
                snap, snap_path = self._find_snap(snap_id)
                if not snap:
                    self._send(404, "application/json",
                               json.dumps({"error": "Snapshot not found"}).encode())
                    return
                try:
                    from src.extractor import ContentExtractor
                    extractor = ContentExtractor(snap_path)
                    data = extractor.extract()
                    self._send(200, "application/json",
                               json.dumps({"status": "ok", "snap_id": snap_id, "sections": len(data.get("content", {}).get("sections", []))}).encode())
                except Exception as e:
                    log("ERR", f"Extraction failed for {snap_id}: {e}")
                    self._send(500, "application/json",
                               json.dumps({"error": str(e)}).encode())

            def _view_snapshot(self, snap_id: str):
                """Serve the structured view UI for a snapshot."""
                snap, snap_path = self._find_snap(snap_id)
                if not snap:
                    self._archive_not_found(f"Snapshot {snap_id}")
                    return
                html = VIEW_HTML.replace("{{SNAP_ID}}", snap_id)
                body = html.encode("utf-8")
                self._send(200, "text/html; charset=utf-8", body,
                           extra_headers={"Cache-Control": "no-cache"})

            def _serve_asset(self, snap_id: str, asset_path: str):
                """Serve a file from a snapshot's directory."""
                snap, snap_path = self._find_snap(snap_id)
                if not snap:
                    self._404(f"/__asset/{snap_id}/{asset_path}")
                    return
                # Decode percent-encoded path
                asset_path = urllib.parse.unquote(asset_path)
                filepath = snap_path / asset_path
                # Security: prevent directory traversal
                try:
                    filepath = filepath.resolve()
                    snap_resolved = snap_path.resolve()
                    if not str(filepath).startswith(str(snap_resolved)):
                        self._404(f"/__asset/{snap_id}/{asset_path}")
                        return
                except Exception:
                    self._404(f"/__asset/{snap_id}/{asset_path}")
                    return
                if not filepath.exists() or not filepath.is_file():
                    self._404(f"/__asset/{snap_id}/{asset_path}")
                    return
                ct, _ = mimetypes.guess_type(str(filepath))
                ct = ct or "application/octet-stream"
                body = filepath.read_bytes()
                self._send(200, ct, body, extra_headers={
                    "Cache-Control": "public, max-age=3600",
                })

            def _serve_mhtml(self, snap_id: str):
                """Serve the MHTML snapshot as a downloadable/viewable file."""
                for snap in archive.data["snapshots"]:
                    if snap["id"] == snap_id:
                        mhtml_path = archive.root / snap["path"] / "snapshot.mhtml"
                        if mhtml_path.exists():
                            body = mhtml_path.read_bytes()
                            self._send(200, "multipart/related; type=\"text/html\"", body, extra_headers={
                                "Content-Disposition": f"inline; filename=\"{snap_id}.mhtml\"",
                            })
                            return
                self._archive_not_found(f"MHTML for {snap_id}")

            def _serve_url(self, url: str):
                # PERF: Uses cached routes dict — no manifest re-parsing
                all_routes = archive.get_all_routes()

                # BUG FIX: Build a normalized URL index for fuzzy matching
                # This handles cases where the HTML references //cdn.example.com/style.css
                # but we recorded https://cdn.example.com/style.css
                url_variants = [url]
                parsed = urllib.parse.urlparse(url)
                
                # Also try without query string
                no_query = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
                if no_query != url:
                    url_variants.append(no_query)

                # Also try with trailing slash removed/added
                if parsed.path.endswith("/"):
                    url_variants.append(urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", "")))
                else:
                    url_variants.append(urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path + "/", "", "", "")))

                # 1. Try all URL variants for exact match
                rel_path = None
                matched_url = url
                for variant in url_variants:
                    if variant in all_routes:
                        rel_path = all_routes[variant]
                        matched_url = variant
                        break

                # 2. Path+netloc match (ignore query string & scheme differences)
                if not rel_path:
                    req_parsed = urllib.parse.urlparse(url)
                    for orig, rp in all_routes.items():
                        op = urllib.parse.urlparse(orig)
                        if op.path == req_parsed.path and op.netloc == req_parsed.netloc:
                            rel_path = rp
                            matched_url = orig
                            break

                # 3. Match recorded API response
                if not rel_path:
                    api_responses = archive.get_all_api_responses()
                    api_match = None
                    req_method = self.command.upper()
                    
                    req_body_str = ""
                    if req_method in ("POST", "PUT") and self.headers.get("Content-Length"):
                        try:
                            length = int(self.headers["Content-Length"])
                            req_body_str = self.rfile.read(length).decode("utf-8", errors="ignore")
                        except Exception:
                            pass
                    
                    for entry in api_responses:
                        if entry.get("url") == url and entry.get("method", "GET").upper() == req_method:
                            # If it's a POST, try to match a substring of the body (e.g. GraphQL operation)
                            rec_body = entry.get("request", {}).get("body", "")
                            if req_method == "POST" and rec_body and req_body_str:
                                # For GraphQL, check if the operation name matches
                                op_match = re.search(r'"operationName"\s*:\s*"([^"]+)"', req_body_str)
                                rec_op_match = re.search(r'"operationName"\s*:\s*"([^"]+)"', rec_body)
                                if op_match and rec_op_match:
                                    if op_match.group(1) == rec_op_match.group(1):
                                        api_match = entry
                                        break
                                else:
                                    # Fallback to simple substring or exact match if no operationName
                                    if req_body_str[:100] in rec_body or rec_body[:100] in req_body_str:
                                        api_match = entry
                                        break
                            else:
                                api_match = entry
                                break
                    
                    if not api_match:
                        # Path-only match for API
                        req_parsed = urllib.parse.urlparse(url)
                        for entry in api_responses:
                            entry_parsed = urllib.parse.urlparse(entry.get("url", ""))
                            if (entry_parsed.path == req_parsed.path and 
                                entry_parsed.netloc == req_parsed.netloc and
                                entry.get("method", "GET").upper() == req_method):
                                
                                rec_body = entry.get("request", {}).get("body", "")
                                if req_method == "POST" and rec_body and req_body_str:
                                    op_match = re.search(r'"operationName"\s*:\s*"([^"]+)"', req_body_str)
                                    rec_op_match = re.search(r'"operationName"\s*:\s*"([^"]+)"', rec_body)
                                    if op_match and rec_op_match and op_match.group(1) == rec_op_match.group(1):
                                        api_match = entry
                                        break
                                    elif not op_match and not rec_op_match:
                                        api_match = entry
                                        break
                                else:
                                    api_match = entry
                                    break
                                
                    if api_match:
                        resp = api_match.get("response", {})
                        status = resp.get("status", 200)
                        headers = resp.get("headers", {})
                        body_str = resp.get("body", "")
                        
                        # Case-insensitive headers lookup for content-type
                        ct = "application/json; charset=utf-8"
                        for k, v in headers.items():
                            if k.lower() == "content-type":
                                ct = v
                                break
                        
                        body = body_str.encode("utf-8", errors="replace")
                        if "html" in ct.lower():
                            try:
                                t_script = _get_tokens_script(url)
                                # Rewrite HTML content in API response (e.g. swap lazy loaded images)
                                body_str = rewrite_html(body_str, all_routes, url, tokens_script=t_script, is_final_page=False)
                                body = body_str.encode("utf-8", errors="replace")
                            except Exception as e:
                                log("WARN", f"Failed rewriting API HTML: {e}")
                                
                        self._send(status, ct, body, extra_headers={
                            "X-WR-Source": f"api_responses/{api_match['id']}.json",
                            "X-WR-OrigURL": url,
                        })
                        return

                    # 3b. Unrecorded API call: return graceful empty JSON instead of 404
                    # This prevents Vue/Nuxt/React apps from crashing when dynamic API
                    # endpoints were not captured during recording.
                    req_parsed = urllib.parse.urlparse(url)
                    _API_PATTERNS = ("/api/", "/graphql", "/rest/", "/v1/", "/v2/", "/v3/",
                                     "/qimaoapi/", "/ajax/", "/action/", "/service/")
                    accept_hdr = self.headers.get("Accept", "")
                    is_api_req = (
                        any(p in req_parsed.path for p in _API_PATTERNS) or
                        "application/json" in accept_hdr
                    )
                    if is_api_req:
                        if "/graphql" in req_parsed.path:
                            stub = b'{"data": {}}'
                        else:
                            stub = json.dumps({"code": 0, "data": None, "msg": "", "result": None,
                                            "__wr_stub": True}).encode()
                        self._send(200, "application/json; charset=utf-8", stub, extra_headers={
                            "X-WR-Source": "stub",
                            "X-WR-OrigURL": url,
                        })
                        return

                def _get_tokens_script(req_url: str) -> str:
                    try:
                        parsed = urllib.parse.urlparse(req_url)
                        domain = parsed.netloc.replace(":", "_")
                        domain_aliases = {domain}
                        if domain.startswith("www."):
                            domain_aliases.add(domain[4:])
                        else:
                            domain_aliases.add("www." + domain)
                        
                        snap_path = None
                        for s in archive.data["snapshots"]:
                            if s["domain"] in domain_aliases:
                                snap_path = archive.root / s["path"]
                                break
                        
                        if not snap_path:
                            return ""
                            
                        cookies = []
                        cookies_path = snap_path / "tokens" / "cookies.json"
                        if cookies_path.exists():
                            try: cookies = json.loads(cookies_path.read_text(encoding="utf-8"))
                            except Exception: pass
                            
                        ls_tokens = []
                        mf_path = snap_path / "manifest.json"
                        if mf_path.exists():
                            try:
                                mf = json.loads(mf_path.read_text(encoding="utf-8"))
                                ls_tokens = mf.get("tokens", {}).get("localStorage", [])
                            except Exception: pass
                            
                        if not cookies and not ls_tokens:
                            return ""
                            
                        js = ["<script>(function(){try{"]
                        for c in cookies:
                            c_name = c.get('name', '').replace("'", "\\'")
                            c_val = c.get('value', '').replace("'", "\\'")
                            c_domain = c.get('domain', '').replace("'", "\\'")
                            js.append(f"document.cookie='{c_name}={c_val}; domain={c_domain}; path=/';")
                        for t in ls_tokens:
                            v = t.get('value', '')
                            if '=' in v:
                                key, val = v.split('=', 1)
                                key = key.replace("'", "\\'").replace("\\", "\\\\").replace("\n", "\\n")
                                val = val.replace("'", "\\'").replace("\\", "\\\\").replace("\n", "\\n")
                                js.append(f"localStorage.setItem('{key}', '{val}');")
                        js.append("}catch(e){}})();</script>")
                        return "".join(js)
                    except Exception as e:
                        log("WARN", f"Failed to load tokens for {req_url}: {e}")
                        return ""

                # 4. Fallback: serve final_page.html for matching domain
                # Also handles www. prefix alias (e.g., recorded under qimao.com but
                # requested as www.qimao.com after a redirect)
                if not rel_path:
                    req_parsed = urllib.parse.urlparse(url)
                    netloc = req_parsed.netloc
                    domain = netloc.replace(":", "_")
                    # Build a set of domain aliases to try
                    domain_aliases = {domain}
                    if domain.startswith("www."):
                        domain_aliases.add(domain[4:])  # www.example.com → example.com
                    else:
                        domain_aliases.add("www." + domain)  # example.com → www.example.com

                    for snap in archive.data["snapshots"]:
                        if snap["domain"] in domain_aliases:
                            candidate = archive.root / snap["path"] / "final_page.html"
                            if candidate.exists():
                                html = candidate.read_text(encoding="utf-8", errors="replace")
                                t_script = _get_tokens_script(url)
                                html = rewrite_html(html, all_routes, snap["url"], tokens_script=t_script, is_final_page=True)
                                self._send(200, "text/html; charset=utf-8", html.encode("utf-8"), extra_headers={
                                    "Content-Security-Policy": "sandbox allow-scripts allow-same-origin allow-popups allow-forms allow-top-navigation-by-user-activation allow-modals"
                                })
                                return

                if rel_path and rel_path.startswith("redirect:"):
                    try:
                        _, status_str, target_url = rel_path.split(":", 2)
                        status = int(status_str)
                        encoded_target = urllib.parse.quote(target_url, safe="")
                        self.send_response(status)
                        self.send_header("Location", f"/__wb/{encoded_target}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    except Exception as e:
                        log("WARN", f"Failed to serve redirect route {rel_path}: {e}")

                if not rel_path:
                    self._archive_not_found(url)
                    return

                filepath = archive.root / rel_path
                if not filepath.exists():
                    self._archive_not_found(url)
                    return

                content = filepath.read_bytes()
                
                # Guess MIME type from original URL path (which has clean file extensions)
                parsed_url = urllib.parse.urlparse(url)
                ct, _ = mimetypes.guess_type(parsed_url.path)
                
                # Fallback to guessing from filepath (stripping query string hashes like __q...)
                if not ct:
                    path_str = str(filepath)
                    if "__q" in path_str:
                        path_str = re.sub(r'__q[a-f0-9]+', '', path_str)
                    ct, _ = mimetypes.guess_type(path_str)
                    
                ct = (ct or "application/octet-stream").lower()

                # Content-sniffing fallback: if we couldn't guess the type or it's octet-stream,
                # peek at the first few bytes to see if it's actually HTML.
                # This fixes URLs like `/releases/tag/v1.0.0` being downloaded instead of viewed.
                if ct == "application/octet-stream":
                    peek = content[:1024].strip()
                    peek_lower = peek.lower()
                    if peek_lower.startswith(b"<!doctype html") or peek_lower.startswith(b"<html"):
                        ct = "text/html; charset=utf-8"
                    elif peek_lower.startswith(b"<svg") or b"<svg" in peek_lower[:100]:
                        ct = "image/svg+xml"
                    elif peek.startswith(b"<") and not peek.startswith(b"<?xml"):
                        ct = "text/html; charset=utf-8"
                    elif peek.startswith(b"{") or peek.startswith(b"["):
                        ct = "application/json; charset=utf-8"
                    elif self.headers.get("Sec-Fetch-Dest") == "script" or "/js/" in parsed_url.path or parsed_url.path.endswith(".mjs"):
                        ct = "application/javascript"
                    elif self.headers.get("Sec-Fetch-Dest") == "style" or "/css/" in parsed_url.path:
                        ct = "text/css"

                def safe_decode(b: bytes) -> str:
                    for enc in ("utf-8", "gb18030", "utf-8-sig"):
                        try:
                            return b.decode(enc)
                        except UnicodeDecodeError:
                            continue
                    return b.decode("utf-8", errors="replace")

                # Rewrite HTML links → /__wb/...
                if "html" in ct:
                    try:
                        text = open(filepath, "r", encoding="utf-8", errors="ignore").read()
                        t_script = _get_tokens_script(url)
                        is_final = "final_page.html" in str(filepath)
                        text = rewrite_html(text, all_routes, matched_url, tokens_script=t_script, is_final_page=is_final)
                        content = text.encode("utf-8")
                    except Exception:
                        pass
                
                # Rewrite CSS links → /__wb/...
                elif "css" in ct:
                    try:
                        text = safe_decode(content)
                        text = rewrite_css(text, all_routes, matched_url)
                        content = text.encode("utf-8")
                    except Exception:
                        pass

                # Rewrite JS links
                elif ct in ("application/javascript", "text/javascript"):
                    try:
                        text = safe_decode(content)
                        text = rewrite_css(text, all_routes, matched_url)  # Reuse CSS rewriter for url() in JS
                        
                        # Rewrite location properties to support SPA routing inside wayback proxy
                        text = re.sub(r'\bwindow\.location\.pathname\b', 'window.__wr_path()', text)
                        text = re.sub(r'(?<!window\.)\blocation\.pathname\b', '(window.__wr_path?window.__wr_path():location.pathname)', text)
                        text = re.sub(r'\bwindow\.location\.href\b', 'window.__wr_href()', text)
                        text = re.sub(r'(?<!window\.)\blocation\.href\b', '(window.__wr_href?window.__wr_href():location.href)', text)
                        
                        # FIX: Force lazy images in JS (like Reddit avatars) to scale properly and load eagerly
                        text = re.sub(r'(<img\b[^>]*?)loading=["\']?lazy["\']?', r'\1loading="eager" style="width:100%;height:100%;object-fit:cover;"', text, flags=re.IGNORECASE)
                        text = re.sub(r'(<faceplate-img\b[^>]*?)loading=["\']?lazy["\']?', r'\1loading="eager"', text, flags=re.IGNORECASE)
                        
                        content = text.encode("utf-8")
                    except Exception:
                        pass

                # Append charset=utf-8 for text-based resources to prevent browser encoding guess failures
                if ct and any(t in ct for t in ("text/html", "text/css", "javascript", "json")):
                    if "charset" not in ct:
                        ct = f"{ct}; charset=utf-8"

                extra_hdrs = {
                    "X-WR-Source": rel_path,
                    "X-WR-OrigURL": url,
                    # PERF: Cache static assets aggressively in browser
                    "Cache-Control": "public, max-age=3600" if ("html" not in ct and "css" not in ct) else "no-cache",
                }
                
                # Add Sandbox CSP to prevent JS from auto-refreshing or auto-redirecting (stops WAF loops)
                if "html" in ct:
                    extra_hdrs["Content-Security-Policy"] = "sandbox allow-scripts allow-same-origin allow-popups allow-forms allow-top-navigation-by-user-activation allow-modals"

                self._send(200, ct, content, extra_headers=extra_hdrs)

            def _archive_not_found(self, url: str):
                body = f"""<!DOCTYPE html><html><head><meta charset=UTF-8>
<title>Not in Archive</title>
<style>body{{font-family:sans-serif;background:#0d1117;color:#e6edf3;display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;gap:16px}}
a{{color:#7c3aed}}h1{{font-size:2rem}}p{{color:#8b949e}}</style></head>
<body>
<h1>🕸️ Chưa được lưu trữ</h1>
<p>URL này chưa có trong kho archive:</p>
<code style="background:#161b22;padding:8px 16px;border-radius:6px;color:#58a6ff">{url}</code>
<a href="/__archive__">← Về Dashboard</a>
</body></html>""".encode("utf-8")
                self._send(404, "text/html; charset=utf-8", body)

            def _send(self, status, ct, body, extra_headers=None):
                self.send_response(status)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                if extra_headers:
                    for k, v in extra_headers.items():
                        try: self.send_header(k, v)
                        except: pass
                self.end_headers()
                self.wfile.write(body)

            def _404(self, path):
                body = f"404 Not Found: {path}".encode()
                self._send(404, "text/plain", body)

            def log_message(self, fmt, *args):
                log("SRV", fmt % args)

        # PERF: ThreadingMixIn allows concurrent requests instead of queuing
        class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
            allow_reuse_address = True
            daemon_threads = True  # Don't block on Ctrl+C

        with ThreadedTCPServer(("", port), Handler) as httpd:
            log("OK",  f"Wayback Replay Server → http://localhost:{port}")
            log("INFO", f"Dashboard             → http://localhost:{port}/__archive__")
            log("INFO", f"Archive dir           → {archive.root.resolve()}")
            log("INFO", "Press Ctrl+C to stop\n")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                log("INFO", "Server stopped.")
