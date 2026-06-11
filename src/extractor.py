"""
Content Extractor for SaveTheWeb snapshots.

Parses final_page.html from a snapshot directory and extracts structured
content data (metadata, navigation, content sections, images, links, assets)
into a JSON file.

Supports both flat extraction (for backwards compatibility and markdown generation)
and a new hierarchical area-based extraction mode that preserves the nested structure
of DOM components (e.g. associating book covers, titles, descriptions, and metadata).

Usage:
    from src.extractor import ContentExtractor

    extractor = ContentExtractor("web_archive/snapshots/example.com_20260605_194745")
    data = extractor.extract()
    # => writes extracted_data.json and returns the dict
"""

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag, NavigableString

from src.utils import log


# ──────────────────────────────────────────────────────────────────────────────
# Configurations & Selectors
# ──────────────────────────────────────────────────────────────────────────────

_NAV_SELECTORS = [
    "nav", "header", "[role='navigation']",
    ".navbar", ".nav", ".navigation", ".menu", ".header-nav",
    "#nav", "#menu", "#navigation", "#header-nav",
]

_CONTENT_SELECTORS = [
    "article", "main", "[role='main']",
    ".content", ".main-content", ".post-content", ".article-body",
    ".entry-content", ".page-content", ".post-body",
    "#content", "#main", "#main-content",
    "section",
]

_LAYOUT_CLASSES = {
    "row", "col", "grid", "container", "clearfix", "d-flex", "flex", 
    "active", "hide", "show", "visible", "invisible", "disabled"
}

_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".bmp", ".ico", ".tiff"}
_FONT_EXTS = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
_CSS_EXTS = {".css"}
_JS_EXTS = {".js"}


# ──────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────────────────────────────────────

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


def _should_skip_tag(el: Tag) -> bool:
    """Filter out non-content layout elements during hierarchical parsing."""
    if el.name in {"script", "style", "noscript", "iframe", "svg", "canvas", "br", "hr", "header", "footer", "nav"}:
        return True
    cls = _safe_attr(el, "class").lower()
    eid = _safe_attr(el, "id").lower()
    for keyword in ("header", "footer", "nav", "menu", "sidebar", "ad-", "banner", "popup", "modal", "comment-form"):
        if keyword in cls or keyword in eid:
            return True
    return False


def _get_semantic_key(el: Tag) -> str:
    """Determine a semantic key for a Tag based on class/id/tag name, ignoring layout utilities."""
    classes = el.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    
    # Check for first class name that is not a generic layout utility
    for cls in classes:
        cls_clean = cls.strip().lower()
        if cls_clean not in _LAYOUT_CLASSES and not re.match(r'^col-\w+-\d+$', cls_clean):
            return cls.strip()
            
    # Fallback to ID if present
    eid = el.get("id")
    if eid and isinstance(eid, str) and eid.strip():
        return eid.strip()
        
    # Fallback to defaults
    if el.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return "title"
    if el.name == "p":
        return "description"
        
    return el.name


# ──────────────────────────────────────────────────────────────────────────────
# URLResolver
# ──────────────────────────────────────────────────────────────────────────────

class URLResolver:
    """Resolves relative URLs and maps absolute URLs to local snapshot files."""
    def __init__(self, base_url: str, routes: dict):
        self.base_url = base_url
        self.routes = routes

    def resolve(self, url: str) -> str:
        """Resolve a relative URL against the base URL, avoiding double slash issues."""
        if not url or url.startswith(("data:", "javascript:", "mailto:", "tel:", "#")):
            return url
        if url.startswith(("http://", "https://", "//")):
            return url
        if self.base_url:
            base = self.base_url if self.base_url.endswith("/") else self.base_url + "/"
            return urljoin(base, url)
        return url

    def map_to_local(self, url: str) -> str | None:
        """Look up the absolute URL in manifest routes and return the local path."""
        if not url or not self.routes:
            return None

        # Exact match
        local = self.routes.get(url)
        if local and not local.startswith("redirect:"):
            return local.replace("\\", "/")

        # Trailing slash variants
        alt = url.rstrip("/") if url.endswith("/") else url + "/"
        local = self.routes.get(alt)
        if local and not local.startswith("redirect:"):
            return local.replace("\\", "/")

        # Scheme-agnostic check
        parsed = urlparse(url)
        for route_url, route_path in self.routes.items():
            rp = urlparse(route_url)
            if (rp.netloc == parsed.netloc
                    and rp.path == parsed.path
                    and rp.query == parsed.query
                    and not route_path.startswith("redirect:")):
                return route_path.replace("\\", "/")

        return None


