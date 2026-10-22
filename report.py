"""Slack-ready text: schedules, pick sheets, ingest summaries, standings. Pure formatting; no I/O."""

from datetime import date, datetime, timedelta
from itertools import groupby

import rules
from schedule import AWAY, FINAL, HOME, NATIONAL, Game
from season import Season
from teams import TEAMS

WIN, LOSS, PENDING, VOID = "✅", "❌", "⏳", "➖"


def nickname(code: str) -> str:
    return TEAMS[code][1] if code in TEAMS else code or "?"


def clock(dt: datetime) -> str:
    """7 pm, 7:30 pm"""
    return dt.strftime("%-I:%M %p").lower().replace(":00", "")


def event_tag(game: Game) -> str:
    if "Cup" in game.event:
        return " 🏆"
    if "Mexico" in game.event or "Global" in game.event or "London" in game.event or "Paris" in game.event:
        return f" ({game.event.replace('NBA ', '').replace(' Game', '')})"
    return ""


def nba_url(game: Game) -> str:
    return f"https://www.nba.com/game/{game.away.lower()}-vs-{game.home.lower()}-{game.id}"


def watch_links(game: Game, team: str = "", nba_label: str = "NBA.com") -> list:
    """[(label, link or "")] for where to watch, shared by the page and the Sheet. Before and during the game:
    NBA.com (League Pass), national feeds, then local feeds (only `team`'s, unprefixed, when given; otherwise
    both teams', prefixed with the nickname). Once final: the highlights video if matched, else NBA.com.
    Empty for games without a real NBA game id."""
    if not game.id.isdigit():
        return []
    if game.status == FINAL:
        return [("▶ Highlights", game.highlights)] if game.highlights else [(nba_label, nba_url(game))]
    links = [(nba_label, nba_url(game))] + [(b.name, b.link) for b in game.broadcasts if b.scope == NATIONAL]
    for scope, side in ((AWAY, game.away), (HOME, game.home)):
        if not team or team == side:
            links += [(b.name if team else f"{nickname(side)}: {b.name}", b.link)
                      for b in game.broadcasts if b.scope == scope]
    return links


def national_tv(game: Game) -> str:
    """' · ESPN' for nationally televised games (where League Pass is blacked out in the US), else ''."""
    names = [b.name for b in game.broadcasts if b.scope == NATIONAL]
    return " · 📺 " + ", ".join(names) if names else ""


def schedule_md(season: Season, week: int, games: list, as_of: date, header: bool = True) -> str:
    """One game per line, grouped by day, flagging games that tip before the deadline."""
    start, end = season.week_bounds(week)
    deadline = season.deadline(week)
    games = sorted((g for g in games if start <= g.tip < end), key=lambda g: g.tip)
    off = season.off_week_label(week)
    lines = [f"🏀 *PEAshooter Week {week}* · {start:%a %b %-d} – {end - timedelta(days=1):%a %b %-d}"]
    if off:
        lines.append(f"_{off}: no regular picks this week._")
    else:
        lines.append(f"Picks due *{deadline:%a %b %-d}, {clock(deadline)} ET* · {season.picks_per_week} picks · "
                     f"times ET · {len(games)} games")
    lines.append("")
    if not header:
        lines = []
    locked = cup = False
    for day, day_games in groupby(games, key=lambda g: g.tip.astimezone(season.tz).date()):
        lines.append(f"*{day:%a %b %-d}*")
        for g in day_games:
            special = season.special_for(g.tip)
            tags = event_tag(g)
            cup = cup or "🏆" in tags
            if special:
                tags += f" ⭐ {special.name}, {special.points} pts"
            elif not off and g.tip <= deadline:
                tags += " 🔒"
                locked = True
            lines.append(f"• {clock(g.tip.astimezone(season.tz))} · {nickname(g.away)} @ {nickname(g.home)}{tags}")
        lines.append("")
    legend = (["🔒 tips at/before the deadline, so it can't be picked"] if locked else []) + \
             (["🏆 NBA Cup game (counts like any other game)"] if cup else []) + \
             [f"schedule as of {as_of:%b %-d}; times can shift"]
    lines.append("_" + " · ".join(legend) + "_")
    return "\n".join(lines) + "\n"


