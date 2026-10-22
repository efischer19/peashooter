"""The public scoreboard page: the week's games and scores, standings, and picks once they lock. Pure formatting; no I/O.

The page is meant to be public, so members appear only by their `alias` from season.toml, never their roster
name, and nothing links to the forms or the Sheet.
"""

from datetime import date, datetime, timedelta
from html import escape
from itertools import groupby

from report import LOSS, PENDING, VOID, WIN, clock, event_tag, nba_url, nickname, pick_result, watch_links
from schedule import CANCELLED, FINAL, IN_PROGRESS, NATIONAL, POSTPONED
from season import Season

# Primary team colours, for the tricode badges.
COLORS = {
    "ATL": "#C8102E", "BOS": "#007A33", "BKN": "#000000", "CHA": "#1D1160", "CHI": "#CE1141",
    "CLE": "#860038", "DAL": "#00538C", "DEN": "#0E2240", "DET": "#C8102E", "GSW": "#1D428A",
    "HOU": "#CE1141", "IND": "#002D62", "LAC": "#C8102E", "LAL": "#552583", "MEM": "#5D76A9",
    "MIA": "#98002E", "MIL": "#00471B", "MIN": "#0C2340", "NOP": "#0C2340", "NYK": "#006BB6",
    "OKC": "#007AC1", "ORL": "#0077C0", "PHI": "#006BB6", "PHX": "#1D1160", "POR": "#E03A3E",
    "SAC": "#5A2D81", "SAS": "#000000", "TOR": "#CE1141", "UTA": "#002B5C", "WAS": "#002B5C",
}
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