# ──────────────────────────────────────────────────────────────────────────────
# MetadataExtractor
# ──────────────────────────────────────────────────────────────────────────────

class MetadataExtractor:
    """Extracts page metadata from HTML <head>."""
    def __init__(self, soup: BeautifulSoup, resolver: URLResolver):
        self.soup = soup
        self.resolver = resolver

    def extract(self) -> dict:
        if not self.soup:
            return {}

        meta = {}

        # Title
        title_el = self.soup.find("title")
        meta["title"] = _text(title_el)

        # Description
        desc_el = self.soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        meta["description"] = _safe_attr(desc_el, "content")

        # Charset
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

        # Canonical
        canon_el = self.soup.find("link", attrs={"rel": "canonical"})
        meta["canonical_url"] = _safe_attr(canon_el, "href")

        # Favicon
        fav_el = (
            self.soup.find("link", attrs={"rel": re.compile(r"(shortcut )?icon", re.I)})
            or self.soup.find("link", attrs={"rel": "apple-touch-icon"})
        )
        if fav_el:
            fav_url = self.resolver.resolve(_safe_attr(fav_el, "href"))
            meta["favicon"] = {
                "url": fav_url,
                "local_path": self.resolver.map_to_local(fav_url),
            }
        else:
            meta["favicon"] = None

        # OG Image
        og_el = self.soup.find("meta", attrs={"property": "og:image"})
        if og_el:
            og_url = _safe_attr(og_el, "content")
            meta["og_image"] = {
                "url": og_url,
                "local_path": self.resolver.map_to_local(og_url),
            }
        else:
            meta["og_image"] = None

        # OG details
        for prop in ("og:title", "og:type", "og:site_name", "og:url", "og:description"):
            el = self.soup.find("meta", attrs={"property": prop})
            key = prop.replace("og:", "og_")
            meta[key] = _safe_attr(el, "content") if el else ""

        return meta


# ──────────────────────────────────────────────────────────────────────────────
# NavigationExtractor
# ──────────────────────────────────────────────────────────────────────────────

class NavigationExtractor:
    """Extracts navigation links and structure."""
    def __init__(self, soup: BeautifulSoup, resolver: URLResolver):
        self.soup = soup
        self.resolver = resolver

    def extract(self) -> list[dict]:
        if not self.soup:
            return []

        nav_blocks = []
        seen_elements = set()

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
                            "resolved_url": self.resolver.resolve(href),
                        })

                if links:
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


# ──────────────────────────────────────────────────────────────────────────────
# AssetFlowExtractor
# ──────────────────────────────────────────────────────────────────────────────

class AssetFlowExtractor:
    """Classifies static assets and logs internal/external routes + API calls."""
    def __init__(self, soup: BeautifulSoup, resolver: URLResolver, snap_dir: Path, routes: dict):
        self.soup = soup
        self.resolver = resolver
        self.snap_dir = snap_dir
        self.routes = routes

    def extract_images(self) -> dict:
        if not self.soup:
            return {"img_tags": [], "background_images": [], "icons": []}

        img_tags = []
        seen_srcs = set()
        for img in self.soup.find_all("img"):
            src = _safe_attr(img, "src")
            if not src or src in seen_srcs:
                continue
            seen_srcs.add(src)
            resolved = self.resolver.resolve(src)
            img_tags.append({
                "src": src,
                "resolved_url": resolved,
                "local_path": self.resolver.map_to_local(resolved),
                "alt": _safe_attr(img, "alt"),
                "width": _safe_attr(img, "width"),
                "height": _safe_attr(img, "height"),
            })

        bg_images = []
        for el in self.soup.find_all(style=True):
            style = _safe_attr(el, "style")
            for match in re.findall(r"url\(['\"]?([^)'\">]+)['\"]?\)", style):
                resolved = self.resolver.resolve(match)
                bg_images.append({
                    "url": match,
                    "resolved_url": resolved,
                    "local_path": self.resolver.map_to_local(resolved),
                    "element": el.name,
                })

        icons = []
        for link in self.soup.find_all("link", rel=True):
            rel_val = link.get("rel", [])
            rel_str = " ".join(rel_val).lower() if isinstance(rel_val, list) else str(rel_val).lower()

            if any(kw in rel_str for kw in ("icon", "apple-touch-icon", "shortcut")):
                href = _safe_attr(link, "href")
                if href:
                    resolved = self.resolver.resolve(href)
                    icons.append({
                        "rel": rel_str,
                        "href": href,
                        "resolved_url": resolved,
                        "local_path": self.resolver.map_to_local(resolved),
                        "sizes": _safe_attr(link, "sizes"),
                        "type": _safe_attr(link, "type"),
                    })

        return {
            "img_tags": img_tags,
            "background_images": bg_images,
            "icons": icons,
        }

    def extract_flow(self) -> dict:
        if not self.soup:
            return {
                "internal_links": [], "external_links": [],
                "api_calls": [], "redirects": [],
            }

        internal = []
        external = []
        seen_hrefs = set()
        base_domain = urlparse(self.resolver.base_url).netloc.lower() if self.resolver.base_url else ""

        for a in self.soup.find_all("a", href=True):
            href = _safe_attr(a, "href")
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            resolved = self.resolver.resolve(href)
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

        api_calls = self._load_api_calls()

        redirects = []
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
        api_dir = self.snap_dir / "api_responses"
        if not api_dir.is_dir():
            return []

        calls = []
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
            except Exception as exc:
                log("WARN", f"Cannot read API response {json_file.name}: {exc}")

        return calls

    def extract_assets(self) -> dict:
        css = []
        js = []
        fonts = []
        images = []
        other = []

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


