import re
import urllib.parse


def _build_url_index(all_routes: dict) -> dict:
    """
    Build a lookup index that maps multiple URL variations to the same
    archived route, enabling fuzzy matching for resources that reference
    different URL forms (protocol-relative, path-only, with/without trailing slash).
    
    Returns: dict mapping normalized URL variants -> original URL (orig_url)
    """
    index = {}
    for url in all_routes:
        # Original URL (exact match — highest priority)
        index[url] = url

        parsed = urllib.parse.urlparse(url)

        # Without query string
        no_query = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
        if no_query != url:
            index.setdefault(no_query, url)

        # Protocol-relative form: //domain/path
        proto_rel = f"//{parsed.netloc}{parsed.path}"
        index.setdefault(proto_rel, url)

        # Path-only form: /path  (for same-origin resources)
        if parsed.path:
            index.setdefault(parsed.path, url)

    return index


def rewrite_css(css_text: str, all_routes: dict, base_url: str = "") -> str:
    """
    Rewrite url(...) and @import inside CSS content to point to Wayback local proxies.
    """
    url_index = _build_url_index(all_routes)

    def resolve(url: str) -> str:
        if url.startswith("//"):
            scheme = urllib.parse.urlparse(base_url).scheme if base_url else "https"
            return f"{scheme}:{url}"
        if base_url and not url.startswith(("http://", "https://", "data:", "#")):
            return urllib.parse.urljoin(base_url, url)
        return url

    def maybe_rewrite(url: str) -> str:
        if url.startswith(("data:", "#", "javascript:", "mailto:", "tel:")):
            return url

        resolved = resolve(url)

        # 1. Try exact match on the resolved URL
        if resolved in all_routes:
            return "/__wb/" + urllib.parse.quote(resolved, safe="")

        # 2. Try the fuzzy URL index (protocol-relative, path-only, etc.)
        if resolved in url_index:
            return "/__wb/" + urllib.parse.quote(url_index[resolved], safe="")

        # 3. Try matching just the original (un-resolved) URL in the index
        if url in url_index:
            return "/__wb/" + urllib.parse.quote(url_index[url], safe="")

        return url

    def replace_css_url(m: re.Match) -> str:
        inner = m.group(1).strip()
        # Handle HTML-entity-encoded quotes: url(&quot;...&quot;)
        if inner.startswith('&quot;') and inner.endswith('&quot;'):
            url = inner[6:-6]
            rewritten = maybe_rewrite(url)
            return f'url(&quot;{rewritten}&quot;)'
        # Extract url from quotes if present
        if inner and inner[0] in ('"', "'") and inner[-1] == inner[0]:
            quote = inner[0]
            url = inner[1:-1]
            rewritten = maybe_rewrite(url)
            return f"url({quote}{rewritten}{quote})"
        else:
            rewritten = maybe_rewrite(inner)
            return f"url({rewritten})"

    def replace_import(m: re.Match) -> str:
        """Handle @import url('...') and @import '...' """
        url = m.group(1) or m.group(2)
        if url:
            rewritten = maybe_rewrite(url)
            if m.group(1):  # @import url(...) form
                return f'@import url("{rewritten}")'
            else:  # @import "..." form
                return f'@import "{rewritten}"'
        return m.group(0)

    # Match @import url(...) and @import "..."
    css_text = re.sub(
        r'@import\s+(?:url\(\s*["\']?([^"\')\s]+)["\']?\s*\)|["\']([^"\']+)["\'])',
        replace_import, css_text, flags=re.IGNORECASE
    )

    # Match url(...)
    css_text = re.sub(r'url\(\s*([^)]+?)\s*\)', replace_css_url, css_text, flags=re.IGNORECASE)
    return css_text


