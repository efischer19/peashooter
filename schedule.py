"""NBA games and where they come from. The real upstream source plugs in behind ScheduleSource."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol

SCHEDULED, IN_PROGRESS, FINAL, POSTPONED, CANCELLED = "scheduled", "in_progress", "final", "postponed", "cancelled"
NATIONAL, HOME, AWAY = "natl", "home", "away"


@dataclass(frozen=True)
class Broadcast:
    """A TV or streaming feed for a game. Local (home/away) feeds are usually in-market only."""
    scope: str  # NATIONAL, HOME or AWAY
    name: str  # e.g. "ESPN", "DAZN-IND", "Jazz+"
    link: str = ""  # a watch link when the feed has one

    def to_dict(self) -> dict:
        return {"scope": self.scope, "name": self.name, "link": self.link}


@dataclass(frozen=True)
class Game:
    id: str
    tip: datetime  # timezone-aware
    away: str
    home: str
    status: str = SCHEDULED
    away_score: Optional[int] = None
    home_score: Optional[int] = None
    event: str = ""  # NBA game label, e.g. "Emirates NBA Cup", "NBA Mexico City Game"
    broadcasts: tuple = ()  # Broadcasts, national first
    highlights: str = ""  # a full-game highlights video URL, matched after the game (see highlights.py)

    @property
    def teams(self) -> tuple:
        return (self.away, self.home)

    @property
    def winner(self) -> Optional[str]:
        if self.status != FINAL or self.away_score is None or self.home_score is None:
            return None
        return self.home if self.home_score > self.away_score else self.away

    def label(self, tz) -> str:
        """e.g. 'Tue 10/27 BOS @ NYK'"""
        local = self.tip.astimezone(tz)
        return f"{local:%a} {local.month}/{local.day} {self.away} @ {self.home}"

    def to_dict(self) -> dict:
        return {"id": self.id, "tip": self.tip.astimezone(timezone.utc).isoformat(), "away": self.away, "home": self.home,
                "status": self.status, "away_score": self.away_score, "home_score": self.home_score, "event": self.event,
                "broadcasts": [b.to_dict() for b in self.broadcasts], "highlights": self.highlights}

    @classmethod
    def from_dict(cls, d: dict) -> "Game":
        tip = datetime.fromisoformat(d["tip"])
        if tip.tzinfo is None:
            raise ValueError(f"game {d['id']}: tip time needs a timezone")
        return cls(id=str(d["id"]), tip=tip, away=d["away"], home=d["home"], status=d.get("status", SCHEDULED),
                   away_score=d.get("away_score"), home_score=d.get("home_score"), event=d.get("event") or "",
                   broadcasts=tuple(Broadcast(**b) for b in d.get("broadcasts") or ()),
                   highlights=d.get("highlights") or "")


class ScheduleSource(Protocol):
    def games(self, start: datetime, end: datetime) -> list:
        """Games tipping in [start, end), with current status and scores."""


class FixtureSource:
    """Games from a local JSON list of Game dicts. Stand-in until the real upstream source is chosen."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def games(self, start: datetime, end: datetime) -> list:
        games = [Game.from_dict(d) for d in json.loads(self.path.read_text())]
        return sorted((g for g in games if start <= g.tip < end), key=lambda g: g.tip)
