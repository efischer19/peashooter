"""The pick helper page: choose a week and a shooter, tap teams in the week's games, get form-ready picks.

Static HTML with the data inlined; the page itself only does selection, and works out the lock from the
deadline against the viewer's clock, so it only needs rebuilding when the data changes. Legality comes from
pool.form_options, the same rules the form validates against, so the page never offers a pick the pool would drop.
Members appear by alias (as on the scoreboard), so a prefilled form link fills Week and Picks and leaves Name to
the form. Without a form URL (the default until the page is behind a login) it offers the text to copy only.
"""

import json
from datetime import datetime
from html import escape
from typing import Optional

import pool
from report import clock, nickname
from scoreboard import COLORS, CSS, aliases
from season import Season
from teams import TEAMS


def pick_text(season: Season, game, team: str) -> str:
    """'Cavaliers vs Timberwolves Mon': the team, its opponent and the day, which the parser can't misread."""
    other = game.home if team == game.away else game.away
    where = "@" if team == game.away else "vs"
    return f"{nickname(team)} {where} {nickname(other)} {game.tip.astimezone(season.tz):%a}"


def next_deadline_week(season: Season, now: datetime) -> Optional[int]:
    """The first regular week whose deadline hasn't passed."""
    return next((w for w in range(1, season.weeks + 1) if season.is_regular(w) and season.deadline(w) > now), None)


def picker_weeks(season: Season, now: datetime) -> list:
    """The week being picked, and the regular week after it for planning."""
    first = next_deadline_week(season, now)
    if first is None:
        return []
    later = next((w for w in range(first + 1, season.weeks + 1) if season.is_regular(w)), None)
    return [first] + ([later] if later else [])


def week_data(season: Season, store, week: int) -> dict:
    """Everything the page needs for one week: games by day, and per shooter what's legal and what's used."""
    names = aliases(season)
    games = pool.week_games(store, season, week)
    cutoff = season.deadline(week)
    out = {"week": week, "deadline": f"{cutoff:%a %b %-d}, {clock(cutoff)} ET", "deadlineAt": cutoff.isoformat(),
           "games": [], "shooters": {}}
    for g in games:
        if season.special_for(g.tip):
            continue
        local = g.tip.astimezone(season.tz)
        out["games"].append({"id": g.id, "day": f"{local:%A, %b %-d}", "time": clock(local), "away": g.away,
                             "home": g.home, "early": g.tip <= cutoff,
                             "text": {t: pick_text(season, g, t) for t in g.teams}})
    for m in season.members:
        used = {}
        cycle = season.cycle_for(week)
        for w in (season.weeks_in_cycle(cycle) if cycle else []):
            if w < week:
                for p in store.picks(member=m.name, weeks=[w], kind=pool.REGULAR, accepted=True):
                    used.setdefault(p.team, w)
        legal = [f"{g.id}|{t}" for g, t in pool.form_options(store, season, m.name, week)]
        out["shooters"][names[m.name]] = {"used": used, "legal": legal}
    return out


