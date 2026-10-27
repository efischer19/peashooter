"""PEAshooter admin CLI: run the pool by hand from Google Form CSV exports. Output is Slack-ready text.

    uv run --extra nba admin.py schedule-md --week 1 [--week 2 ...] [--out DIR]
    uv run --extra google --extra nba admin.py [--post] sunday     # open the coming week's form + grid, announce
    uv run --extra google --extra nba admin.py [--post] reminder   # who hasn't picked yet
    uv run --extra google --extra nba admin.py [--post] monday     # deadline: close, ingest, grid, summary
    uv run --extra google --extra nba admin.py daily               # sync scores, rebuild grids
    uv run --extra nba admin.py [--post] digest                    # morning: standings + today's games
    uv run --extra nba admin.py site [--out data/site]             # public scoreboard page (index.html)
    uv run --extra google --extra nba admin.py ingest --week 1 [--dry-run]   # reads the Sheet
    uv run --extra nba admin.py ingest responses.csv --week 1               # or a CSV export
    uv run --extra nba admin.py replace --week 1 --member "Bob" "Lakers Fri, Heat vs Knicks"
    uv run --extra nba admin.py remaining --week 2
    uv run --extra nba admin.py picks --week 1
    uv run --extra nba admin.py standings
    uv run --extra nba admin.py grid --week 1 [--sheet]    # needs --extra google for --sheet

Commands that need games sync the relevant weeks from the schedule source first (skip with --no-sync).
"""

import argparse
import csv
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional

import highlights
import pool
import report
from env import load_env_file
import rules
from season import Season, load_season
from store import Store
from teams import TEAMS

TIMESTAMP_FORMATS = ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


@dataclass(frozen=True)
class Response:
    row: int
    submitted_at: datetime
    name: str
    week: Optional[int]
    picks: str


def parse_timestamp(text: str, tz) -> datetime:
    """Google Sheets exports timestamps in the spreadsheet's time zone; set it to the season's (File > Settings)."""
    text = text.strip()
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        dt = next((datetime.strptime(text, f) for f in TIMESTAMP_FORMATS if _matches(text, f)), None)
        if dt is None:
            raise ValueError(f"unrecognised timestamp {text!r}")
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def _matches(text: str, fmt: str) -> bool:
    try:
        datetime.strptime(text, fmt)
        return True
    except ValueError:
        return False


def _column(headers: list, keyword: str, required: bool = True) -> Optional[str]:
    found = [h for h in headers if keyword in h.lower()]
    if not found and required:
        raise ValueError(f"no column containing {keyword!r} in {headers}")
    return found[0] if found else None


def responses_from_rows(headers: list, rows: list, season: Season) -> list:
    """Form responses from a header row plus data rows (lists or dicts). Columns are found by keyword:
    timestamp, name, week (optional), pick. Row numbers match the spreadsheet (header is row 1)."""
    ts_col, name_col, pick_col = (_column(headers, k) for k in ("timestamp", "name", "pick"))
    week_col = _column(headers, "week", required=False)
    out = []
    for i, row in enumerate(rows, start=2):
        if not isinstance(row, dict):
            row = dict(zip(headers, list(row) + [""] * (len(headers) - len(row))))
        if not (row.get(ts_col) or "").strip():
            continue
        week_num = re.search(r"\d+", (row.get(week_col) or "") if week_col else "")
        out.append(Response(i, parse_timestamp(row[ts_col], season.tz), (row[name_col] or "").strip(),
                            int(week_num.group()) if week_num else None, row[pick_col] or ""))
    return out


