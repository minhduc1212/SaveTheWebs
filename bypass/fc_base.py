#!/usr/bin/env python3
"""
NovelUpdates Crawler
Inspired by Firecrawl's architecture:
- Stealth browser fingerprinting
- Human-like request timing
- HTML cleaning to extract main content
- Structured data output
"""

import asyncio
import json
import re
import time
import random
from dataclasses import dataclass, asdict
from typing import Optional
from pathlib import Path

from bs4 import BeautifulSoup


# ── Dependency check ──────────────────────────────────────────────────────────
def check_deps():
    missing = []
    try:
        import playwright
    except ImportError:
        missing.append("playwright")
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        missing.append("beautifulsoup4")
    try:
        import markdownify
    except ImportError:
        missing.append("markdownify")
    if missing:
        print(f"[INSTALL] pip install {' '.join(missing)} --break-system-packages")
        print("[INSTALL] playwright install chromium")
    return len(missing) == 0


# ─────────────────────────────────────────────────────────────────────────────
# DATA MODELS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class NovelInfo:
    title: str
    url: str
    cover_url: Optional[str]
    rating: Optional[str]
    status: Optional[str]
    type: Optional[str]
    genres: list[str]
    tags: list[str]
    authors: list[str]
    artists: list[str]
    year: Optional[str]
    description: str
    chapters: list[dict]
    related_series: list[dict]
    recommendations: list[dict]
    raw_markdown: str


# ─────────────────────────────────────────────────────────────────────────────
# STEALTH CONFIG  (Firecrawl-inspired browser fingerprint)
# ─────────────────────────────────────────────────────────────────────────────

STEALTH_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "max-age=0",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Google Chrome";v="120", "Chromium";v="120", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

# Realistic viewport sizes
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 800},
]

# JavaScript to inject for bot-detection bypass
STEALTH_JS = """
() => {
    // Override webdriver property
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // Override languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en']
    });

    // Override plugins (real Chrome has plugins)
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5]
    });

    // Override chrome property (Playwright doesn't set this)
    window.chrome = {
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {}
    };

    // Override permissions
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);

    // Override connection
    Object.defineProperty(navigator, 'connection', {
        get: () => ({
            rtt: 50,
            downlink: 10,
            effectiveType: '4g',
            saveData: false
        })
    });

    // Randomize canvas fingerprint slightly
    const getCtx = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(type, attrs) {
        const ctx = getCtx.call(this, type, attrs);
        if (type === '2d') {
            const getImageData = ctx.getImageData;
            ctx.getImageData = function(x, y, w, h) {
                const data = getImageData.call(this, x, y, w, h);
                for (let i = 0; i < data.data.length; i += 100) {
                    data.data[i] = data.data[i] ^ 1;
                }
                return data;
            };
        }
        return ctx;
    };
}
"""


# ─────────────────────────────────────────────────────────────────────────────
# ANTI-BOT ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class AntiBotEngine:
    """Mimics Firecrawl's Fire-engine stealth layer"""

    @staticmethod
    async def human_delay(min_ms=500, max_ms=2000):
        """Random human-like delay"""
        delay = random.uniform(min_ms, max_ms) / 1000
        await asyncio.sleep(delay)

    @staticmethod
    async def human_scroll(page):
        """Simulate human scrolling pattern"""
        total_height = await page.evaluate("document.body.scrollHeight")
        viewport_height = page.viewport_size["height"]
        current = 0
        while current < total_height * 0.6:
            scroll_amount = random.randint(200, 500)
            current = min(current + scroll_amount, total_height)
            await page.evaluate(f"window.scrollTo(0, {current})")
            await asyncio.sleep(random.uniform(0.1, 0.4))

    @staticmethod
    async def setup_page(browser):
        """Create a stealth-configured browser context & page"""
        vp = random.choice(VIEWPORTS)
        context = await browser.new_context(
            viewport=vp,
            locale="en-US",
            timezone_id="America/New_York",
            java_script_enabled=True,
            accept_downloads=False,
            ignore_https_errors=True,
        )
        page = await context.new_page()

        # Inject stealth JS before any script runs
        await page.add_init_script(STEALTH_JS)

        # Block unnecessary resources (speed + stealth) - DO NOT block fonts/images as they break Turnstile
        await page.route(
            "**/{google-analytics,gtag,doubleclick,facebook,twitter}*",
            lambda route: route.abort(),
        )

        return context, page


