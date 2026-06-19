/**
 * SaveTheWeb — Replay Service Worker
 *
 * Scope: /   (registered from the replayed page via navigator.serviceWorker.register('/sw.js'))
 *
 * Responsibility:
 *   1. Intercept every outgoing fetch (images, CSS, JS, XHR, fetch() API calls).
 *   2. If the request targets a URL that is in our archive, rewrite it to
 *      /__wb/<percent-encoded-url> so WaybackServer serves it locally.
 *   3. If the request is already a /__wb/ or /__archive__ internal path, pass it through.
 *   4. For anything else (un-archived external URL) return a graceful stub so
 *      the page doesn't throw network errors.
 *
 * Communication:
 *   The SW receives the live route map from the main thread via postMessage
 *   { type: 'INIT_ROUTES', routes: { [url]: relPath } }
 *   It stores this in a module-level Map so look-ups are O(1).
 *
 * Why not just redirect everything to /__wb/?
 *   We need to distinguish "in archive" vs "not in archive" because some requests
 *   (e.g. blob: URLs, data: URIs, inline resources) must never be proxied.
 */

const SW_VERSION = 'savetheweb-v1';

// ── Route registry ────────────────────────────────────────────────────────────
// Populated via postMessage from the injected tokens script in rewrite_html.
// Keys   = original absolute URLs (e.g. "https://cdn.example.com/app.js")
// Values = anything truthy (we only need to know IF the key exists)
let _routeSet = new Set();

// URL variants index: maps normalised forms back to canonical archived URL
// Built once when routes are received, then used for O(1) fuzzy lookups.
let _variantMap = new Map();   // normalised-variant → canonical URL

// Flag: have we received routes yet?
let _ready = false;

// ── Install / Activate ────────────────────────────────────────────────────────

self.addEventListener('install', (event) => {
    // Skip the waiting phase so the new SW activates immediately without
    // requiring a full page reload (important during development).
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    // Claim all open clients immediately so the very first navigation after
    // registration is already intercepted (no uncontrolled-page window).
    event.waitUntil(self.clients.claim());
});

// ── Message handler (route injection) ────────────────────────────────────────

self.addEventListener('message', (event) => {
    const msg = event.data;
    if (!msg || msg.type !== 'INIT_ROUTES') return;

    const routes = msg.routes || {};   // { [url]: relPath }
    _routeSet = new Set(Object.keys(routes));
    _variantMap = _buildVariantMap(_routeSet);
    _ready = true;
});

/**
 * Build a Map from every URL variant form → canonical URL.
 * This mirrors the Python _build_url_index() logic in rewriter.py.
 */
function _buildVariantMap(urlSet) {
    const m = new Map();
    for (const url of urlSet) {
        // Canonical
        m.set(url, url);

        try {
            const p = new URL(url);

            // Without query string
            const noQuery = p.origin + p.pathname;
            if (!m.has(noQuery)) m.set(noQuery, url);

            // Protocol-relative
            const protoRel = '//' + p.host + p.pathname;
            if (!m.has(protoRel)) m.set(protoRel, url);

            // Path-only
            if (!m.has(p.pathname)) m.set(p.pathname, url);

            // Trailing-slash variants
            const withSlash    = p.origin + p.pathname.replace(/\/?$/, '/');
            const withoutSlash = p.origin + p.pathname.replace(/\/$/, '');
            if (!m.has(withSlash))    m.set(withSlash, url);
            if (!m.has(withoutSlash)) m.set(withoutSlash, url);

        } catch (_) { /* not a parseable URL — skip variants */ }
    }
    return m;
}

// ── Fetch interception ────────────────────────────────────────────────────────

self.addEventListener('fetch', (event) => {
    const req = event.request;
    const url = req.url;

    // 1. Always pass through non-HTTP(S) schemes (blob:, data:, chrome-extension:, etc.)
    if (!url.startsWith('http://') && !url.startsWith('https://')) return;

    // 2. Block localhost self-referral loops (e.g. /__wb/http%3A%2F%2Flocalhost%3A...)
    // These happen when the SW miscategorises a local URL as an archived one.
    if (url.startsWith(self.location.origin + '/__wb/http%3A%2F%2Flocalhost') ||
        url.startsWith(self.location.origin + '/__wb/https%3A%2F%2Flocalhost')) {
        return; // Let it go to network (server will 404 gracefully)
    }

    // 3. Pass through our own internal paths untouched
    if (_isInternal(url, req.referrer)) return;

    event.respondWith((async () => {
        // 3. Wait up to 50ms for routes to arrive if we just started (avoids early page load race conditions)
        if (!_ready) {
            for (let i = 0; i < 5; i++) {
                if (_ready) break;
                await new Promise(r => setTimeout(r, 10));
            }
            if (!_ready) {
                return fetch(req);
            }
        }

        // Get the active window/client URL
        let clientUrl = null;
        if (event.clientId) {
            try {
                const client = await self.clients.get(event.clientId);
                if (client) {
                    clientUrl = client.url;
                }
            } catch (_) {}
        }

        // Determine the original canonical URL of the request
        const canonical = _getCanonicalUrl(url, req.referrer, clientUrl);
        
        if (canonical) {
            const resolved = _resolve(canonical);
            if (resolved) {
                return _serveFromArchive(req, resolved);
            }
        }

        // Fallback: If it's a localhost request, try matching by pathname
        if (url.startsWith(self.location.origin)) {
            try {
                const parsed = new URL(url);
                const resolvedPath = _resolve(parsed.pathname);
                if (resolvedPath) {
                    return _serveFromArchive(req, resolvedPath);
                }
            } catch (_) {}
        }

        // Return a graceful stub
        return _serveStub(req, canonical || url);
    })());
});

