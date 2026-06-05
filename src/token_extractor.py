import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.archive import SnapshotStore

_TOKEN_RE = {
    "jwt":     re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "bearer":  re.compile(r"[Bb]earer\s+([A-Za-z0-9\-._~+/]{20,})"),
    "api_key": re.compile(r"(?:api[_-]?key|apikey|x-api-key)[\"'\s:=]+([A-Za-z0-9\-_]{16,})"),
    "oauth":   re.compile(r"(?:access_token|oauth_token)[\"'\s:=]+([A-Za-z0-9\-_.]{16,})"),
    "session": re.compile(r"(?:session[_-]?id|PHPSESSID|JSESSIONID)[\"'\s:=]+([A-Za-z0-9\-_]{16,})"),
    "csrf":    re.compile(r"(?:csrf[_-]?token|_token|X-CSRF-TOKEN)[\"'\s:=]+([A-Za-z0-9\-_+/=]{16,})"),
}

def extract_tokens(text: str, url: str, store: "SnapshotStore"):
    for tt, pat in _TOKEN_RE.items():
        for m in pat.findall(text):
            val = m if isinstance(m, str) else m
            if len(val) > 10:
                store.save_token(tt, val, url)