def read_responses(path: Path, season: Season) -> list:
    """Responses from a CSV export of the linked responses tab."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return responses_from_rows(reader.fieldnames or [], list(reader), season)


def member_for(season: Season, name: str) -> Optional[str]:
    member = season.member(name)
    return member.name if member else None


def refresh(store: Store, season: Season, source, weeks: list) -> None:
    if source is not None and weeks:
        start = season.week_start(min(weeks)) - timedelta(days=1)
        pool.sync_schedule(store, source, start, season.week_start(max(weeks) + 1))


def responses_for_week(season: Season, responses: list, week: int) -> list:
    """Rows labelled with this week, or (without a Week column) sent between the previous deadline and grace end."""
    if any(r.week is not None for r in responses):
        return [r for r in responses if r.week == week]
    opens = season.deadline(week) - timedelta(days=7)
    return [r for r in responses if opens < r.submitted_at <= season.grace_end(week)]


def ingest(season: Season, store: Store, responses: list, week: int, source=None) -> str:
    """Validate and store a week's responses; the latest on-time response per member counts."""
    refresh(store, season, source, [week])
    games = pool.week_games(store, season, week)
    if not games:
        raise ValueError(f"no games stored for week {week}; sync the schedule first")
    rows = sorted(responses_for_week(season, responses, week), key=lambda r: r.submitted_at)
    by_member, unknown = {}, []
    for r in rows:
        member = member_for(season, r.name)
        if member is None:
            unknown.append(f"{r.name} (row {r.row})")
        else:
            by_member.setdefault(member, []).append(r)

    results, late = {}, {}
    if season.is_regular(week):
        deadline = season.deadline(week)
        for member, mine in by_member.items():
            on_time = [r for r in mine if r.submitted_at <= deadline]
            if len(on_time) < len(mine):
                late[member] = bool(on_time)
            chosen = on_time[-1] if on_time else mine[-1]  # an all-late response is stored as rejected, for the record
            parsed = rules.parse_picks(chosen.picks, games, after=deadline, tz=season.tz)
            results[member] = pool.ingest_form(
                store, season, member, week, [(p.game_id, p.team) for p in parsed if p.game_id],
                chosen.submitted_at, unparsed=tuple(p.rejection() for p in parsed if not p.game_id))
    else:
        specials = [g for g in games if season.special_for(g.tip)]
        if not specials:
            raise ValueError(f"week {week} is an off week with no special games")
        for member, mine in by_member.items():
            decisions = []
            for r in mine:  # in time order, so each special game locks at its own tip
                parsed = rules.parse_picks(r.picks, specials, after=season.week_start(week), tz=season.tz)
                decisions = pool.submit_specials(store, season, member, [(p.game_id, p.team) for p in parsed
                                                                         if p.game_id], r.submitted_at)
                decisions += [p.rejection() for p in parsed if not p.game_id]
            results[member] = decisions
    missing = [m.name for m in season.members if m.name not in by_member]
    return report.ingest_summary_md(season, week, results, missing, late, unknown)


def replace(season: Season, store: Store, week: int, name: str, text: str, now: datetime, source=None,
            override: str = "") -> str:
    """Record DM replacements for a member's dropped picks (grace window, untipped games only). With `override`
    (the organizer's reason), games the week's form could have picked count too, even after tip or grace."""
    member = member_for(season, name)
    if member is None:
        raise ValueError(f"{name!r} isn't on the roster")
    refresh(store, season, source, [week])
    after = season.deadline(week) if override else now
    parsed = rules.parse_picks(text, pool.week_games(store, season, week), after=after, tz=season.tz)
    selections = [(p.game_id, p.team) for p in parsed if p.game_id]
    decisions = pool.submit_override(store, season, member, week, selections, now, override) if override else \
        pool.submit_replacements(store, season, member, week, selections, now)
    decisions += [p.rejection() for p in parsed if not p.game_id]
    games = store.games_by_id()
    lines = [f"{'✅' if d.accepted else '❌'} {report.pick_text(season, games.get(d.game_id), d.team)}"
             + ("" if d.accepted else f": {d.note}") for d in decisions]
    lines.append(f"Open slots left: {pool.open_slots(store, season, member, week)}")
    return "\n".join(lines) + "\n"


