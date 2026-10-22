"""The season calendar: weeks, cycles, deadlines, off weeks, special games and members (from season.toml)."""

import os
import tomllib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

SEASON_FILE = Path(__file__).resolve().parent / "season.toml"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def season_path() -> Path:
    """PEASHOOTER_SEASON overrides the default season.toml next to this file."""
    return Path(os.environ.get("PEASHOOTER_SEASON") or SEASON_FILE)


@dataclass(frozen=True)
class Special:
    name: str
    date: date
    points: int


@dataclass(frozen=True)
class Member:
    name: str  # the member's key everywhere (picks, form dropdown); keep it stable
    slack_id: str = ""  # for the Slack bot; optional until then
    alias: str = ""  # the only name the public scoreboard page shows


@dataclass(frozen=True)
class Season:
    name: str
    tz: ZoneInfo
    week1_start: date  # weeks run 7 days from this date's weekday
    weeks: int
    picks_per_week: int = 10
    cycle_weeks: int = 3
    points_per_win: int = 1
    deadline_day: int = 0  # days after the week starts
    deadline_time: time = time(19, 0)
    grace: timedelta = timedelta(hours=24)
    off_weeks: tuple = ()  # ((week, label), ...)
    specials: tuple = ()
    members: tuple = ()

    def week_start(self, week: int) -> datetime:
        return datetime.combine(self.week1_start + timedelta(weeks=week - 1), time(0), self.tz)

    def week_bounds(self, week: int) -> tuple:
        return self.week_start(week), self.week_start(week + 1)

    def week_for(self, when: datetime) -> Optional[int]:
        days = (when.astimezone(self.tz).date() - self.week1_start).days
        week = days // 7 + 1
        return week if days >= 0 and week <= self.weeks else None

    def off_week_label(self, week: int) -> Optional[str]:
        return dict(self.off_weeks).get(week)

    def is_regular(self, week: int) -> bool:
        return 1 <= week <= self.weeks and self.off_week_label(week) is None

    def regular_weeks(self) -> list:
        return [w for w in range(1, self.weeks + 1) if self.is_regular(w)]

    def cycle_for(self, week: int) -> Optional[int]:
        """Cycles count regular weeks only, so off weeks pause a cycle rather than break it."""
        regular = self.regular_weeks()
        return regular.index(week) // self.cycle_weeks + 1 if week in regular else None

    def weeks_in_cycle(self, cycle: int) -> list:
        return [w for w in self.regular_weeks() if self.cycle_for(w) == cycle]

    def deadline(self, week: int) -> datetime:
        """When the week's form picks lock."""
        day = self.week_start(week).date() + timedelta(days=self.deadline_day)
        return datetime.combine(day, self.deadline_time, self.tz)

    def grace_end(self, week: int) -> datetime:
        return self.deadline(week) + self.grace

    def special_for(self, tip: datetime) -> Optional[Special]:
        local_day = tip.astimezone(self.tz).date()
        return next((s for s in self.specials if s.date == local_day), None)

    def member(self, name_or_slack_id: str) -> Optional[Member]:
        """Case-insensitive name, or exact Slack ID."""
        key = name_or_slack_id.strip()
        return next((m for m in self.members if m.name.casefold() == key.casefold()
                     or (m.slack_id and m.slack_id == key)), None)


def load_season(path: Path | None = None) -> Season:
    raw = tomllib.loads(Path(path or season_path()).read_text())
    s = raw["season"]
    week1_start = s["week1_start"]
    deadline_weekday = WEEKDAYS.index(s.get("deadline_day", WEEKDAYS[week1_start.weekday()]).lower())
    hour, minute = (int(x) for x in s.get("deadline_time", "19:00").split(":"))
    season = Season(
        name=s["name"],
        tz=ZoneInfo(s.get("timezone", "America/New_York")),
        week1_start=week1_start,
        weeks=int(s["weeks"]),
        picks_per_week=int(s.get("picks_per_week", 10)),
        cycle_weeks=int(s.get("cycle_weeks", 3)),
        points_per_win=int(s.get("points_per_win", 1)),
        deadline_day=(deadline_weekday - week1_start.weekday()) % 7,
        deadline_time=time(hour, minute),
        grace=timedelta(hours=float(s.get("grace_hours", 24))),
        off_weeks=tuple(sorted((int(k), v) for k, v in raw.get("off_weeks", {}).items())),
        specials=tuple(Special(x["name"], x["date"], int(x["points"])) for x in raw.get("specials", [])),
        members=tuple(Member(m["name"], m.get("slack_id", ""), m.get("alias", "")) for m in raw.get("members", [])),
    )
    names = [m.name.casefold() for m in season.members]
    if len(set(names)) != len(names):
        raise ValueError("member names must be unique")
    bad = [w for w, _ in season.off_weeks if not 1 <= w <= season.weeks]
    if bad:
        raise ValueError(f"off_weeks {bad} are outside weeks 1-{season.weeks}")
    return season
