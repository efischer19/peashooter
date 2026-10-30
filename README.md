# PEAshooter: Pick 'Em All, Shooter

A season-long NBA pick 'em pool for a Slack group. Members pick on a small web page, or straight in a Google Form. A deterministic Python CLI on cron checks and scores the picks, and the results go to Slack, a Google Sheet and an optional public scoreboard page.

- Every pick week, each member picks straight-up winners (`picks_per_week`, e.g. 5). A pick is one team in one specific game.
- Within each cycle (`cycle_weeks`, e.g. 6), no team can be picked twice; with 5 × 6 = 30 you pick every team once.
- Special games (e.g. the NBA Cup Final and Christmas Day) are everybody-picks-everything, for bonus points.
- No eliminations: wins are points on a season-long leaderboard.

All rules and the calendar live in one config file; nothing league-specific is in the code. There's no LLM anywhere in the scoring path: validation, deadlines and points are plain, tested Python, and the Google Form responses stay the auditable raw record.

There's no server to run. Google Forms is the backend, the pages are static files on S3, and the machine running cron only makes outbound connections (to Google, stats.nba.com, Slack and S3). Members don't need to open the Form or the Sheet: they pick on the pick helper page and follow along in Slack and on the scoreboard. Google still keeps every response, timestamped, so everything else can be rebuilt from it.

## Status

