"""Pick validation and scoring. Pure functions: no storage, no network."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from schedule import CANCELLED, FINAL, POSTPONED, SCHEDULED, Game
from season import WEEKDAYS, Season
from teams import find_teams

# Rejection codes. A "refillable" rejection opens a slot the member can fill by DM during the grace window.
UNKNOWN_GAME, WRONG_TEAM, NOT_THIS_WEEK, SPECIAL_GAME = "unknown_game", "wrong_team", "not_this_week", "special_game"
TIPPED, USED_THIS_CYCLE, DUPLICATE, OVER_LIMIT, LATE = "tipped", "used_this_cycle", "duplicate", "over_limit", "late"
UNPARSED = "unparsed"  # a pick line that didn't match exactly one game
NOT_REFILLABLE = {OVER_LIMIT, LATE}


@dataclass(frozen=True)
class Decision:
    game_id: str
    team: str
    accepted: bool
    code: str = ""
    note: str = ""


def legal_options(season: Season, week: int, games: list, used: set, cutoff: datetime) -> list:
    """(game, team) pairs a member may still pick this week: regular games tipping after `cutoff`, teams not used this cycle."""
    start, end = season.week_bounds(week)
    return [
        (g, team)
        for g in sorted(games, key=lambda g: g.tip)
        if start <= g.tip < end and g.tip > cutoff and g.status == SCHEDULED and not season.special_for(g.tip)
        for team in g.teams
        if team not in used
    ]


def validate_regular(season: Season, week: int, games_by_id: dict, selections: list, used: set,
                     cutoff: datetime, slots: int) -> list:
    """Check (game_id, team) picks in tip order; the earliest game wins a duplicate. `used` = teams already spent this cycle."""
    start, end = season.week_bounds(week)
    tip = lambda sel: games_by_id[sel[0]].tip if sel[0] in games_by_id else end
    taken, out = set(), []
    for game_id, team in sorted(selections, key=tip):
        g = games_by_id.get(game_id)
        if g is None:
            code, note = UNKNOWN_GAME, "that game isn't on the schedule"
        elif team not in g.teams:
            code, note = WRONG_TEAM, f"{team} isn't playing in {g.away} @ {g.home}"
        elif not start <= g.tip < end:
            code, note = NOT_THIS_WEEK, "that game isn't in this pick week"
        elif season.special_for(g.tip):
            code, note = SPECIAL_GAME, "special games are picked separately"
        elif g.tip <= cutoff:
            code, note = TIPPED, f"{g.label(season.tz)} had already tipped"
        elif team in used:
            code, note = USED_THIS_CYCLE, f"{team} was already used this cycle"
        elif team in taken:
            code, note = DUPLICATE, f"{team} is already picked this week"
        elif len(taken) >= slots:
            code, note = OVER_LIMIT, "over the weekly pick limit"
        else:
            taken.add(team)
            out.append(Decision(game_id, team, True))
            continue
        out.append(Decision(game_id, team, False, code, note))
    return out


def validate_special(season: Season, games_by_id: dict, selections: list, now: datetime) -> list:
    """Special-game picks: one winner per special game, locked at that game's tip."""
    seen, out = set(), []
    for game_id, team in selections:
        g = games_by_id.get(game_id)
        if g is None or not season.special_for(g.tip):
            out.append(Decision(game_id, team, False, UNKNOWN_GAME, "that isn't a special game"))
        elif team not in g.teams:
            out.append(Decision(game_id, team, False, WRONG_TEAM, f"{team} isn't playing in {g.away} @ {g.home}"))
        elif g.tip <= now:
            out.append(Decision(game_id, team, False, TIPPED, f"{g.label(season.tz)} had already tipped"))
        elif game_id in seen:
            out.append(Decision(game_id, team, False, DUPLICATE, "only one pick per game"))
        else:
            seen.add(game_id)
            out.append(Decision(game_id, team, True))
    return out


