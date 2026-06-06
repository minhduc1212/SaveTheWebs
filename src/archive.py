import json
import hashlib
import urllib.parse
from pathlib import Path
from datetime import datetime
from src.utils import DEFAULT_ARCHIVE, VERSION, log


class ArchiveIndex:
    """
    Quản lý kho lưu trữ nhiều website.
    Cấu trúc:
      web_archive/
        index.json               ← danh sách tất cả snapshots
        snapshots/
          <domain>_<ts>/         ← mỗi lần record = 1 snapshot
            manifest.json
            assets/...
            api_responses/...
            tokens/...
            final_page.html
    """
    def __init__(self, archive_dir: str = DEFAULT_ARCHIVE):
        self.root = Path(archive_dir)
        self.snap_dir = self.root / "snapshots"
        self.index_path = self.root / "index.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.snap_dir.mkdir(exist_ok=True)
        self._routes_cache: dict | None = None  # FIX: cache routes to avoid per-request disk reads
        self._apis_cache: list | None = None    # FIX: cache API responses to avoid per-request disk reads
        self._load()

    def _load(self):
        if self.index_path.exists():
            self.data = json.loads(self.index_path.read_text(encoding="utf-8"))
            try:
                self._last_mtime = self.index_path.stat().st_mtime
            except Exception:
                self._last_mtime = 0
        else:
            self.data = {"version": VERSION, "snapshots": [], "domains": {}}
            self._last_mtime = 0

    def check_reload(self):
        """Check if index.json has been modified on disk and reload if necessary."""
        if not self.index_path.exists():
            return
        try:
            mtime = self.index_path.stat().st_mtime
            if getattr(self, "_last_mtime", 0) != mtime:
                self._load()
                self.invalidate_cache()
                self._last_mtime = mtime
                log("INFO", "Archive index reloaded from disk (detected change)")
        except Exception:
            pass

    def save(self):
        self.index_path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        try:
            self._last_mtime = self.index_path.stat().st_mtime
        except Exception:
            pass

    def invalidate_cache(self):
        """Invalidate the routes and APIs caches (call after adding new snapshots)."""
        self._routes_cache = None
        self._apis_cache = None

    def new_snapshot(self, url: str) -> "SnapshotStore":
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.replace(":", "_")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        snap_id = f"{domain}_{ts}"
        snap_path = self.snap_dir / snap_id
        snap_path.mkdir(parents=True, exist_ok=True)

        entry = {
            "id": snap_id,
            "url": url,
            "domain": domain,
            "recorded_at": datetime.now().isoformat(),
            "path": str(snap_path.relative_to(self.root)),
            "asset_count": 0,
            "api_count": 0,
        }
        self.data["snapshots"].append(entry)
        self.data["domains"].setdefault(domain, []).append(snap_id)
        self.invalidate_cache()
        self.save()
        return SnapshotStore(snap_path, entry, self)

    def get_snapshots(self, domain: str = None):
        self.check_reload()
        snaps = self.data["snapshots"]
        if domain:
            snaps = [s for s in snaps if s["domain"] == domain]
        return sorted(snaps, key=lambda x: x["recorded_at"], reverse=True)

    def search(self, query: str):
        self.check_reload()
        q = query.lower()
        results = []
        for snap in self.data["snapshots"]:
            score = 0
            if q in snap["url"].lower(): score += 10
            if q in snap["domain"].lower(): score += 5
            manifest_path = self.root / snap["path"] / "manifest.json"
            if manifest_path.exists():
                content = manifest_path.read_text(encoding="utf-8").lower()
                score += content.count(q)
            if score > 0:
                results.append({**snap, "_score": score})
        return sorted(results, key=lambda x: x["_score"], reverse=True)

    def get_all_routes(self) -> dict:
        """
        Return dict: url → local_path (relative to archive root) for ALL snapshots.
        FIX: Cached — disk reads only happen once, then served from memory.
        """
        self.check_reload()
        if self._routes_cache is not None:
            return self._routes_cache

        routes = {}
        for snap in self.data["snapshots"]:
            mf_path = self.root / snap["path"] / "manifest.json"
            if not mf_path.exists():
                continue
            try:
                mf = json.loads(mf_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for url, rel in mf.get("routes", {}).items():
                # Newest snapshot wins (last write wins — snapshots appended newest-last)
                if rel.startswith("redirect:"):
                    routes[url] = rel
                else:
                    routes[url] = str(Path(snap["path"]) / rel).replace("\\", "/")

        # WAF Bypass: Cloudflare redirects to ?solution=...&js_challenge=1 when solved,
        # and returns the real page on that URL. We map the clean base URL to the real page.
        waf_mapping = {}
        for url, path in routes.items():
            if "js_challenge=1" in url or "solution=" in url:
                base_url = url.split("?")[0]
                waf_mapping[base_url] = path
                
        for base_url, path in waf_mapping.items():
            routes[base_url] = path

        # ALWAYS prioritize final_page.html for the snapshot's main URL across ALL snapshots
        # This completely bypasses WAF challenges and blank SPA shells for the entry page.
        # It must be at the very end to override any WAF mappings.
        for snap in self.data["snapshots"]:
            if "url" in snap:
                final_page_path = self.root / snap["path"] / "final_page.html"
                if final_page_path.exists():
                    routes[snap["url"]] = str(Path(snap["path"]) / "final_page.html").replace("\\", "/")

        self._routes_cache = routes
        return routes

    def get_all_api_responses(self) -> list:
        """Return list of all api response entries."""
        self.check_reload()
        if self._apis_cache is not None:
            return self._apis_cache

        results = []
        for snap in self.data["snapshots"]:
            api_dir = self.root / snap["path"] / "api_responses"
            if not api_dir.exists():
                continue
            for f in api_dir.glob("*.json"):
                try:
                    entry = json.loads(f.read_text(encoding="utf-8"))
                    entry["_snap_id"] = snap["id"]
                    results.append(entry)
                except Exception:
                    pass
        self._apis_cache = results
        return results

    def update_snapshot_counts(self, snap_id: str, asset_count: int, api_count: int):
        for s in self.data["snapshots"]:
            if s["id"] == snap_id:
                s["asset_count"] = asset_count
                s["api_count"] = api_count
                break
        self.invalidate_cache()
        self.save()


class SnapshotStore:
    def __init__(self, snap_path: Path, meta: dict, index: ArchiveIndex):
        self.path = snap_path
        self.meta = meta
        self.index = index
        self.assets_dir = snap_path / "assets"
        self.api_dir = snap_path / "api_responses"
        self.tokens_dir = snap_path / "tokens"
        self.manifest: dict = {
            "id": meta["id"],
            "url": meta["url"],
            "domain": meta["domain"],
            "recorded_at": meta["recorded_at"],
            "routes": {},
            "tokens": {},
            "api_calls": [],
        }
        for d in [self.assets_dir, self.api_dir, self.tokens_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def url_to_filepath(self, url: str, content_type: str = "") -> Path:
        parsed = urllib.parse.urlparse(url)
        path_str = parsed.path.lstrip("/") or "index"
        
        # Windows filename sanitization: replace illegal chars but keep '/' for directories
        import re
        path_str = re.sub(r'[<>:"|?*\x00-\x1f]', '_', path_str)
        
        p_path = Path(path_str)
        stem = str(p_path.parent / p_path.stem) if p_path.parent != Path(".") else p_path.stem
        suffix = p_path.suffix
        
        # If no extension is present in the path, try to guess it from content_type
        if not suffix:
            ext_map = {
                "text/html": ".html", "text/css": ".css",
                "application/javascript": ".js", "text/javascript": ".js",
                "application/json": ".json", "image/svg+xml": ".svg",
                "image/png": ".png", "image/jpeg": ".jpg",
                "image/gif": ".gif", "image/webp": ".webp",
                "font/woff": ".woff", "font/woff2": ".woff2",
                "font/ttf": ".ttf", "font/otf": ".otf",
            }
            suffix = ext_map.get(content_type.split(";")[0].strip(), "")
            
        # Append query hash to the stem
        if parsed.query:
            q_hash = hashlib.md5(parsed.query.encode()).hexdigest()[:8]
            stem = f"{stem}__q{q_hash}"
            
        # Reconstruct path ensuring correct format
        final_path = f"{stem}{suffix}"
        
        domain = parsed.netloc.replace(":", "_")
        fp = self.assets_dir / domain / final_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        return fp

    def save_asset(self, url: str, body: bytes, ct: str) -> Path:
        fp = self.url_to_filepath(url, ct)
        if fp.exists():
            fp = fp.with_name(f"{fp.stem}_{hashlib.md5(url.encode()).hexdigest()[:6]}{fp.suffix}")
        fp.write_bytes(body)
        rel = str(fp.relative_to(self.path))
        self.manifest["routes"][url] = rel
        return fp

    def save_redirect(self, url: str, target_url: str, status: int):
        self.manifest["routes"][url] = f"redirect:{status}:{target_url}"

    def save_api(self, url, method, req_hdrs, req_body, status, resp_hdrs, resp_body) -> str:
        eid = hashlib.md5(f"{method}:{url}".encode()).hexdigest()[:12]
        entry = {
            "id": eid, "url": url, "method": method,
            "request": {"headers": req_hdrs, "body": req_body.decode("utf-8", errors="replace") if req_body else None},
            "response": {"status": status, "headers": dict(resp_hdrs),
                         "body": resp_body.decode("utf-8", errors="replace")},
            "recorded_at": datetime.now().isoformat(),
        }
        (self.api_dir / f"{eid}.json").write_text(json.dumps(entry, ensure_ascii=False, indent=2), "utf-8")
        self.manifest["api_calls"].append({"id": eid, "url": url, "method": method})
        return eid

    def save_token(self, ttype: str, value: str, source: str):
        self.manifest["tokens"].setdefault(ttype, [])
        e = {"value": value, "source": source}
        if e not in self.manifest["tokens"][ttype]:
            self.manifest["tokens"][ttype].append(e)

    def save_cookies(self, cookies: list):
        (self.tokens_dir / "cookies.json").write_text(
            json.dumps(cookies, ensure_ascii=False, indent=2), "utf-8")
        self.manifest["tokens"]["cookies"] = cookies

    def flush(self):
        (self.path / "manifest.json").write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2), "utf-8")
        self.index.update_snapshot_counts(
            self.meta["id"],
            len(self.manifest["routes"]),
            len(self.manifest["api_calls"]),
        )
        log("OK", f"Snapshot saved: {self.path.name}  "
            f"({len(self.manifest['routes'])} assets, {len(self.manifest['api_calls'])} APIs)")
