"""Shared fixtures: a test season and a synthetic schedule. No network."""

import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from schedule import FINAL, Game  # noqa: E402
from season import Member, Season, Special  # noqa: E402
from store import Store  # noqa: E402
from teams import TEAMS  # noqa: E402

ET = ZoneInfo("America/New_York")
CODES = sorted(TEAMS)


def make_season(**overrides) -> Season:
    kwargs = dict(
        name="Test", tz=ET, week1_start=date(2026, 10, 26), weeks=10,
        off_weeks=((7, "Cup Final week"), (9, "Christmas week")),
        specials=(Special("NBA Cup Final", date(2026, 12, 11), 5), Special("Christmas Day", date(2026, 12, 25), 2)),
        members=(Member("Alice", "U1"), Member("Bob"), Member("Cat")),
    )
    kwargs.update(overrides)
    return Season(**kwargs)


def at(season: Season, week: int, day: int, hour: int = 19, minute: int = 30) -> datetime:
    """Local time on day `day` (0 = Monday) of `week`."""
    return datetime.combine(season.week_start(week).date() + timedelta(days=day), time(hour, minute), ET)


def week_schedule(season: Season, week: int) -> list:
    """Every team plays Tue, Thu and Sat (three different opponents); the home team always wins once final."""
    games = []
    for day, shift in ((1, 0), (3, 1), (5, 2)):
        for i in range(15):
            away, home = CODES[i], CODES[15 + (i + shift) % 15]
            games.append(Game(f"w{week}d{day}g{i}", at(season, week, day), away, home))
    return games


def finish(games: list) -> list:
    return [Game(g.id, g.tip, g.away, g.home, FINAL, 100, 110) for g in games]


@pytest.fixture
def season():
    return make_season()


@pytest.fixture
def store():
    return Store(":memory:")
