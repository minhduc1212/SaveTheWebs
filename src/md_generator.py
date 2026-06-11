"""
Markdown Generator for SaveTheWeb extracted data.

Converts the structured JSON output from ContentExtractor into a clean,
human-readable Markdown document with YAML frontmatter, table of contents,
embedded images, tables, code blocks, and a Mermaid site-flow diagram.

Usage:
    from src.md_generator import MarkdownGenerator

    # From an extracted_data.json file:
    gen = MarkdownGenerator("web_archive/snapshots/example.com_20260605_194745/extracted_data.json")
    gen.generate()  # => writes content.md

    # Or from a dict directly:
    gen = MarkdownGenerator(data=extracted_dict)
    gen.generate(output_path="web_archive/snapshots/.../content.md")
"""

import json
import re
from pathlib import Path
from textwrap import dedent

from src.utils import log


class MarkdownGenerator:
    """
    Converts extracted snapshot data (JSON) into a Markdown document.

    The output includes:
        - YAML frontmatter with metadata
        - Banner/hero image (if available)
        - Auto-generated table of contents from headings
        - Content sections with proper heading hierarchy
        - Images embedded with local relative paths
        - Tables, lists, code blocks, blockquotes preserved
        - Navigation structure
        - Site flow diagram as a Mermaid code block
        - Asset summary table
    """

    def __init__(
        self,
        json_path: str | Path | None = None,
        *,
        data: dict | None = None,
    ):
        """
        Args:
            json_path: Path to extracted_data.json (also determines output dir).
            data:      Pre-loaded extracted data dict.  If both are given,
                       ``data`` takes priority.
        """
        self.json_path: Path | None = Path(json_path) if json_path else None
        self.data: dict = data or {}
        self.snap_dir: Path | None = self.json_path.parent if self.json_path else None

        if not self.data and self.json_path:
            self._load_json()

    # ── Public API ────────────────────────────────────────────────────────

    def generate(self, output_path: str | Path | None = None) -> str:
        """
        Generate the Markdown string and optionally write it to disk.

        Args:
            output_path: Where to write the .md file.  Defaults to
                         ``content.md`` in the same directory as the JSON.

        Returns:
            The full Markdown string.
        """
        parts: list[str] = [
            self._build_frontmatter(),
            self._build_banner(),
            self._build_toc(),
            self._build_content_sections(),
            self._build_navigation_section(),
            self._build_flow_section(),
            self._build_asset_summary(),
        ]

        md = "\n".join(p for p in parts if p)

        # Determine output path
        if output_path is None and self.snap_dir:
            output_path = self.snap_dir / "content.md"

        if output_path:
            out = Path(output_path)
            try:
                out.write_text(md, encoding="utf-8")
                log("OK", f"Markdown generated → {out.name}  ({out.parent.name})")
            except OSError as exc:
                log("ERR", f"Failed to write {out}: {exc}")

        return md

    @staticmethod
    def generate_all(archive_dir: str | Path = "web_archive") -> int:
        """
        Generate Markdown for every snapshot that has extracted_data.json.

        Returns:
            Number of Markdown files generated.
        """
        archive_root = Path(archive_dir)
        snap_root = archive_root / "snapshots"
        count = 0

        if not snap_root.is_dir():
            log("WARN", f"No snapshots directory in {archive_root}")
            return 0

        for snap_dir in sorted(snap_root.iterdir()):
            json_path = snap_dir / "extracted_data.json"
            if not json_path.exists():
                continue
            try:
                gen = MarkdownGenerator(json_path)
                gen.generate()
                count += 1
            except Exception as exc:
                log("ERR", f"Markdown generation failed for {snap_dir.name}: {exc}")

        log("OK", f"Generated {count} Markdown file(s) from {archive_root}")
        return count

    # ── Loading ───────────────────────────────────────────────────────────

    def _load_json(self):
        """Load extracted_data.json."""
        if not self.json_path or not self.json_path.exists():
            log("WARN", f"extracted_data.json not found: {self.json_path}")
            return

        try:
            raw = self.json_path.read_text(encoding="utf-8")
            self.data = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            log("ERR", f"Failed to load extracted data: {exc}")

    # ── Frontmatter ───────────────────────────────────────────────────────

    def _build_frontmatter(self) -> str:
        """Build YAML frontmatter block."""
        meta = self.data.get("meta", {})
        lines = [
            "---",
            f"title: \"{_yaml_escape(meta.get('title', ''))}\"",
            f"url: \"{_yaml_escape(self.data.get('source_url', ''))}\"",
            f"snapshot_id: \"{_yaml_escape(self.data.get('snapshot_id', ''))}\"",
            f"recorded_at: \"{_yaml_escape(self.data.get('recorded_at', ''))}\"",
            f"description: \"{_yaml_escape(meta.get('description', ''))}\"",
            f"language: \"{_yaml_escape(meta.get('language', ''))}\"",
            f"charset: \"{_yaml_escape(meta.get('charset', ''))}\"",
        ]
        if meta.get("canonical_url"):
            lines.append(f"canonical_url: \"{_yaml_escape(meta['canonical_url'])}\"")
        if meta.get("og_title"):
            lines.append(f"og_title: \"{_yaml_escape(meta['og_title'])}\"")
        lines.append("---")
        return "\n".join(lines) + "\n"

    # ── Banner / Hero ─────────────────────────────────────────────────────

    def _build_banner(self) -> str:
        """Embed the OG image or first content image as a banner."""
        meta = self.data.get("meta", {})

        # Try OG image first
        og = meta.get("og_image")
        if og and isinstance(og, dict):
            path = og.get("local_path") or og.get("url", "")
            if path:
                return f"![Banner]({path})\n"

        # Fallback: first image from content
        images = self.data.get("images", {})
        img_tags = images.get("img_tags", []) if isinstance(images, dict) else []
        if img_tags:
            first = img_tags[0]
            path = first.get("local_path") or first.get("src", "")
            alt = first.get("alt", "Banner")
            if path:
                return f"![{_md_escape(alt)}]({path})\n"

        return ""

    # ── Table of Contents ─────────────────────────────────────────────────

    def _build_toc(self) -> str:
        """Generate a table of contents from extracted headings."""
        content = self.data.get("content", {})
        headings = content.get("headings", [])

        if not headings:
            return ""

        lines = ["## Table of Contents\n"]
        for h in headings:
            level = h.get("level", 2)
            text = h.get("text", "")
            if not text:
                continue
            anchor = _slugify(text)
            indent = "  " * (level - 1)
            lines.append(f"{indent}- [{_md_escape(text)}](#{anchor})")

        return "\n".join(lines) + "\n"

    # ── Content Sections ──────────────────────────────────────────────────

    def _build_content_sections(self) -> str:
        """Build Markdown for all extracted content sections."""
        content = self.data.get("content", {})
        sections = content.get("sections", [])

        if not sections:
            return ""

        parts: list[str] = ["## Content\n"]

        for section in sections:
            section_md = self._render_section(section)
            if section_md.strip():
                parts.append(section_md)

        return "\n".join(parts) + "\n"

    def _render_section(self, section: dict) -> str:
        """Render a single content section to Markdown."""
        lines: list[str] = []

        # Section heading
        heading = section.get("heading", "")
        if heading:
            lines.append(f"### {_md_escape(heading)}\n")

        # Paragraphs
        for para in section.get("paragraphs", []):
            if para:
                lines.append(f"{para}\n")

        # Images
        for img in section.get("images", []):
            path = img.get("local_path") or img.get("src", "")
            alt = img.get("alt", "")
            if path:
                lines.append(f"![{_md_escape(alt)}]({path})\n")

        # Lists
        for lst in section.get("lists", []):
            list_type = lst.get("type", "ul")
            for i, item in enumerate(lst.get("items", []), 1):
                if list_type == "ol":
                    lines.append(f"{i}. {item}")
                else:
                    lines.append(f"- {item}")
            lines.append("")

        # Code blocks
        for block in section.get("code_blocks", []):
            lang = block.get("language", "")
            code = block.get("code", "")
            lines.append(f"```{lang}")
            lines.append(code)
            lines.append("```\n")

        # Tables
        for table in section.get("tables", []):
            table_md = _render_md_table(
                table.get("headers", []),
                table.get("rows", []),
            )
            if table_md:
                lines.append(table_md)

        # Blockquotes
        for bq in section.get("blockquotes", []):
            quoted = "\n".join(f"> {line}" for line in bq.split("\n"))
            lines.append(f"{quoted}\n")

        # Links summary (only if there are links not covered by paragraphs)
        links = section.get("links", [])
        if links and not section.get("paragraphs"):
            lines.append("**Links:**\n")
            for link in links[:30]:  # cap to avoid massive lists
                text = link.get("text", link.get("href", ""))
                href = link.get("href", "")
                if text and href:
                    lines.append(f"- [{_md_escape(text)}]({href})")
            lines.append("")

        return "\n".join(lines)

    # ── Navigation ────────────────────────────────────────────────────────

    def _build_navigation_section(self) -> str:
        """Build Markdown for the navigation structure."""
        nav_blocks = self.data.get("navigation", [])
        if not nav_blocks:
            return ""

        lines = ["## Navigation\n"]

        for block in nav_blocks:
            label = block.get("label", "Navigation")
            element = block.get("element", "")
            lines.append(f"### {_md_escape(label)} (`<{element}>`)\n")

            for link in block.get("links", []):
                text = link.get("label", "")
                href = link.get("href", "")
                if text and href:
                    lines.append(f"- [{_md_escape(text)}]({href})")
                elif text:
                    lines.append(f"- {text}")
            lines.append("")

        return "\n".join(lines) + "\n"

    # ── Flow / Site Map ───────────────────────────────────────────────────

    def _build_flow_section(self) -> str:
        """Build flow section with link summary and a Mermaid diagram."""
        flow = self.data.get("flow", {})
        if not flow:
            return ""

        internal = flow.get("internal_links", [])
        external = flow.get("external_links", [])
        api_calls = flow.get("api_calls", [])
        redirects = flow.get("redirects", [])

        lines = ["## Site Flow\n"]

        # Summary counts
        lines.append(
            f"- **Internal links:** {len(internal)}  \n"
            f"- **External links:** {len(external)}  \n"
            f"- **API calls:** {len(api_calls)}  \n"
            f"- **Redirects:** {len(redirects)}  \n"
        )

        # Mermaid diagram — show up to 20 nodes to keep it readable
        mermaid = self._build_mermaid_diagram(internal, external, api_calls, redirects)
        if mermaid:
            lines.append(mermaid)

        # API calls table
        if api_calls:
            lines.append("### API Calls\n")
            headers = ["Method", "URL", "Status", "File"]
            rows = []
            for call in api_calls:
                rows.append([
                    call.get("method", ""),
                    _truncate(call.get("url", ""), 80),
                    str(call.get("status", "")),
                    call.get("file", ""),
                ])
            lines.append(_render_md_table(headers, rows))

        # Redirects table
        if redirects:
            lines.append("### Redirects\n")
            headers = ["From", "To", "Status"]
            rows = [
                [
                    _truncate(r.get("from_url", ""), 60),
                    _truncate(r.get("to_url", ""), 60),
                    str(r.get("status", "")),
                ]
                for r in redirects
            ]
            lines.append(_render_md_table(headers, rows))

        return "\n".join(lines) + "\n"

    def _build_mermaid_diagram(
        self,
        internal: list[dict],
        external: list[dict],
        api_calls: list[dict],
        redirects: list[dict],
    ) -> str:
        """Generate a Mermaid flowchart of the site structure."""
        # Keep diagram compact: limit nodes
        MAX_NODES = 15
        lines = ["```mermaid", "graph LR"]

        source_url = self.data.get("source_url", "page")
        source_label = _mermaid_label(source_url)
        lines.append(f"  PAGE[\"{source_label}\"]")

        node_count = 1

        # Internal links
        for link in internal[:MAX_NODES]:
            if node_count >= MAX_NODES:
                break
            href = link.get("href", "")
            label = link.get("text", "") or href
            node_id = f"INT{node_count}"
            lines.append(f"  PAGE --> {node_id}[\"{_mermaid_label(label)}\"]")
            node_count += 1

        # External links (show a few)
        for link in external[:5]:
            if node_count >= MAX_NODES:
                break
            href = link.get("href", "")
            label = link.get("text", "") or href
            node_id = f"EXT{node_count}"
            lines.append(f"  PAGE -.-> {node_id}[\"{_mermaid_label(label)}\"]")
            node_count += 1

        # API calls
        for call in api_calls[:5]:
            if node_count >= MAX_NODES:
                break
            method = call.get("method", "")
            url = call.get("url", "")
            node_id = f"API{node_count}"
            label = f"{method} {_mermaid_label(url)}"
            lines.append(f"  PAGE ==> {node_id}[\"{label}\"]")
            node_count += 1

        # Redirects
        for redir in redirects[:3]:
            if node_count >= MAX_NODES:
                break
            from_url = redir.get("from_url", "")
            to_url = redir.get("to_url", "")
            node_id = f"RED{node_count}"
            lines.append(
                f"  {node_id}[\"{_mermaid_label(from_url)}\"] "
                f"-->|{redir.get('status', '')}| "
                f"RED{node_count}T[\"{_mermaid_label(to_url)}\"]"
            )
            node_count += 1

        lines.append("```\n")

        # Only emit if there are connections beyond just the page node
        if node_count <= 1:
            return ""

        return "\n".join(lines)

    # ── Asset Summary ─────────────────────────────────────────────────────

    def _build_asset_summary(self) -> str:
        """Build an asset summary table."""
        assets = self.data.get("assets", {})
        if not assets:
            return ""

        lines = ["## Assets\n"]

        summary_rows = [
            ["CSS", str(len(assets.get("css", [])))],
            ["JavaScript", str(len(assets.get("js", [])))],
            ["Fonts", str(len(assets.get("fonts", [])))],
            ["Images", str(len(assets.get("images", [])))],
            ["Other", str(len(assets.get("other", [])))],
            ["**Total**", f"**{assets.get('total_count', 0)}**"],
        ]
        lines.append(_render_md_table(["Type", "Count"], summary_rows))

        # List individual assets per category (collapsed for readability)
        for category in ("css", "js", "fonts", "images"):
            items = assets.get(category, [])
            if not items:
                continue
            cat_label = category.upper() if category in ("css", "js") else category.capitalize()
            lines.append(f"\n<details>\n<summary>{cat_label} ({len(items)} files)</summary>\n")
            for item in items:
                local = item.get("local_path", "")
                url = item.get("url", "")
                lines.append(f"- `{local}` ← {_truncate(url, 80)}")
            lines.append("\n</details>\n")

        return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────────────────────────
