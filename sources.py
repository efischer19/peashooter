"""Schedule/results sources and how to pick one from the [source] section of season.toml.

nba_api is the interim source until hoopstat-haus (github.com/efischer19/hoopstat-haus) can serve
schedules and results. Install it with `uv sync --extra nba`.
"""

import logging
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Optional

from schedule import AWAY, CANCELLED, FINAL, HOME, IN_PROGRESS, NATIONAL, POSTPONED, SCHEDULED, Broadcast, FixtureSource, Game
from season import season_path
from teams import TEAMS

logger = logging.getLogger(__name__)

# NBA game ID prefixes: 001 preseason, 002 regular season (incl. Cup group and knockout games),
# 003 All-Star, 004 playoffs, 005 play-in, 006 NBA Cup Final (doesn't count in standings).
DEFAULT_GAME_TYPES = ("002", "006")
_STATUS = {1: SCHEDULED, 2: IN_PROGRESS, 3: FINAL}
# Watchable feeds in a flattened ScheduleLeagueV2 row (radio left out), national first.
BROADCAST_COLUMNS = (
    *((NATIONAL, f"nationalBroadcasters_{i}") for i in range(3)),
    (AWAY, "awayTvBroadcasters"), (AWAY, "awayOttBroadcasters"),
    (HOME, "homeTvBroadcasters"), (HOME, "homeOttBroadcasters"),
)


def broadcasts_from_nba_row(row: dict) -> tuple:
    out = []
    for scope, prefix in BROADCAST_COLUMNS:
        name = str(row.get(f"{prefix}_broadcasterDisplay") or "").strip()
        if name and row.get(f"{prefix}_broadcasterMedia", "tv") != "radio":
            link = str(row.get(f"{prefix}_broadcasterVideoLink") or "").strip()
            out.append(Broadcast(scope, name, link if link.startswith("https://") else ""))
    return tuple(dict.fromkeys(out))  # drop exact repeats


def game_from_nba_row(row: dict, game_types=DEFAULT_GAME_TYPES) -> Optional[Game]:
    """One ScheduleLeagueV2 'SeasonGames' row -> Game. None for other game types or TBD matchups."""
    game_id = str(row.get("gameId") or "")
    if not game_id.startswith(tuple(game_types)):
        return None
    away, home = row.get("awayTeam_teamTricode"), row.get("homeTeam_teamTricode")
    if away not in TEAMS or home not in TEAMS:
        return None  # e.g. Cup knockout games before the teams are set
    status_text = str(row.get("gameStatusText") or "").lower()
    if row.get("postponedStatus") == "Y" or "ppd" in status_text or "postponed" in status_text:
        status = POSTPONED
    elif "cancel" in status_text:
        status = CANCELLED
    else:
        status = _STATUS.get(int(row.get("gameStatus") or 1), SCHEDULED)
    scored = status in (IN_PROGRESS, FINAL)
    return Game(
        id=game_id,
        tip=datetime.fromisoformat(row["gameDateTimeUTC"].replace("Z", "+00:00")),
        away=away,
        home=home,
        status=status,
        away_score=int(row["awayTeam_score"]) if scored else None,
        home_score=int(row["homeTeam_score"]) if scored else None,
        event=str(row.get("gameLabel") or ""),
        broadcasts=broadcasts_from_nba_row(row),
    )


class NbaApiSource:
    """Whole-season schedule and scores from stats.nba.com via nba_api: one request per call."""

    def __init__(self, season: str, timeout: int = 60, game_types=DEFAULT_GAME_TYPES):
        self.season = season  # NBA season label, e.g. "2026-27"
        self.timeout = timeout
        self.game_types = tuple(game_types)

    def rows(self) -> list:
        from nba_api.stats.endpoints import ScheduleLeagueV2  # optional dependency

        table = ScheduleLeagueV2(season=self.season, timeout=self.timeout).season_games.get_dict()
        return [dict(zip(table["headers"], values)) for values in table["data"]]

    def games(self, start: datetime, end: datetime) -> list:
        games = (game_from_nba_row(r, self.game_types) for r in self.rows())
        return sorted((g for g in games if g and start <= g.tip < end), key=lambda g: g.tip)


def load_source(path: Path | None = None):
    """Build the source named in season.toml's [source] section."""
    path = Path(path or season_path())
    cfg = tomllib.loads(path.read_text()).get("source", {})
    kind = cfg.get("kind", "nba_api")
    if kind == "nba_api":
        return NbaApiSource(cfg["nba_season"], timeout=int(cfg.get("timeout", 60)),
                            game_types=cfg.get("game_types", DEFAULT_GAME_TYPES))
    if kind == "fixture":
        return FixtureSource(path.parent / cfg["path"])
    raise ValueError(f"unknown [source] kind {kind!r}; expected 'nba_api' or 'fixture'")
