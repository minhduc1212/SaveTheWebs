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
        </div>
        <div class="snap-footer">
          <div class="snap-ts">⏰ ${new Date(s.recorded_at).toLocaleString('vi-VN')}</div>
          <div class="actions">
            <a href="/__mhtml/${s.id}" class="btn btn-secondary" target="_blank" title="Xem snapshot MHTML gốc">📄 MHTML</a>
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

loadData();
</script>
</body>
</html>
"""


class WaybackServer:
    """
    Replay server kiểu Wayback Machine.
    Routes:
      /__archive__          → Dashboard (fast – data loaded via AJAX)
      /__archive__/api/*    → JSON API cho dashboard
      /__wb/<encoded_url>   → Serve snapshot của URL đó
      /__mhtml/<snap_id>    → Serve MHTML snapshot for a recording

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
                    except Exception:
                        self._404(path)
                        return
                    self._serve_url(url)

                # ── Root → redirect to dashboard ──────────────────────
                elif path in ("/", ""):
                    self.send_response(302)
                    self.send_header("Location", "/__archive__")
                    self.end_headers()

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

            def _api(self, sub: str):
                if sub == "snapshots":
                    # PERF: Serve from in-memory index, no disk reads
                    snaps = sorted(
                        archive.data["snapshots"],
                        key=lambda x: x.get("recorded_at", ""),
                        reverse=True,
                    )
                    body = json.dumps(snaps).encode()
                    self._send(200, "application/json", body,
                               extra_headers={"Cache-Control": "no-store"})
                elif sub.startswith("search?"):
                    q = urllib.parse.parse_qs(sub[7:]).get("q", [""])[0]
                    body = json.dumps(archive.search(q)).encode()
                    self._send(200, "application/json", body)
                else:
                    self._404(sub)

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
                    
                    for entry in api_responses:
                        if entry.get("url") == url and entry.get("method", "GET").upper() == req_method:
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
                                api_match = entry
                                break

                    if api_match:
                        resp = api_match.get("response", {})
                        status = resp.get("status", 200)
                        headers = resp.get("headers", {})
                        body_str = resp.get("body", "")
                        body = body_str.encode("utf-8", errors="replace")
                        ct = headers.get("content-type", "application/json; charset=utf-8")
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
                        stub = json.dumps({"code": 0, "data": None, "msg": "", "result": None,
                                           "__wr_stub": True}).encode()
                        self._send(200, "application/json; charset=utf-8", stub, extra_headers={
                            "X-WR-Source": "stub",
                            "X-WR-OrigURL": url,
                        })
                        return

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
                                html = rewrite_html(html, all_routes, snap["url"])
                                self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))
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
                        path_str = path_str.split("__q")[0]
                    ct, _ = mimetypes.guess_type(path_str)
                    
                ct = (ct or "application/octet-stream").lower()

                # Content-sniffing fallback: if we couldn't guess the type or it's octet-stream,
                # peek at the first few bytes to see if it's actually HTML.
                # This fixes URLs like `/releases/tag/v1.0.0` being downloaded instead of viewed.
                if ct == "application/octet-stream":
                    peek = content[:512].strip().lower()
                    if peek.startswith(b"<!doctype html") or peek.startswith(b"<html"):
                        ct = "text/html; charset=utf-8"

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
                        text = safe_decode(content)
                        text = rewrite_html(text, all_routes, matched_url)
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
                        
                        content = text.encode("utf-8")
                    except Exception:
                        pass

                # Append charset=utf-8 for text-based resources to prevent browser encoding guess failures
                if ct and any(t in ct for t in ("text/html", "text/css", "javascript", "json")):
                    if "charset" not in ct:
                        ct = f"{ct}; charset=utf-8"

                self._send(200, ct, content, extra_headers={
                    "X-WR-Source": rel_path,
                    "X-WR-OrigURL": url,
                    # PERF: Cache static assets aggressively in browser
                    "Cache-Control": "public, max-age=3600" if ("html" not in ct and "css" not in ct) else "no-cache",
                })

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