def page_html(season: Season, data: list, default: str = "", form_url: str = "", entries: Optional[dict] = None,
              site_url: str = "") -> str:
    """`data` is week_data for each week offered. `entries` maps "week" and "picks" to the form's prefill entry ids
    (decimal question ids). `site_url` is the scoreboard's absolute URL, for the link back."""
    teams = {code: {"nick": nickname(code), "color": COLORS.get(code, "#555")} for code in TEAMS}
    payload = json.dumps({"weeks": data, "teams": teams, "perWeek": season.picks_per_week, "default": default,
                          "formUrl": form_url, "entries": entries or {}, "cycleWeeks": season.cycle_weeks},
                         ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E🏀%3C/text%3E%3C/svg%3E">
<title>PEAshooter Picks</title>
<style>{CSS}{PICKER_CSS}</style>
</head>
<body>
<main>
<header>
<h1>🏀 <span>PEA</span>shooter picks</h1>
<div class="sub">{escape(season.name)} · <a href="{escape(site_url or './')}">Scoreboard</a></div>
</header>
<div class="controls">
<label>Week <select id="week"></select></label>
<label>Shooter <select id="shooter"></select></label>
</div>
<p class="note" id="deadline"></p>
<section>
<h2>Teams left this cycle</h2>
<div class="left" id="left"></div>
</section>
<section>
<h2>This week's games</h2>
<div id="days"></div>
</section>
</main>
<aside class="tray" id="tray">
<div class="tray-in">
<div class="tray-top"><b id="count"></b><button type="button" id="clear">Clear</button></div>
<div class="chips" id="chips"></div>
<textarea id="text" rows="5" readonly aria-label="Your picks, ready to paste into the form"></textarea>
<div class="actions"><button type="button" id="copy">Copy picks</button>
<a id="form" class="primary" target="_blank" rel="noopener">Open the form, prefilled ↗</a></div>
<p class="note" id="paste">Copy your picks, then paste them into the week's form (the link is in Slack).</p>
</div>
</aside>
<script>const DATA = {payload};
{PICKER_JS}</script>
</body>
</html>
"""


PICKER_CSS = """
a{color:var(--accent)}
.controls{display:flex;gap:12px;flex-wrap:wrap;margin-top:20px}
.controls label{display:flex;flex-direction:column;gap:4px;font-size:.75rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.controls select{font:inherit;font-size:1rem;text-transform:none;letter-spacing:0;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 12px;min-width:150px}
.left{display:flex;flex-wrap:wrap;gap:5px}
.left .tm.spent{opacity:.22}
.left .tm.chosen{outline:2px solid var(--pick-line);outline-offset:1px}
.pickgame{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:8px;display:grid;grid-template-columns:62px 1fr;gap:6px 10px;align-items:center}
.pickgame .when{color:var(--muted);font-size:.82rem;padding-left:6px}
.pickgame .sides{display:grid;gap:6px}
.team{display:flex;align-items:center;gap:9px;width:100%;font:inherit;color:var(--ink);text-align:left;background:transparent;border:1px solid transparent;border-radius:9px;padding:5px 8px;cursor:pointer}
.team:hover:not(:disabled){border-color:var(--line);background:var(--bg)}
.team .at{color:var(--muted);font-size:.78rem;margin-left:auto}
.team.on{background:var(--pick-bg);border-color:var(--pick-line);color:var(--pick-ink);font-weight:700}
.team.on .at{color:var(--pick-ink)}
.team:disabled{cursor:not-allowed;color:var(--muted)}
.team:disabled .tm{opacity:.3}
.team.elsewhere:not(.on){opacity:.55}
.tray{position:sticky;bottom:0;background:linear-gradient(transparent,var(--bg) 18px);padding:18px 16px 16px}
.tray-in{max-width:688px;margin:0 auto;background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:0 -6px 30px rgba(0,0,0,.12);padding:12px 14px;display:grid;gap:10px}
.tray-top{display:flex;align-items:center;justify-content:space-between}
.tray-top b.full{color:var(--win)}
.chips{display:flex;flex-wrap:wrap;gap:6px;min-height:24px}
.chips .who{display:inline-block;font-weight:700;font-size:.8rem;color:var(--pick-ink);background:var(--pick-bg);border:1px solid var(--pick-line);border-radius:6px;padding:1px 7px;cursor:pointer}
.chips .empty{color:var(--muted);font-size:.86rem;font-style:italic}
textarea{width:100%;font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px;resize:none}
.actions{display:flex;gap:8px;flex-wrap:wrap}
button,.actions a{font:inherit;font-size:.9rem;font-weight:600;border-radius:9px;padding:8px 14px;border:1px solid var(--line);background:var(--bg);color:var(--ink);cursor:pointer;text-decoration:none}
.actions a.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.actions a[aria-disabled=true]{opacity:.4;pointer-events:none}
#clear{padding:4px 10px;font-size:.8rem}
"""

PICKER_JS = r"""
const $ = id => document.getElementById(id);
const tm = code => `<span class="tm" style="--c:${DATA.teams[code].color}">${code}</span>`;
let state = {week: null, shooter: null, picks: []};  // picks: [{id, team}]

const locked = w => Date.now() > Date.parse(w.deadlineAt);
function weekData() { return DATA.weeks.find(w => w.week === state.week); }
function shooter() { return weekData().shooters[state.shooter]; }

function init() {
  $("week").innerHTML = DATA.weeks.map(w => `<option value="${w.week}">Week ${w.week}${locked(w) ? " (locked)" : ""}</option>`).join("");
  const names = Object.keys(DATA.weeks[0].shooters);
  $("shooter").innerHTML = names.map(n => `<option>${n}</option>`).join("");
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem("peashooter-picker") || "{}"); } catch (e) {}
  state.week = DATA.weeks.some(w => w.week === saved.week) ? saved.week : DATA.weeks[0].week;
  state.shooter = names.includes(saved.shooter) ? saved.shooter : (names.includes(DATA.default) ? DATA.default : names[0]);
  $("week").value = state.week; $("shooter").value = state.shooter;
  $("week").onchange = e => { state.week = +e.target.value; state.picks = []; render(); };
  $("shooter").onchange = e => { state.shooter = e.target.value; state.picks = []; render(); };
  $("clear").onclick = () => { state.picks = []; render(); };
  $("copy").onclick = async () => {
    try { await navigator.clipboard.writeText($("text").value); $("copy").textContent = "Copied ✓"; }
    catch (e) { $("text").select(); document.execCommand("copy"); $("copy").textContent = "Copied ✓"; }
    setTimeout(() => $("copy").textContent = "Copy picks", 1500);
  };
  render();
}

