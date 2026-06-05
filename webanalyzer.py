#!/usr/bin/env python3
"""
WebAnalyzer – Phân tích và tái cấu trúc site đã ghi để dùng offline hoàn toàn.
Thay thế tất cả URL tuyệt đối → đường dẫn file cục bộ trong HTML/CSS/JS.
"""

import json
import re
import os
import urllib.parse
import hashlib
from pathlib import Path
from typing import Optional
import argparse

DEFAULT_DIR = "recorded_site"

COLOR = {
    "green":  "\033[92m",
    "yellow": "\033[93m",
    "cyan":   "\033[96m",
    "reset":  "\033[0m",
    "bold":   "\033[1m",
}

def log(level: str, msg: str):
    colors = {"OK": COLOR["green"], "PATCH": COLOR["cyan"], "WARN": COLOR["yellow"]}
    c = colors.get(level, COLOR["reset"])
    print(f"  {c}[{level}]{COLOR['reset']} {msg}")


class OfflinePatcher:
    """Thay URL tuyệt đối → đường dẫn cục bộ trong toàn bộ tài nguyên."""

    def __init__(self, recorded_dir: str = DEFAULT_DIR):
        self.base = Path(recorded_dir)
        self.manifest_path = self.base / "manifest.json"
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.routes = self.manifest.get("routes", {})  # url → relative_path

    def _find_local_path(self, url: str) -> Optional[str]:
        """Tìm file cục bộ tương ứng với URL đã biết."""
        # Exact match
        if url in self.routes:
            return self.routes[url]
        # Path-only match
        parsed = urllib.parse.urlparse(url)
        for orig_url, rel_path in self.routes.items():
            if urllib.parse.urlparse(orig_url).path == parsed.path:
                return rel_path
        return None

    def _rewrite_css_urls(self, css_text: str, css_file_path: Path) -> str:
        """Thay url(...) trong CSS."""
        def replacer(m):
            raw = m.group(1).strip("'\"")
            if raw.startswith("data:") or raw.startswith("#"):
                return m.group(0)
            local = self._find_local_path(raw)
            if local:
                # Đường dẫn tương đối từ file CSS
                abs_local = (self.base / local).resolve()
                rel = os.path.relpath(abs_local, css_file_path.parent)
                return f"url('{rel}')"
            return m.group(0)

        return re.sub(r'url\(["\']?([^)"\']+)["\']?\)', replacer, css_text)

    def _rewrite_html_attrs(self, html: str) -> str:
        """Thay src/href/action trong HTML."""
        def replace_attr(m):
            attr = m.group(1)
            quote = m.group(2)
            url = m.group(3)
            if url.startswith("data:") or url.startswith("#") or url.startswith("javascript:"):
                return m.group(0)
            local = self._find_local_path(url)
            if local:
                return f'{attr}={quote}{local}{quote}'
            return m.group(0)

        html = re.sub(
            r'(src|href|action)=(["\'])([^"\']+)\2',
            replace_attr, html, flags=re.IGNORECASE
        )
        return html

    def patch_all(self):
        """Patching tất cả HTML, CSS, JS đã lưu."""
        patched = 0
        for url, rel_path in self.routes.items():
            filepath = self.base / rel_path
            if not filepath.exists():
                continue
            ext = filepath.suffix.lower()
            try:
                if ext in {".html", ".htm"}:
                    content = filepath.read_text(encoding="utf-8", errors="replace")
                    new_content = self._rewrite_html_attrs(content)
                    if new_content != content:
                        filepath.write_text(new_content, encoding="utf-8")
                        log("PATCH", f"HTML: {rel_path}")
                        patched += 1
                elif ext == ".css":
                    content = filepath.read_text(encoding="utf-8", errors="replace")
                    new_content = self._rewrite_css_urls(content, filepath)
                    if new_content != content:
                        filepath.write_text(new_content, encoding="utf-8")
                        log("PATCH", f"CSS:  {rel_path}")
                        patched += 1
            except Exception as e:
                log("WARN", f"Cannot patch {rel_path}: {e}")

        log("OK", f"Patched {patched} files for offline use")

    def generate_index(self, output_file: str = "offline_index.html"):
        """Tạo trang index offline với danh sách tất cả tài nguyên."""
        api_calls = self.manifest.get("api_calls", [])
        tokens = self.manifest.get("tokens", {})
        recorded_at = self.manifest.get("recorded_at", "unknown")

        rows_assets = ""
        for url, rel_path in self.routes.items():
            fp = self.base / rel_path
            size = fp.stat().st_size if fp.exists() else 0
            ext = Path(rel_path).suffix.upper().lstrip(".")
            rows_assets += f"""
            <tr>
                <td><span class="badge badge-{ext.lower()}">{ext}</span></td>
                <td class="url-cell" title="{url}">{url[:80]}{'...' if len(url)>80 else ''}</td>
                <td>{size:,} B</td>
                <td><a href="{rel_path}" target="_blank">📂 Open</a></td>
            </tr>"""

        rows_api = ""
        for call in api_calls[:50]:
            rows_api += f"""
            <tr>
                <td><span class="method {call['method'].lower()}">{call['method']}</span></td>
                <td class="url-cell" title="{call['url']}">{call['url'][:80]}{'...' if len(call['url'])>80 else ''}</td>
                <td><a href="api_responses/{call['id']}.json" target="_blank">📄 View</a></td>
            </tr>"""

        token_html = ""
        for ttype, tlist in tokens.items():
            if ttype == "cookies":
                token_html += f'<div class="token-group"><b>🍪 Cookies:</b> {len(tlist)} saved → <a href="tokens/cookies.json">cookies.json</a></div>'
            else:
                token_html += f'<div class="token-group"><b>🔑 {ttype}:</b> {len(tlist)} found → <a href="tokens/{ttype}_tokens.json">view</a></div>'

        html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WebRecorder – Offline Index</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Segoe UI',sans-serif;background:#0f1117;color:#e2e8f0;padding:24px}}
  h1{{font-size:1.8rem;color:#7c3aed;margin-bottom:4px}}
  .subtitle{{color:#64748b;font-size:.85rem;margin-bottom:24px}}
  .stats{{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap}}
  .stat-card{{background:#1e2130;border:1px solid #2d3748;border-radius:12px;padding:16px 24px;min-width:140px}}
  .stat-card .num{{font-size:2rem;font-weight:700;color:#7c3aed}}
  .stat-card .label{{font-size:.8rem;color:#94a3b8;margin-top:2px}}
  h2{{font-size:1.1rem;color:#a78bfa;margin:24px 0 12px;border-bottom:1px solid #2d3748;padding-bottom:6px}}
  table{{width:100%;border-collapse:collapse;font-size:.82rem}}
  th{{background:#1e2130;padding:8px 12px;text-align:left;color:#94a3b8;font-weight:500}}
  td{{padding:7px 12px;border-bottom:1px solid #1e2130;vertical-align:middle}}
  tr:hover td{{background:#1a1f2e}}
  .url-cell{{max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#cbd5e1}}
  a{{color:#818cf8;text-decoration:none}} a:hover{{text-decoration:underline}}
  .badge{{display:inline-block;padding:2px 7px;border-radius:4px;font-size:.7rem;font-weight:700}}
  .badge-html{{background:#166534;color:#bbf7d0}} .badge-css{{background:#1e3a5f;color:#93c5fd}}
  .badge-js{{background:#713f12;color:#fde68a}} .badge-json{{background:#4c1d95;color:#c4b5fd}}
  .badge-png,.badge-jpg,.badge-gif,.badge-webp{{background:#1e293b;color:#e2e8f0}}
  .method{{display:inline-block;padding:2px 6px;border-radius:4px;font-size:.7rem;font-weight:700}}
  .method.get{{background:#064e3b;color:#34d399}} .method.post{{background:#1e3a5f;color:#60a5fa}}
  .method.put{{background:#713f12;color:#fbbf24}} .method.delete{{background:#7f1d1d;color:#f87171}}
  .token-group{{background:#1e2130;border:1px solid #2d3748;border-radius:8px;padding:10px 16px;margin-bottom:8px}}
  .final-html{{background:#1e2130;border:1px solid #2d3748;border-radius:8px;padding:16px;margin-bottom:8px}}
</style>
</head>
<body>
<h1>📼 WebRecorder – Offline Archive</h1>
<div class="subtitle">Recorded: {recorded_at} | Use this index to navigate captured assets</div>

<div class="stats">
  <div class="stat-card"><div class="num">{len(self.routes)}</div><div class="label">Assets Saved</div></div>
  <div class="stat-card"><div class="num">{len(api_calls)}</div><div class="label">API Calls</div></div>
  <div class="stat-card"><div class="num">{len(tokens)}</div><div class="label">Token Types</div></div>
</div>

<div class="final-html">
  📄 <b>Final captured page:</b>
  <a href="final_page.html" target="_blank">final_page.html</a>
  – The full rendered HTML of the recorded session
</div>

<h2>🔑 Tokens & Authentication</h2>
{token_html if token_html else '<p style="color:#64748b">No tokens found</p>'}

<h2>🌐 Captured Assets ({len(self.routes)})</h2>
<table>
  <thead><tr><th>Type</th><th>URL</th><th>Size</th><th>File</th></tr></thead>
  <tbody>{rows_assets}</tbody>
</table>

<h2>🔌 API Calls ({len(api_calls)})</h2>
<table>
  <thead><tr><th>Method</th><th>URL</th><th>Response</th></tr></thead>
  <tbody>{rows_api}</tbody>
</table>

</body>
</html>"""

        out = self.base / output_file
        out.write_text(html, encoding="utf-8")
        log("OK", f"Index generated: {out.resolve()}")
        return str(out)


def main():
    parser = argparse.ArgumentParser(description="WebAnalyzer – Patch & analyze recorded site")
    parser.add_argument("-o", "--output", default=DEFAULT_DIR, help="Thư mục đã ghi")
    parser.add_argument("--patch", action="store_true", help="Patch URL tuyệt đối → cục bộ")
    parser.add_argument("--index", action="store_true", help="Tạo offline_index.html")
    args = parser.parse_args()

    patcher = OfflinePatcher(args.output)
    if args.patch:
        patcher.patch_all()
    if args.index or not args.patch:
        patcher.generate_index()
        print(f"\n  ✅ Open: {Path(args.output).resolve() / 'offline_index.html'}")


if __name__ == "__main__":
    main()