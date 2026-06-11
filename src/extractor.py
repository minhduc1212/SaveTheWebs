"""
Content Extractor for SaveTheWeb snapshots.

Parses final_page.html from a snapshot directory and extracts structured
content data (metadata, navigation, content sections, images, links, assets)
into a JSON file.

Usage:
    from src.extractor import ContentExtractor

    extractor = ContentExtractor("web_archive/snapshots/example.com_20260605_194745")
    data = extractor.extract()
    # => writes extracted_data.json and returns the dict

    # Or extract all snapshots in the archive:
    results = ContentExtractor.extract_all("web_archive")
"""

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag, NavigableString

from src.utils import log


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

# CSS selectors commonly used for navigation containers
_NAV_SELECTORS = [
    "nav", "header", "[role='navigation']",
    ".navbar", ".nav", ".navigation", ".menu", ".header-nav",
    "#nav", "#menu", "#navigation", "#header-nav",
]

# CSS selectors for main content containers (ordered by specificity)
_CONTENT_SELECTORS = [
    "article", "main", "[role='main']",
    ".content", ".main-content", ".post-content", ".article-body",
    ".entry-content", ".page-content", ".post-body",
    "#content", "#main", "#main-content",
    "section",
]

# Image extensions for classifying assets
_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".bmp", ".ico", ".tiff"}
_FONT_EXTS = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
_CSS_EXTS = {".css"}
_JS_EXTS = {".js"}


def _text(el) -> str:
    """Get cleaned text from an element, collapsing whitespace."""
    if el is None:
        return ""
    raw = el.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", raw).strip()


def _safe_attr(el, attr: str, default: str = "") -> str:
    """Safely get an attribute from a bs4 Tag."""
    if el is None or not isinstance(el, Tag):
        return default
    val = el.get(attr, default)
    if isinstance(val, list):
        return " ".join(val)
    return str(val) if val else default


def _classify_asset(path_str: str) -> str:
    """Return the asset category based on file extension."""
    ext = Path(path_str).suffix.lower()
    # Handle URL-encoded extensions like .woff%3Fv=3.2.1
    if "%" in ext:
        ext = ext.split("%")[0]
    if ext in _IMG_EXTS:
        return "image"
    if ext in _FONT_EXTS:
        return "font"
    if ext in _CSS_EXTS:
        return "css"
    if ext in _JS_EXTS:
        return "js"
    if ext in {".html", ".htm"}:
        return "html"
    return "other"


# ──────────────────────────────────────────────────────────────────────────────
# ContentExtractor
# ──────────────────────────────────────────────────────────────────────────────