def remaining(season: Season, store: Store, week: int) -> str:
    if not season.is_regular(week):
        raise ValueError(f"week {week} has no regular picks")
    teams = {m.name: sorted(set(TEAMS) - pool.used_teams(store, season, m.name, week))
             for m in season.members}
    return report.remaining_md(season, week, teams)


def picks(season: Season, store: Store, week: int, source=None) -> str:
    refresh(store, season, source, [week])
    return report.pick_sheet_md(season, week, store.picks(weeks=[week]), store.games_by_id())


def standings(season: Season, store: Store, now: datetime, source=None) -> str:
    current = season.week_for(now) or season.weeks
    refresh(store, season, source, [max(1, current - 1), current])
    return report.standings_md(season, pool.standings(store, season))


def week_grid(season: Season, store: Store, week: int, now: datetime, source=None, reveal: bool = False):
    import grid

    refresh(store, season, source, [week])
    return grid.build_week_grid(season, week, pool.week_games(store, season, week), store.picks(), now, reveal)


def upcoming_week(season: Season, now: datetime) -> int:
    """The week being picked: from Sunday on, that's the week starting Monday."""
    week = season.week_for(now + timedelta(days=1))
    if week is None:
        raise ValueError("no PEAshooter week coming up")
    return week


def current_week(season: Season, now: datetime) -> int:
    week = season.week_for(now)
    if week is None:
        raise ValueError(f"{now:%b %-d} isn't in the season")
    return week


def google():
    """(forms, sheets) API clients and the Sheet ID."""
    import os

    from google_form import services
    forms, sheets = services()
    return forms, sheets, os.environ["PEASHOOTER_SHEET_ID"]


def sheet_responses(sheets, sheet_id: str, season: Season) -> list:
    from google_sheet import read_form_responses
    return responses_from_rows(*read_form_responses(sheets, sheet_id), season)


def sunday(season: Season, store: Store, week: int, now: datetime, source=None) -> str:
    """Open the form for `week`, set up the cycle's tabs, and return the announcement."""
    from google_form import set_up_week

    order, _ = tab_plan(season, week, [])
    refresh(store, season, source, order)
    forms, sheets, sheet_id = google()
    form = set_up_week(forms, season, store, week, now)
    tab = rebuild_tabs(season, store, sheets, sheet_id, week, now)[week]
    from slack_post import Thread

    games = pool.week_games(store, season, week)
    return Thread(report.announcement_md(season, week, games, form["responderUri"], tab),
                  (report.schedule_md(season, week, games, now.date(), header=False),))


def reminder(season: Season, store: Store, week: int, now: datetime) -> str:
    """Who hasn't submitted yet (a nudge before the deadline)."""
    _, sheets, sheet_id = google()
    responses = responses_for_week(season, sheet_responses(sheets, sheet_id, season), week)
    deadline = season.deadline(week)
    sent = {member_for(season, r.name) for r in responses if r.submitted_at <= deadline}
    waiting = [m.name for m in season.members if m.name not in sent]
    if not waiting:
        return f"🏀 Everyone's picks are in for Week {week}. 🎉\n"
    return (f"⏰ Week {week} picks lock *{deadline:%a} {report.clock(deadline)} ET*. "
            f"Still waiting on: {', '.join(sorted(waiting, key=str.casefold))}\n")


def monday(season: Season, store: Store, week: int, now: datetime, source=None) -> str:
    """At the deadline: close the form, ingest the week's responses, rebuild the tabs, return the summary."""
    from google_form import set_accepting

    forms, sheets, sheet_id = google()
    if season.is_regular(week):  # special weeks stay open: each special game locks at its own tip
        import os
        set_accepting(forms, os.environ["PEASHOOTER_FORM_ID"], False)
    text = ingest(season, store, sheet_responses(sheets, sheet_id, season), week, source)
    tab = rebuild_tabs(season, store, sheets, sheet_id, week, now)[week]
    return text + f"\n📊 <{tab}|Tracker>: everyone's picks, filled in as games finish\n"


