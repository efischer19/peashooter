"""Pull the schedule and scores into the local store. Meant for a daily cron (or run it by hand).

    uv run --extra nba sync.py              # last week through next week
    uv run --extra nba sync.py --all        # the whole season calendar

Also matches full-game highlight videos when season.toml has a [highlights] playlist.
Exits non-zero on failure so cron can alert (a highlights failure is only reported).
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone

from env import load_env_file
from highlights import refresh as refresh_highlights
from pool import sync_schedule
from schedule import FINAL
from season import load_season
from sources import load_source
from store import Store


def sync_window(season, now: datetime, everything: bool = False) -> tuple:
    if everything:
        return season.week_start(1), season.week_start(season.weeks + 1)
    return now - timedelta(days=8), now + timedelta(days=15)


def run(season, source, store, now: datetime, everything: bool = False, highlights: bool = False) -> str:
    start, end = sync_window(season, now, everything)
    before = {g.id: g.status for g in store.games(start, end)}
    count = sync_schedule(store, source, start, end)
    newly_final = [g for g in store.games(start, end) if g.status == FINAL and before.get(g.id) != FINAL]
    lines = [f"Synced {count} games, {start:%Y-%m-%d} to {end:%Y-%m-%d}; {len(newly_final)} newly final."]
    lines += [f"  {g.label(season.tz)}: {g.away} {g.away_score}, {g.home} {g.home_score}" for g in newly_final]
    note = refresh_highlights(store, season) if highlights else ""
    return "\n".join(lines + ([note] if note else []))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="sync the whole season, not just nearby weeks")
    args = parser.parse_args(argv)
    load_env_file()
    try:
        print(run(load_season(), load_source(), Store(), datetime.now(timezone.utc), args.all, highlights=True))
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