function toggle(id, team) {
  const i = state.picks.findIndex(p => p.id === id && p.team === team);
  if (i >= 0) state.picks.splice(i, 1);
  else {
    state.picks = state.picks.filter(p => p.team !== team && p.id !== id);  // one game per team, one side per game
    if (state.picks.length < DATA.perWeek) state.picks.push({id, team});
  }
  render();
}

function render() {
  try { localStorage.setItem("peashooter-picker", JSON.stringify({week: state.week, shooter: state.shooter})); } catch (e) {}
  const w = weekData(), s = shooter(), legal = new Set(s.legal);
  const chosen = new Set(state.picks.map(p => p.team)), full = state.picks.length >= DATA.perWeek;
  $("deadline").textContent = locked(w) ? `Week ${w.week} picks locked ${w.deadline}.`
    : `Picks due ${w.deadline}. Games before then are locked; teams you've used this cycle are greyed out.`;
  $("left").innerHTML = Object.keys(DATA.teams).sort((a, b) => DATA.teams[a].nick.localeCompare(DATA.teams[b].nick))
    .map(t => `<span class="${s.used[t] ? "tm spent" : chosen.has(t) ? "tm chosen" : "tm"}" style="--c:${DATA.teams[t].color}" title="${DATA.teams[t].nick}${s.used[t] ? `: used in week ${s.used[t]}` : ""}">${t}</span>`).join("");
  const byDay = [];
  for (const g of w.games) { (byDay.at(-1)?.day === g.day ? byDay.at(-1) : byDay[byDay.push({day: g.day, games: []}) - 1]).games.push(g); }
  $("days").innerHTML = byDay.map(d => `<details class="day" open><summary>${d.day}<span class="count">${d.games.length} game${d.games.length === 1 ? "" : "s"}</span></summary><div class="games">${
    d.games.map(g => `<div class="pickgame"><div class="when">${g.time}${g.early ? "<br>🔒" : ""}</div><div class="sides">${
      [g.away, g.home].map(t => {
        const on = state.picks.some(p => p.id === g.id && p.team === t);
        const why = s.used[t] ? `used wk ${s.used[t]}` : g.early ? "before the deadline" : "";
        const ok = legal.has(`${g.id}|${t}`) && !locked(w) && (on || !full || state.picks.some(p => p.id === g.id || p.team === t));
        const where = t === g.away ? `@ ${g.home}` : `vs ${g.away}`;
        return `<button type="button" class="team${on ? " on" : ""}${chosen.has(t) && !on ? " elsewhere" : ""}" data-id="${g.id}" data-team="${t}" ${ok ? "" : "disabled"} title="${why || g.text[t]}">${tm(t)}<span>${DATA.teams[t].nick}</span><span class="at">${why || where}</span></button>`;
      }).join("")}</div></div>`).join("")}</div></details>`).join("") || `<p class="note">No games this week.</p>`;
  document.querySelectorAll(".team:not(:disabled)").forEach(b => b.onclick = () => toggle(b.dataset.id, b.dataset.team));
  const games = Object.fromEntries(w.games.map(g => [g.id, g]));
  const picks = [...state.picks].sort((a, b) => w.games.indexOf(games[a.id]) - w.games.indexOf(games[b.id]));
  $("count").textContent = `${picks.length} of ${DATA.perWeek} picked`;
  $("count").className = picks.length === DATA.perWeek ? "full" : "";
  $("chips").innerHTML = picks.length ? picks.map(p => `<span class="who" data-id="${p.id}" data-team="${p.team}" title="Remove">${games[p.id].text[p.team]} ✕</span>`).join("")
    : `<span class="empty">Tap a team to pick it.</span>`;
  document.querySelectorAll(".chips .who").forEach(c => c.onclick = () => toggle(c.dataset.id, c.dataset.team));
  const text = picks.map(p => games[p.id].text[p.team]).join("\n");
  $("text").value = text;
  $("text").style.display = picks.length ? "" : "none";
  const link = $("form");
  if (DATA.formUrl && picks.length) {
    const q = new URLSearchParams({usp: "pp_url"});
    q.set(`entry.${DATA.entries.week}`, `Week ${w.week}`);
    q.set(`entry.${DATA.entries.picks}`, text);
    link.href = `${DATA.formUrl}?${q}`; link.removeAttribute("aria-disabled");
  } else { link.removeAttribute("href"); link.setAttribute("aria-disabled", "true"); }
  link.style.display = DATA.formUrl ? "" : "none";
  $("paste").style.display = DATA.formUrl ? "none" : "";
}
init();
"""