def announcement_md(season: Season, week: int, games: list, form_url: str, tracker_url: str) -> str:
    """The Sunday post's main message: heading, deadline and links (the schedule goes in its thread)."""
    start, end = season.week_bounds(week)
    deadline = season.deadline(week)
    in_week = [g for g in games if start <= g.tip < end]
    lines = [f"🏀 *PEAshooter Week {week}* · {start:%a %b %-d} – {end - timedelta(days=1):%a %b %-d}"]
    off = season.off_week_label(week)
    if off:
        specials = [g for g in in_week if season.special_for(g.tip)]
        lines.append(f"_{off}: no regular picks._ Pick the winner of all {len(specials)} special games; "
                     "each locks at its own tip-off.")
    else:
        lines.append(f"Picks due *{deadline:%a %b %-d}, {clock(deadline)} ET* · {season.picks_per_week} picks · "
                     f"{len(in_week)} games")
    lines += ["", f"👉 <{form_url}|*Make your picks*> · 📊 <{tracker_url}|Tracker>: what you can still pick",
              "🧵 Full schedule in the thread"]
    return "\n".join(lines) + "\n"


def pick_result(season: Season, game, team: str) -> str:
    pts = rules.pick_points(season, game, team)
    if pts is None:
        return PENDING
    if game is None or game.winner is None:
        return VOID
    return WIN if pts else LOSS


def pick_text(season: Season, game, team: str) -> str:
    if game is None:
        return nickname(team)
    opponent = game.home if team == game.away else game.away
    where = "@" if team == game.away else "vs"
    return f"{nickname(team)} ({game.tip.astimezone(season.tz):%a} {where} {opponent})"


def ingest_summary_md(season: Season, week: int, results: dict, missing: list, late: dict,
                      unknown_names: list) -> str:
    """After the deadline: who's in, whose picks were dropped and why, and how to fix them."""
    names = {m.name: m.name for m in season.members}
    total = len(season.members)
    sections = [f"🏀 *PEAshooter Week {week}: picks are in* ({len(results)}/{total})"]
    clean, problems, extras = [], [], []
    for member, decisions in sorted(results.items(), key=lambda kv: names.get(kv[0], kv[0]).lower()):
        ok = sum(d.accepted for d in decisions)
        ignored = [d for d in decisions if d.code == rules.OVER_LIMIT]
        bad = [d for d in decisions if not d.accepted and d.code != rules.OVER_LIMIT]
        if ignored:
            extras.append(f"{names.get(member, member)} ({', '.join(nickname(d.team) for d in ignored)})")
        if not bad and ok == season.picks_per_week:
            clean.append(names.get(member, member))
            continue
        problems.append(f"• *{names.get(member, member)}*: {ok}/{season.picks_per_week} picks count")
        problems += [f"    ◦ {d.note}" for d in bad]
    if clean:
        sections.append(f"✅ All {season.picks_per_week} good: {', '.join(clean)}")
    if extras:
        sections.append(f"ℹ️ More than {season.picks_per_week} picks: the {season.picks_per_week} earliest games "
                        f"count. Ignored: {'; '.join(extras)}")
    if problems:
        grace = season.grace_end(week)
        sections.append("\n".join([f"⚠️ *Needs fixing* (DM replacements by {grace:%a} {clock(grace)} ET, "
                                    "games that haven't started only):"] + problems))
    # members who sent nothing aren't named: sitting a week out is fine, no calling out
    if late:
        sections.append(f"⏰ Came in after the deadline (not counted): {', '.join(names.get(m, m) for m in late)}")
    if unknown_names:
        sections.append(f"❓ Responses from names not on the roster: {', '.join(unknown_names)}")
    return "\n\n".join(sections) + "\n"


def pick_sheet_md(season: Season, week: int, picks: list, games_by_id: dict) -> str:
    """Everyone's counted picks for the week with results, plus points."""
    by_member = {}
    for p in picks:
        if p.week == week and p.accepted:
            by_member.setdefault(p.member, []).append(p)
    lines = [f"🏀 *PEAshooter Week {week}: pick sheet*", ""]
    for m in season.members:
        mine = sorted(by_member.get(m.name, []),
                      key=lambda p: games_by_id[p.game_id].tip if p.game_id in games_by_id else datetime.max)
        if not mine:
            lines.append(f"*{m.name}*: no picks")
            continue
        pts = sum(rules.pick_points(season, games_by_id.get(p.game_id), p.team) or 0 for p in mine)
        lines.append(f"*{m.name}* ({pts} pts)")
        lines += [f"  {pick_result(season, games_by_id.get(p.game_id), p.team)} "
                  f"{pick_text(season, games_by_id.get(p.game_id), p.team)}" for p in mine]
    lines += ["", f"_{WIN} win · {LOSS} loss · {PENDING} not played yet · {VOID} postponed (no point)_"]
    return "\n".join(lines) + "\n"


