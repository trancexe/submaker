"""URL parser for FrameX links."""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse, parse_qs


@dataclass
class ParsedLink:
    media_type: str            # "movie" | "tv" | "anime"
    tmdb_id: str               # TMDB ID (or AniList ID for anime)
    season: Optional[int] = None
    episode: Optional[int] = None
    raw_input: str = ""

    @property
    def is_tv(self) -> bool:
        return self.media_type == "tv"

    @property
    def is_anime(self) -> bool:
        return self.media_type == "anime"

    @property
    def label(self) -> str:
        if self.is_tv:
            s = f" S{self.season:02d}" if self.season else ""
            e = f"E{self.episode:02d}" if self.episode else ""
            return f"TV {self.tmdb_id}{s}{e}"
        if self.is_anime:
            e = f" EP{self.episode}" if self.episode else ""
            return f"Anime {self.tmdb_id}{e}"
        return f"Movie {self.tmdb_id}"


_FRAMEX_HOSTS = re.compile(
    r"^https?://(?:www\.)?framextv\.[a-z0-9\-]+",
    re.IGNORECASE
)

_PATH_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"/(?:watch|embed)/anime/(\d+)/(\d+)"), "anime"),
    (re.compile(r"/(?:watch|embed|anime)/anime/(\d+)$"), "anime"),
    (re.compile(r"/anime/(\d+)$"), "anime"),
    (re.compile(r"/(?:watch|embed|tv)/(?:tv/)?(\d+)/(\d+)/(\d+)"), "tv"),
    (re.compile(r"/(?:watch|embed|tv)/(?:tv/)?(\d+)$"), "tv_or_movie"),
    (re.compile(r"/(?:watch|embed)/movie/(\d+)"), "movie"),
    (re.compile(r"/movie/(\d+)"), "movie"),
    (re.compile(r"/(?:watch|embed)/(\d+)/(\d+)/(\d+)"), "tv"),
    (re.compile(r"/(?:watch|embed)/(\d+)$"), "movie"),
]


def parse_link(raw: str) -> ParsedLink:
    raw = raw.strip()
    if not raw:
        raise ValueError("Input URL tidak boleh kosong.")

    if re.fullmatch(r"\d+", raw):
        return ParsedLink(media_type="movie", tmdb_id=raw, raw_input=raw)

    parsed_url = urlparse(raw)
    path = parsed_url.path.rstrip("/")
    qs = parse_qs(parsed_url.query)

    for pattern, kind in _PATH_PATTERNS:
        m = pattern.search(path)
        if not m:
            continue

        groups = m.groups()
        qs_ep = int(qs["episode"][0]) if "episode" in qs and qs["episode"][0].isdigit() else None
        qs_season = int(qs["season"][0]) if "season" in qs and qs["season"][0].isdigit() else None

        if kind == "anime":
            ep = int(groups[1]) if len(groups) > 1 else qs_ep
            return ParsedLink(
                media_type="anime",
                tmdb_id=groups[0],
                episode=ep or 1,
                raw_input=raw,
            )

        if kind == "tv":
            season = int(groups[1]) if len(groups) > 1 else (qs_season or 1)
            episode = int(groups[2]) if len(groups) > 2 else (qs_ep or 1)
            return ParsedLink(
                media_type="tv",
                tmdb_id=groups[0],
                season=season,
                episode=episode,
                raw_input=raw,
            )

        if kind == "tv_or_movie":
            if "/tv" in path.lower() or qs_season is not None or qs_ep is not None:
                return ParsedLink(
                    media_type="tv",
                    tmdb_id=groups[0],
                    season=qs_season or 1,
                    episode=qs_ep or 1,
                    raw_input=raw,
                )
            return ParsedLink(media_type="movie", tmdb_id=groups[0], raw_input=raw)

        return ParsedLink(media_type="movie", tmdb_id=groups[0], raw_input=raw)

    raise ValueError(f"Tidak dapat mengekstrak ID dari URL: {raw}")
