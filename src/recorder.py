import asyncio
import base64
import re
import urllib.parse
from pathlib import Path
from typing import Optional

try:
    from playwright.async_api import async_playwright, Response
except ImportError:
    print("Thiếu playwright: pip install playwright && playwright install chromium")
    raise

from src.archive import ArchiveIndex, SnapshotStore
from src.token_extractor import extract_tokens
from src.utils import DEFAULT_ARCHIVE, STATIC_MIME, C, log


# ── Content-type classification ──────────────────────────────────────────────
# BUG FIX: The old `is_api` check used `"json" in ct` and `"xml" in ct`,
# which misclassified `image/svg+xml` (SVGs), `application/ld+json` (SEO),
# `application/manifest+json`, `application/xhtml+xml` as API responses.
# These are PAGE ASSETS, not API calls. This was a root cause of broken pages.

# These are the ONLY content-types that should be treated as API responses:
_API_CONTENT_TYPES = {
    "application/json",
    "text/json",
    "application/xml",
    "text/xml",
    "application/soap+xml",
}

# URL path patterns that indicate API endpoints
_API_URL_PATTERNS = ("/api/", "/graphql", "/rest/", "/v1/", "/v2/", "/v3/")

# Content-types that are page assets even if they contain "json" or "xml"
_ASSET_OVERRIDE_TYPES = {
    "image/svg+xml",              # SVG images
    "application/xhtml+xml",      # XHTML pages
    "application/ld+json",        # Structured data / SEO
    "application/manifest+json",  # Web app manifest
    "application/geo+json",       # GeoJSON
    "application/vnd.api+json",   # JSON:API spec (sometimes embeddable)
}


def _is_api_response(url: str, content_type: str) -> bool:
    """Determine if a response is an API call vs. a page asset."""
    ct = content_type.split(";")[0].strip().lower()

    # Explicit asset overrides — never treat as API
    if ct in _ASSET_OVERRIDE_TYPES:
        return False

    # Explicit API content-types
    if ct in _API_CONTENT_TYPES:
        return True

    # URL-pattern heuristic (only if content-type is ambiguous/unknown)
    if any(p in url for p in _API_URL_PATTERNS):
        # But NOT if the response is clearly a static file type
        if ct and (ct.startswith(("text/css", "text/html", "image/", "font/",
                                  "audio/", "video/", "application/javascript",
                                  "text/javascript", "application/wasm"))):
            return False
        return True

    return False


