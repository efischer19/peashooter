# PEAshooter roadmap

*Updated Oct 29, 2026 (week 2 of the 2026-27 season). The setup and commands are in the [README](../README.md).*

## Where things stand
- **Live and cron-driven** since week 1:
  - Sunday: the Form opens and the schedule posts.
  - Monday: a reminder, then the 6:45pm ET lock, ingest and summary.
  - Daily: sync, the digest, and the scoreboard page publish.
- **Watch links:**
  - Before a game: NBA.com (League Pass) plus the national and local feeds.
  - Once final: the full-game highlights on YouTube, and the League Pass replay on NBA.com.
- **Season shape:** 5 picks a week and 6-week cycles starting Oct 19, Nov 30, Jan 18 and Mar 1. Week 8 (Cup Final week) is the only off week.
- **Bonus games:** the Cup Final (Fri Dec 11) is worth **3 points**, and each Christmas game (Fri Dec 25) is worth **2 points**. Decided Oct 29.

## Ground rules
These hold for everything below.
- **Deterministic code decides picks, deadlines and scores.** An LLM can only ever be a read-only sidekick.
- **Google Forms is the backend.** Google writes the raw responses, timestamped, into the linked Sheet. Everything else can be rebuilt from them. The goal is that nobody *needs* to open the Form or the Sheet, not that they go away.
- **The pool machine only makes outbound connections.** It pulls from Google and the schedule source, and pushes to S3 and Slack. Nothing reaches it from outside, not even through a tunnel.
- **Slack posts stay.** The digest, reminders and summaries are the water cooler. Web pages add to them; they don't replace them.
- **Never reveal picks before they lock.** Regular picks stay hidden until the weekly deadline, and bonus picks until their game tips.

