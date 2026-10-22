"""Pool operations over the store: what the admin CLI and cron jobs call. Still no Google or Slack here."""

from datetime import datetime

import rules
from season import Season
from store import Store
from teams import TEAMS

REGULAR, SPECIAL = "regular", "special"


def sync_schedule(store: Store, source, start: datetime, end: datetime) -> int:
    games = source.games(start, end)
    store.upsert_games(games)
    return len(games)


def week_games(store: Store, season: Season, week: int) -> list:
    return store.games(*season.week_bounds(week))


def used_teams(store: Store, season: Season, member: str, week: int, include_current: bool = False) -> set:
    """Teams `member` has spent in `week`'s cycle, from earlier weeks (and this one if include_current)."""
    cycle = season.cycle_for(week)
    if cycle is None:
        return set()
    weeks = [w for w in season.weeks_in_cycle(cycle) if w < week or (include_current and w == week)]
    return {p.team for p in store.picks(member=member, weeks=weeks, kind=REGULAR, accepted=True)}


def remaining_teams(store: Store, season: Season, member: str, week: int) -> list:
    used = used_teams(store, season, member, week, include_current=True)
    return sorted(set(TEAMS) - used)


def form_options(store: Store, season: Season, member: str, week: int) -> list:
    """What goes on a member's weekly form: legal (game, team) pairs as of the deadline."""
    used = used_teams(store, season, member, week)
    return rules.legal_options(season, week, week_games(store, season, week), used, season.deadline(week))


def ingest_form(store: Store, season: Season, member: str, week: int, selections: list,
                submitted_at: datetime, unparsed: tuple = ()) -> list:
    """Validate and store a member's form response, replacing any earlier response for the week.

    `unparsed` holds Decisions for pick lines that couldn't be matched to a game; they're stored as
    rejections, so the member can replace them by DM.
    """
    if not season.is_regular(week):
        raise ValueError(f"week {week} has no regular picks")
    if submitted_at > season.deadline(week):
        decisions = [rules.Decision(g, t, False, rules.LATE, "submitted after the deadline") for g, t in selections]
    else:
        decisions = rules.validate_regular(season, week, store.games_by_id(), selections,
                                           used_teams(store, season, member, week),
                                           cutoff=season.deadline(week), slots=season.picks_per_week)
    decisions = list(unparsed) + decisions
    store.replace_picks(member, week, REGULAR, "form", decisions, submitted_at)
    return decisions


def open_slots(store: Store, season: Season, member: str, week: int) -> int:
    """How many dropped form picks the member can still replace by DM."""
    picks = store.picks(member=member, weeks=[week], kind=REGULAR)
    refillable = sum(1 for p in picks if p.source == "form" and not p.accepted and p.code not in rules.NOT_REFILLABLE)
    replaced = sum(1 for p in picks if p.source == "dm" and p.accepted)
    accepted = sum(1 for p in picks if p.accepted)
    return max(0, min(refillable - replaced, season.picks_per_week - accepted))


def submit_replacements(store: Store, season: Season, member: str, week: int, selections: list,
                        now: datetime) -> list:
    """DM replacements for rejected picks: only within the grace window, only for games not yet tipped."""
    if now > season.grace_end(week):
        decisions = [rules.Decision(g, t, False, rules.LATE, "the grace window has closed") for g, t in selections]
    else:
        decisions = rules.validate_regular(season, week, store.games_by_id(), selections,
                                           used_teams(store, season, member, week, include_current=True),
                                           cutoff=now, slots=open_slots(store, season, member, week))
    store.add_picks(member, week, REGULAR, "dm", decisions, now)
    return decisions


def submit_specials(store: Store, season: Season, member: str, selections: list, now: datetime) -> list:
    """Special-game picks; a new pick for a game replaces the old one until that game tips."""
    games = store.games_by_id()
    decisions = rules.validate_special(season, games, selections, now)
    ok = [d for d in decisions if d.accepted]
    store.delete_picks(member, SPECIAL, [d.game_id for d in ok])
    for d in decisions:
        week = season.week_for(games[d.game_id].tip) if d.game_id in games else 0
        store.add_picks(member, week or 0, SPECIAL, "form", [d], now)
    return decisions


def standings(store: Store, season: Season) -> list:
    return rules.standings(season, store.picks(accepted=True), store.games_by_id())


def cycle_grid(store: Store, season: Season, cycle: int) -> dict:
    """{member: {team: week}} for the Sheet's cycle grid."""
    grid = {m.name: {} for m in season.members}
    for p in store.picks(weeks=season.weeks_in_cycle(cycle), kind=REGULAR, accepted=True):
        grid.setdefault(p.member, {})[p.team] = p.week
    return grid