# ─────────────────────────────────────────────────────────────────────────────
# HTML CLEANER  (Firecrawl's main-content extraction logic)
# ─────────────────────────────────────────────────────────────────────────────

class HTMLCleaner:
    """
    Firecrawl uses a multi-pass pipeline:
    1. Remove noise elements (ads, nav, footer, scripts)
    2. Extract semantic main content via readability heuristics
    3. Convert to Markdown (html-to-markdown / turndown)
    4. Post-process markdown (clean whitespace, fix links)
    """

    NOISE_SELECTORS = [
        "script", "style", "noscript", "iframe", "object", "embed",
        "header", "footer", "nav", "#header", "#footer", "#nav",
        ".header", ".footer", ".navigation", ".sidebar", ".ads",
        ".advertisement", ".cookie-notice", ".popup", ".modal",
        "#respond", ".comments", "#comments", ".comment-section",
        "[class*='social']", "[class*='share']", "[class*='cookie']",
        "[class*='newsletter']", "[class*='subscribe']",
        ".wpDiscuz", "#wpdiscuz", ".nnMenu",
    ]

    @classmethod
    def clean(cls, html: str, base_url: str = "") -> tuple[str, "BeautifulSoup"]:
        """Clean HTML and return (markdown, soup)"""
        from bs4 import BeautifulSoup
        import markdownify

        soup = BeautifulSoup(html, "html.parser")

        # Remove noise
        for sel in cls.NOISE_SELECTORS:
            for el in soup.select(sel):
                el.decompose()

        # Remove empty elements
        for tag in soup.find_all(True):
            if not tag.get_text(strip=True) and tag.name not in ["img", "br", "hr"]:
                try:
                    tag.decompose()
                except Exception:
                    pass

        # Fix relative URLs
        if base_url:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.startswith("/"):
                    a["href"] = base_url.rstrip("/") + href

        # Convert to markdown
        md = markdownify.markdownify(
            str(soup),
            heading_style="ATX",
            bullets="-",
            strip=["script", "style"],
        )

        # Clean markdown
        md = re.sub(r'\n{3,}', '\n\n', md)
        md = re.sub(r'[ \t]+$', '', md, flags=re.MULTILINE)
        md = md.strip()

        return md, soup


# ─────────────────────────────────────────────────────────────────────────────
# NOVELUPDATES PARSER
# ─────────────────────────────────────────────────────────────────────────────