In use for the 2026-27 season. Working: the rules engine, schedule and score sync, the weekly Google Form and Sheet tracker, Slack posts (a weekly cycle plus a daily digest), the public scoreboard page and the pick helper (with Slack sign-in and submitting from the page), all on cron. Not built yet: a Slack bot that reads DMs for pick fixes (they go through the organizer's `admin.py replace` for now). What's next (bonus-game windows, and more) is in [docs/ROADMAP.md](docs/ROADMAP.md).

## Setup

```sh
cp season.example.toml season.toml   # your calendar, rules and members
cp .env.example .env                 # paths and (later) credentials
uv sync --extra nba --extra google   # nba_api (schedule/scores) and Google client libraries
uv run pytest
uv run --extra nba sync.py --all     # load the season's schedule into data/peashooter.db
uv run --extra nba admin.py site     # optional: build the scoreboard page in data/site/
```

Run `sync.py` (no flags) daily from cron to pick up final scores. It syncs last week through next week in one request and exits non-zero on failure.

## Running weeks by hand

One Google Form for the whole season, created and updated by `google_form.py` (after the Google setup below):

```sh
uv run --extra google --extra nba google_form.py --week 1   # creates the form (first run), sets it to week 1, opens it
```

It asks for **Name** (dropdown from `season.toml`), **Week** (only the current week) and **Picks** (one per line, naming the team *and* its game: `Celtics vs Knicks`, `Celtics @ Knicks` or `Celtics Tue`). The week's schedule goes in the form description. The one manual step: in the form editor, **Responses → Link to Sheets → Create a new spreadsheet**. Then `google_form.py --status` records the Sheet's ID in `.env` and sets its time zone.

Each week:

```sh
uv run --extra nba admin.py schedule-md --week 3            # Sunday: post the schedule
uv run --extra google --extra nba google_form.py --week 3   # Sunday: switch the form to week 3 and open it
uv run --extra google google_form.py --close                # Monday at the deadline
# Monday after the deadline: File → Download → CSV of the responses tab
uv run --extra nba admin.py ingest responses.csv --week 3   # post the summary
uv run --extra nba admin.py replace --week 3 --member "Bob" "Lakers Fri"   # DM fixes during the grace window
uv run --extra nba admin.py picks --week 3                  # pick sheet with results
uv run --extra nba admin.py standings
uv run --extra nba admin.py digest                           # standings + today's games (what cron posts daily)
uv run --extra nba admin.py results                          # yesterday's digest thread with ✅/❌ (--post edits it)
uv run admin.py remaining --week 4                          # teams left going into next week
```

The Sheet shows one "Week N" tab per week of the current cycle, with the current week in front. When a new cycle starts, the previous cycle's tabs are hidden, not deleted: they stay as the record, and you can unhide them in Sheets. `admin.py tabs --week N` sets this up by hand; `sunday`, `monday` and `daily` keep it up to date.

A last **Watch** column follows the scoreboard page: before and during a game, links to NBA.com, the national broadcaster and that row's team's local feeds; once final, the full-game highlights video if one is matched (see below), else NBA.com. Members with no picks stored at all have their columns hidden; they reappear on the next rebuild after their first submission.

A **Who's In** tab, right after the current week's tab, lists each member as ✅ In, ⚠️ Late or — for that week, with the time of their last submission. It's built from formulas over the responses tab, so it updates the moment a form comes in, and it never shows picks. The same commands point it at the current week.

Re-running `ingest` with a newer CSV is safe: each member's latest on-time response replaces their earlier one.

## Google setup (one time, ~10 minutes)

PEAshooter signs in to Google as you (OAuth), not as a service account: service accounts have no Drive storage, so they can't own Forms or Sheets in a personal Google account.

1. [console.cloud.google.com](https://console.cloud.google.com): create a project (e.g. "peashooter").
2. **APIs & Services → Library:** enable the **Google Sheets API** and the **Google Forms API**.
3. **Google Auth Platform** (formerly the "OAuth consent screen") → *Get started*: app name, your email, audience **External**. Publishing also needs, on the **Branding** page, a home page URL, a privacy policy URL (this repo's `PRIVACY.md` works) and an authorized domain. No logo.
4. **Audience → Publish app** (status *In production*). In *Testing*, refresh tokens expire after 7 days. Unverified is fine for your own account.
5. **Clients → Create client → Desktop app**, then **Download JSON** and save it as `~/.config/peashooter/client_secret.json`.
6. `uv run --extra google google_auth.py`. Sign in, click past "Google hasn't verified this app" (*Advanced → Go to …*), and allow both permissions. The token is saved to `~/.config/peashooter/token.json`.
7. Put the Sheet and Form IDs in `.env` and run `uv run --extra google google_auth.py --check`.

Copy the two JSON files to wherever the bot runs; the token refreshes itself.

## Slack setup (posting)

1. [api.slack.com/apps](https://api.slack.com/apps) → **Create New App → From a manifest** → pick the workspace → paste `slack_manifest.yaml`.
2. **Install to Workspace**, then copy the **Bot User OAuth Token** (`xoxb-…`) into `.env` as `SLACK_BOT_TOKEN`.
3. In Slack, `/invite @PEAshooter` to the channel, and put its ID (channel name → *About*, bottom: `C…`) in `.env` as `SLACK_CHANNEL_ID`. Start with a test channel and swap in the real one at launch.
4. Add `--post` to any `admin.py` command to post its output, e.g. `admin.py --post reminder`.

## Running it on a schedule

`deploy/crontab.example` runs the week (times ET):

- Sunday 11:00 `sunday`: open the form for the coming week, write its availability grid, post the schedule; then publish the pages, so the pick helper knows the form is open.
- Monday 17:00 `reminder`, then 18:45 `monday`: close the form, ingest, rebuild the grid, post the summary.
- Daily 4:00 `daily`: sync scores and highlights, rebuild the grids. 4:15 `digest`: standings with each member's points from yesterday, then today's games and who picked what in its thread. Before posting, it edits yesterday's thread to mark each pick ✅ or ❌ (only the thread reply; the morning's standings stay as they were). 4:20 (and Monday 18:50, right after the lock): publish the scoreboard and the pick helper.

Picks in the digest and on the page follow the grid's rules: regular picks appear once the week locks, and special-game picks once that game tips. Run everything from one machine, since the local database is part of the record.

## Public scoreboard page (optional)

`admin.py site` writes `data/site/index.html`: standings, this week's and last week's games by day, and who picked what once picks lock. Members appear only by their `alias` in `season.toml` (or "Shooter N"), never by name. It links to the pick helper, never to the form or the Sheet. `deploy/publish_site.sh` builds it and uploads it to an S3 prefix (`SITE_S3`, `AWS_PROFILE`); set `PEASHOOTER_SITE_URL` in `.env` and the digest links to it. Give the uploading IAM user `s3:PutObject` on that prefix only.

Each game card has a watch link under its time:

- **Before and during the game:** a TV menu with the game's NBA.com page (League Pass), the national broadcaster, and each team's local TV and streaming feeds, as listed in the schedule feed. Feeds with a watch link (DAZN, ESPN, NBC Sports and others) open it; the rest are plain text. Local feeds are in-market only, and League Pass blacks out US national games, so the menu lists every option. The digest names the national network next to each of today's games.
- **After the game:** full-game highlights on YouTube, if `[highlights] youtube_playlist` is set in `season.toml`. `daily` (and `sync.py`) match videos titled `AWAY at HOME | FULL GAME HIGHLIGHTS | Month D, YYYY` to games by teams and date. A YouTube failure is reported but never fails the run. Without a match, the link goes to the game's NBA.com page.

## Pick helper page (optional)

`admin.py picker` writes `data/site/picks.html`, and `deploy/publish_site.sh` uploads it next to the scoreboard at `<prefix>/picks`. It offers the week of the next deadline and the week after, for planning. You choose a shooter (by alias) and tap teams; teams used this cycle and games before the deadline are disabled, by the same rules the form validates against. It produces pick text the parser can't misread (`Cavaliers @ Wizards Mon`).

On its own the page is copy-text only and safe to leave public. To let members submit from it:

1. **Put the page behind a login.** For example, a Cloudflare Access application on the `picks` path, using Slack as a generic OIDC login (`openid email profile`) and a policy on the `https://slack.com/team_id` claim. Add the `https://slack.com/user_id` claim to the login method, and members' `slack_id`s to `season.toml`.
2. **Record the form's details.** Run `google_form.py --status` once. It (and every later open or close) records the form's URL, its prefill entry ids and the week it's open for in `.env`.
3. **Set `PEASHOOTER_PICKER_FORM=1`** in `.env`.

The page then asks the login who's signed in and selects their shooter, matching a hash of the Slack user id (no Slack ids appear in the page). For the week the form is open, it offers **Submit picks**, which posts straight to the Google Form from the browser, plus a prefilled-form link as a fallback. The browser can't read the form's reply, so Monday's summary is the confirmation; sending again replaces the earlier picks. With the switch on, the Slack posts lead with the page, and the digest links to it while the form is open.

## Data source

Schedules and scores come from stats.nba.com via [nba_api](https://github.com/swar/nba_api) (`[source] kind = "nba_api"`). The plan is to switch to [hoopstat-haus](https://github.com/efischer19/hoopstat-haus) once it can serve them. Any object with `games(start, end) -> list[Game]` works as a source; `kind = "fixture"` reads a local JSON file for testing.

`season.toml`, `.env`, `data/` and service-account files are git-ignored. Keep credentials there or in the environment, never in code.

## Layout

| File | Purpose |
|---|---|
| `season.py` | Loads `season.toml`: weeks, cycles, deadlines, off weeks, specials, members |
| `teams.py` | NBA teams and fuzzy name matching ("Sixers", "Timberwovles") |
| `schedule.py` | `Game` and the `ScheduleSource` interface; `FixtureSource` reads a local JSON file |
| `rules.py` | Pure validation, scoring, standings and DM pick parsing |
| `store.py` | SQLite storage, the source of truth (`PEASHOOTER_DB`) |
| `pool.py` | Pool operations combining the store and the rules |
| `sources.py` | nba_api source and `[source]` config |
| `sync.py` | Cron entry point: pull schedule and scores into the store |
| `report.py` | Slack-ready text and Block Kit: schedules, pick sheets, summaries, standings, the daily digest |
| `scoreboard.py` | The public scoreboard page (HTML), aliases only |
| `picker.py` | The pick helper page (HTML): legal picks per shooter, pick text, and submitting to the form |
| `highlights.py` | Matches full-game highlight videos from a YouTube playlist to finished games |
| `admin.py` | CLI for running the pool by hand |
| `env.py` | Loads `.env` |
| `google_auth.py` | One-time Google sign-in, plus `--check` |
| `google_form.py` | Creates the season's form, sets it up each week, opens and closes it |
| `grid.py`, `google_sheet.py` | The per-week tracker grid, and writing it as a Sheet tab |
| `slack_post.py` | Posts to Slack (`chat:write`), with thread replies |
| `deploy/` | Example crontab and the script that publishes the scoreboard and pick helper |

## License

MIT. See also the [privacy policy](PRIVACY.md).
