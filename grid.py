"""The per-week tracker grid: one row per team-in-game, one column per member, every cell's state.

Pure: built from the season, the week's games and stored picks. Renderers (Sheets, text) live elsewhere.
Before the deadline only availability shows; picks appear once they're locked.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import rules
from schedule import FINAL, Game
from season import Season
from teams import TEAMS, team_name

# Cell states
OPEN = "open"            # can pick
LOCKED = "locked"        # game tips before the deadline
USED = "used"            # team already used earlier this cycle
TAKEN = "taken"          # team picked in another game this week
NO_GAME = "no_game"      # team doesn't play this week
PENDING, WIN, LOSS, VOID = "pending", "win", "loss", "void"
DROPPED = "dropped"      # submitted but didn't count

RESULT_TEXT = {PENDING: "⏳", WIN: "✅", LOSS: "❌", VOID: "➖", DROPPED: "✗"}


@dataclass(frozen=True)
class Cell:
    state: str
    text: str = ""
    note: str = ""


@dataclass(frozen=True)
class Row:
    team: str
    game: Optional[Game]
    game_text: str
    cells: tuple


@dataclass
class WeekGrid:
    week: int
    title: str
    subtitle: str
    members: list
    rows: list = field(default_factory=list)
    summary: list = field(default_factory=list)  # [(label, [value per member])]
    revealed: bool = False
    idle: frozenset = frozenset()  # members with no picks stored at all (their columns can be hidden)


def _game_text(season: Season, game: Game, team: str, locked: bool) -> str:
    local = game.tip.astimezone(season.tz)
    where = f"@ {TEAMS[game.home][1]}" if team == game.away else f"vs {TEAMS[game.away][1]}"
    special = season.special_for(game.tip)
    tag = " 🔒" if locked else (f" ⭐{special.points}" if special else "")
    hour = local.strftime("%-I:%M %p").lower().replace(":00", "")
    return f"{local:%a %-m/%-d} {where} · {hour}{tag}"


def _result_cell(season: Season, game: Game, team: str) -> Cell:
    pts = rules.pick_points(season, game, team)
    if pts is None:
        return Cell(PENDING, RESULT_TEXT[PENDING])
    if game.winner is None:
        return Cell(VOID, RESULT_TEXT[VOID], "Postponed or cancelled: no point")
    return Cell(WIN if pts else LOSS, RESULT_TEXT[WIN if pts else LOSS],
                f"{game.away} {game.away_score}, {game.home} {game.home_score}")


def build_week_grid(season: Season, week: int, games: list, picks: list, now: datetime,
                    reveal: bool = False) -> WeekGrid:
    """`picks`: stored picks (any week, any status) for the members; `games`: this week's games.
    `reveal` shows picks before the deadline (for previews; normally they appear once picks lock)."""
    members = sorted((m.name for m in season.members), key=str.casefold)
    start, end = season.week_bounds(week)
    games = sorted((g for g in games if start <= g.tip < end), key=lambda g: g.tip)
    regular = season.is_regular(week)
    deadline = season.deadline(week)
    revealed = reveal or now > deadline if regular else reveal  # special picks show per game, as each tips
    cycle = season.cycle_for(week)
    last_day = end - timedelta(days=1)

    if regular:
        subtitle = (f"{start:%a %b %-d} – {last_day:%a %b %-d} · cycle {cycle} "
                    f"(weeks {', '.join(map(str, season.weeks_in_cycle(cycle)))}) · "
                    f"picks due {deadline:%a %b %-d}, {deadline.strftime('%-I:%M %p').lower().replace(':00', '')} ET")
        if not revealed:
            subtitle += " · picks appear after the deadline"
        elif now <= deadline:
            subtitle += " · PREVIEW: picks shown early"
    else:
        subtitle = f"{season.off_week_label(week)}: special games only · each pick shows once its game tips"
    idle = frozenset(members) - {p.member for p in picks}
    grid = WeekGrid(week, f"Week {week}", subtitle, members, revealed=revealed, idle=idle)

    # Earlier weeks of the cycle grey out teams only once that week's picks are locked (or when revealing)
    earlier = [w for w in season.weeks_in_cycle(cycle) if w < week and (reveal or now > season.deadline(w))] \
        if cycle else []
    used_week = {m: {} for m in members}  # member -> team -> week used earlier this cycle
    this_week = {m: {} for m in members}  # member -> (game_id, team) -> pick
    for p in picks:
        if p.member not in used_week:
            continue
        if p.kind == "regular" and p.accepted and p.week in earlier:
            used_week[p.member].setdefault(p.team, p.week)
        elif p.week == week or (not regular and p.kind == "special"):
            current = this_week[p.member].get((p.game_id, p.team))
            if current is None or (p.accepted and not current.accepted):
                this_week[p.member][(p.game_id, p.team)] = p
    picked_teams = {m: {t for (g, t), p in this_week[m].items() if p.accepted} for m in members}

    if regular:
        by_team = {t: [g for g in games if t in g.teams and not season.special_for(g.tip)] for t in TEAMS}
    else:
        specials = [g for g in games if season.special_for(g.tip)]
        by_team = {t: [g for g in specials if t in g.teams] for t in TEAMS}
        by_team = {t: gs for t, gs in by_team.items() if gs}

    for team in sorted(by_team, key=team_name):
        team_games = by_team[team] or [None]
        for game in team_games:
            locked = bool(game) and regular and game.tip <= deadline
            cells = []
            for m in members:
                show = revealed if regular else bool(game) and (reveal or game.tip <= now)
                pick = this_week[m].get((game.id, team)) if game and show else None
                if pick and pick.accepted:
                    cells.append(_result_cell(season, game, team))
                elif pick:
                    cells.append(Cell(DROPPED, RESULT_TEXT[DROPPED], f"Didn't count: {pick.note}"))
                elif game is None:
                    used = used_week[m].get(team)
                    cells.append(Cell(USED, f"wk {used}", f"Used in week {used}") if used else Cell(NO_GAME))
                elif locked:
                    cells.append(Cell(LOCKED, "", "Tips before the deadline"))
                elif team in used_week[m]:
                    cells.append(Cell(USED, f"wk {used_week[m][team]}", f"Used in week {used_week[m][team]}"))
                elif revealed and team in picked_teams[m]:
                    cells.append(Cell(TAKEN, "", "Picked in another game this week"))
                else:
                    cells.append(Cell(OPEN))
            text = _game_text(season, game, team, locked) if game else "no games this week"
            grid.rows.append(Row(team, game, text, tuple(cells)))

    if regular:
        counted, points, left = [], [], []
        for m in members:
            accepted = [p for p in this_week[m].values() if p.accepted]
            games_by_id = {g.id: g for g in games}
            pts = [rules.pick_points(season, games_by_id.get(p.game_id), p.team) for p in accepted]
            counted.append(f"{len(accepted)}/{season.picks_per_week}" if revealed else "")
            pending = sum(x is None for x in pts)
            points.append((f"{sum(x or 0 for x in pts)}" + (f" (+{pending}⏳)" if pending else "")) if revealed else "")
            spent = set(used_week[m]) | (picked_teams[m] if revealed else set())
            left.append(str(len(TEAMS) - len(spent)))
        grid.summary = [("Picks counted", counted), ("Points this week", points),
                        ("Teams left in cycle", left)]
    return grid


def grid_text(grid: WeekGrid) -> str:
    """Plain-text preview (for the terminal and tests)."""
    symbol = {OPEN: "·", LOCKED: "🔒", NO_GAME: "-", TAKEN: "x"}
    width = max(4, *(len(m) for m in grid.members))
    lines = [f"{grid.title} · {grid.subtitle}",
             f"{'Team':<22} {'Game':<30} " + " ".join(f"{m[:width]:^{width}}" for m in grid.members)]
    previous = None
    for row in grid.rows:
        name = team_name(row.team) if row.team != previous else ""
        previous = row.team
        cells = " ".join(f"{(c.text or symbol.get(c.state, '')):^{width}}" for c in row.cells)
        lines.append(f"{name:<22} {row.game_text:<30} {cells}")
    for label, values in grid.summary:
        lines.append(f"{'':<22} {label:<30} " + " ".join(f"{v:^{width}}" for v in values))
    return "\n".join(lines) + "\n"