def tab_plan(season: Season, week: int, existing: list) -> tuple:
    """(visible weeks, front first; weeks to hide) for the Sheet while `week` is current.

    Visible: every week of the current cycle, plus last week's tab while its results finish. In an off week,
    the surrounding cycle stays visible. Older tabs are hidden, not deleted: they're the record.
    """
    cycle = season.cycle_for(week)
    if cycle is None:  # off week: use the cycle it sits inside
        earlier = [w for w in season.regular_weeks() if w < week]
        cycle = season.cycle_for(earlier[-1] if earlier else season.regular_weeks()[0])
    visible = set(season.weeks_in_cycle(cycle)) | {week}
    if week - 1 in existing:
        visible.add(week - 1)
    order = [week] + sorted(visible - {week})
    return order, sorted(set(existing) - visible)


def rebuild_tabs(season: Season, store: Store, sheets, sheet_id: str, week: int, now: datetime) -> dict:
    """Create or rebuild every tab in the plan, hide the rest, and put `week` in front. Returns {week: link}."""
    import grid
    from google_sheet import arrange_tabs, week_tabs, write_week_tab

    order, hidden = tab_plan(season, week, week_tabs(sheets, sheet_id))
    links = {w: write_week_tab(sheets, sheet_id, grid.build_week_grid(
        season, w, pool.week_games(store, season, w), store.picks(), now)) for w in order}
    arrange_tabs(sheets, sheet_id, order, hidden)
    write_status(season, sheets, sheet_id, week)
    return links


def write_status(season: Season, sheets, sheet_id: str, week: int) -> str:
    """Point the "Who's In" tab at `week`, right after the week's own tab."""
    from google_sheet import write_status_tab

    members = sorted((m.name for m in season.members), key=str.casefold)
    if season.is_regular(week):
        deadline = season.deadline(week)
        subtitle = (f"Picks lock {deadline:%a %b %-d}, {report.clock(deadline)} ET · updates as forms come in · "
                    "picks stay hidden until the lock")
        return write_status_tab(sheets, sheet_id, week, members, deadline.replace(tzinfo=None), subtitle)
    subtitle = f"{season.off_week_label(week)}: each special game locks at its own tip-off"
    return write_status_tab(sheets, sheet_id, week, members, None, subtitle)


def daily(season: Season, store: Store, now: datetime, source=None) -> str:
    """Sync scores and rebuild the grids from last week on (no post)."""
    week = current_week(season, now)
    refresh(store, season, source, [w for w in (week - 1, week) if w >= 1])
    note = highlights.refresh(store, season) if source is not None else ""
    _, sheets, sheet_id = google()
    weeks = rebuild_tabs(season, store, sheets, sheet_id, week, now)
    return "Rebuilt " + ", ".join(f"Week {w}" for w in sorted(weeks)) + "\n" + (note + "\n" if note else "")



def picks_visible(season: Season, game, now: datetime) -> bool:
    """Regular picks show once their week locks; special-game picks once the game tips (as in the grid)."""
    if season.special_for(game.tip):
        return game.tip <= now
    week = season.week_for(game.tip)
    return week is not None and now > season.deadline(week)


def digest(season: Season, store: Store, now: datetime, source=None):
    """Morning post: standings with yesterday's results, then today's games and who picked what (in the thread)."""
    from slack_post import Thread

    week = current_week(season, now)
    today = datetime.combine(now.astimezone(season.tz).date(), time(0), season.tz)
    yesterday = today - timedelta(days=1)
    refresh(store, season, source, sorted({w for w in (season.week_for(yesterday), week) if w}))
    games, picks = store.games_by_id(), store.picks(accepted=True)
    played = {g.id for g in store.games(yesterday, today)}
    todays = store.games(today, today + timedelta(days=1))
    hidden = {g.id for g in todays if not picks_visible(season, g, now)}
    shown, pickers = {g.id for g in todays} - hidden, {}
    for p in sorted(picks, key=lambda p: p.member.casefold()):
        if p.game_id in shown:
            pickers.setdefault(p.game_id, {}).setdefault(p.team, []).append(p.member)
    args = (season, week, now, pool.standings(store, season),
            rules.standings(season, [p for p in picks if p.game_id in played], games), todays, pickers, hidden)
    main, reply = report.digest_md(*args)
    main_blocks, reply_blocks = report.digest_blocks(*args, site_url=os.environ.get("PEASHOOTER_SITE_URL", ""),
                                                     highlights_url=highlights.playlist_url())
    return Thread(main, (reply,) if reply else (), (main_blocks, reply_blocks) if reply else (main_blocks,))