class ContentExtractor:
    """
    Extracts structured content from a SaveTheWeb snapshot directory.

    The snapshot directory is expected to contain:
        - final_page.html   — fully rendered DOM
        - manifest.json     — routes mapping URLs → local asset paths
        - assets/           — downloaded CSS, JS, images, fonts
        - api_responses/    — captured API call data (JSON files)
        - tokens/           — cookies and localStorage data

    The extractor parses the HTML, maps image/asset URLs to their local paths
    using the manifest routes, and writes the result to extracted_data.json.
    """

    def __init__(self, snapshot_dir: str | Path):
        self.snap_dir = Path(snapshot_dir)
        self.html_path = self.snap_dir / "final_page.html"
        self.manifest_path = self.snap_dir / "manifest.json"
        self.manifest: dict = {}
        self.routes: dict = {}
        self.soup: BeautifulSoup | None = None
        self.base_url: str = ""

    # ── Public API ────────────────────────────────────────────────────────

    def extract(self) -> dict:
        """
        Run the full extraction pipeline.

        Returns:
            dict with keys: meta, navigation, content, images, flow, assets.
        Side-effect:
            Writes extracted_data.json into the snapshot directory.
        """
        self._load_manifest()
        self._load_html()

        data = {
            "snapshot_id": self.manifest.get("id", self.snap_dir.name),
            "source_url": self.base_url,
            "recorded_at": self.manifest.get("recorded_at", ""),
            "meta": self._extract_meta(),
            "navigation": self._extract_navigation(),
            "content": self._extract_content(),
            "images": self._extract_images(),
            "flow": self._extract_flow(),
            "assets": self._extract_assets(),
        }

        out_path = self.snap_dir / "extracted_data.json"
        try:
            out_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log("OK", f"Extracted data → {out_path.name}  ({self.snap_dir.name})")
        except OSError as exc:
            log("ERR", f"Failed to write extracted_data.json: {exc}")

        return data

    @staticmethod
    def extract_all(archive_dir: str | Path = "web_archive") -> list[dict]:
        """
        Extract content from every snapshot in the archive.

        Args:
            archive_dir: Path to the archive root (contains index.json).

        Returns:
            List of extracted data dicts, one per snapshot.
        """
        archive_root = Path(archive_dir)
        index_path = archive_root / "index.json"
        results = []

        if index_path.exists():
            try:
                index_data = json.loads(index_path.read_text(encoding="utf-8"))
                snapshots = index_data.get("snapshots", [])
            except (json.JSONDecodeError, OSError) as exc:
                log("ERR", f"Failed to read index.json: {exc}")
                snapshots = []

            for snap in snapshots:
                snap_path = archive_root / snap.get("path", "")
                if not snap_path.exists():
                    log("WARN", f"Snapshot dir missing: {snap_path}")
                    continue
                try:
                    extractor = ContentExtractor(snap_path)
                    results.append(extractor.extract())
                except Exception as exc:
                    log("ERR", f"Extraction failed for {snap_path.name}: {exc}")
        else:
            # Fallback: scan snapshots/ directory directly
            snap_root = archive_root / "snapshots"
            if snap_root.is_dir():
                for snap_path in sorted(snap_root.iterdir()):
                    if not snap_path.is_dir():
                        continue
                    if not (snap_path / "final_page.html").exists():
                        continue
                    try:
                        extractor = ContentExtractor(snap_path)
                        results.append(extractor.extract())
                    except Exception as exc:
                        log("ERR", f"Extraction failed for {snap_path.name}: {exc}")

        log("OK", f"Extracted {len(results)} snapshot(s) from {archive_root}")
        return results

    # ── Loading ───────────────────────────────────────────────────────────

    def _load_manifest(self):
        """Load manifest.json and populate routes lookup."""
        if not self.manifest_path.exists():
            log("WARN", f"No manifest.json in {self.snap_dir.name}")
            return

        try:
            raw = self.manifest_path.read_text(encoding="utf-8")
            self.manifest = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            log("ERR", f"Failed to parse manifest.json: {exc}")
            return

        self.routes = self.manifest.get("routes", {})
        self.base_url = self.manifest.get("url", "")

    def _load_html(self):
        """Load and parse final_page.html with encoding fallback."""
        if not self.html_path.exists():
            log("WARN", f"No final_page.html in {self.snap_dir.name}")
            return

        html = ""
        for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk", "latin-1"):
            try:
                html = self.html_path.read_text(encoding=encoding)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        else:
            # Last resort: read bytes and let BS4 handle encoding detection
            try:
                raw_bytes = self.html_path.read_bytes()
                html = raw_bytes.decode("utf-8", errors="replace")
            except OSError as exc:
                log("ERR", f"Cannot read final_page.html: {exc}")
                return

        try:
            self.soup = BeautifulSoup(html, "html.parser")
        except Exception as exc:
            log("ERR", f"BeautifulSoup parse error: {exc}")

    # ── URL ↔ Local Path mapping ──────────────────────────────────────────

    def _resolve_url(self, url: str) -> str:
        """Resolve a possibly-relative URL against the base URL."""
        if not url or url.startswith(("data:", "javascript:", "mailto:", "tel:", "#")):
            return url
        if url.startswith(("http://", "https://", "//")):
            return url
        # Relative URL → absolute
        if self.base_url:
            return urljoin(self.base_url + "/", url)
        return url

    def _map_to_local(self, url: str) -> str | None:
        """
        Look up the absolute URL in manifest routes and return the local
        asset path relative to the snapshot directory. Returns None if
        no mapping found.
        """
        if not url or not self.routes:
            return None

        # Try exact match first
        local = self.routes.get(url)
        if local and not local.startswith("redirect:"):
            return local.replace("\\", "/")

        # Try with/without trailing slash
        alt = url.rstrip("/") if url.endswith("/") else url + "/"
        local = self.routes.get(alt)
        if local and not local.startswith("redirect:"):
            return local.replace("\\", "/")

        # Try matching ignoring scheme (http vs https)
        parsed = urlparse(url)
        for route_url, route_path in self.routes.items():
            rp = urlparse(route_url)
            if (rp.netloc == parsed.netloc
                    and rp.path == parsed.path
                    and rp.query == parsed.query
                    and not route_path.startswith("redirect:")):
                return route_path.replace("\\", "/")

        return None

    # ── Meta extraction ───────────────────────────────────────────────────

    def _extract_meta(self) -> dict:
        """Extract page metadata from <head>."""
        if not self.soup:
            return {}

        meta: dict = {}

        # Title
        title_el = self.soup.find("title")
        meta["title"] = _text(title_el)

        # <meta name="description">
        desc_el = self.soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        meta["description"] = _safe_attr(desc_el, "content")

        # Charset — from <meta charset="..."> or http-equiv
        charset_el = self.soup.find("meta", attrs={"charset": True})
        if charset_el:
            meta["charset"] = _safe_attr(charset_el, "charset")
        else:
            ct_el = self.soup.find("meta", attrs={"http-equiv": re.compile(r"content-type", re.I)})
            if ct_el:
                ct = _safe_attr(ct_el, "content")
                m = re.search(r"charset=([^\s;\"']+)", ct, re.I)
                meta["charset"] = m.group(1) if m else ""
            else:
                meta["charset"] = ""

        # Language
        html_el = self.soup.find("html")
        meta["language"] = _safe_attr(html_el, "lang")

        # Canonical URL
        canon_el = self.soup.find("link", attrs={"rel": "canonical"})
        meta["canonical_url"] = _safe_attr(canon_el, "href")

        # Favicon
        fav_el = (
            self.soup.find("link", attrs={"rel": re.compile(r"(shortcut )?icon", re.I)})
            or self.soup.find("link", attrs={"rel": "apple-touch-icon"})
        )
        if fav_el:
            fav_url = self._resolve_url(_safe_attr(fav_el, "href"))
            meta["favicon"] = {
                "url": fav_url,
                "local_path": self._map_to_local(fav_url),
            }
        else:
            meta["favicon"] = None

        # Open Graph image
        og_el = self.soup.find("meta", attrs={"property": "og:image"})
        if og_el:
            og_url = _safe_attr(og_el, "content")
            meta["og_image"] = {
                "url": og_url,
                "local_path": self._map_to_local(og_url),
            }
        else:
            meta["og_image"] = None

        # Extra OG tags (title, type, site_name, etc.)
        for prop in ("og:title", "og:type", "og:site_name", "og:url", "og:description"):
            el = self.soup.find("meta", attrs={"property": prop})
            key = prop.replace("og:", "og_")
            meta[key] = _safe_attr(el, "content") if el else ""

        return meta

    # ── Navigation extraction ─────────────────────────────────────────────

    def _extract_navigation(self) -> list[dict]:
        """Extract navigation structures from the page."""
        if not self.soup:
            return []

        nav_blocks: list[dict] = []
        seen_elements: set[int] = set()  # track by element id to avoid duplicates

        for selector in _NAV_SELECTORS:
            try:
                elements = self.soup.select(selector)
            except Exception:
                continue

            for el in elements:
                el_id = id(el)
                if el_id in seen_elements:
                    continue
                seen_elements.add(el_id)

                links = []
                for a in el.find_all("a", href=True):
                    href = _safe_attr(a, "href")
                    label = _text(a)
                    if label or href:
                        links.append({
                            "label": label,
                            "href": href,
                            "resolved_url": self._resolve_url(href),
                        })

                if links:
                    # Determine a label for this nav block
                    block_label = (
                        _safe_attr(el, "aria-label")
                        or _safe_attr(el, "id")
                        or _safe_attr(el, "class")
                        or el.name
                    )
                    nav_blocks.append({
                        "element": el.name,
                        "label": block_label,
                        "links": links,
                    })

        return nav_blocks

    # ── Content extraction ────────────────────────────────────────────────

    def _extract_content(self) -> dict:
        """Extract headings and content sections."""
        if not self.soup:
            return {"headings": [], "sections": []}

        headings = self._extract_headings()
        sections = self._extract_sections()

        return {
            "headings": headings,
            "sections": sections,
        }

    def _extract_headings(self) -> list[dict]:
        """Extract all h1-h6 headings with hierarchy info."""
        headings = []
        for level in range(1, 7):
            for h in self.soup.find_all(f"h{level}"):
                text = _text(h)
                if text:
                    headings.append({
                        "level": level,
                        "text": text,
                        "id": _safe_attr(h, "id"),
                    })
        # Sort by document order (already in order from find_all on soup)
        # Re-scan in document order instead
        headings_ordered: list[dict] = []
        for h in self.soup.find_all(re.compile(r"^h[1-6]$")):
            text = _text(h)
            if text:
                headings_ordered.append({
                    "level": int(h.name[1]),
                    "text": text,
                    "id": _safe_attr(h, "id"),
                })
        return headings_ordered

    def _extract_sections(self) -> list[dict]:
        """Extract content from semantic containers or fallback to <body>."""
        sections: list[dict] = []
        found_elements: set[int] = set()

        for selector in _CONTENT_SELECTORS:
            try:
                elements = self.soup.select(selector)
            except Exception:
                continue

            for el in elements:
                el_id = id(el)
                # Skip if already processed or is a child of processed element
                if el_id in found_elements:
                    continue
                # Skip navigation containers that may also match
                if el.name == "nav":
                    continue

                found_elements.add(el_id)
                section_data = self._parse_section(el)
                if section_data and self._section_has_content(section_data):
                    sections.append(section_data)

        # Fallback: if no semantic sections found, parse <body> directly
        if not sections:
            body = self.soup.find("body")
            if body:
                section_data = self._parse_section(body)
                if section_data:
                    sections.append(section_data)

        return sections

    def _parse_section(self, el: Tag) -> dict:
        """Parse a content container element into structured data."""
        section: dict = {
            "element": el.name,
            "id": _safe_attr(el, "id"),
            "class": _safe_attr(el, "class"),
        }

        # Heading (first heading within this section)
        heading_el = el.find(re.compile(r"^h[1-6]$"))
        section["heading"] = _text(heading_el) if heading_el else ""

        # Paragraphs
        section["paragraphs"] = [
            _text(p) for p in el.find_all("p", recursive=True)
            if _text(p)
        ]

        # Images
        section["images"] = []
        for img in el.find_all("img"):
            src = _safe_attr(img, "src")
            resolved = self._resolve_url(src)
            section["images"].append({
                "src": src,
                "resolved_url": resolved,
                "local_path": self._map_to_local(resolved),
                "alt": _safe_attr(img, "alt"),
                "width": _safe_attr(img, "width"),
                "height": _safe_attr(img, "height"),
            })

        # Links
        section["links"] = []
        for a in el.find_all("a", href=True):
            href = _safe_attr(a, "href")
            label = _text(a)
            if label or href:
                section["links"].append({
                    "text": label,
                    "href": href,
                    "resolved_url": self._resolve_url(href),
                })

        # Lists (ul/ol)
        section["lists"] = []
        for lst in el.find_all(["ul", "ol"], recursive=True):
            # Skip if this list is inside a nav (already extracted)
            if lst.find_parent("nav"):
                continue
            items = [_text(li) for li in lst.find_all("li", recursive=False) if _text(li)]
            if items:
                section["lists"].append({
                    "type": lst.name,
                    "items": items,
                })

        # Code blocks
        section["code_blocks"] = []
        for pre in el.find_all("pre"):
            code_el = pre.find("code")
            code_text = _text(code_el) if code_el else _text(pre)
            lang = ""
            if code_el:
                cls = _safe_attr(code_el, "class")
                lang_match = re.search(r"language-(\w+)", cls)
                if lang_match:
                    lang = lang_match.group(1)
            if code_text:
                section["code_blocks"].append({
                    "language": lang,
                    "code": code_text,
                })
        # Standalone <code> not inside <pre>
        for code_el in el.find_all("code"):
            if code_el.find_parent("pre"):
                continue
            code_text = _text(code_el)
            if code_text and len(code_text) > 20:  # skip tiny inline code
                section["code_blocks"].append({
                    "language": "",
                    "code": code_text,
                })

        # Tables
        section["tables"] = []
        for table in el.find_all("table"):
            table_data = self._parse_table(table)
            if table_data:
                section["tables"].append(table_data)

        # Blockquotes
        section["blockquotes"] = [
            _text(bq) for bq in el.find_all("blockquote")
            if _text(bq)
        ]

        return section

    @staticmethod
    def _section_has_content(section: dict) -> bool:
        """Check if a parsed section contains any meaningful content."""
        return bool(
            section.get("paragraphs")
            or section.get("images")
            or section.get("lists")
            or section.get("code_blocks")
            or section.get("tables")
            or section.get("blockquotes")
            or section.get("heading")
        )

    @staticmethod
    def _parse_table(table: Tag) -> dict | None:
        """Parse an HTML <table> into headers + rows."""
        headers: list[str] = []
        rows: list[list[str]] = []

        # Headers from <thead> or first <tr>
        thead = table.find("thead")
        if thead:
            for th in thead.find_all(["th", "td"]):
                headers.append(_text(th))
        else:
            first_row = table.find("tr")
            if first_row:
                ths = first_row.find_all("th")
                if ths:
                    headers = [_text(th) for th in ths]

        # Body rows
        tbody = table.find("tbody") or table
        for tr in tbody.find_all("tr"):
            cells = [_text(td) for td in tr.find_all(["td", "th"])]
            # Skip the header row if it was in <tbody>
            if cells == headers and not table.find("thead"):
                continue
            if any(cells):
                rows.append(cells)

        if not headers and not rows:
            return None

        return {"headers": headers, "rows": rows}

    # ── Images & Media extraction ─────────────────────────────────────────

    def _extract_images(self) -> dict:
        """Collect all images, background images, and icons."""
        if not self.soup:
            return {"img_tags": [], "background_images": [], "icons": []}

        # All <img> tags
        img_tags: list[dict] = []
        seen_srcs: set[str] = set()
        for img in self.soup.find_all("img"):
            src = _safe_attr(img, "src")
            if not src or src in seen_srcs:
                continue
            seen_srcs.add(src)
            resolved = self._resolve_url(src)
            img_tags.append({
                "src": src,
                "resolved_url": resolved,
                "local_path": self._map_to_local(resolved),
                "alt": _safe_attr(img, "alt"),
                "width": _safe_attr(img, "width"),
                "height": _safe_attr(img, "height"),
            })

        # Background images from inline styles
        bg_images: list[dict] = []
        for el in self.soup.find_all(style=True):
            style = _safe_attr(el, "style")
            for match in re.findall(r"url\(['\"]?([^)'\">]+)['\"]?\)", style):
                resolved = self._resolve_url(match)
                bg_images.append({
                    "url": match,
                    "resolved_url": resolved,
                    "local_path": self._map_to_local(resolved),
                    "element": el.name,
                })

        # Favicons and icons
        icons: list[dict] = []
        for link in self.soup.find_all("link", rel=True):
            rel_val = link.get("rel", [])
            if isinstance(rel_val, list):
                rel_str = " ".join(rel_val).lower()
            else:
                rel_str = str(rel_val).lower()

            if any(kw in rel_str for kw in ("icon", "apple-touch-icon", "shortcut")):
                href = _safe_attr(link, "href")
                if href:
                    resolved = self._resolve_url(href)
                    icons.append({
                        "rel": rel_str,
                        "href": href,
                        "resolved_url": resolved,
                        "local_path": self._map_to_local(resolved),
                        "sizes": _safe_attr(link, "sizes"),
                        "type": _safe_attr(link, "type"),
                    })

        return {
            "img_tags": img_tags,
            "background_images": bg_images,
            "icons": icons,
        }

    # ── Flow extraction ───────────────────────────────────────────────────

    def _extract_flow(self) -> dict:
        """Extract internal/external links, API calls, and redirects."""
        if not self.soup:
            return {
                "internal_links": [], "external_links": [],
                "api_calls": [], "redirects": [],
            }

        internal: list[dict] = []
        external: list[dict] = []
        seen_hrefs: set[str] = set()

        base_domain = urlparse(self.base_url).netloc.lower() if self.base_url else ""

        for a in self.soup.find_all("a", href=True):
            href = _safe_attr(a, "href")
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            resolved = self._resolve_url(href)
            link_data = {
                "text": _text(a),
                "href": href,
                "resolved_url": resolved,
            }

            parsed = urlparse(resolved)
            if (not parsed.netloc
                    or parsed.netloc.lower() == base_domain
                    or parsed.netloc.lower().endswith("." + base_domain)):
                internal.append(link_data)
            else:
                external.append(link_data)

        # API calls from api_responses/ directory
        api_calls = self._load_api_calls()

        # Redirects from manifest routes
        redirects: list[dict] = []
        for url, target in self.routes.items():
            if isinstance(target, str) and target.startswith("redirect:"):
                parts = target.split(":", 2)
                status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                dest = parts[2] if len(parts) > 2 else ""
                redirects.append({
                    "from_url": url,
                    "to_url": dest,
                    "status": status,
                })

        return {
            "internal_links": internal,
            "external_links": external,
            "api_calls": api_calls,
            "redirects": redirects,
        }

    def _load_api_calls(self) -> list[dict]:
        """Load API response data from api_responses/*.json files."""
        api_dir = self.snap_dir / "api_responses"
        if not api_dir.is_dir():
            return []

        calls: list[dict] = []
        for json_file in sorted(api_dir.glob("*.json")):
            try:
                raw = json_file.read_text(encoding="utf-8")
                entry = json.loads(raw)
                calls.append({
                    "id": entry.get("id", json_file.stem),
                    "url": entry.get("url", ""),
                    "method": entry.get("method", ""),
                    "status": entry.get("response", {}).get("status"),
                    "recorded_at": entry.get("recorded_at", ""),
                    "file": str(json_file.relative_to(self.snap_dir)),
                })
            except (json.JSONDecodeError, OSError) as exc:
                log("WARN", f"Cannot read API response {json_file.name}: {exc}")

        return calls

    # ── Asset classification ──────────────────────────────────────────────

    def _extract_assets(self) -> dict:
        """Classify all assets from manifest routes by type."""
        css: list[dict] = []
        js: list[dict] = []
        fonts: list[dict] = []
        images: list[dict] = []
        other: list[dict] = []

        for url, local_path in self.routes.items():
            if isinstance(local_path, str) and local_path.startswith("redirect:"):
                continue

            category = _classify_asset(local_path)
            entry = {
                "url": url,
                "local_path": local_path.replace("\\", "/"),
            }

            if category == "css":
                css.append(entry)
            elif category == "js":
                js.append(entry)
            elif category == "font":
                fonts.append(entry)
            elif category == "image":
                images.append(entry)
            elif category != "html":
                other.append(entry)

        return {
            "css": css,
            "js": js,
            "fonts": fonts,
            "images": images,
            "other": other,
            "total_count": len(css) + len(js) + len(fonts) + len(images) + len(other),
        }