CSS = """
:root{--bg:#f5f4f0;--card:#fff;--ink:#1d1d1f;--muted:#6e6e73;--line:#e2e0da;--accent:#c2410c;--win:#1f7a45;--loss:#b3261e;--gold:#a16207;--pick-bg:#fef3c7;--pick-line:#eab308;--pick-ink:#713f12}
@media (prefers-color-scheme:dark){:root{--bg:#111113;--card:#1b1b1e;--ink:#ececef;--muted:#9b9ba1;--line:#2d2d31;--accent:#fb923c;--win:#5ac98a;--loss:#ff8a80;--gold:#facc15;--pick-bg:#3a2f0b;--pick-line:#ca8a04;--pick-ink:#fde68a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:720px;margin:0 auto;padding:28px 16px 56px}
h1{font-size:1.7rem;margin:0;letter-spacing:-.01em}
h1 span{color:var(--accent)}
.sub{color:var(--muted);margin-top:2px}
section{margin-top:32px}
h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:0 0 10px}
table{width:100%;border-collapse:separate;border-spacing:0;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{padding:8px 12px;white-space:nowrap;text-align:right;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:0}
th{font-size:.75rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
th.name,td.name{text-align:left;width:100%}
td.rank{text-align:center;width:2.5em}
td.pts{font-weight:700}
.day{margin-top:10px}
.day>summary{display:flex;align-items:baseline;gap:8px;padding:8px 0;font-weight:600;cursor:pointer;list-style:none}
.day>summary::-webkit-details-marker{display:none}
.day>summary::before{content:"▸";color:var(--muted);width:1em;transition:transform .15s}
.day[open]>summary::before{transform:rotate(90deg)}
.day .count{margin-left:auto;color:var(--muted);font-weight:400;font-size:.85rem}
.day .games{margin-bottom:8px}
.day .today{font-size:.72rem;font-weight:700;color:var(--card);background:var(--accent);border-radius:999px;padding:1px 8px}
.games{display:grid;gap:8px;align-items:start}
@media (min-width:640px){.games{grid-template-columns:1fr 1fr}}
.game{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px}
.row{display:flex;align-items:center;gap:14px}
.status{width:62px;flex:none;color:var(--muted);font-size:.82rem;font-variant-numeric:tabular-nums}
.status.live{color:var(--loss);font-weight:700}
.teams{flex:1;display:grid;gap:5px;min-width:0}
.side{display:flex;align-items:center;gap:9px}
.side .nick{min-width:0}
.status{display:flex;flex-direction:column;align-items:flex-start;gap:2px}
.watch,.tv>summary{display:grid;place-items:center;width:28px;height:28px;margin-left:-4px;border-radius:6px;color:var(--muted);cursor:pointer;list-style:none}
.tv>summary::-webkit-details-marker{display:none}
.watch:hover,.watch:focus-visible,.tv>summary:hover,.tv>summary:focus-visible,.tv[open]>summary{color:var(--accent);background:var(--bg)}
.tv{position:relative}
.tv .menu{position:absolute;z-index:5;top:30px;left:-4px;min-width:200px;background:var(--card);border:1px solid var(--line);border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.14);padding:6px;font-size:.86rem;color:var(--ink)}
.tv .menu a,.tv .menu span{display:block;padding:5px 8px;border-radius:6px;white-space:nowrap}
.tv .menu a{color:var(--ink);text-decoration:none}
.tv .menu a:hover,.tv .menu a:focus-visible{background:var(--bg);color:var(--accent)}
.tv .menu span{color:var(--muted)}
.tv .menu small{display:block;padding:4px 8px 2px;color:var(--muted);font-size:.72rem;border-top:1px solid var(--line);margin-top:4px}
.side .score{margin-left:auto;font-variant-numeric:tabular-nums;font-weight:600}
.side.lost{color:var(--muted)}
.side.won .nick{font-weight:600}
.tm{flex:none;width:3.1em;text-align:center;font-size:.7rem;font-weight:700;letter-spacing:.04em;color:#fff;background:var(--c);border-radius:5px;padding:2px 0;box-shadow:inset 0 0 0 1px rgba(255,255,255,.18)}
.tag{font-size:.75rem;color:var(--muted);margin-top:6px}
.tag.special{color:var(--gold);font-weight:600}
.nowrap{white-space:nowrap}
.side .who{display:inline-block;font-weight:700;font-size:.78rem;line-height:1.3;color:var(--pick-ink);background:var(--pick-bg);border:1px solid var(--pick-line);border-radius:5px;padding:0 6px;margin-left:5px}
.note{color:var(--muted);font-size:.86rem;font-style:italic;margin:6px 0 0}
details.week{margin-top:32px}
.week>summary{cursor:pointer;font-size:.8rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);font-weight:600}
footer{margin-top:40px;color:var(--muted);font-size:.8rem;border-top:1px solid var(--line);padding-top:14px}
"""


def aliases(season: Season) -> dict:
    """{member name: public name}. A member without an alias is "Shooter N" (roster order), never their name."""
    return {m.name: m.alias or f"Shooter {i}" for i, m in enumerate(season.members, 1)}


def badge(code: str) -> str:
    return f'<span class="tm" style="--c:{COLORS.get(code, "#555")}">{escape(code)}</span>'


def status_html(season: Season, g) -> str:
    """The left column: tip time or state, with the watch link under it."""
    cls, label = "status", clock(g.tip.astimezone(season.tz))
    if g.status == FINAL:
        label = "Final"
    elif g.status == IN_PROGRESS:
        cls, label = "status live", "Live"
    elif g.status in (POSTPONED, CANCELLED):
        label = g.status.capitalize()
    return f'<div class="{cls}"><span>{label}</span>{watch_html(g)}</div>'


