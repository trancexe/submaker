"""StreamDown / Submaker Downloader Configuration."""

import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# System ffmpeg is used directly (/usr/bin/ffmpeg)
FFMPEG_BIN = "ffmpeg"
FFPROBE_BIN = "ffprobe"

# FrameX API Endpoints
FRAMEX_API_BASE = "https://api.framextv.tech"
FRAMEX_STREAM_ENDPOINT = f"{FRAMEX_API_BASE}/api/stream"
FRAMEX_DETAILS_ENDPOINT = f"{FRAMEX_API_BASE}/api/details"
FRAMEX_ANIME_BASE = f"{FRAMEX_API_BASE}/anime"
FRAMEX_ANIME_STREAM_ENDPOINT = f"{FRAMEX_ANIME_BASE}/api/stream"
FRAMEX_ANIME_PROVIDERS_ENDPOINT = f"{FRAMEX_ANIME_BASE}/api/providers"
ANILIST_GRAPHQL_ENDPOINT = "https://graphql.anilist.co"
FRAMEX_SITE = "https://framextv.xyz"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.rivestream.app/",
    "Origin": "https://www.rivestream.app",
}

MAX_CONCURRENT_SEGMENTS = 10
SEGMENT_RETRY_LIMIT = 5
SEGMENT_RETRY_BACKOFF_BASE = 1.5
SEGMENT_TIMEOUT = 30