# Utility functions
# ──────────────────────────────────────────────────────────────────────────────

def _yaml_escape(s: str) -> str:
    """Escape a string for safe use inside YAML double-quoted values."""
    if not s:
        return ""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _md_escape(s: str) -> str:
    """Light escape for Markdown inline text (brackets, pipes)."""
    if not s:
        return ""
    return s.replace("[", "\\[").replace("]", "\\]").replace("|", "\\|")


def _slugify(text: str) -> str:
    """Convert heading text to a GitHub-style anchor slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    return slug


def _truncate(s: str, length: int = 80) -> str:
    """Truncate a string, appending '…' if it exceeds length."""
    if not s or len(s) <= length:
        return s or ""
    return s[:length - 1] + "…"


def _mermaid_label(text: str) -> str:
    """Sanitize text for use as a Mermaid node label."""
    if not text:
        return "..."
    # Remove characters that break Mermaid syntax
    text = _truncate(text, 40)
    text = re.sub(r'["\[\]{}()<>|#&;`]', "", text)
    text = text.replace("\n", " ").strip()
    return text or "..."


def _render_md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a Markdown table from headers and rows."""
    if not headers and not rows:
        return ""

    # If no headers provided, generate generic ones
    if not headers and rows:
        headers = [f"Col {i+1}" for i in range(len(rows[0]))]

    num_cols = len(headers)

    # Escape pipe characters in cells
    def _cell(s: str) -> str:
        return (s or "").replace("|", "\\|")

    header_line = "| " + " | ".join(_cell(h) for h in headers) + " |"
    sep_line = "| " + " | ".join("---" for _ in headers) + " |"

    data_lines: list[str] = []
    for row in rows:
        # Pad or truncate row to match header count
        cells = list(row) + [""] * (num_cols - len(row))
        data_lines.append("| " + " | ".join(_cell(c) for c in cells[:num_cols]) + " |")

    return "\n".join([header_line, sep_line] + data_lines) + "\n"