def side_html(season: Season, g, code: str, score, picked: dict, names: dict) -> str:
    """One team's line: badge, nickname, then who picked it (bold) with the result mark, then the score."""
    cls = "side" + ((" won" if code == g.winner else " lost") if g.winner else "")
    shown = f'<span class="score">{score}</span>' if score is not None and g.status in (FINAL, IN_PROGRESS) else ""
    who = ""
    if code in picked:
        mark = pick_result(season, g, code)
        who = sorted((names.get(m, "Shooter ?") for m in picked[code]), key=str.casefold)
        chips = [f'<b class="who">{escape(w)}</b>' for w in who]
        if mark != PENDING:  # keep the mark on the same line as the last chip
            chips[-1] = f'<span class="nowrap">{chips[-1]} {mark}</span>'
        who = "".join(chips)
    return (f'<div class="{cls}">{badge(code)}<span class="nick">{escape(nickname(code))}{who}</span>'
            f'{shown}</div>')


TV_ICON = ('<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" '
           'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.5" y="7" width="19" '
           'height="13" rx="2"/><path d="M8 2.5 12 7l4-4.5"/></svg>')


PLAY_ICON = ('<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" '
             'stroke-linejoin="round" aria-hidden="true"><rect x="2.5" y="5" width="19" height="14" rx="3"/>'
             '<path d="M10 9.2v5.6l4.8-2.8z" fill="currentColor"/></svg>')


def feed_html(name: str, link: str) -> str:
    """A menu line: a link when the feed has one, plain text when it doesn't."""
    if link:
        return f'<a href="{escape(link)}" target="_blank" rel="noopener">{escape(name)} ↗</a>'
    return f'<span>{escape(name)}</span>'


def watch_html(g) -> str:
    """Under the game time: full-game highlights once a final game has them; before that, a TV menu with
    NBA.com (League Pass) and every national and local feed; a plain NBA.com link when there are no feeds."""
    links = watch_links(g, nba_label="NBA.com · League Pass")
    if not links:
        return ""
    matchup = f"{escape(g.away)} @ {escape(g.home)}"
    if g.status == FINAL and g.highlights:
        return (f'<a class="watch" href="{escape(g.highlights)}" target="_blank" rel="noopener" '
                f'title="Full-game highlights" aria-label="Full-game highlights, {matchup}">{PLAY_ICON}</a>')
    if len(links) == 1:
        return (f'<a class="watch" href="{nba_url(g)}" target="_blank" rel="noopener" title="Watch on NBA.com" '
                f'aria-label="Watch {matchup} on NBA.com">{TV_ICON}</a>')
    local = any(b.scope != NATIONAL for b in g.broadcasts)
    note = "<small>Team feeds are in-market only</small>" if local else ""
    return (f'<details class="tv"><summary title="Where to watch" aria-label="Where to watch {matchup}">{TV_ICON}'
            f'</summary><div class="menu">{"".join(feed_html(*x) for x in links)}{note}</div></details>')


def game_html(season: Season, g, pickers: dict, hidden: set, names: dict) -> str:
    tags = []
    special = season.special_for(g.tip)
    if special:
        tags.append(f'<div class="tag special">⭐ {escape(special.name)} · {special.points} pts a pick</div>')
    elif event_tag(g).strip():
        tags.append(f'<div class="tag">{escape(g.event)}</div>')
    picked = {} if g.id in hidden else pickers.get(g.id, {})
    return (f'<div class="game"><div class="row">{status_html(season, g)}<div class="teams">'
            f'{side_html(season, g, g.away, g.away_score, picked, names)}'
            f'{side_html(season, g, g.home, g.home_score, picked, names)}</div></div>{"".join(tags)}</div>')


def open_days(today: date) -> tuple:
    """Days whose game lists start expanded: yesterday and today."""
    return today - timedelta(days=1), today