# ──────────────────────────────────────────────────────────────────────────────
# StructuredContentExtractor (Flat & Hierarchical/Area Modes)
# ──────────────────────────────────────────────────────────────────────────────

class StructuredContentExtractor:
    """Extracts flat paragraphs/tables/code and the new exact DOM hierarchical area trees."""
    def __init__(self, soup: BeautifulSoup, resolver: URLResolver):
        self.soup = soup
        self.resolver = resolver

    def extract(self) -> dict:
        if not self.soup:
            return {"headings": [], "sections": [], "hierarchical_areas": []}

        return {
            "headings": self._extract_headings(),
            "sections": self._extract_flat_sections(),
            "hierarchical_areas": self._extract_hierarchical_areas(),
        }

    def _extract_headings(self) -> list[dict]:
        headings_ordered = []
        for h in self.soup.find_all(re.compile(r"^h[1-6]$")):
            text = _text(h)
            if text:
                headings_ordered.append({
                    "level": int(h.name[1]),
                    "text": text,
                    "id": _safe_attr(h, "id"),
                })
        return headings_ordered

    def _extract_flat_sections(self) -> list[dict]:
        sections = []
        found_elements = set()

        for selector in _CONTENT_SELECTORS:
            try:
                elements = self.soup.select(selector)
            except Exception:
                continue

            for el in elements:
                el_id = id(el)
                if el_id in found_elements:
                    continue
                if el.name == "nav":
                    continue

                found_elements.add(el_id)
                section_data = self._parse_flat_section(el)
                if section_data and self._section_has_content(section_data):
                    sections.append(section_data)

        if not sections:
            body = self.soup.find("body")
            if body:
                section_data = self._parse_flat_section(body)
                if section_data:
                    sections.append(section_data)

        return sections

    def _parse_flat_section(self, el: Tag) -> dict:
        section = {
            "element": el.name,
            "id": _safe_attr(el, "id"),
            "class": _safe_attr(el, "class"),
        }

        heading_el = el.find(re.compile(r"^h[1-6]$"))
        section["heading"] = _text(heading_el) if heading_el else ""

        section["paragraphs"] = [
            _text(p) for p in el.find_all("p", recursive=True)
            if _text(p)
        ]

        section["images"] = []
        for img in el.find_all("img"):
            src = _safe_attr(img, "src")
            resolved = self.resolver.resolve(src)
            section["images"].append({
                "src": src,
                "resolved_url": resolved,
                "local_path": self.resolver.map_to_local(resolved),
                "alt": _safe_attr(img, "alt"),
                "width": _safe_attr(img, "width"),
                "height": _safe_attr(img, "height"),
            })

        section["links"] = []
        for a in el.find_all("a", href=True):
            href = _safe_attr(a, "href")
            label = _text(a)
            if label or href:
                section["links"].append({
                    "text": label,
                    "href": href,
                    "resolved_url": self.resolver.resolve(href),
                })

        section["lists"] = []
        for lst in el.find_all(["ul", "ol"], recursive=True):
            if lst.find_parent("nav"):
                continue
            items = [_text(li) for li in lst.find_all("li", recursive=False) if _text(li)]
            if items:
                section["lists"].append({
                    "type": lst.name,
                    "items": items,
                })

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

        for code_el in el.find_all("code"):
            if code_el.find_parent("pre"):
                continue
            code_text = _text(code_el)
            if code_text and len(code_text) > 20:
                section["code_blocks"].append({
                    "language": "",
                    "code": code_text,
                })

        section["tables"] = []
        for table in el.find_all("table"):
            table_data = self._parse_table(table)
            if table_data:
                section["tables"].append(table_data)

        section["blockquotes"] = [
            _text(bq) for bq in el.find_all("blockquote")
            if _text(bq)
        ]

        return section

    def _section_has_content(self, section: dict) -> bool:
        return bool(
            section.get("paragraphs")
            or section.get("images")
            or section.get("lists")
            or section.get("code_blocks")
            or section.get("tables")
            or section.get("blockquotes")
            or section.get("heading")
        )

    def _parse_table(self, table: Tag) -> dict | None:
        headers = []
        rows = []

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

        tbody = table.find("tbody") or table
        for tr in tbody.find_all("tr"):
            cells = [_text(td) for td in tr.find_all(["td", "th"])]
            if cells == headers and not table.find("thead"):
                continue
            if any(cells):
                rows.append(cells)

        if not headers and not rows:
            return None

        return {"headers": headers, "rows": rows}

    def _extract_hierarchical_areas(self) -> list[dict]:
        """Runs the DOM recursive hierarchical builder starting from main content areas."""
        areas = []
        found_elements = set()

        for selector in _CONTENT_SELECTORS:
            try:
                elements = self.soup.select(selector)
            except Exception:
                continue

            for el in elements:
                el_id = id(el)
                if el_id in found_elements:
                    continue
                if el.name == "nav" or _should_skip_tag(el):
                    continue

                found_elements.add(el_id)
                parsed = self._parse_hierarchical_element(el)
                if parsed:
                    areas.append({
                        "element": el.name,
                        "id": _safe_attr(el, "id"),
                        "class": _safe_attr(el, "class"),
                        "data": parsed
                    })

        # Fallback to body
        if not areas:
            body = self.soup.find("body")
            if body:
                parsed = self._parse_hierarchical_element(body)
                if parsed:
                    areas.append({
                        "element": "body",
                        "id": _safe_attr(body, "id"),
                        "class": _safe_attr(body, "class"),
                        "data": parsed
                    })

        return areas

    def _parse_hierarchical_element(self, el: Tag) -> dict | list | str | None:
        """Recursively parses a Tag into a detailed dictionary layout mapping DOM layout to JSON attributes."""
        if not isinstance(el, Tag):
            return None

        if _should_skip_tag(el):
            return None

        child_tags = [c for c in el.contents if isinstance(c, Tag) and not _should_skip_tag(c)]

        # 1. Handle leaf tags (no significant Tag children)
        if not child_tags:
            if el.name == "img":
                src = self.resolver.resolve(_safe_attr(el, "src"))
                local_path = self.resolver.map_to_local(src)
                alt = _safe_attr(el, "alt")
                cls = _get_semantic_key(el)
                
                if cls and cls != "img":
                    return {
                        f"{cls}_src": src,
                        f"{cls}_alt": alt,
                        f"{cls}_local": local_path
                    }
                else:
                    key_prefix = "icon" if ("ico" in src or "icon" in src or "user" in src) else "img"
                    return {
                        f"{key_prefix}_src": src,
                        f"{key_prefix}_alt": alt,
                        f"{key_prefix}_local": local_path
                    }
            elif el.name == "a":
                href = self.resolver.resolve(_safe_attr(el, "href"))
                text = _text(el)
                cls = _get_semantic_key(el)
                if cls and cls != "a":
                    return {
                        f"{cls}_href": href,
                        f"{cls}_name": text
                    }
                else:
                    return {
                        "href": href,
                        "text": text
                    }
            else:
                # Other leaf tags like span, i, b, p, h1-h6
                text = _text(el)
                if not text:
                    return None
                cls = _get_semantic_key(el)
                if cls == el.name:
                    return text
                return {cls: text}

        # 2. Handle a tag with a single img child (link-image wrapper)
        if el.name == "a" and len(child_tags) == 1 and child_tags[0].name == "img":
            img_el = child_tags[0]
            href = self.resolver.resolve(_safe_attr(el, "href"))
            src = self.resolver.resolve(_safe_attr(img_el, "src"))
            local_path = self.resolver.map_to_local(src)
            alt = _safe_attr(img_el, "alt")
            
            cls = _get_semantic_key(el)
            if not cls or cls == "a":
                cls = _get_semantic_key(img_el)
            
            if cls and cls != "img" and cls != "a":
                return {
                    f"{cls}_href": href,
                    f"{cls}_src": src,
                    f"{cls}_alt": alt,
                    f"{cls}_local": local_path
                }
            else:
                return {
                    "href": href,
                    "img_src": src,
                    "img_alt": alt,
                    "img_local": local_path
                }

        # 3. Handle headings containing text and possibly a link
        if el.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            text = _text(el)
            a_child = el.find("a")
            if a_child and isinstance(a_child, Tag):
                href = self.resolver.resolve(_safe_attr(a_child, "href"))
                return {
                    "title": text,
                    "title_href": href
                }
            else:
                return {
                    "title": text
                }

        # 4. Handle lists (ul, ol)
        if el.name in {"ul", "ol"}:
            items = []
            for li in el.find_all("li", recursive=False):
                li_val = self._parse_hierarchical_element(li)
                if li_val:
                    items.append(li_val)
            return items if items else None

        # 5. Handle generic container tags (div, li, section, etc.)
        res_dict = {}
        
        # Check direct text inside container (e.g. text nodes mixed with child elements)
        direct_text = "".join(c for c in el.contents if isinstance(c, NavigableString)).strip()
        if direct_text:
            res_dict["text"] = re.sub(r"\s+", " ", direct_text)

        for child in child_tags:
            child_val = self._parse_hierarchical_element(child)
            if not child_val:
                continue

            # Check if the child tag represents a leaf node structure (including headings)
            is_leaf_child = (
                (not [c for c in child.contents if isinstance(c, Tag) and not _should_skip_tag(c)]) or 
                (child.name == "a" and len([c for c in child.contents if isinstance(c, Tag) and not _should_skip_tag(c)]) == 1 and child.contents[0].name == "img") or
                (child.name in {"h1", "h2", "h3", "h4", "h5", "h6"})
            )

            if is_leaf_child and isinstance(child_val, dict):
                # Flat-merge properties of simple leaf children directly into the container dict
                for k, v in child_val.items():
                    if k not in res_dict:
                        res_dict[k] = v
                    else:
                        if not isinstance(res_dict[k], list):
                            res_dict[k] = [res_dict[k]]
                        res_dict[k].append(v)
            else:
                child_key = _get_semantic_key(child)
                
                # Simplify if child_val is a dict with only one key matching child_key
                if isinstance(child_val, dict) and len(child_val) == 1 and child_key in child_val:
                    child_val = child_val[child_key]

                if child_key not in res_dict:
                    res_dict[child_key] = child_val
                else:
                    if not isinstance(res_dict[child_key], list):
                        res_dict[child_key] = [res_dict[child_key]]
                    res_dict[child_key].append(child_val)

        return res_dict if res_dict else None


