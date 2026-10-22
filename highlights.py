"""Full-game highlight videos for finished games, matched from a YouTube playlist.

Set the playlist in season.toml (optional; without it this does nothing):

    [highlights]
    youtube_playlist = "PL..."   # e.g. the NBA's "Nightly Full Game Highlights" playlist for the season

Titles look like "KINGS at CLIPPERS | FULL GAME HIGHLIGHTS | October 21, 2026": away and home nicknames plus
the local game date, which is enough to match a stored game. Anything else in the playlist is skipped.
The playlist page lists the newest ~100 videos, so run this daily: matches are kept once found.
"""

import json
import re
import tomllib
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

from season import Season, season_path
from teams import resolve_team

TITLE = re.compile(r"^\s*(?P<away>.+?)\s+at\s+(?P<home>.+?)\s*\|[^|]*FULL GAME HIGHLIGHTS[^|]*\|\s*(?P<date>\w+ \d{1,2}, \d{4})",
                   re.IGNORECASE)
INITIAL_DATA = re.compile(r"var ytInitialData = (\{.*?\});</script>", re.DOTALL)


def playlist_id(path: Path | None = None) -> str:
    raw = tomllib.loads(Path(path or season_path()).read_text())
    return str(raw.get("highlights", {}).get("youtube_playlist", "")).strip()


def fetch_playlist(playlist: str, timeout: int = 30) -> list:
    """[(video_id, title)] from the playlist's public page, newest first."""
    req = urllib.request.Request(f"https://www.youtube.com/playlist?list={playlist}",
                                 headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return videos_from_page(resp.read().decode("utf-8", "replace"))


def videos_from_page(html: str) -> list:
    m = INITIAL_DATA.search(html)
    if not m:
        raise ValueError("no ytInitialData on the playlist page (did YouTube change its layout?)")
    found = []

    def walk(node):
        if isinstance(node, dict):
            lockup = node.get("lockupViewModel")
            if lockup and lockup.get("contentId"):
                title = (lockup.get("metadata", {}).get("lockupMetadataViewModel", {})
                         .get("title", {}).get("content", ""))
                found.append((lockup["contentId"], title))
            vid = node.get("playlistVideoRenderer")  # older layout
            if vid and vid.get("videoId"):
                found.append((vid["videoId"], "".join(r.get("text", "") for r in vid.get("title", {}).get("runs", []))))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(json.loads(m.group(1)))
    return list(dict.fromkeys(found))


def parse_title(title: str) -> Optional[tuple]:
    """(away, home, date) from a full-game highlights title, or None."""
    m = TITLE.match(title)
    if not m:
        return None
    away, home = resolve_team(m["away"]), resolve_team(m["home"])
    try:
        day = datetime.strptime(m["date"], "%B %d, %Y").date()
    except ValueError:
        return None
    return (away, home, day) if away and home and away != home else None


def match(season: Season, games: list, videos: list) -> dict:
    """{game_id: (url, title)} for videos whose teams and local date match a game."""
    by_key = {(g.away, g.home, g.tip.astimezone(season.tz).date()): g for g in games}
    out = {}
    for video_id, title in reversed(videos):  # oldest first, so a re-upload (newer) wins
        key = parse_title(title)
        if key and key in by_key:
            out[by_key[key].id] = (f"https://www.youtube.com/watch?v={video_id}", title)
    return out


def sync_highlights(store, season: Season, playlist: str, fetch=None) -> str:
    """Match the playlist against stored games and save new matches. Returns a one-line summary."""
    if not playlist:
        return ""
    videos = (fetch or fetch_playlist)(playlist)
    known = {g.id: g.highlights for g in store.games()}
    found = match(season, store.games(), videos)
    new = {gid: v for gid, v in found.items() if known.get(gid) != v[0]}
    store.save_highlights(new)
    return f"Highlights: {len(videos)} videos in the playlist, {len(new)} newly matched."


def refresh(store, season: Season) -> str:
    """sync_highlights with the configured playlist, never raising: highlights are a nice-to-have."""
    try:
        return sync_highlights(store, season, playlist_id())
    except Exception as e:
        return f"Highlights: skipped ({type(e).__name__}: {e})"
