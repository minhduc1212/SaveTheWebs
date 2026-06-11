import json
import sys
from pathlib import Path

# Force UTF-8 encoding for stdout
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

path = Path("web_archive/snapshots/www.qidian.com_20260611_092407/extracted_data.json")
data = json.loads(path.read_text(encoding="utf-8"))

def search_keys(obj, target_key, depth=0):
    results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == target_key:
                results.append((depth, v))
            else:
                results.extend(search_keys(v, target_key, depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(search_keys(item, target_key, depth + 1))
    return results

print("Searching for 'book-img' keys...")
book_imgs = search_keys(data, "book-img")
print(f"Found {len(book_imgs)} matches.")
for depth, val in book_imgs[:5]:
    print(f"Depth {depth}:", json.dumps(val, ensure_ascii=False, indent=2))

print("\nSearching for 'book-info' keys...")
book_infos = search_keys(data, "book-info")
print(f"Found {len(book_infos)} matches.")
for depth, val in book_infos[:5]:
    print(f"Depth {depth}:", json.dumps(val, ensure_ascii=False, indent=2))