def remaining_md(season: Season, week: int, remaining: dict) -> str:
    """Teams each member can still pick in `week`'s cycle (before that week's picks)."""
    names = {m.name: m.name for m in season.members}
    cycle = season.cycle_for(week)
    weeks = season.weeks_in_cycle(cycle)
    lines = [f"🏀 *Teams left going into Week {week}* (cycle {cycle}: weeks {', '.join(map(str, weeks))})", ""]
    for member, teams in remaining.items():
        lines.append(f"*{names.get(member, member)}* ({len(teams)}): {', '.join(teams)}")
    return "\n".join(lines) + "\n"


def standing_line(r: dict) -> str:
    place = {1: "🥇", 2: "🥈", 3: "🥉"}.get(r["rank"], f"{r['rank']}.")
    return f"{place} *{r['name']}*: {r['points']} pts ({r['wins']}–{r['losses']})"


def standings_md(season: Season, rows: list) -> str:
    lines = ["🏀 *PEAshooter standings*", ""]
    for r in rows:
        lines.append(standing_line(r) + (f" · {r['pending']} pending" if r["pending"] else ""))
    return "\n".join(lines) + "\n"


def digest_md(season: Season, week: int, now: datetime, rows: list, yesterday: list, games: list,
              pickers: dict, hidden: set) -> tuple:
    """The morning post: (standings with yesterday's results, today's games with who picked what, or None).

    `yesterday` is standings rows over picks in games that tipped yesterday; `pickers` is {game_id: {team: [names]}}
    for games whose picks are visible; `hidden` holds the ids of games whose picks aren't locked yet.
    """
    off = season.off_week_label(week)
    lines = [f"🏀 *PEAshooter* · {now:%a %b %-d} · Week {week}" + (f" ({off})" if off else ""), "", "*Standings*"]
    played = {r["member"]: r for r in yesterday if r["wins"] + r["losses"] + r["pending"]}
    if not any(r["wins"] + r["losses"] for r in rows):  # opening day: a column of tied 🥇s says nothing
        lines.append("_No results yet._")
    else:
        for r in rows:
            y = played.get(r["member"])
            lines.append(standing_line(r) + (f" · +{y['points']} yesterday" if y else ""))
    if played:
        wins, losses, pending = (sum(r[k] for r in played.values()) for k in ("wins", "losses", "pending"))
        summary = f"*Yesterday*: {wins + losses + pending} picks, {wins} {WIN} {losses} {LOSS}" + \
                  (f" {pending} {PENDING}" if pending else "")
        best = max(r["points"] for r in played.values())
        if best:
            summary += " · Best day: " + ", ".join(f"{r['name']} ({r['wins']}–{r['losses']})"
                                                   for r in played.values() if r["points"] == best)
        lines += ["", summary]
    if not games:
        return "\n".join(lines + ["", "_No games today._"]) + "\n", None

    out = [f"*Today: {len(games)} game{'s' if len(games) != 1 else ''}* (times ET)"]
    notes = []
    for g in sorted(games, key=lambda g: g.tip):
        special = season.special_for(g.tip)
        line = f"• {clock(g.tip.astimezone(season.tz))} · {nickname(g.away)} @ {nickname(g.home)}{event_tag(g)}{national_tv(g)}"
        if special:
            line += f" ⭐ {special.name}, {special.points} pts"
        if g.id in hidden:
            note = "⭐ bonus-game picks show once the game tips" if special else \
                f"Week {week} picks lock {season.deadline(week):%a} {clock(season.deadline(week))} ET and show after that"
            notes += [note] if note not in notes else []
        else:
            picked = pickers.get(g.id, {})
            line += ": " + (" · ".join(f"{nickname(t)} ({', '.join(picked[t])})" for t in g.teams if t in picked)
                            or "no picks")
        out.append(line)
    if notes:
        out += ["", "_" + " · ".join(notes) + "_"]
    return "\n".join(lines) + "\n", "\n".join(out) + "\n"


def _cell(text: str, bold: bool = False) -> dict:
    """A table cell: rich text when bold, plain otherwise."""
    if not bold:
        return {"type": "raw_text", "text": text}
    return {"type": "rich_text", "elements": [{"type": "rich_text_section", "elements": [
        {"type": "text", "text": text, "style": {"bold": True}}]}]}