class NovelUpdatesParser:
    """Extract structured data from NovelUpdates HTML"""

    BASE_URL = "https://www.novelupdates.com"

    @classmethod
    def parse_novel_page(cls, soup, url: str, raw_md: str) -> NovelInfo:
        """Parse a novel detail page"""

        # Title
        title_el = soup.select_one("h1.seriestitlenu") or soup.select_one(".seriestitlenu")
        title = title_el.get_text(strip=True) if title_el else "Unknown"

        # Cover
        cover_el = soup.select_one(".seriesimg img")
        cover_url = cover_el.get("src") if cover_el else None

        # Rating
        rating = None
        for h5 in soup.select("h5"):
            txt = h5.get_text(strip=True)
            if "Rating" in txt:
                match = re.search(r'Rating\(([^)]+)\)', txt)
                if match:
                    rating = match.group(1)

        # Info table / sidebar metadata
        from bs4 import Tag
        info = cls._parse_info_table(soup)

        # Description
        desc_el = soup.select_one("#editdescription") or soup.select_one(".seriessinopse")
        description = desc_el.get_text(separator="\n", strip=True) if desc_el else ""

        # Chapters
        chapters = cls._parse_chapters(soup)

        # Filter out noisy values from tags
        tags = [t for t in info.get("tags", []) if t not in ["Tags List", "Request Tag"]]

        return NovelInfo(
            title=title,
            url=url,
            cover_url=cover_url,
            rating=rating or info.get("rating"),
            status=info.get("status"),
            type=info.get("type"),
            genres=info.get("genres", [])[:20],
            tags=tags[:30],
            authors=info.get("authors", []),
            artists=info.get("artists", []),
            year=info.get("year"),
            description=description,
            chapters=chapters[:20],
            related_series=info.get("related_series", [])[:10],
            recommendations=info.get("recommendations", [])[:10],
            raw_markdown=raw_md,
        )

    @classmethod
    def _parse_info_table(cls, soup) -> dict:
        from bs4 import Tag
        result = {}
        for h5 in soup.select("h5.seriesother"):
            label = h5.get_text(strip=True).lower()
            
            # Find all elements after this h5 until the next h5.seriesother
            content_nodes = []
            curr = h5.next_sibling
            while curr and not (curr.name == "h5" and "seriesother" in curr.get("class", [])):
                if isinstance(curr, Tag):
                    content_nodes.append(curr)
                curr = curr.next_sibling
            
            if "type" in label:
                for node in content_nodes:
                    a = node.find("a") if node.name != "a" else node
                    if a and "genre" in a.get("class", []):
                        result["type"] = a.get_text(strip=True)
                        break
            elif "genre" in label:
                genres = []
                for node in content_nodes:
                    for a in node.find_all("a") if node.name != "a" else [node]:
                        txt = a.get_text(strip=True)
                        if txt and txt not in genres:
                            genres.append(txt)
                result["genres"] = genres
            elif "tags" in label or "tag" in label:
                tags = []
                for node in content_nodes:
                    for a in node.find_all("a") if node.name != "a" else [node]:
                        txt = a.get_text(strip=True)
                        if txt and txt not in tags:
                            tags.append(txt)
                result["tags"] = tags
            elif "author" in label:
                authors = []
                for node in content_nodes:
                    for a in node.find_all("a") if node.name != "a" else [node]:
                        txt = a.get_text(strip=True)
                        if txt and txt not in authors:
                            authors.append(txt)
                result["authors"] = authors
            elif "artist" in label:
                artists = []
                for node in content_nodes:
                    for a in node.find_all("a") if node.name != "a" else [node]:
                        txt = a.get_text(strip=True)
                        if txt and txt not in artists:
                            artists.append(txt)
                result["artists"] = artists
            elif "year" in label:
                for node in content_nodes:
                    txt = node.get_text(strip=True)
                    match = re.search(r'\b(19\d\d|20\d\d)\b', txt)
                    if match:
                        result["year"] = match.group(1)
                        break
            elif "status in coo" in label:
                txts = [node.get_text(strip=True) for node in content_nodes]
                full_status = " ".join([t for t in txts if t]).lower()
                if "complete" in full_status:
                    result["status"] = "Completed"
                elif "ongoing" in full_status:
                    result["status"] = "Ongoing"
                elif "hiatus" in full_status:
                    result["status"] = "On Hiatus"
            elif "related series" in label:
                related = []
                for node in content_nodes:
                    for a in node.find_all("a") if node.name != "a" else [node]:
                        title_val = a.get_text(strip=True)
                        url_val = a.get("href", "")
                        if title_val and url_val and {"title": title_val, "url": url_val} not in related:
                            related.append({"title": title_val, "url": url_val})
                result["related_series"] = related
            elif "recommendations" in label:
                recs = []
                for node in content_nodes:
                    for a in node.find_all("a") if node.name != "a" else [node]:
                        title_val = a.get_text(strip=True)
                        url_val = a.get("href", "")
                        if title_val and url_val and {"title": title_val, "url": url_val} not in recs:
                            recs.append({"title": title_val, "url": url_val})
                result["recommendations"] = recs
        return result

    @classmethod
    def _parse_chapters(cls, soup) -> list[dict]:
        chapters = []
        for row in soup.select("table#myTable tr, .rl_links tr"):
            if "tbl_sort" in row.get("class", []):
                continue
            tds = row.select("td")
            if len(tds) >= 3:
                # Release column is tds[2]
                rel_el = tds[2].select_one("a, span")
                title = rel_el.get_text(strip=True) if rel_el else tds[2].get_text(strip=True)
                url = rel_el.get("href", "") if (rel_el and rel_el.name == "a") else ""
                
                # Group column is tds[1]
                grp_el = tds[1].select_one("a")
                group = grp_el.get_text(strip=True) if grp_el else tds[1].get_text(strip=True)
                
                # Date column is tds[0]
                date = tds[0].get_text(strip=True)
                
                if title:
                    chapters.append({
                        "title": title,
                        "url": url,
                        "group": group,
                        "date": date,
                    })
        return chapters

    @classmethod
    def parse_search_results(cls, soup) -> list[dict]:
        """Parse search results page"""
        results = []
        for item in soup.select(".search_main_box_nu, .search-results .novel-item"):
            title_el = item.select_one(".search_title a, .novel-title a, a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            url = title_el.get("href", "")

            rating_el = item.select_one(".search_ratings, .novel-rating")
            rating = rating_el.get_text(strip=True) if rating_el else ""

            chapters_el = item.select_one(".search_chapters_nu")
            chapter_count = chapters_el.get_text(strip=True) if chapters_el else ""

            img_el = item.select_one("img")
            cover = img_el.get("src") if img_el else None

            if title and url:
                results.append({
                    "title": title,
                    "url": url,
                    "rating": rating,
                    "chapters": chapter_count,
                    "cover": cover,
                })
        return results


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CRAWLER
# ─────────────────────────────────────────────────────────────────────────────

class NovelUpdatesCrawler:
    """
    Full crawl pipeline:
    1. Launch stealth Playwright browser
    2. Navigate with human-like behavior
    3. Wait for JS rendering / Cloudflare check
    4. Extract and clean HTML
    5. Parse structured data
    """

    BASE_URL = "https://www.novelupdates.com"

    async def _launch_browser(self, pw, verbose: bool = True):
        try:
            # Try launching Chrome stable (helps with CF bypass)
            return await pw.chromium.launch(
                headless=False,
                channel="chrome",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-infobars",
                    "--window-size=1920,1080",
                ],
            )
        except Exception as e:
            if verbose:
                print(f"[CRAWLER] Could not launch Chrome stable ({e}). Falling back to Chromium...")
            return await pw.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-infobars",
                    "--window-size=1920,1080",
                ],
            )

    async def _get_page_content_and_title(self, page):
        try:
            html = await page.content()
            title = await page.title()
            return html, title
        except Exception:
            try:
                # If navigation is in progress, wait for it to settle
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
                html = await page.content()
                title = await page.title()
                return html, title
            except Exception:
                return "", ""

    async def crawl_novel(self, url: str, verbose: bool = True) -> Optional[NovelInfo]:
        from playwright.async_api import async_playwright

        if verbose:
            print(f"\n[CRAWLER] Starting: {url}")
            print("[STEALTH] Injecting fingerprint overrides...")

        async with async_playwright() as pw:
            browser = await self._launch_browser(pw, verbose)

            try:
                context, page = await AntiBotEngine.setup_page(browser)

                # Navigate
                if verbose:
                    print("[NAVIGATE] Loading page...")
                await AntiBotEngine.human_delay(800, 1500)

                resp = await page.goto(url, wait_until="domcontentloaded", timeout=40000)

                if verbose:
                    print(f"[HTTP] Status: {resp.status if resp else 'unknown'}")

                # Human-like delay
                await AntiBotEngine.human_delay(1500, 3000)

                # Wait for Cloudflare bypass if needed
                html, title = await self._get_page_content_and_title(page)
                
                # Check for Cloudflare challenge (both status code and page content)
                cf_check = lambda h, t: "Just a moment" in h or "Checking your browser" in h or "Attention Required" in h or "Just a moment" in t
                
                max_cf_wait = 8  # Try up to 40 seconds (8 * 5s)
                while cf_check(html, title) and max_cf_wait > 0:
                    if verbose:
                        print(f"[CF] Cloudflare challenge active (Title: '{title}'), waiting 5s... ({max_cf_wait} retries left)")
                    # Save a screenshot to debug if needed
                    try:
                        await page.screenshot(path="cf_challenge_status.png")
                        if verbose:
                            print("[CF] Saved screenshot to cf_challenge_status.png")
                    except Exception as e:
                        pass
                    
                    # Try to locate and click Turnstile checkbox if visible in iframe
                    try:
                        for frame in page.frames:
                            if "challenges.cloudflare.com" in frame.url:
                                checkbox = await frame.query_selector("input[type='checkbox']")
                                if checkbox:
                                    if verbose:
                                        print("[CF] Found Turnstile checkbox in frame. Clicking...")
                                    await checkbox.click()
                                    await page.wait_for_timeout(2000)
                    except Exception as e:
                        if verbose:
                            print(f"[CF] Error checking/clicking Turnstile: {e}")

                    await page.wait_for_timeout(5000)
                    html, title = await self._get_page_content_and_title(page)
                    max_cf_wait -= 1

                # Additional network idle wait if we just got through CF
                if not cf_check(html, title) and max_cf_wait < 8:
                    if verbose:
                        print("[CF] Cloudflare bypassed successfully! Waiting for network to settle...")
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        pass

                # Human-like scroll
                await AntiBotEngine.human_delay(1000, 2000)
                await AntiBotEngine.human_scroll(page)
                await AntiBotEngine.human_delay(500, 1000)

                # Get final rendered HTML
                html, title = await self._get_page_content_and_title(page)
                if verbose:
                    print(f"[PAGE] Final Title: {title}")
                    print(f"[HTML] Final Size: {len(html):,} bytes")

                # Clean & parse
                if verbose:
                    print("[PARSE] Parsing structured data from original HTML...")
                original_soup = BeautifulSoup(html, "html.parser")

                if verbose:
                    print("[CLEAN] Extracting main content...")
                raw_md, _ = HTMLCleaner.clean(html, self.BASE_URL)

                if verbose:
                    print(f"[CLEAN] Markdown: {len(raw_md):,} chars")

                novel = NovelUpdatesParser.parse_novel_page(original_soup, url, raw_md)

                if verbose:
                    print(f"[DONE] ✓ '{novel.title}' — {len(novel.chapters)} chapters")

                return novel

            except Exception as e:
                if verbose:
                    print(f"[ERROR] {e}")
                return None
            finally:
                await browser.close()

    async def search(self, query: str, verbose: bool = True) -> list[dict]:
        """Search NovelUpdates"""
        from playwright.async_api import async_playwright

        search_url = f"{self.BASE_URL}/series-finder/?sf=1&sh={query.replace(' ', '%20')}&sort=sdate&order=desc"
        if verbose:
            print(f"\n[SEARCH] Query: {query}")

        async with async_playwright() as pw:
            browser = await self._launch_browser(pw, verbose)
            try:
                context, page = await AntiBotEngine.setup_page(browser)
                await AntiBotEngine.human_delay(500, 1200)
                await page.goto(search_url, wait_until="domcontentloaded", timeout=40000)
                await AntiBotEngine.human_delay(1500, 3000)

                # Wait for Cloudflare bypass if needed
                html, title = await self._get_page_content_and_title(page)
                cf_check = lambda h, t: "Just a moment" in h or "Checking your browser" in h or "Attention Required" in h or "Just a moment" in t
                
                max_cf_wait = 8
                while cf_check(html, title) and max_cf_wait > 0:
                    if verbose:
                        print(f"[SEARCH_CF] Cloudflare challenge active (Title: '{title}'), waiting 5s...")
                    await page.wait_for_timeout(5000)
                    html, title = await self._get_page_content_and_title(page)
                    max_cf_wait -= 1

                if not cf_check(html, title) and max_cf_wait < 8:
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        pass

                from bs4 import BeautifulSoup
                original_soup = BeautifulSoup(html, "html.parser")
                results = NovelUpdatesParser.parse_search_results(original_soup)
                if verbose:
                    print(f"[SEARCH] Found {len(results)} results")
                return results
            finally:
                await browser.close()


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    import sys

    # Reconfigure stdout/stderr to UTF-8 on Windows to avoid encoding errors
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    if not check_deps():
        return

    crawler = NovelUpdatesCrawler()

    if len(sys.argv) < 2:
        # Default: crawl a popular novel
        url = "https://www.hetushu.com/"
    else:
        url = sys.argv[1]

    if url.startswith("search:"):
        results = await crawler.search(url[7:])
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        novel = await crawler.crawl_novel(url)
        if novel:
            out = asdict(novel)
            del out["raw_markdown"]  # too long for CLI
            print(json.dumps(out, indent=2, ensure_ascii=False))
            # Save full output
            outfile = Path("novel_data.json")
            outfile.write_text(
                json.dumps(asdict(novel), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"\n[SAVED] {outfile.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())