## Schedule
| When | What |
|---|---|
| Now (target: live for week 4, Sun Nov 8) | **Picker, Phases 0 and 1**: the page with copy-text, then Cloudflare Access with Slack sign-in and the prefilled Form button |
| Late Nov, once the Cup quarterfinals are set | Re-check the Cup knockout dates and game IDs in the feed |
| Built by Sun Dec 6 (week 8's Form opens) | **Bonus window**, used first for the Cup Final (closes when the Final tips, Dec 11) |
| By Mon Dec 21 | The Christmas bonus window (the same mechanism, for 5 games) |
| Cycle 3 boundary, Jan 18 | **Picker, Phase 2**: submit from the page |
| Whenever | Phase 3 (PWA) and the later items below |

## Picker, Phase 0: wire up the pick-helper page (next up)
`picker.py` builds a static page. You choose a week and a shooter, then tap teams in that week's games. Teams that are already used this cycle, or whose games tip before the deadline, are disabled. The page gives unambiguous pick text, one line per pick (`Cavaliers @ Wizards Mon`), to copy into the Form.

**Phase 0 is copy-text only (decided Oct 29).** The page is public until Phase 1 is set up, and the Form works on the honor system, so the Form's link stays off it for now. The prefilled-Form button arrives with Phase 1.

Legality comes from `pool.form_options`, the same rule the Form validates against, so the page can never offer a pick the pool would drop.

**Checked Oct 29**
- The Form doesn't require a Google sign-in and doesn't collect emails, so links prefilled with `entry.<id>=` work for anyone.
- Prefill entry IDs are the Forms API `questionId` read as hex and written in decimal. `week_requests` reuses the existing items, so the IDs are stable from week to week.
- No CloudFront changes are needed. The default behaviour already serves new keys under the prefix, and the upload credentials can already write anywhere under it.

**Decisions**
- **Entry IDs go in `.env`.** `google_form.py --status` writes `PEASHOOTER_FORM_URL` (the responder URL), `PEASHOOTER_FORM_WEEK_ENTRY` and `PEASHOOTER_FORM_PICKS_ENTRY`. The picker build reads them and makes no Google calls, so `publish_site.sh` keeps needing only `--extra nba`. When they're unset, the page leaves out the Form button and still offers the text to copy. Phase 0 publishes without them.
- **The page works out the lock itself.** Each game's tip and the deadline go into the page as ISO times, and the JavaScript disables locked games against the viewer's clock. So the page needs rebuilding only when the data changes: in the existing daily and Monday 18:50 publishes, plus one new Sunday 11:05 run once the Form is set to the new week. No hourly rebuilds are needed.
- **Weeks offered:** the week of the next deadline, plus the week after it when the schedule has it, for planning.
- **The prefill link is only offered for the week of the next deadline**, starting on the Sunday it opens. The Form's Week dropdown holds only that week, so a prefilled link for any other week would fail. Other weeks get text only.
- **Name is never prefilled.** The page shows aliases only, so the shooter picks their name in the Form's own dropdown.
- **Links between the pages:** the scoreboard header gets a "Make picks" link. The picker links back to the scoreboard by its absolute URL (`PEASHOOTER_SITE_URL`), because `./` resolves differently at `/peashooter/picks` than at `/peashooter/picks/`.

**Tasks**
- [ ] An `admin.py picker` command that writes `data/site/picks.html`.
- [ ] `google_form.py --status`: print the entry IDs and the responder URL, and record them in `.env`.
- [ ] `deploy/publish_site.sh`: also build the picker and upload it to `<prefix>/picks` and `<prefix>/picks/index.html`.
- [ ] Add a Sunday 11:05 publish to `deploy/crontab.example`.
- [ ] Tests in the style of `test_scoreboard.py`:
  - the legal set, used teams, skipped special games and the pick-text format;
  - the entry IDs, and the page with and without a Form URL;
  - the prefill link offered only for the open week.
- [ ] **Sun Nov 1:** once the Form opens for week 3, check against the live `viewform` page that the entry IDs appear in it (the Form is closed today, so this couldn't be checked).

## The bonus window: Cup Final and Christmas
**Decided:** bonus picks stay open until **each game tips**, for the Cup Final and for Christmas alike. One mechanism covers both.

**Plan** (to confirm when it's built):
- **One Form, two modes.** In bonus mode, the Week question offers a single option ("Cup Final" or "Christmas") and the Picks question asks for one winner per bonus game.
  - **Week 8 (Cup Final, no regular picks):** `sunday` on Dec 6 opens the Form in bonus mode.
  - **Week 10 (Christmas):** the Form runs as a normal week through the Monday Dec 21 close. Then `monday` reopens it in bonus mode until the last Christmas game tips.
- **Validation uses the Form's own timestamp:** a bonus pick counts only if its response arrived before that game's tip. Later responses replace earlier ones game by game, so a pick for a game that has already tipped can't be changed.
- **Closing:** a new cron job (`admin.py bonus`, every 15 minutes in bonus weeks) ingests the responses and closes the Form after the last bonus game tips. Picks show per game, at tip.
- **Display:** the grid, page and digest show bonus picks separately from regular picks, with their points. They don't count toward the 30-team cycle rule.
- **Before building:** check how today's `ingest` and `rules` already treat special weeks (`season.special_for`, `pool.REGULAR`), and reuse that instead of starting over.

## Picker, Phase 1: Cloudflare Access with Slack sign-in (started Oct 29)
Once Access is in front of the page, the build gets the Form entry IDs and the page shows the prefilled-Form button.

- Make `<site>/peashooter/picks*` a Cloudflare Access application. The site is already proxied by Cloudflare, so an Access application on the path works without a subdomain.
- **Identity provider:** Slack as a generic OIDC provider. Use the scopes `openid email profile` and the callback URL `https://<team>.cloudflareaccess.com/cdn-cgi/access/callback`. The policy allows the workspace, or a list of emails. Set a long session, e.g. a month.
- The page fetches `/cdn-cgi/access/get-identity` to preselect the shooter, which needs Slack IDs on the roster.
- **The bypass is accepted.** Access can be bypassed through the origin URLs (CloudFront and S3). That's fine, because the page holds nothing private: never put an email-to-alias map in the HTML. Match on a hash, or on the Slack user-ID claim.
  - With the Form button on the page, a bypass also exposes the Form's link. The S3 website endpoint can be guessed from the bucket name. That's accepted for now: it's the same honor system, and a stranger's submission would show up at the Monday close.
  - **Optional hardening:** CloudFront sends a secret `Referer` header to the origin, and a bucket-policy Deny on `peashooter/picks*` blocks reads without it. Scoped to that prefix, it doesn't affect the rest of the bucket. Add it only if this ever matters.
- **Policy:** allow anyone whose `https://slack.com/team_id` claim is the workspace's team ID. That's simpler than an email list and covers any roster change.
- **Console work (owner):**
  - [ ] Set up the Zero Trust team.
  - [ ] Turn on Sign in with Slack in the Slack app.
  - [ ] Create the Access application and its policy.
  - [ ] Add the Slack IDs for every member to `season.toml`. The bot only has `chat:write`, so copy them by hand: profile → ⋯ → Copy member ID.
- **Test early on one phone:**
  - **Installed iOS PWAs keep their own cookies**, so the login may finish in Safari and not carry back into the app.
  - **The manifest and icons are fetched without the login cookie.** Add an Access Bypass for them, or use `crossorigin="use-credentials"`.

## Picker, Phase 2: submit from the page (switch at Jan 18)
- **Preferred:** a `no-cors` POST from the browser to the Form's `/formResponse` with the `entry.*` fields. It's fully serverless. The page can't read the response, so confirmation comes from the Monday close, or from DMs later.
- **Upgrade, if spoofing ever matters:** a Cloudflare Worker that verifies `Cf-Access-Jwt-Assertion` and posts to the Form server-side, filling in Name from the verified login. The pool machine stays untouched either way.
- Keep the plain Form link as a fallback for the first cycle.

## Phase 3: PWA
A manifest, icons and a small service worker on the static site. No Web Push is needed, because Slack carries the reminders.

## Later
- **Results on yesterday's thread:** once yesterday's games finish, edit that digest thread reply to add ✅/❌ marks. Needs the channel and `ts` of each post saved (a `posts` table), then `chat.update`, rendering the lines with `report.pick_result`. It could run in `daily` or just before the next digest.
- **Slack DM bot** (Socket Mode, outbound only): pick fixes and submission confirmations by DM, so fixes don't go through the organizer. Needs Slack IDs on the roster.
- **Read-only OpenClaw sidekick:** questions and banter ("what teams do I have left?"), with no write access to anything.
- **hoopstat-haus as the data source:** swap nba_api out once hoopstat-haus publishes upcoming schedules, not just completed games.
- **Roster changes:** members join or leave only at a cycle boundary (the next one is Nov 30).

## Long term: clean-room rebuild
The same architecture, engineered properly with ADRs and specs: the Form backend, a static front end, Slack, and an outbound-only pool machine. It isn't a move to a server-based web stack. The current code is a deliberate first pass for a handful of friends, so keep changes in its style and don't over-engineer it.