# ──────────────────────────────────────────────────────────────────────────────
# ContentExtractor (Facade Interface)
# ──────────────────────────────────────────────────────────────────────────────

class ContentExtractor:
    """
    Orchestrates the full extraction workflow on a SaveTheWeb snapshot.
    Delegates parsing to specialized, single-responsibility extractor classes.
    """

    def __init__(self, snapshot_dir: str | Path):
        self.snap_dir = Path(snapshot_dir)
        self.html_path = self.snap_dir / "final_page.html"
        self.manifest_path = self.snap_dir / "manifest.json"
        self.manifest: dict = {}
        self.routes: dict = {}
        self.soup: BeautifulSoup | None = None
        self.base_url: str = ""

    def extract(self) -> dict:
        """
        Run the extraction pipeline and write the output into extracted_data.json.
        """
        self._load_manifest()
        self._load_html()

        resolver = URLResolver(self.base_url, self.routes)
        metadata_extractor = MetadataExtractor(self.soup, resolver)
        navigation_extractor = NavigationExtractor(self.soup, resolver)
        content_extractor = StructuredContentExtractor(self.soup, resolver)
        asset_flow_extractor = AssetFlowExtractor(self.soup, resolver, self.snap_dir, self.routes)

        data = {
            "snapshot_id": self.manifest.get("id", self.snap_dir.name),
            "source_url": self.base_url,
            "recorded_at": self.manifest.get("recorded_at", ""),
            "meta": metadata_extractor.extract(),
            "navigation": navigation_extractor.extract(),
            "content": content_extractor.extract(),
            "images": asset_flow_extractor.extract_images(),
            "flow": asset_flow_extractor.extract_flow(),
            "assets": asset_flow_extractor.extract_assets(),
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

    def _load_manifest(self):
        """Load manifest.json properties."""
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
        """Load and parse final_page.html."""
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
