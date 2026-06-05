import os
import mimetypes
from datetime import datetime
from pathlib import Path

# Register modern web MIME types that are often missing from the Windows registry
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("font/otf", ".otf")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/avif", ".avif")
mimetypes.add_type("image/x-icon", ".ico")


DEFAULT_ARCHIVE = "web_archive"
VERSION = "2.0"

STATIC_MIME = {
    # Text
    "text/html", "text/css", "text/javascript", "text/plain", "text/xml",
    # Application
    "application/javascript", "application/x-javascript",
    "application/json", "application/ld+json", "application/manifest+json",
    "application/xml", "application/xhtml+xml",
    "application/octet-stream", "application/wasm",
    "application/pdf",
    # Images
    "image/svg+xml", "image/png", "image/jpeg", "image/gif", "image/webp",
    "image/avif", "image/ico", "image/x-icon", "image/bmp", "image/tiff",
    "image/vnd.microsoft.icon",
    # Fonts
    "font/woff", "font/woff2", "font/ttf", "font/otf",
    "application/x-font-ttf", "application/x-font-woff", "application/font-woff",
    "application/font-woff2", "application/x-font-opentype",
    "application/vnd.ms-fontobject",
    # Audio/Video
    "audio/mpeg", "audio/ogg", "audio/wav", "audio/webm",
    "video/mp4", "video/webm", "video/ogg",
}

C = {
    "G": "\033[92m", "Y": "\033[93m", "R": "\033[91m",
    "C": "\033[96m", "B": "\033[94m", "M": "\033[95m",
    "W": "\033[97m", "X": "\033[0m", "BD": "\033[1m",
}

import sys

# Reconfigure stdout/stderr to UTF-8 on Windows if not already done
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

def log(level: str, msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    lc = {"INFO": C["C"], "OK": C["G"], "WARN": C["Y"], "ERR": C["R"], "SAVE": C["B"], "SRV": C["M"]}
    c = lc.get(level, C["X"])
    text = f"{C['BD']}[{ts}]{C['X']} {c}[{level:4}]{C['X']} {msg}"
    try:
        print(text)
    except UnicodeEncodeError:
        # Safe fallback replacing characters that the console encoding does not support
        safe_text = text.encode(sys.stdout.encoding or 'ascii', errors='replace').decode(sys.stdout.encoding or 'ascii')
        print(safe_text)