def pick_points(season: Season, game: Optional[Game], team: str) -> Optional[int]:
    """Points for a pick: None while pending. Postponed or cancelled games are void (0), and the team still counts as used."""
    if game is None or game.status in (POSTPONED, CANCELLED):
        return 0
    if game.status != FINAL:
        return None
    special = season.special_for(game.tip)
    return (special.points if special else season.points_per_win) if game.winner == team else 0


def standings(season: Season, picks: list, games_by_id: dict) -> list:
    """Leaderboard rows from accepted picks (objects with .member, .week, .game_id, .team).

    Ties break on best single week; still-tied members share a rank.
    """
    rows = {m.name: {"member": m.name, "name": m.name, "points": 0, "wins": 0, "losses": 0, "pending": 0,
                         "by_week": {}} for m in season.members}
    for p in picks:
        row = rows.setdefault(p.member, {"member": p.member, "name": p.member, "points": 0, "wins": 0, "losses": 0,
                                         "pending": 0, "by_week": {}})
        pts = pick_points(season, games_by_id.get(p.game_id), p.team)
        if pts is None:
            row["pending"] += 1
            continue
        row["points"] += pts
        row["wins" if pts else "losses"] += 1
        row["by_week"][p.week] = row["by_week"].get(p.week, 0) + pts
    for row in rows.values():
        row["best_week"] = max(row["by_week"].values(), default=0)
    ordered = sorted(rows.values(), key=lambda r: (-r["points"], -r["best_week"], r["name"].lower()))
    for i, row in enumerate(ordered):
        prev = ordered[i - 1] if i else None
        tied = prev and (prev["points"], prev["best_week"]) == (row["points"], row["best_week"])
        row["rank"] = prev["rank"] if tied else i + 1
    return ordered


def _weekday(word: str) -> Optional[int]:
    """'wed', 'thurs', 'Saturday' -> 0-6; needs at least 3 letters of the day name."""
    return next((i for i, day in enumerate(WEEKDAYS) if len(word) >= 3 and day.startswith(word)), None)


@dataclass(frozen=True)
class ParsedPick:
    text: str
    team: Optional[str] = None
    game_id: Optional[str] = None
    error: str = ""

    def rejection(self) -> Decision:
        return Decision("", self.team or "", False, UNPARSED, f'"{self.text}": {self.error}')


def parse_picks(text: str, games: list, after: datetime, tz) -> list:
    """Turn DM text like "BOS, Lakers over Nuggets, Heat Fri" into (team, game) picks.

    One pick per line; on a single line, commas or semicolons separate picks. The first team named is the
    pick, unless a team is named twice ("ORL @ NYK - Knicks" is the Knicks); another team or a weekday narrows
    which game ("celtics, BOS @ DET" is the Celtics at Detroit).
    Only games tipping after `after` are considered.
    """
    out = []
    lines = [line for line in text.splitlines() if line.strip()]
    chunks = lines if len(lines) > 1 else re.split(r"[,;]+", text)
    for chunk in (c.strip() for c in chunks):
        if not chunk:
            continue
        named = find_teams(chunk)
        if not named:
            out.append(ParsedPick(chunk, error="couldn't find a team in that"))
            continue
        # a team named twice is the pick ("Magic @ Knicks - Knicks"); otherwise the first one named
        team = next((t for t in named if named.count(t) > 1), named[0])
        opponent = next((t for t in named if t != team), None)
        day = next((d for d in map(_weekday, re.findall(r"[a-z]+", chunk.lower())) if d is not None), None)
        candidates = [g for g in sorted(games, key=lambda g: g.tip)
                      if team in g.teams and g.tip > after and g.status == SCHEDULED
                      and (opponent is None or opponent in g.teams)
                      and (day is None or g.tip.astimezone(tz).weekday() == day)]
        if len(candidates) == 1:
            out.append(ParsedPick(chunk, team, candidates[0].id))
        elif not candidates:
            out.append(ParsedPick(chunk, team, error=f"no upcoming {team} game matches that"))
        else:
            options = ", ".join(g.label(tz) for g in candidates)
            out.append(ParsedPick(chunk, team, error=f"{team} has {len(candidates)} games left ({options}); say which"))
    return out