def week_html(season: Season, week: int, games: list, pickers: dict, hidden: set, names: dict, today: date) -> str:
    out = []
    if any(g.id in hidden and not season.special_for(g.tip) for g in games):
        out.append(f'<p class="note">Week {week} picks lock {season.deadline(week):%a %b %-d} at '
                   f'{clock(season.deadline(week))} ET and show here after that.</p>')
    if any(g.id in hidden and season.special_for(g.tip) for g in games):
        out.append('<p class="note">Bonus-game picks show once the game tips.</p>')
    local_day = lambda g: g.tip.astimezone(season.tz).date()
    for day, day_games in groupby(sorted(games, key=lambda g: g.tip), key=local_day):
        day_games = list(day_games)
        flag = ' <span class="today">Today</span>' if day == today else ""
        count = f'<span class="count">{len(day_games)} game{"s" if len(day_games) != 1 else ""}</span>'
        out.append(f'<details class="day"{" open" if day in open_days(today) else ""}>'
                   f'<summary>{day:%A, %b %-d}{flag}{count}</summary><div class="games">'
                   + "".join(game_html(season, g, pickers, hidden, names) for g in day_games) + "</div></details>")
    return "\n".join(out) if games else '<p class="note">No games this week.</p>'


def standings_html(season: Season, week: int, rows: list, names: dict) -> str:
    if not any(r["wins"] + r["losses"] for r in rows):
        return '<p class="note">No results yet.</p>'
    body = []
    for r in (r for r in rows if r["wins"] + r["losses"] + r["pending"]):  # members who've never picked sit it out
        body.append(f'<tr><td class="rank">{MEDALS.get(r["rank"], r["rank"])}</td>'
                    f'<td class="name">{escape(names.get(r["member"], "Shooter ?"))}</td>'
                    f'<td class="pts">{r["points"]}</td><td>{r["wins"]}–{r["losses"]}</td>'
                    f'<td>{r["by_week"].get(week, 0)}</td></tr>')
    return ('<table><thead><tr><th></th><th class="name">Shooter</th><th>Pts</th><th>W–L</th>'
            f'<th>Wk {week}</th></tr></thead><tbody>{"".join(body)}</tbody></table>')


def page_html(season: Season, week: int, now: datetime, rows: list, games: dict, pickers: dict, hidden: set) -> str:
    """The whole page. `games` is {week: [Game]} with the current week last; `pickers` is {game_id: {team: [member]}}
    for games whose picks are visible; `hidden` holds the ids of games whose picks aren't locked yet."""
    names, today = aliases(season), now.astimezone(season.tz).date()
    off = season.off_week_label(week)
    cycle = season.cycle_for(week)
    sub = f"Week {week}" + (f" · {off}" if off else f" · Cycle {cycle}" if cycle else "")
    earlier = [w for w in games if w != week]
    local = lambda g: g.tip.astimezone(season.tz).date()
    past = "".join(f'<details class="week"{" open" if any(local(g) in open_days(today) for g in games[w]) else ""}>'
                   f'<summary>Week {w}</summary>'
                   f'{week_html(season, w, games[w], pickers, hidden, names, today)}</details>' for w in earlier)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E🏀%3C/text%3E%3C/svg%3E">
<title>{escape(season.name)}</title>
<style>{CSS}</style>
</head>
<body>
<main>
<header>
<h1>🏀 <span>PEA</span>shooter</h1>
<div class="sub">{escape(season.name)} · {sub}</div>
</header>
<section>
<h2>Standings</h2>
{standings_html(season, week, rows, names)}
</section>
<section>
<h2>This week</h2>
{week_html(season, week, games.get(week, []), pickers, hidden, names, today)}
</section>
{past}
<footer>
Pick 'Em All, Shooter: straight-up NBA picks, {season.picks_per_week} a week, no team twice in a
{season.cycle_weeks}-week cycle. {WIN} win · {LOSS} loss · {VOID} void. Times ET.<br>
Updated {now.astimezone(season.tz):%a %b %-d}, {clock(now.astimezone(season.tz))} ET.
</footer>
</main>
<script>
document.addEventListener("click", e => document.querySelectorAll("details.tv[open]").forEach(d => {{
  if (!d.contains(e.target)) d.open = false;
}}));
</script>
</body>
</html>
"""