def site(season: Season, store: Store, now: datetime, source=None) -> str:
    """The public scoreboard page (HTML): last week and this week's games, standings, and picks once they lock."""
    import scoreboard

    week = current_week(season, now)
    weeks = [w for w in (week - 1, week) if w >= 1]
    refresh(store, season, source, weeks)
    games = {w: pool.week_games(store, season, w) for w in weeks}
    hidden = {g.id for gs in games.values() for g in gs if not picks_visible(season, g, now)}
    pickers = {}
    for p in store.picks(weeks=weeks, accepted=True):
        if p.game_id not in hidden:
            pickers.setdefault(p.game_id, {}).setdefault(p.team, []).append(p.member)
    return scoreboard.page_html(season, week, now, pool.standings(store, season), games, pickers, hidden)


def schedule_md(season: Season, store: Store, weeks: list, now: datetime, out: Optional[Path] = None,
                source=None) -> str:
    refresh(store, season, source, weeks)
    texts = {w: report.schedule_md(season, w, pool.week_games(store, season, w), now.date()) for w in weeks}
    if out is None:
        return "\n".join(texts.values())
    out.mkdir(parents=True, exist_ok=True)
    for w, text in texts.items():
        (out / f"week{w}.md").write_text(text)
    return "\n".join(str(out / f"week{w}.md") for w in weeks) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-sync", action="store_true", help="don't refresh games from the schedule source")
    parser.add_argument("--post", action="store_true", help="also post the output to Slack")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("schedule-md", help="Slack-ready schedule for one or more weeks")
    p.add_argument("--week", type=int, action="append", required=True)
    p.add_argument("--out", type=Path, help="write weekN.md files here instead of printing")
    p = sub.add_parser("ingest", help="validate and store a week's responses (from the Sheet, or a CSV export)")
    p.add_argument("csv", type=Path, nargs="?", help="CSV export of the responses tab; default: read the Sheet")
    p.add_argument("--week", type=int, required=True)
    p.add_argument("--dry-run", action="store_true", help="check everything but store nothing")
    p = sub.add_parser("replace", help="record a member's DM replacement picks")
    p.add_argument("--week", type=int, required=True)
    p.add_argument("--member", required=True, help="roster name or Slack ID")
    p.add_argument("picks", help='e.g. "Lakers Fri, Heat vs Knicks"')
    p.add_argument("--at", help="when the DM was sent (ISO, local time); default now")
    p.add_argument("--override", metavar="REASON", default="",
                   help="organizer ruling: also allow games that have tipped or a closed grace window (recorded)")
    for name, help_text in (("remaining", "teams each member has left going into a week"),
                            ("picks", "everyone's counted picks and results for a week")):
        sub.add_parser(name, help=help_text).add_argument("--week", type=int, required=True)
    sub.add_parser("standings", help="season leaderboard")
    p = sub.add_parser("grid", help="the week's tracker grid: preview it, or write it to the Sheet")
    p.add_argument("--week", type=int, help="default: the current week")
    for name, help_text in (("sunday", "open the form for the coming week, write its grid, announce it"),
                            ("reminder", "list who hasn't submitted yet"),
                            ("monday", "at the deadline: close the form, ingest, rebuild the grid, summarise")):
        sub.add_parser(name, help=help_text).add_argument("--week", type=int, help="default: the coming week"
                                                          if name != "monday" else "default: the current week")
    sub.add_parser("daily", help="sync scores and rebuild the cycle's tabs (no post)")
    sub.add_parser("digest", help="morning post: standings, yesterday's results, today's games and picks")
    sub.add_parser("site", help="public scoreboard page: games, standings, locked picks (aliases only)").add_argument(
        "--out", type=Path, default=Path("data/site"), help="directory for index.html (default: data/site)")
    sub.add_parser("tabs", help="set up the Sheet's tabs for a week's cycle").add_argument(
        "--week", type=int, help="default: the coming week")
    p.add_argument("--sheet", action="store_true", help="write the 'Week N' tab in the Google Sheet")
    p.add_argument("--reveal", action="store_true", help="show picks before the deadline (preview)")
    args = parser.parse_args(argv)

    load_env_file()
    season, store = load_season(), Store()
    now = datetime.now(timezone.utc).astimezone(season.tz)
    source = None
    if not args.no_sync and args.command not in ("remaining", "reminder"):
        from sources import load_source
        source = load_source()
    try:
        if args.command == "schedule-md":
            text = schedule_md(season, store, args.week, now, args.out, source)
        elif args.command == "ingest":
            if args.csv:
                responses = read_responses(args.csv, season)
            else:
                import os

                from google_form import services
                from google_sheet import read_form_responses
                headers, rows = read_form_responses(services()[1], os.environ["PEASHOOTER_SHEET_ID"])
                responses = responses_from_rows(headers, rows, season)
            if args.dry_run:
                scratch = Store(":memory:")
                refresh(store, season, source, [args.week])
                scratch.upsert_games(store.games())
                for p in store.picks():  # earlier weeks' picks still matter for the cycle rule
                    scratch.add_picks(p.member, p.week, p.kind, p.source, [rules.Decision(
                        p.game_id, p.team, p.accepted, p.code, p.note)], p.submitted_at)
                store, source = scratch, None
            text = ingest(season, store, responses, args.week, source)
            if args.dry_run:
                text += "\n(dry run: nothing was stored)\n"
        elif args.command == "replace":
            at = parse_timestamp(args.at, season.tz) if args.at else now
            text = replace(season, store, args.week, args.member, args.picks, at, source, args.override)
        elif args.command == "remaining":
            text = remaining(season, store, args.week)
        elif args.command == "picks":
            text = picks(season, store, args.week, source)
        elif args.command == "sunday":
            text = sunday(season, store, args.week or upcoming_week(season, now), now, source)
        elif args.command == "reminder":
            text = reminder(season, store, args.week or upcoming_week(season, now), now)
        elif args.command == "monday":
            text = monday(season, store, args.week or current_week(season, now), now, source)
        elif args.command == "daily":
            text = daily(season, store, now, source)
        elif args.command == "digest":
            text = digest(season, store, now, source)
        elif args.command == "site":
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "index.html").write_text(site(season, store, now, source))
            text = f"Wrote {args.out / 'index.html'}\n"
        elif args.command == "tabs":
            week = args.week or upcoming_week(season, now)
            refresh(store, season, source, tab_plan(season, week, [])[0])
            _, sheets, sheet_id = google()
            links = rebuild_tabs(season, store, sheets, sheet_id, week, now)
            text = "\n".join(f"Week {w}: {links[w]}" for w in links) + "\n"
        elif args.command == "grid":
            built = week_grid(season, store, args.week or current_week(season, now), now, source, args.reveal)
            if args.sheet:
                import os

                from google_form import services
                from google_sheet import write_week_tab
                text = write_week_tab(services()[1], os.environ["PEASHOOTER_SHEET_ID"], built) + "\n"
            else:
                import grid
                text = grid.grid_text(built)
        else:
            text = standings(season, store, now, source)
        print(text, end="")
        if args.post:
            from slack_post import post_thread
            post_thread(text)
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