def rewrite_html(html: str, all_routes: dict, base_url: str = "", tokens_script: str = "", is_final_page: bool = False) -> str:
    """
    Rewrite all href/src/action/srcset/data-src attributes that point to
    archived URLs so the replay server can serve them locally.

    Also:
    - Injects a <base> tag so relative URLs resolve correctly
    - Swaps lazy-load attributes to standard src for offline rendering
    - Rewrites inline CSS url() references
    - Rewrites <style> blocks
    - Injects tokens_script to restore cookies and localStorage
    """
    if is_final_page:
        html = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', html, flags=re.IGNORECASE)

    url_index = _build_url_index(all_routes)

    # 0. Inject SPA routing helper script into the head to support client-side routers
    spa_script = """<script>
(function() {
  try {
    var originalPathname = Object.getOwnPropertyDescriptor(Location.prototype, 'pathname');
    var originalHref = Object.getOwnPropertyDescriptor(Location.prototype, 'href');
    var originalOrigin = Object.getOwnPropertyDescriptor(Location.prototype, 'origin');
    var originalHost = Object.getOwnPropertyDescriptor(Location.prototype, 'host');
    var originalHostname = Object.getOwnPropertyDescriptor(Location.prototype, 'hostname');
    
    var realOrigin = originalOrigin ? originalOrigin.get.call(window.location) : window.location.origin;
    var realHref = originalHref ? originalHref.get.call(window.location) : window.location.href;

    window.__wr_path = function() {
      try {
        var p = originalPathname ? originalPathname.get.call(window.location) : window.location.pathname;
        if (p.indexOf('/__wb/') === 0) {
          var nextSlash = p.indexOf('/', 6);
          if (nextSlash === -1) return '/';
          return p.substring(nextSlash) || '/';
        }
        return p;
      } catch(e) { return '/'; }
    };
    
    window.__wr_href = function() {
      try {
        var h = originalHref ? originalHref.get.call(window.location) : window.location.href;
        var idx = h.indexOf('/__wb/');
        if (idx !== -1) {
          var rest = h.substring(idx + 6);
          var nextSlash = rest.indexOf('/');
          var targetUrl = decodeURIComponent(nextSlash === -1 ? rest : rest.substring(0, nextSlash));
          if (nextSlash !== -1) {
            targetUrl += rest.substring(nextSlash);
          }
          return targetUrl;
        }
        return h;
      } catch(e) { return ''; }
    };
    
    window.__wr_origin = function() {
      try { return new URL(window.__wr_href()).origin; } 
      catch(e) { return originalOrigin ? originalOrigin.get.call(window.location) : window.location.origin; }
    };
    
    window.__wr_host = function() {
      try { return new URL(window.__wr_href()).host; } 
      catch(e) { return originalHost ? originalHost.get.call(window.location) : window.location.host; }
    };
  
    window.__wr_hostname = function() {
      try { return new URL(window.__wr_href()).hostname; } 
      catch(e) { return originalHostname ? originalHostname.get.call(window.location) : window.location.hostname; }
    };
  
    var safeDefine = function(obj, prop, desc) {
      try { Object.defineProperty(obj, prop, desc); } catch(e) {}
    };

    safeDefine(Location.prototype, 'pathname', { get: window.__wr_path, set: function(val) { console.warn('Blocked pathname assignment: ' + val); }, configurable: true });
    safeDefine(Location.prototype, 'href', { get: window.__wr_href, set: function(val) { console.warn('Blocked href assignment to: ' + val); }, configurable: true });
    safeDefine(Location.prototype, 'origin', { get: window.__wr_origin, configurable: true });
    safeDefine(Location.prototype, 'host', { get: window.__wr_host, set: function(val) { console.warn('Blocked host assignment: ' + val); }, configurable: true });
    safeDefine(Location.prototype, 'hostname', { get: window.__wr_hostname, set: function(val) { console.warn('Blocked hostname assignment: ' + val); }, configurable: true });
    safeDefine(document, 'URL', { get: window.__wr_href, configurable: true });
    safeDefine(document, 'domain', { get: window.__wr_hostname, configurable: true });
    safeDefine(window, 'origin', { get: window.__wr_origin, configurable: true });
    
    safeDefine(Location.prototype, 'search', { set: function(val) { console.warn('Blocked search: ' + val); }, configurable: true, get: function() { return ''; } });
    safeDefine(Location.prototype, 'protocol', { set: function(val) { console.warn('Blocked protocol: ' + val); }, configurable: true, get: function() { return 'http:'; } });
    safeDefine(Location.prototype, 'port', { set: function(val) { console.warn('Blocked port: ' + val); }, configurable: true, get: function() { return ''; } });
    safeDefine(Location.prototype, 'hash', { set: function(val) { console.warn('Blocked hash: ' + val); }, configurable: true, get: function() { return ''; } });
    safeDefine(Location.prototype, 'reload', { value: function() { console.warn('Blocked location.reload()'); }, configurable: true });
    safeDefine(Location.prototype, 'replace', { value: function(url) { console.warn('Blocked location.replace: ' + url); }, configurable: true });
    safeDefine(Location.prototype, 'assign', { value: function(url) { console.warn('Blocked location.assign: ' + url); }, configurable: true });

    // Intercept window.open
    var originalWindowOpen = window.open;
    window.open = function(url, target, features) {
      if (url && typeof url === 'string') {
        try {
          var absUrl = new URL(url, realHref).href;
          if (absUrl.startsWith('http') && absUrl.indexOf(realOrigin) !== 0) {
            url = realOrigin + '/__wb/' + encodeURIComponent(absUrl);
          }
        } catch(e) {}
      }
      return originalWindowOpen.call(window, url, target, features);
    };

    // Intercept all <a> tag clicks (even inside Shadow DOMs)
    document.addEventListener('click', function(e) {
      var anchor = null;
      if (e.composedPath) {
        var path = e.composedPath();
        for (var i = 0; i < path.length; i++) {
          if (path[i].tagName === 'A') { anchor = path[i]; break; }
        }
      }
      if (!anchor && e.target.closest) { anchor = e.target.closest('a'); }
      if (!anchor || !anchor.href) return;
      
      var hrefAttr = anchor.getAttribute('href');
      if (hrefAttr && (hrefAttr.startsWith('javascript:') || hrefAttr.startsWith('#'))) return;
      
      var absoluteUrl = anchor.href;
      if (absoluteUrl.startsWith('http') && absoluteUrl.indexOf(realOrigin) !== 0) {
        e.preventDefault();
        e.stopPropagation();
        var proxyUrl = realOrigin + '/__wb/' + encodeURIComponent(absoluteUrl);
        if (anchor.target === '_blank') {
          originalWindowOpen.call(window, proxyUrl, '_blank');
        } else if (originalHref && originalHref.set) {
          originalHref.set.call(window.location, proxyUrl);
        } else {
          window.location.assign(proxyUrl);
        }
      }
    }, true);

    // Intercept forms submitting to external domains
    document.addEventListener('submit', function(e) {
      if (e.target && e.target.action) {
        if (e.target.action.startsWith('http') && e.target.action.indexOf(realOrigin) !== 0) {
          e.preventDefault();
          e.stopPropagation();
          console.warn('[WR] Blocked external form submit:', e.target.action);
        }
      }
    }, true);

    try {
      var originalGo = history.go;
      history.go = function(delta) {
        if (delta === 0 || delta === undefined) {
          console.warn('Blocked history.go(0) refresh');
          return;
        }
        return originalGo.apply(this, arguments);
      };
    } catch(e) {}

    // Fallback: block navigation
    window.addEventListener('beforeunload', function (e) {
      console.warn('Navigation blocked by WebRecorder fallback');
      e.preventDefault();
      e.returnValue = 'Navigation blocked';
      return 'Navigation blocked';
    });

    var originalPushState = history.pushState;
    var originalReplaceState = history.replaceState;
    function wrapStateMethod(original) {
      return function(state, unused, url) {
        if (url) {
          var currentWb = '';
          var p = originalPathname.get.call(window.location);
          if (p.indexOf('/__wb/') === 0) {
            var nextSlash = p.indexOf('/', 6);
            currentWb = nextSlash === -1 ? p : p.substring(0, nextSlash);
          }
          if (currentWb) {
            if (url.indexOf('/') === 0) {
              url = currentWb + url;
            } else if (url.indexOf('http://') !== 0 && url.indexOf('https://') !== 0) {
              var cleanPath = window.__wr_path();
              var base = cleanPath.substring(0, cleanPath.lastIndexOf('/') + 1);
              url = currentWb + base + url;
            } else {
              url = currentWb.substring(0, 5) + '/' + encodeURIComponent(url);
            }
          }
        }
        return original.apply(this, [state, unused, url]);
      };
    }
    history.pushState = wrapStateMethod(originalPushState);
    history.replaceState = wrapStateMethod(originalReplaceState);
  } catch(e) {}
})();
</script>"""

    def _build_route_injection_script(all_routes: dict) -> str:
        import json
        url_keys = [u for u, v in all_routes.items() if not str(v).startswith("redirect:")]
        routes_json = json.dumps(url_keys)
        return f"""<script>
(function() {{
  try {{
    var _wrRouteList = {routes_json};
    var _wrRoutesObj = {{}};
    for (var i = 0; i < _wrRouteList.length; i++) {{
      _wrRoutesObj[_wrRouteList[i]] = 1;
    }}
    function _sendRoutesToSW(reg) {{
      var target = reg.active || reg.installing || reg.waiting;
      if (!target) return;
      target.postMessage({{ type: 'INIT_ROUTES', routes: _wrRoutesObj }});
    }}
    if ('serviceWorker' in navigator) {{
      navigator.serviceWorker.register('/sw.js', {{ scope: '/' }})
        .then(function(reg) {{
          _sendRoutesToSW(reg);
          reg.addEventListener('updatefound', function() {{
            var newSW = reg.installing;
            if (newSW) {{
              newSW.addEventListener('statechange', function() {{
                if (newSW.state === 'activated') _sendRoutesToSW(reg);
              }});
            }}
          }});
        }})
        .catch(function(err) {{
          console.warn('[WR] SW registration failed:', err);
        }});
      navigator.serviceWorker.ready.then(function(reg) {{
        _sendRoutesToSW(reg);
      }}).catch(function() {{}});
    }}
  }} catch(e) {{
    console.warn('[WR] Route injection failed:', e);
  }}
}})();
</script>"""

    route_injection_script = _build_route_injection_script(all_routes)

    if "<head>" in html:
        html = html.replace("<head>", f"<head>{tokens_script}{spa_script}{route_injection_script}", 1)
    elif "<HEAD>" in html:
        html = html.replace("<HEAD>", f"<HEAD>{tokens_script}{spa_script}{route_injection_script}", 1)
    else:
        html = f"{tokens_script}{spa_script}{route_injection_script}{html}"

    def resolve(url: str) -> str:
        """Resolve a possibly-relative URL against base_url."""
        if url.startswith("//"):
            scheme = urllib.parse.urlparse(base_url).scheme if base_url else "https"
            return f"{scheme}:{url}"
        if base_url and not url.startswith(("http://", "https://", "data:", "#")):
            return urllib.parse.urljoin(base_url, url)
        return url

    def maybe_rewrite(url: str) -> str:
        """Return /__wb/<encoded> if url is in archive, else original url."""
        # Unescape HTML entities (e.g. &amp; -> &) before looking up in all_routes
        import html as html_lib
        url_decoded = html_lib.unescape(url)
        
        if url_decoded.startswith(("data:", "#", "javascript:", "mailto:", "tel:")):
            return url

        resolved = resolve(url_decoded)

        # 1. Exact match on resolved URL
        if resolved in all_routes:
            return "/__wb/" + urllib.parse.quote(resolved, safe="")

        # 2. Fuzzy match via URL index
        if resolved in url_index:
            return "/__wb/" + urllib.parse.quote(url_index[resolved], safe="")

        # 3. Match un-resolved URL
        if url in url_index:
            return "/__wb/" + urllib.parse.quote(url_index[url], safe="")

        return url

    def replace_attr(m: re.Match) -> str:
        attr, q, url = m.group(1), m.group(2), m.group(3)
        return f'{attr}={q}{maybe_rewrite(url)}{q}'

    def replace_srcset(m: re.Match) -> str:
        """Handle srcset="url1 2x, url2 1x" — each comma-separated candidate."""
        attr, q, srcset = m.group(1), m.group(2), m.group(3)
        parts = srcset.split(",")
        rewritten = []
        for part in parts:
            tokens = part.strip().split()
            if tokens:
                tokens[0] = maybe_rewrite(tokens[0])
            rewritten.append(" ".join(tokens))
        return f'{attr}={q}{", ".join(rewritten)}{q}'

    def replace_css_url(m: re.Match) -> str:
        """Handle CSS url("...") / url('...') / url(...) references."""
        inner = m.group(1).strip()
        # Handle HTML-entity-encoded quotes: url(&quot;...&quot;)
        if inner.startswith('&quot;') and inner.endswith('&quot;'):
            url = inner[6:-6]
            rewritten = maybe_rewrite(url)
            return f'url(&quot;{rewritten}&quot;)'
        # Standard quoted URLs
        if inner and inner[0] in ('"', "'") and inner[-1] == inner[0]:
            quote = inner[0]
            url = inner[1:-1]
            rewritten = maybe_rewrite(url)
            return f"url({quote}{rewritten}{quote})"
        else:
            rewritten = maybe_rewrite(inner)
            return f"url({rewritten})"

    def rewrite_style_block(m: re.Match) -> str:
        """Rewrite URLs inside <style>...</style> blocks."""
        open_tag = m.group(1)
        css_content = m.group(2)
        close_tag = m.group(3)
        rewritten_css = re.sub(r'url\(\s*([^)]+?)\s*\)', replace_css_url, css_content, flags=re.IGNORECASE)
        return f"{open_tag}{rewritten_css}{close_tag}"

    # NOTE: Do NOT inject <base> tag — it breaks all rewritten /__wb/ URLs
    # by resolving them against the original domain (e.g. https://docln.net/__wb/...)
    # instead of localhost:8080/__wb/... . Un-rewritten relative URLs are handled
    # by the server's referer-based fallback routing instead.

    # 1. Standard attribute rewrites (src, href, action, data-src, etc.)
    html = re.sub(
        r'(src|href|action|data-src|data-original|data-lazy-src|data-lazy|poster|data-bg|data-background)=(["\'])([^"\']{4,})\2',
        replace_attr, html, flags=re.IGNORECASE
    )

    # 2. srcset / data-srcset attribute
    html = re.sub(
        r'(srcset|data-srcset)=(["\'])([^"\']+)\2',
        replace_srcset, html, flags=re.IGNORECASE
    )

    # 3. Rewrite URLs inside <style>...</style> blocks (full CSS parsing)
    html = re.sub(
        r'(<style[^>]*>)(.*?)(</style>)',
        rewrite_style_block, html, flags=re.IGNORECASE | re.DOTALL
    )

    # 4. CSS url() in inline style attributes
    # BUG FIX: The old regex only caught the FIRST url() per style attribute.
    # New approach: find each style="..." attribute, extract the value, and run
    # the full CSS url() rewriter on it — this catches ALL url() calls.
    def rewrite_inline_style(m: re.Match) -> str:
        prefix = m.group(1)  # 'style=' or 'style ='
        quote = m.group(2)   # the delimiter (' or ")
        value = m.group(3)   # the style attribute value
        # Rewrite all url() inside this style value
        rewritten = re.sub(r'url\(\s*([^)]+?)\s*\)', replace_css_url, value, flags=re.IGNORECASE)
        return f'{prefix}{quote}{rewritten}{quote}'

    html = re.sub(
        r'(style\s*=\s*)(["\'])(.*?)\2',
        rewrite_inline_style, html, flags=re.IGNORECASE | re.DOTALL
    )

    # 5. FIX: Swap lazy-load images on <img> tags to render immediately offline
    def fix_lazy_images(m: re.Match) -> str:
        img_tag = m.group(0)
        lazy_url = None
        # Look for standard lazy loading attributes
        for attr in ("data-src", "data-original", "data-lazy-src", "data-lazy"):
            pat = rf'{attr}=(["\'])(.*?)\1'
            lazy_match = re.search(pat, img_tag, re.IGNORECASE)
            if lazy_match:
                lazy_url = lazy_match.group(2)
                break

        if lazy_url:
            rewritten_lazy = maybe_rewrite(lazy_url)
            if re.search(r'\bsrc=', img_tag, re.IGNORECASE):
                # Check if existing src is a placeholder (tiny, blank, or data URI)
                existing_src = re.search(r'src=["\']([^"\']*)["\']', img_tag, re.IGNORECASE)
                if existing_src:
                    existing = existing_src.group(1)
                    is_placeholder = (
                        not existing or
                        existing.startswith("data:") or
                        "blank" in existing.lower() or
                        "placeholder" in existing.lower() or
                        "1x1" in existing or
                        len(existing) < 10
                    )
                    if is_placeholder:
                        img_tag = re.sub(
                            r'src=(["\']).*?\1',
                            f'src="{rewritten_lazy}"',
                            img_tag,
                            count=1,
                            flags=re.IGNORECASE
                        )
            else:
                # No src attribute — add one
                img_tag = img_tag.replace("<img ", f'<img src="{rewritten_lazy}" ', 1)

        # Remove loading="lazy" from ALL images to ensure offline rendering
        img_tag = re.sub(r'\s*loading=["\']?lazy["\']?', '', img_tag, flags=re.IGNORECASE)

        return img_tag

    html = re.sub(r'<img\s+[^>]*/?>', fix_lazy_images, html, flags=re.IGNORECASE)

    # 6. FIX: Force eager loading for faceplate-img in HTML to bypass IntersectionObserver
    html = re.sub(r'(<faceplate-img\b[^>]*?)loading=["\']?lazy["\']?', r'\1loading="eager"', html, flags=re.IGNORECASE)

    # 7. Normalize charset meta tags to UTF-8 to prevent browsers from rendering garbled text
    html = re.sub(
        r'<meta\s+charset=["\']?(?:gbk|gb2312|gb18030|big5|iso-8859-1|windows-1252)["\']?\s*/?>',
        '<meta charset="utf-8">',
        html,
        flags=re.IGNORECASE
    )

    # 7. Strip <meta http-equiv="refresh"> to prevent redirect loops, accounting for arbitrary attribute order
    html = re.sub(
        r'<meta\s+(?:[^>]*?\s+)?http-equiv=["\']?refresh["\']?[^>]*>',
        '',
        html,
        flags=re.IGNORECASE
    )
    html = re.sub(
        r'(<meta\s+http-equiv=["\']content-type["\']\s+content=["\']text/html;\s*charset=)(?:gbk|gb2312|gb18030|big5|iso-8859-1|windows-1252)(["\']\s*/?>)',
        r'\1utf-8\2',
        html,
        flags=re.IGNORECASE
    )

    return html
