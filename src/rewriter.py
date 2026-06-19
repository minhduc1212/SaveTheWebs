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


def rewrite_js(js_code: str) -> str:
    """
    Rewrite references to window.location, document.location, and location properties in JS code
    to point to our proxy window.__wr_location.
    """
    # 1. Rewrite window.location / document.location to window.__wr_location
    js_code = re.sub(r'\bwindow\s*\.\s*location\b', 'window.__wr_location', js_code)
    js_code = re.sub(r'\bdocument\s*\.\s*location\b', 'window.__wr_location', js_code)
    
    # 2. Rewrite location.prop to window.__wr_location.prop
    js_code = re.sub(
        r'(?<!\.)\blocation\s*\.\s*(href|pathname|origin|host|hostname|port|protocol|search|hash|assign|replace|reload)\b',
        r'window.__wr_location.\1',
        js_code
    )
    
    # 3. Rewrite location['prop'] to window.__wr_location['prop']
    js_code = re.sub(
        r'(?<!\.)\blocation\s*\[\s*(["\'])(href|pathname|origin|host|hostname|port|protocol|search|hash|assign|replace|reload)\1\s*\]',
        r'window.__wr_location[\1\2\1]',
        js_code
    )
    
    return js_code



def strip_tracking_and_ads(html: str) -> str:
    """
    Strip third-party tracking scripts, analytics, and external ad iframes from the HTML payload.
    """
    # Regex to find <script>...</script> (both src and inline)
    script_pattern = re.compile(r'<script\b([^>]*?)>([\s\S]*?)</script>', re.IGNORECASE)
    
    # Domains or keywords for tracking
    tracking_indicators = [
        "google-analytics.com", "googletagmanager.com", "googlesyndication.com",
        "doubleclick.net", "facebook.net", "mixpanel.com", "hotjar.com",
        "amplitude.com", "sentry.io", "quantserve.com", "scorecardresearch.com",
        "crazyegg.com", "optimizely.com", "gtag(", "ga('send'", "ga(\"send\"",
        "fbq(", "mixpanel.track", "Sentry.init", "amplitude.getInstance"
    ]
    
    def script_replacer(match):
        attrs = match.group(1)
        content = match.group(2)
        
        # Check if src attribute contains tracking domains
        src_match = re.search(r'src=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        if src_match:
            src = src_match.group(1)
            if any(ind in src for ind in tracking_indicators if "." in ind):
                return "<!-- Stripped tracking script -->"
        
        # Check inline content
        if any(ind in content for ind in tracking_indicators if "(" in ind or "." in ind):
            return "<!-- Stripped inline tracking code -->"
            
        return match.group(0)
        
    html = script_pattern.sub(script_replacer, html)
    
    # Regex to find <iframe...>...</iframe> and <iframe... />
    iframe_pattern = re.compile(r'<iframe\b([^>]*?)(?:>([\s\S]*?)</iframe>|/>)', re.IGNORECASE)
    ad_iframe_indicators = [
        "googleads", "doubleclick", "googlesyndication", "adnxs", "adsystem",
        "adservice", "smartadserver", "taboola", "outbrain", "adroll", "popads",
        "clickunder", "popunder"
    ]
    
    def iframe_replacer(match):
        attrs = match.group(1)
        src_match = re.search(r'src=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        if src_match:
            src = src_match.group(1)
            if any(ind in src for ind in ad_iframe_indicators):
                return "<!-- Stripped ad iframe -->"
        return match.group(0)
        
    html = iframe_pattern.sub(iframe_replacer, html)
    return html


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
    # Strip third-party tracking scripts, analytics, and external ad iframes
    html = strip_tracking_and_ads(html)

    # We no longer strip all scripts on final page to maintain basic UI interactions (JS-driven).
    # Tracking scripts are stripped, and background APIs are neutralized with mocks instead.
    # if is_final_page:
    #     html = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', html, flags=re.IGNORECASE)

    url_index = _build_url_index(all_routes)

    # 0. Inject SPA routing helper script into the head to support client-side routers
    spa_script = """<script>
(function() {
  try {
    // Native fetch & XMLHttpRequest are left intact to be intercepted by the Service Worker and served with recorded archive responses.

    // Robustly fetch native property descriptors from both Location.prototype and window.location
    var originalPathname = Object.getOwnPropertyDescriptor(Location.prototype, 'pathname') || Object.getOwnPropertyDescriptor(window.location, 'pathname');
    var originalHref = Object.getOwnPropertyDescriptor(Location.prototype, 'href') || Object.getOwnPropertyDescriptor(window.location, 'href');
    var originalOrigin = Object.getOwnPropertyDescriptor(Location.prototype, 'origin') || Object.getOwnPropertyDescriptor(window.location, 'origin');
    var originalHost = Object.getOwnPropertyDescriptor(Location.prototype, 'host') || Object.getOwnPropertyDescriptor(window.location, 'host');
    var originalHostname = Object.getOwnPropertyDescriptor(Location.prototype, 'hostname') || Object.getOwnPropertyDescriptor(window.location, 'hostname');
    var originalProtocol = Object.getOwnPropertyDescriptor(Location.prototype, 'protocol') || Object.getOwnPropertyDescriptor(window.location, 'protocol');
    var originalPort = Object.getOwnPropertyDescriptor(Location.prototype, 'port') || Object.getOwnPropertyDescriptor(window.location, 'port');
    var originalSearch = Object.getOwnPropertyDescriptor(Location.prototype, 'search') || Object.getOwnPropertyDescriptor(window.location, 'search');
    var originalHash = Object.getOwnPropertyDescriptor(Location.prototype, 'hash') || Object.getOwnPropertyDescriptor(window.location, 'hash');
    
    // Save native getters and setters securely (avoiding property access on window.location during runtime)
    var nativeHrefGet = originalHref && originalHref.get;
    var nativeHrefSet = originalHref && originalHref.set;
    var nativeOriginGet = originalOrigin && originalOrigin.get;

    // Establish a static fallback for the original page address URL
    var realOrigin = nativeOriginGet ? nativeOriginGet.call(window.location) : window.location.origin;
    var realHref = nativeHrefGet ? nativeHrefGet.call(window.location) : window.location.href;
    
    // Maintain a tracked variable of the current browser-side address-bar URL
    window.__wr_current_real_href = realHref;

    window.__wr_href = function() {
      try {
        var h = nativeHrefGet ? nativeHrefGet.call(window.location) : window.__wr_current_real_href;
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
      } catch(e) { return window.__wr_current_real_href || ''; }
    };

    window.__wr_path = function() {
      try {
        var cleanUrl = window.__wr_href();
        return new URL(cleanUrl).pathname || '/';
      } catch(e) { return '/'; }
    };
    
    window.__wr_origin = function() {
      try { return new URL(window.__wr_href()).origin; } 
      catch(e) { return realOrigin; }
    };
    
    window.__wr_host = function() {
      try { return new URL(window.__wr_href()).host; } 
      catch(e) { return ''; }
    };
  
    window.__wr_hostname = function() {
      try { return new URL(window.__wr_href()).hostname; } 
      catch(e) { return ''; }
    };

    window.__wr_protocol = function() {
      try { return new URL(window.__wr_href()).protocol; } 
      catch(e) { return 'http:'; }
    };

    window.__wr_port = function() {
      try { return new URL(window.__wr_href()).port || ''; } 
      catch(e) { return ''; }
    };

    window.__wr_search = function() {
      try { return new URL(window.__wr_href()).search || ''; } 
      catch(e) { return ''; }
    };

    window.__wr_hash = function() {
      try { return new URL(window.__wr_href()).hash || ''; } 
      catch(e) { return ''; }
    };

    var setLocationUrl = function(url) {
      if (!url) return;
      var absUrl = url;
      try {
        absUrl = new URL(url, window.__wr_href()).href;
      } catch(e) {}
      if (absUrl && typeof absUrl === 'string' && absUrl.startsWith('http') && absUrl.indexOf(realOrigin) !== 0) {
        absUrl = realOrigin + '/__wb/' + encodeURIComponent(absUrl);
      }
      window.__wr_current_real_href = absUrl;
      if (nativeHrefSet) {
        nativeHrefSet.call(window.location, absUrl);
      } else {
        try {
          window.location.href = absUrl;
        } catch(err) {}
      }
    };
  
    window.__wr_location = new Proxy(window.location, {
      get: function(target, prop) {
        if (prop === 'href') return window.__wr_href();
        if (prop === 'pathname') return window.__wr_path();
        if (prop === 'origin') return window.__wr_origin();
        if (prop === 'host') return window.__wr_host();
        if (prop === 'hostname') return window.__wr_hostname();
        if (prop === 'protocol') return window.__wr_protocol();
        if (prop === 'port') return window.__wr_port();
        if (prop === 'search') return window.__wr_search();
        if (prop === 'hash') return window.__wr_hash();
        if (prop === 'toString' || prop === Symbol.toPrimitive) {
          return function() { return window.__wr_href(); };
        }
        var val = target[prop];
        if (typeof val === 'function') {
          return val.bind(target);
        }
        return val;
      },
      set: function(target, prop, val) {
        if (prop === 'href') {
          setLocationUrl(val);
          return true;
        }
        if (prop === 'pathname' || prop === 'host' || prop === 'hostname' || prop === 'protocol' || prop === 'port' || prop === 'search' || prop === 'hash') {
          try {
            var u = new URL(window.__wr_href());
            u[prop] = val;
            setLocationUrl(u.href);
          } catch(e) {}
          return true;
        }
        try {
          target[prop] = val;
        } catch(e) {}
        return true;
      }
    });

    var safeDefine = function(obj, prop, desc) {
      try { Object.defineProperty(obj, prop, desc); } catch(e) {}
    };

    safeDefine(Location.prototype, 'pathname', {
      get: window.__wr_path,
      set: function(val) {
        try {
          var u = new URL(window.__wr_href());
          u.pathname = val;
          setLocationUrl(u.href);
        } catch(e) {}
      },
      configurable: true
    });

    safeDefine(Location.prototype, 'href', {
      get: window.__wr_href,
      set: setLocationUrl,
      configurable: true
    });

    safeDefine(Location.prototype, 'origin', { get: window.__wr_origin, configurable: true });
    
    safeDefine(Location.prototype, 'host', {
      get: window.__wr_host,
      set: function(val) {
        try {
          var u = new URL(window.__wr_href());
          u.host = val;
          setLocationUrl(u.href);
        } catch(e) {}
      },
      configurable: true
    });

    safeDefine(Location.prototype, 'hostname', {
      get: window.__wr_hostname,
      set: function(val) {
        try {
          var u = new URL(window.__wr_href());
          u.hostname = val;
          setLocationUrl(u.href);
        } catch(e) {}
      },
      configurable: true
    });

    safeDefine(Location.prototype, 'protocol', {
      get: window.__wr_protocol,
      set: function(val) {
        try {
          var u = new URL(window.__wr_href());
          u.protocol = val;
          setLocationUrl(u.href);
        } catch(e) {}
      },
      configurable: true
    });

    safeDefine(Location.prototype, 'port', {
      get: window.__wr_port,
      set: function(val) {
        try {
          var u = new URL(window.__wr_href());
          u.port = val;
          setLocationUrl(u.href);
        } catch(e) {}
      },
      configurable: true
    });

    safeDefine(Location.prototype, 'search', {
      get: window.__wr_search,
      set: function(val) {
        try {
          var u = new URL(window.__wr_href());
          u.search = val;
          setLocationUrl(u.href);
        } catch(e) {}
      },
      configurable: true
    });

    safeDefine(Location.prototype, 'hash', {
      get: window.__wr_hash,
      set: function(val) {
        if (originalHref && originalHref.set) {
          var currentRealHref = originalHref.get.call(window.location);
          var hashIdx = currentRealHref.indexOf('#');
          var base = hashIdx === -1 ? currentRealHref : currentRealHref.substring(0, hashIdx);
          if (val && val.indexOf('#') !== 0) val = '#' + val;
          originalHref.set.call(window.location, base + val);
        }
      },
      configurable: true
    });

    safeDefine(Location.prototype, 'reload', {
      value: function() {
        if (originalHref && originalHref.set) {
          originalHref.set.call(window.location, originalHref.get.call(window.location));
        } else {
          window.location.reload();
        }
      },
      configurable: true
    });

    safeDefine(Location.prototype, 'replace', { value: setLocationUrl, configurable: true });
    safeDefine(Location.prototype, 'assign', { value: setLocationUrl, configurable: true });
    safeDefine(Location.prototype, 'toString', { value: window.__wr_href, configurable: true });
    safeDefine(Location.prototype, 'valueOf', { value: window.__wr_href, configurable: true });

    safeDefine(document, 'URL', { get: window.__wr_href, configurable: true });
    safeDefine(document, 'domain', { get: window.__wr_hostname, configurable: true });
    safeDefine(window, 'origin', { get: window.__wr_origin, configurable: true });

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

    // NOTE: We intentionally do NOT block beforeunload, because it prevents the
    // user from clicking into replay pages and navigating within them.

    var originalPushState = history.pushState;
    var originalReplaceState = history.replaceState;
    var stateCallCount = 0;
    function wrapStateMethod(original) {
      return function(state, unused, url) {
        stateCallCount++;
        if (stateCallCount > 100) {
          if (stateCallCount % 100 === 0) {
            console.warn('wrapStateMethod called ' + stateCallCount + ' times for URL: ' + url);
          }
          if (stateCallCount > 500) {
            return;
          }
        }
        if (url) {
          try {
            var absUrl = new URL(url, window.__wr_href()).href;
            window.__wr_current_real_href = absUrl;
          } catch(e) {}
          var currentWb = '';
          var p = (originalPathname && originalPathname.get) ? originalPathname.get.call(window.location) : window.__wr_path();
          if (p.indexOf('/__wb/') === 0) {
            var nextSlash = p.indexOf('/', 6);
            currentWb = nextSlash === -1 ? p : p.substring(0, nextSlash);
          }
          if (currentWb && url.indexOf('/__wb/') === -1 && url.indexOf(currentWb) === -1) {
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

    # 3.5 Rewrite Location properties in inline scripts
    def rewrite_inline_script(m: re.Match) -> str:
        open_tag = m.group(1)
        js_content = m.group(2)
        close_tag = m.group(3)
        if js_content.strip() and "src=" not in open_tag.lower():
            try:
                js_content = rewrite_js(js_content)
            except Exception:
                pass
        return f"{open_tag}{js_content}{close_tag}"

    html = re.sub(
        r'(<script[^>]*>)(.*?)(</script>)',
        rewrite_inline_script, html, flags=re.IGNORECASE | re.DOTALL
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