def _links_cell(links: list) -> dict:
    """A table cell of links separated by dots; unlinked feeds stay plain text. Slack rejects empty cells."""
    if not links:
        return _cell("–")
    parts = []
    for i, (label, link) in enumerate(links):
        parts += [{"type": "text", "text": " · "}] if i else []
        parts.append({"type": "link", "url": link, "text": label} if link else {"type": "text", "text": label})
    return {"type": "rich_text", "elements": [{"type": "rich_text_section", "elements": parts}]}


def digest_blocks(season: Season, week: int, now: datetime, rows: list, yesterday: list, games: list,
                  pickers: dict, hidden: set, site_url: str = "") -> tuple:
    """Block Kit for the morning post, from the same inputs as digest_md: (main blocks, thread blocks or None)."""
    off = season.off_week_label(week)
    title = f"🏀 PEAshooter · {now:%a %b %-d} · Week {week}" + (f" ({off})" if off else "")
    main = [{"type": "header", "text": {"type": "plain_text", "text": title, "emoji": True}}]
    played = {r["member"]: r for r in yesterday if r["wins"] + r["losses"] + r["pending"]}
    if not any(r["points"] for r in rows):
        none = "_No results yet._" if not any(r["wins"] + r["losses"] for r in rows) else "_No points yet._"
        main.append({"type": "context", "elements": [{"type": "mrkdwn", "text": none}]})
    else:
        table = [[_cell(h, bold=True) for h in ("#", "Shooter", "Pts", "W–L", "Yday")]]
        for r in rows:
            if not r["points"]:  # zeros add nothing to the table
                continue
            y = played.get(r["member"])
            table.append([_cell({1: "🥇", 2: "🥈", 3: "🥉"}.get(r["rank"], str(r["rank"]))), _cell(r["name"], bold=True),
                          _cell(str(r["points"])), _cell(f"{r['wins']}–{r['losses']}"),
                          _cell(f"+{y['points']}" if y else "–")])
        main.append({"type": "table", "rows": table, "column_settings": [
            {"align": "center"}, {"align": "left"}, {"align": "right"}, {"align": "right"}, {"align": "right"}]})
    notes = []
    if played:
        wins, losses, pending = (sum(r[k] for r in played.values()) for k in ("wins", "losses", "pending"))
        summary = f"*Yesterday:* {wins + losses + pending} picks · {wins} {WIN} {losses} {LOSS}" + \
                  (f" {pending} {PENDING}" if pending else "")
        best = max(r["points"] for r in played.values())
        if best:
            summary += " · Best day: " + ", ".join(f"{r['name']} ({r['wins']}–{r['losses']})"
                                                   for r in played.values() if r["points"] == best)
        notes.append(summary)
    if site_url:
        notes.append(f"<{site_url}|Full scoreboard ↗>")
    if notes:
        main.append({"type": "context", "elements": [{"type": "mrkdwn", "text": n} for n in notes]})
    if not games:
        main.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "_No games today._"}]})
        return main, None

    table, footnotes = [[_cell(h, bold=True) for h in ("ET", "Game", "Picks", "Watch")]], []
    for g in sorted(games, key=lambda g: g.tip):
        special = season.special_for(g.tip)
        matchup = f"{g.away} @ {g.home}{event_tag(g)}" + (f" ⭐ {special.points} pts" if special else "")
        if g.id in hidden:
            note = "⭐ bonus-game picks show once the game tips" if special else \
                f"Week {week} picks lock {season.deadline(week):%a} {clock(season.deadline(week))} ET and show after that"
            footnotes += [note] if note not in footnotes else []
            picks = "🔒"
        else:
            picked = pickers.get(g.id, {})
            picks = " · ".join(f"{nickname(t)} — {', '.join(picked[t])}" for t in g.teams if t in picked) or "–"
        table.append([_cell(clock(g.tip.astimezone(season.tz))), _cell(matchup, bold=True), _cell(picks),
                      _links_cell(watch_links(g))])
    reply = [{"type": "section", "text": {"type": "mrkdwn",
                                          "text": f"*Today · {len(games)} game{'s' if len(games) != 1 else ''}*"}},
             {"type": "table", "rows": table, "column_settings": [
                 {"align": "right"}, {"align": "left"}, {"align": "left", "is_wrapped": True},
                 {"align": "left", "is_wrapped": True}]}]
    if footnotes:
        reply.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "_" + " · ".join(footnotes) + "_"}]})
    return main, reply
