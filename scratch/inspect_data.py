import sys
import re
from pathlib import Path
from bs4 import BeautifulSoup, Tag

# Helper imports from src
sys.path.append(str(Path("D:/LT/SaveTheWeb")))
from src.extractor import _is_layout_class, _clean_semantic_key, _is_junk_url, _get_img_src
from src.extractor import URLResolver

html_path = Path("web_archive/snapshots/qimao.com_20260611_133249/final_page.html")
html = html_path.read_text(encoding="utf-8")
soup = BeautifulSoup(html, "html.parser")

class DummyResolver:
    def resolve(self, url):
        return url or ""

resolver = DummyResolver()

def clean_html_structure(soup: BeautifulSoup, resolver) -> str:
    body = soup.find("body") or soup
    body_copy = BeautifulSoup(str(body), "html.parser").find("body") or BeautifulSoup(str(body), "html.parser")

    TAGS_TO_REMOVE = {
        "script", "style", "noscript", "iframe", "svg", "canvas",
        "link", "meta", "base", "template", "embed", "object", "audio",
        "video", "map", "area", "track", "source", "picture",
        "input", "select", "textarea", "button", "form", "option", 
        "optgroup", "fieldset", "legend", "br", "hr"
    }
    for tag in body_copy.find_all(list(TAGS_TO_REMOVE)):
        tag.decompose()

    from bs4 import Comment
    for comment in body_copy.find_all(text=lambda text: isinstance(text, Comment)):
        comment.extract()

    def process_node(node):
        if not isinstance(node, Tag):
            return

        children = list(node.children)
        for child in children:
            process_node(child)

        attrs = {}
        
        classes = node.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()
        cleaned_classes = []
        for cls in classes:
            cls_clean = cls.strip()
            if cls_clean and not _is_layout_class(cls_clean):
                cleaned_cls = _clean_semantic_key(cls_clean)
                if cleaned_cls:
                    cleaned_classes.append(cleaned_cls)
        if cleaned_classes:
            attrs["class"] = " ".join(cleaned_classes)

        eid = node.get("id")
        if eid and isinstance(eid, str) and eid.strip():
            eid_clean = eid.strip()
            if not any(kw in eid_clean.lower() for kw in ["col", "row", "flex", "grid", "wrapper", "container"]):
                attrs["id"] = eid_clean

        if node.name == "a":
            href = node.get("href")
            if href:
                href_clean = href.strip()
                if not _is_junk_url(href_clean):
                    attrs["href"] = resolver.resolve(href_clean)
        
        elif node.name == "img":
            src = _get_img_src(node)
            if src:
                attrs["src"] = resolver.resolve(src)
            alt = node.get("alt")
            if alt:
                attrs["alt"] = alt.strip()

        node.attrs = attrs

        for child in list(node.children):
            if not isinstance(child, Tag):
                text = str(child)
                normalized = re.sub(r"\s+", " ", text).strip()
                if not normalized:
                    child.extract()
                else:
                    child.replace_with(normalized)

        sub_tags = [c for c in node.children if isinstance(c, Tag)]
        sub_texts = [c for c in node.children if not isinstance(c, Tag)]
        
        if node.name in {"div", "span"} and not node.attrs and len(sub_tags) == 1 and not sub_texts:
            node.replace_with(sub_tags[0])
            return

        if node.name in {"div", "span", "p"} and not sub_tags and not sub_texts:
            node.decompose()

    process_node(body_copy)
    return body_copy.prettify()

clean_html = clean_html_structure(soup, resolver)
print("Clean HTML length:", len(clean_html))
Path("scratch/qimao_clean.html").write_text(clean_html, encoding="utf-8")
print("Saved scratch/qimao_clean.html")