/**
 * Resolve a request URL (which might have leaked to localhost origin) 
 * back to its original canonical absolute archived URL using Referer or Client URL.
 */
function _getCanonicalUrl(requestUrl, referrer, clientUrl) {
    // If it's already an absolute URL to an external domain, it's canonical
    if (!requestUrl.startsWith(self.location.origin)) {
        return requestUrl;
    }

    let archivedPageUrl = null;
    // Extract the encoded archived page URL from Referer or Client URL
    for (const ref of [referrer, clientUrl]) {
        if (ref && ref.includes('/__wb/')) {
            const idx = ref.indexOf('/__wb/');
            const encoded = ref.substring(idx + 6).split('?')[0];
            try {
                archivedPageUrl = decodeURIComponent(encoded);
                break;
            } catch (_) {}
        }
    }

    if (!archivedPageUrl) {
        return null;
    }

    try {
        const parsedRef = new URL(archivedPageUrl);
        const refOrigin = parsedRef.origin;
        const reqParsed = new URL(requestUrl);
        
        // Resolve path relative to the archived page URL's origin or path
        if (reqParsed.pathname.startsWith('/')) {
            return refOrigin + reqParsed.pathname + reqParsed.search;
        } else {
            return new URL(reqParsed.pathname + reqParsed.search, archivedPageUrl).href;
        }
    } catch (_) {
        return null;
    }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Return true if the URL is one of our own internal endpoints that must
 * always go to the network (the local WaybackServer).
 */
function _isInternal(url, referrer) {
    try {
        const parsed = new URL(url);
        const path = parsed.pathname;

        // 1. System paths are always internal (network-only)
        if (
            path === '/' ||
            path === '/favicon.ico' ||
            path.startsWith('/__archive__') ||
            path.startsWith('/__view/') ||
            path.startsWith('/__asset/') ||
            path.startsWith('/__mhtml/') ||
            path.startsWith('/__wb/') ||
            path.startsWith('/sw.js')
        ) {
            return true;
        }

        // 2. External domains that should ALWAYS bypass the SW
        //    (Google Fonts, favicon APIs, CDNs used by dashboard/view UI)
        const externalPassthrough = [
            'fonts.googleapis.com',
            'fonts.gstatic.com',
            'www.google.com',    // favicon API
            'cdn.jsdelivr.net',  // mermaid, marked CDN used by View UI
        ];
        if (externalPassthrough.some(d => parsed.hostname === d || parsed.hostname.endsWith('.' + d))) {
            return true;
        }

        // 3. If the request is initiated by a system page (Dashboard or View UI),
        // it must NOT be intercepted (let it access the real internet/fonts/favicons).
        if (referrer) {
            try {
                const refParsed = new URL(referrer);
                const refPath = refParsed.pathname;
                if (refPath.startsWith('/__archive__') || refPath.startsWith('/__view/')) {
                    return true;
                }
            } catch (_) {}
        }
    } catch (_) {}
    return false;
}

/**
 * Look up the URL in our route set, trying progressively looser matches.
 * Returns the canonical archived URL string, or null if not found.
 */
function _resolve(url) {
    // 1. Exact match
    if (_routeSet.has(url)) return url;

    // 2. Fuzzy via variant map
    if (_variantMap.has(url)) return _variantMap.get(url);

    // 3. Try stripping the query string
    try {
        const p = new URL(url);
        const noQuery = p.origin + p.pathname;
        if (_variantMap.has(noQuery)) return _variantMap.get(noQuery);
    } catch (_) {}

    // 4. Try matching by path-only (pathname) as a last-resort fallback for local/leak URLs
    try {
        const p = new URL(url);
        if (_variantMap.has(p.pathname)) return _variantMap.get(p.pathname);
    } catch (_) {}

    return null;
}

/**
 * Rewrite the request to go through /__wb/<encodedCanonicalUrl> on localhost,
 * preserving the original method, headers, and body.
 */
async function _serveFromArchive(originalReq, canonicalUrl) {
    // Build the /__wb/ URL pointing at our local WaybackServer.
    // self.location.origin is something like "http://localhost:8080".
    const proxyUrl = self.location.origin
        + '/__wb/'
        + encodeURIComponent(canonicalUrl);

    // Clone the original request but point it at our proxy URL.
    // We must pass through the method and body for POST/PUT XHR calls.
    const proxyInit = {
        method:  originalReq.method,
        headers: originalReq.headers,
        // 'manual' lets us see 3xx responses without auto-following — the
        // WaybackServer already handles redirect rewriting server-side.
        redirect: 'follow',
    };

    // Only attach body for methods that carry one (GET/HEAD must not have a body).
    if (!['GET', 'HEAD'].includes(originalReq.method.toUpperCase())) {
        try {
            proxyInit.body = await originalReq.clone().arrayBuffer();
        } catch (_) { /* body already consumed — proceed without */ }
    }

    try {
        const proxyReq  = new Request(proxyUrl, proxyInit);
        const proxyResp = await fetch(proxyReq);
        return proxyResp;
    } catch (err) {
        // WaybackServer is unreachable (e.g. server restarted mid-session)
        console.warn('[SW] Archive proxy fetch failed for', canonicalUrl, err);
        return _makeErrorResponse(503, 'Archive server unreachable');
    }
}

/**
 * For un-archived URLs, return a graceful no-op stub so the page doesn't
 * throw a TypeError("Failed to fetch") or a CORS error that breaks the app.
 *
 * Strategy:
 *   - API-shaped URLs  → empty JSON body (200)
 *   - Image requests   → 1x1 transparent PNG (200)
 *   - Font/CSS/JS      → empty body (200) with correct content-type
 *   - Everything else  → 204 No Content
 */
function _serveStub(req, url) {
    const accept  = req.headers.get('Accept') || '';
    const dest    = req.destination;           // 'image', 'script', 'style', 'font', ''

    // ── API / JSON ────────────────────────────────────────────────────────
    const isApiUrl = /\/api\/|\/graphql|\/rest\/|\/v[123]\/|\/ajax\/|\/action\//.test(url);
    if (isApiUrl || accept.includes('application/json')) {
        const body = url.includes('graphql')
            ? '{"data":{}}'
            : JSON.stringify({ code: 0, data: null, msg: '', __wr_stub: true });
        return _makeResponse(200, 'application/json; charset=utf-8', body);
    }

    // ── HTML Document / Iframe ────────────────────────────────────────────
    if (dest === 'document' || dest === 'iframe' || accept.includes('text/html')) {
        return _makeResponse(200, 'text/html; charset=utf-8', '<!DOCTYPE html><html><body></body></html>');
    }

    // ── Images ────────────────────────────────────────────────────────────
    if (dest === 'image' || /\.(png|jpe?g|gif|webp|avif|svg)(\?|$)/i.test(url)) {
        // 1×1 transparent GIF — 26 bytes, universally understood
        const gif = 'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
        const bytes = Uint8Array.from(atob(gif), c => c.charCodeAt(0));
        return new Response(bytes, {
            status: 200,
            headers: { 'Content-Type': 'image/gif', 'X-WR-Stub': '1' },
        });
    }

    // ── Scripts ───────────────────────────────────────────────────────────
    if (dest === 'script' || /\.m?js(\?|$)/i.test(url)) {
        return _makeResponse(200, 'application/javascript; charset=utf-8', '/* wr-stub */');
    }

    // ── Stylesheets ───────────────────────────────────────────────────────
    if (dest === 'style' || /\.css(\?|$)/i.test(url)) {
        return _makeResponse(200, 'text/css; charset=utf-8', '/* wr-stub */');
    }

    // ── Fonts ─────────────────────────────────────────────────────────────
    if (dest === 'font' || /\.(woff2?|ttf|otf|eot)(\?|$)/i.test(url)) {
        return _makeResponse(200, 'font/woff2', '');
    }

    // ── Default: 204 No Content ───────────────────────────────────────────
    return new Response(null, {
        status:  204,
        headers: { 'X-WR-Stub': '1', 'X-WR-OrigURL': url },
    });
}

function _makeResponse(status, contentType, body) {
    return new Response(body, {
        status,
        headers: {
            'Content-Type':  contentType,
            'Cache-Control': 'no-store',
            'X-WR-Stub':     '1',
        },
    });
}

function _makeErrorResponse(status, message) {
    return new Response(message, {
        status,
        headers: { 'Content-Type': 'text/plain', 'X-WR-Error': '1' },
    });
}