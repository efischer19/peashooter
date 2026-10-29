"""The pick helper page: choose a week and a shooter, tap teams in the week's games, get form-ready picks.

Static HTML with the data inlined; the page itself only does selection, and works out the lock from the
deadline against the viewer's clock, so it only needs rebuilding when the data changes. Legality comes from
pool.form_options, the same rules the form validates against, so the page never offers a pick the pool would drop.
Members appear by alias (as on the scoreboard). Without a form URL the page only offers the text to copy. With one
(the page sits behind Cloudflare Access with Slack sign-in), it asks Access who's signed in, matches their Slack
user id by hash, and lets them submit their own picks straight to the form for the week it's open for, or open
the form prefilled. The form can't confirm a submission to the page; the Monday close is the record.
"""

import hashlib
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


def who_hash(slack_id: str) -> str:
    """How the page recognises a signed-in member without listing Slack ids: a short SHA-256 of the id."""
    return hashlib.sha256(slack_id.encode()).hexdigest()[:16]


def page_html(season: Season, data: list, form_url: str = "", entries: Optional[dict] = None,
              form_week: Optional[int] = None, site_url: str = "") -> str:
    """`data` is week_data for each week offered. `entries` maps "name", "week" and "picks" to the form's entry ids
    (decimal question ids); `form_week` is the week the form is open for (None while it's closed). `site_url` is
    the scoreboard's absolute URL, for the link back. Roster names go in the page only along with a form URL."""
    teams = {code: {"nick": nickname(code), "color": COLORS.get(code, "#555")} for code in TEAMS}
    names = aliases(season)
    roster = {names[m.name]: {"name": m.name, "who": who_hash(m.slack_id) if m.slack_id else ""}
              for m in season.members} if form_url else {}
    payload = json.dumps({"weeks": data, "teams": teams, "perWeek": season.picks_per_week, "formUrl": form_url,
                          "entries": entries or {}, "formWeek": form_week if form_url else None, "roster": roster,
                          "cycleWeeks": season.cycle_weeks}, ensure_ascii=False).replace("</", "<\\/")
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
<div class="actions"><button type="button" id="submit" class="primary">Submit picks</button>
<button type="button" id="copy">Copy picks</button>
<a id="form" target="_blank" rel="noopener">Open the form, prefilled ↗</a></div>
<p class="note" id="status"></p>
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
.actions .primary{background:var(--accent);border-color:var(--accent);color:#fff}
.actions button:disabled{opacity:.4;cursor:not-allowed}
#status{margin:0}
.actions a[aria-disabled=true]{opacity:.4;pointer-events:none}
#clear{padding:4px 10px;font-size:.8rem}
"""

PICKER_JS = r"""
const $ = id => document.getElementById(id);
const tm = code => `<span class="tm" style="--c:${DATA.teams[code].color}">${code}</span>`;
let state = {week: null, shooter: null, picks: []};  // picks: [{id, team}]
let me = null, sending = false;  // me: the signed-in shooter's alias, from Cloudflare Access

const locked = w => Date.now() > Date.parse(w.deadlineAt);
function weekData() { return DATA.weeks.find(w => w.week === state.week); }
function shooter() { return weekData().shooters[state.shooter]; }

function findUserId(node) {  // the Slack user-id claim, wherever Access puts it in the identity
  if (!node || typeof node !== "object") return null;
  for (const [k, v] of Object.entries(node)) {
    if (k.endsWith("user_id") && typeof v === "string") return v;
    const found = findUserId(v);
    if (found) return found;
  }
  return null;
}

async function whoAmI() {
  try {
    const r = await fetch("/cdn-cgi/access/get-identity", {credentials: "same-origin"});
    const id = r.ok ? findUserId(await r.json()) : null;
    if (!id) return null;
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(id)));
    const who = [...digest].map(b => b.toString(16).padStart(2, "0")).join("").slice(0, 16);
    return Object.keys(DATA.roster).find(a => DATA.roster[a].who === who) || null;
  } catch (e) { return null; }
}

const sentKey = () => `peashooter-sent-${state.week}-${state.shooter}`;
function sent() { try { return JSON.parse(localStorage.getItem(sentKey()) || "null"); } catch (e) { return null; } }