class WebRecorder:
    def __init__(self, start_url: str, archive_dir: str = DEFAULT_ARCHIVE, headless: bool = False,
                 timeout: int = 60, scroll_pause: float = 0.5, max_scrolls: int = 100):
        self.start_url = start_url
        self.archive = ArchiveIndex(archive_dir)
        self.store: Optional[SnapshotStore] = None
        self.headless = headless
        self.timeout = timeout * 1000
        self.scroll_pause = scroll_pause
        self.max_scrolls = max_scrolls
        self._seen: set = set()
        self._seen_lock = asyncio.Lock()
        self._css_urls: set = set()  # Track CSS URLs for @import chain following

    async def _on_response(self, resp: Response):
        url = resp.url
        async with self._seen_lock:
            if url in self._seen:
                return
            self._seen.add(url)

        try:
            status = resp.status

            # Handle redirects
            if 300 <= status < 400:
                loc = resp.headers.get("location")
                if loc:
                    target_url = urllib.parse.urljoin(url, loc)
                    self.store.save_redirect(url, target_url, status)
                    log("INFO", f"RED [{status}] {url[:72]} -> {target_url[:72]}")
                    return

            # BUG FIX: Some responses (204 No Content, 304 Not Modified, etc.)
            # have no body. `resp.body()` throws on these. Guard against it.
            if status in (204, 304) or status < 200:
                return

            ct = resp.headers.get("content-type", "")
            ct_main = ct.split(";")[0].strip().lower()

            # BUG FIX: Robustly extract body — catch errors from detached pages,
            # prematurely closed connections, and empty bodies.
            
            # Optimization: Skip large binary downloads based on URL extension and Content-Length
            # The user only wants UI assets (HTML, CSS, JS, images, fonts), not multi-megabyte 
            # software releases (.zip, .exe, .dmg, etc.)
            cl = resp.headers.get("content-length")
            if cl and int(cl) > 10 * 1024 * 1024:  # 10 MB limit
                log("WARN", f"Skipping large file (>10MB): {url[:60]}")
                return
                
            _SKIP_EXTS = {".zip", ".exe", ".dmg", ".pkg", ".tar", ".gz", ".rar", ".7z", 
                          ".mp4", ".mkv", ".avi", ".mov", ".iso", ".bin", ".apk", ".msi"}
            if any(url.lower().split("?")[0].endswith(ext) for ext in _SKIP_EXTS):
                log("WARN", f"Skipping binary extension: {url[:60]}")
                return

            try:
                body = await resp.body()
            except Exception as e:
                log("WARN", f"Body read failed for {url[:60]}: {e}")
                return

            if body is None or len(body) == 0:
                return

            # BUG FIX: Use the new accurate API classifier
            if _is_api_response(url, ct):
                req = resp.request
                rb = None
                try:
                    rb = await req.body()
                except Exception:
                    pass
                self.store.save_api(url, req.method, dict(req.headers), rb,
                                    resp.status, resp.headers, body)
                log("INFO", f"API [{req.method}] {resp.status} {url[:72]}")
                try:
                    extract_tokens(body.decode("utf-8", "replace"), url, self.store)
                except Exception:
                    pass
            else:
                # Save as a page asset (CSS, JS, HTML, images, fonts, etc.)
                fp = self.store.save_asset(url, body, ct_main)
                short = ct_main.split("/")[-1].upper()[:6] if ct_main else "UNKN"
                log("SAVE", f"[{short:6}] {url[:72]}")

                # Extract tokens from text-based assets
                if ct_main in {"text/html", "text/css", "application/javascript",
                               "text/javascript", "application/xhtml+xml"}:
                    try:
                        extract_tokens(body.decode("utf-8", "replace"), url, self.store)
                    except Exception:
                        pass

                # Track CSS files for later @import chain following
                if ct_main in {"text/css"}:
                    self._css_urls.add(url)

        except Exception as e:
            log("WARN", f"Skip {url[:60]}: {e}")

    async def _auto_scroll(self, page, scroll_pause: float = 0.5, max_scrolls: int = 100):
        """
        Incrementally scroll the page to trigger all lazy-loaded images, fonts, and assets.
        Uses instant jumping (scrollTo) for fast and reliable trigger execution.
        """
        log("INFO", "Auto-scrolling page to trigger lazy-loaded assets...")
        try:
            last_height = await page.evaluate("document.body.scrollHeight")
        except Exception:
            log("WARN", "Cannot read page height — skipping scroll")
            return

        scroll_count = 0
        viewport_height = await page.evaluate("window.innerHeight")

        while scroll_count < max_scrolls:
            current_pos = await page.evaluate("window.scrollY")
            next_pos = current_pos + viewport_height

            # Jump to the next viewport position
            await page.evaluate(f"window.scrollTo(0, {next_pos})")
            await page.wait_for_timeout(int(scroll_pause * 1000))

            new_height = await page.evaluate("document.body.scrollHeight")
            at_bottom = await page.evaluate(
                "window.scrollY + window.innerHeight >= document.body.scrollHeight - 20"
            )

            if at_bottom:
                if new_height == last_height:
                    log("INFO", f"Auto-scroll reached bottom ({scroll_count + 1} scrolls, height={new_height}px)")
                    break
                last_height = new_height
                log("INFO", f"Page grew to {new_height}px — continuing scroll...")

            scroll_count += 1

        # Scroll back to the top of the page
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(300)

    async def _collect_cdp_resources(self, cdp_session):
        """
        BUG FIX: Use CDP Page.getResourceTree to enumerate ALL resources loaded
        by the page — this is the same data shown in the browser's "Sources" tab.

        This catches resources that the network response handler missed because:
        - They were served from the browser's disk/memory cache
        - They were loaded before the response handler was attached
        - They were inlined or blobified by the page's JavaScript
        """
        log("INFO", "Collecting all page resources via CDP (Sources tab equivalent)...")
        try:
            tree = await cdp_session.send("Page.getResourceTree")
        except Exception as e:
            log("WARN", f"CDP Page.getResourceTree failed: {e}")
            return

        resources = []
        # Collect from main frame
        frame_tree = tree.get("frameTree", {})
        resources.extend(frame_tree.get("resources", []))
        # Collect from child frames (iframes, etc.)
        for child_frame in frame_tree.get("childFrames", []):
            resources.extend(child_frame.get("resources", []))
            # Recursively get nested child frames
            self._collect_child_frame_resources(child_frame, resources)

        saved_count = 0
        skipped_count = 0
        for res in resources:
            url = res.get("url", "")
            if not url or url.startswith(("data:", "blob:", "javascript:", "about:")):
                continue

            # Check if we already captured this via the response handler
            async with self._seen_lock:
                if url in self._seen:
                    skipped_count += 1
                    continue
                self._seen.add(url)

            # Fetch the resource content via CDP
            frame_id = frame_tree.get("frame", {}).get("id", "")
            try:
                result = await cdp_session.send("Page.getResourceContent", {
                    "frameId": frame_id,
                    "url": url,
                })
            except Exception as e:
                log("WARN", f"CDP getResourceContent failed for {url[:60]}: {e}")
                continue

            content = result.get("content", "")
            is_base64 = result.get("base64Encoded", False)

            if not content:
                continue

            if is_base64:
                body = base64.b64decode(content)
            else:
                body = content.encode("utf-8")

            ct = res.get("mimeType", "application/octet-stream") or "application/octet-stream"
            ct_main = ct.split(";")[0].strip().lower()

            # Don't save API responses collected via CDP — we already have those
            if _is_api_response(url, ct):
                continue

            fp = self.store.save_asset(url, body, ct_main)
            saved_count += 1
            log("SAVE", f"[CDP   ] {url[:72]}")

            # Track CSS for @import following
            if ct_main == "text/css":
                self._css_urls.add(url)

        log("OK", f"CDP resource collection: {saved_count} new assets saved, {skipped_count} already captured")

    def _collect_child_frame_resources(self, frame_tree: dict, resources: list):
        """Recursively collect resources from nested child frames."""
        for child in frame_tree.get("childFrames", []):
            resources.extend(child.get("resources", []))
            self._collect_child_frame_resources(child, resources)

    async def _follow_css_imports(self, page):
        """
        Parse captured CSS files for @import directives and fetch any imported
        stylesheets that weren't captured by the response handler or CDP.
        """
        log("INFO", "Following CSS @import chains...")
        import_re = re.compile(r'@import\s+(?:url\(\s*["\']?([^"\')\s]+)["\']?\s*\)|["\']([^"\']+)["\'])', re.IGNORECASE)

        new_imports = set()
        for css_url in list(self._css_urls):
            # Read the saved CSS file
            rel_path = self.store.manifest["routes"].get(css_url)
            if not rel_path or rel_path.startswith("redirect:"):
                continue
            css_path = self.store.path / rel_path
            if not css_path.exists():
                continue
            try:
                css_text = css_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            for m in import_re.finditer(css_text):
                imported = m.group(1) or m.group(2)
                if not imported or imported.startswith("data:"):
                    continue
                # Resolve relative to the CSS file's URL
                abs_url = urllib.parse.urljoin(css_url, imported)
                async with self._seen_lock:
                    if abs_url not in self._seen:
                        new_imports.add(abs_url)

        if new_imports:
            log("INFO", f"Found {len(new_imports)} un-captured @import URLs — fetching...")
            for import_url in new_imports:
                try:
                    resp = await page.request.get(import_url, timeout=10000)
                    body = await resp.body()
                    ct = resp.headers.get("content-type", "text/css")
                    ct_main = ct.split(";")[0].strip().lower()
                    self.store.save_asset(import_url, body, ct_main)
                    async with self._seen_lock:
                        self._seen.add(import_url)
                    log("SAVE", f"[@IMPRT] {import_url[:72]}")
                except Exception as e:
                    log("WARN", f"Failed to fetch @import {import_url[:60]}: {e}")

    async def _save_mhtml(self, cdp_session):
        """
        Save an MHTML snapshot — a single file containing the complete page state.
        This is a last-resort fallback for perfect offline replay.
        """
        log("INFO", "Capturing MHTML snapshot...")
        try:
            result = await cdp_session.send("Page.captureSnapshot", {"format": "mhtml"})
            mhtml = result.get("data", "")
            if mhtml:
                (self.store.path / "snapshot.mhtml").write_text(mhtml, encoding="utf-8")
                log("OK", f"MHTML snapshot saved ({len(mhtml)} bytes)")
        except Exception as e:
            log("WARN", f"MHTML capture failed: {e}")

    async def record(self):
        self.store = self.archive.new_snapshot(self.start_url)
        log("OK",   f"New snapshot: {self.store.meta['id']}")
        log("INFO", f"Archive dir : {self.archive.root.resolve()}")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"]
            )
            ctx = await browser.new_context(
                ignore_https_errors=True,
                viewport={"width": 1440, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                timezone_id="Asia/Ho_Chi_Minh",
                bypass_csp=True,
                service_workers="block",
                extra_http_headers={
                    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                }
            )
            page = await ctx.new_page()

            # Disable Chromium Cache via CDP to guarantee network requests are captured
            cdp = None
            try:
                cdp = await page.context.new_cdp_session(page)
                await cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
                # Enable Page domain for resource tree collection
                await cdp.send("Page.enable")
            except Exception as e:
                log("WARN", f"Failed to initialize CDP session: {e}")

            # Inject storage interceptor and disable webdriver detection
            await page.add_init_script("""
            (()=>{
              Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
              const cap = k => { window._wr=window._wr||[]; window._wr.push(k); };
              const _ls=localStorage.setItem.bind(localStorage);
              localStorage.setItem=(k,v)=>{ cap({t:'ls',k,v}); return _ls(k,v); };
              const _ss=sessionStorage.setItem.bind(sessionStorage);
              sessionStorage.setItem=(k,v)=>{ cap({t:'ss',k,v}); return _ss(k,v); };
            })();
            """)

            page.on("response", self._on_response)

            log("INFO", f"Navigating → {self.start_url}")
            try:
                await page.goto(self.start_url, wait_until="networkidle", timeout=self.timeout)
            except Exception as e:
                log("WARN", f"Load error (continuing): {e}")

            await page.wait_for_timeout(2000)

            # Collect storage tokens
            try:
                items = await page.evaluate("()=>window._wr||[]")
                for it in items:
                    self.store.save_token(it["t"], f"{it['k']}={it['v']}", self.start_url)
                ls = await page.evaluate("()=>{const r={};for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i);r[k]=localStorage.getItem(k);}return r;}")
                for k, v in (ls or {}).items():
                    if v and len(v) > 8:
                        self.store.save_token("localStorage", f"{k}={v}", self.start_url)
            except Exception:
                pass

            # Auto-scroll to capture all lazy-loaded content
            await self._auto_scroll(page, scroll_pause=self.scroll_pause, max_scrolls=self.max_scrolls)
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            if not self.headless:
                log("INFO", "Auto-scroll finished. Browser OPEN – browse freely. Press ENTER to finish recording...")
                await asyncio.get_event_loop().run_in_executor(None, input)

            # ── Phase 2: CDP resource tree collection ────────────────────────
            # This is the equivalent of the browser's "Sources" tab.
            # It catches EVERYTHING the browser loaded, including cached resources.
            if cdp:
                await self._collect_cdp_resources(cdp)

            # ── Phase 3: Follow CSS @import chains ───────────────────────────
            await self._follow_css_imports(page)

            # ── Phase 4: Save final rendered HTML ────────────────────────────
            try:
                html = await page.content()
                (self.store.path / "final_page.html").write_text(html, encoding="utf-8")
            except Exception:
                pass

            # ── Phase 5: MHTML snapshot ──────────────────────────────────────
            if cdp:
                await self._save_mhtml(cdp)

            cookies = await ctx.cookies()
            if cookies:
                self.store.save_cookies(cookies)

            await browser.close()

        self.store.flush()
        self._print_summary()

        # Automatically trigger content extraction
        try:
            log("INFO", "Triggering automatic content extraction...")
            from src.extractor import ContentExtractor
            extractor = ContentExtractor(self.store.path)
            extractor.extract()
            log("OK", "Automatic content extraction completed!")
        except Exception as e:
            log("ERR", f"Automatic content extraction failed: {e}")

    def _print_summary(self):
        m = self.store.manifest
        print(f"\n{C['BD']}{'═'*62}{C['X']}")
        print(f"  {C['G']}{C['BD']}RECORDING COMPLETE{C['X']}")
        print(f"{'═'*62}")
        print(f"  📸 Snapshot  : {self.store.meta['id']}")
        print(f"  🌐 URL       : {m['url']}")
        print(f"  📁 Assets    : {len(m['routes'])}")
        print(f"  🔌 API calls : {len(m['api_calls'])}")
        print(f"  🔑 Tokens    : {', '.join(m['tokens'].keys()) or 'none'}")
        print(f"{'═'*62}")
        print(f"\n  ▶  Replay   : {C['C']}python webrecorder.py --replay{C['X']}")
        print(f"  📊 Extract  : {C['C']}python webrecorder.py --extract {self.store.meta['id']}{C['X']}")
        print(f"  📦 All      : {C['C']}python webrecorder.py --extract-all{C['X']}")
        print(f"  🔍 Browse   : http://localhost:8080/__archive__\n")