async function submit() {
  const w = weekData(), text = $("text").value, n = state.picks.length;
  if (n < DATA.perWeek && !confirm(`Send only ${n} of ${DATA.perWeek} picks? You can send again before the deadline; the latest one counts.`)) return;
  const body = new URLSearchParams();
  body.set(`entry.${DATA.entries.name}`, DATA.roster[me].name);
  body.set(`entry.${DATA.entries.week}`, `Week ${w.week}`);
  body.set(`entry.${DATA.entries.picks}`, text);
  sending = true; render();
  try {
    await fetch(DATA.formUrl.replace(/\/viewform.*$/, "/formResponse"), {method: "POST", mode: "no-cors", body});
    try { localStorage.setItem(sentKey(), JSON.stringify({at: new Date().toISOString(), text})); } catch (e) {}
    sending = false; render();
  } catch (e) {
    sending = false; render();
    $("status").textContent = "Couldn't send. Try again, or use \u201cOpen the form, prefilled\u201d.";
  }
}

function init() {
  $("week").innerHTML = DATA.weeks.map(w => `<option value="${w.week}">Week ${w.week}${locked(w) ? " (locked)" : ""}</option>`).join("");
  const names = Object.keys(DATA.weeks[0].shooters);
  $("shooter").innerHTML = names.map(n => `<option>${n}</option>`).join("");
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem("peashooter-picker") || "{}"); } catch (e) {}
  state.week = DATA.weeks.some(w => w.week === saved.week) ? saved.week : DATA.weeks[0].week;
  state.shooter = names.includes(saved.shooter) ? saved.shooter : names[0];
  $("week").value = state.week; $("shooter").value = state.shooter;
  $("week").onchange = e => { state.week = +e.target.value; state.picks = []; render(); };
  $("shooter").onchange = e => { state.shooter = e.target.value; state.picks = []; render(); };
  $("clear").onclick = () => { state.picks = []; render(); };
  $("copy").onclick = async () => {
    try { await navigator.clipboard.writeText($("text").value); $("copy").textContent = "Copied ✓"; }
    catch (e) { $("text").select(); document.execCommand("copy"); $("copy").textContent = "Copied ✓"; }
    setTimeout(() => $("copy").textContent = "Copy picks", 1500);
  };
  $("submit").onclick = submit;
  render();
  if (DATA.formUrl) whoAmI().then(alias => {
    me = alias;
    if (me && me !== state.shooter) { state.shooter = me; $("shooter").value = me; state.picks = []; }
    render();
  });
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
  // the form takes only the week it's open for; submitting is for your own picks, once Access says who you are
  const open = Boolean(DATA.formUrl) && w.week === DATA.formWeek && !locked(w);
  const mine = open && me !== null && state.shooter === me;
  const link = $("form");
  link.style.display = open ? "" : "none";
  if (open && picks.length) {
    const q = new URLSearchParams({usp: "pp_url"});
    if (mine) q.set(`entry.${DATA.entries.name}`, DATA.roster[me].name);
    q.set(`entry.${DATA.entries.week}`, `Week ${w.week}`);
    q.set(`entry.${DATA.entries.picks}`, text);
    link.href = `${DATA.formUrl}?${q}`; link.removeAttribute("aria-disabled");
  } else { link.removeAttribute("href"); link.setAttribute("aria-disabled", "true"); }
  const button = $("submit");
  button.style.display = mine ? "" : "none";
  button.disabled = sending || !picks.length;
  button.textContent = sending ? "Sending…" : picks.length && picks.length < DATA.perWeek
    ? `Submit ${picks.length} of ${DATA.perWeek}` : "Submit picks";
  const last = mine ? sent() : null;
  $("status").textContent = sending ? "" : last
    ? `Sent ${new Date(last.at).toLocaleString([], {weekday: "short", hour: "numeric", minute: "2-digit"})}: ${last.text.split("\n").join(" · ")}. Sending again replaces it; Monday's summary in Slack is the record.`
    : mine ? "" : open && me ? `You're signed in as ${me}: submitting here is for your own picks.`
    : open ? "Open the form with these picks filled in, then pick your name."
    : DATA.formUrl && !locked(w) ? `The form opens for week ${w.week} on the Sunday before. Plan now; send then.`
    : "Copy your picks, then paste them into the week's form (the link is in Slack).";
}
init();
"""
