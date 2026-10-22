# PEAshooter privacy policy

PEAshooter is a self-hosted tool that a league organizer runs for their own NBA pick 'em pool. There is no central PEAshooter service: each copy runs on the organizer's own computer, under their own accounts.

## What it handles
- **League members:** display names and Slack user IDs that the organizer lists in their config file.
- **Picks:** what each member submits through the organizer's Google Form, with timestamps.
- **NBA schedules and scores:** public data from stats.nba.com.

## Public scoreboard (optional)
If the organizer publishes the scoreboard page, it shows standings, games and picks (only once they lock) under each member's alias from the config, never their name. It has no forms, cookies, analytics or links to the Sheet.

## Third-party data PEAshooter reads
Schedules, scores and broadcaster listings come from stats.nba.com. If configured, PEAshooter also reads a public YouTube playlist page to link full-game highlights. Neither request carries anything about league members.

## Google data
PEAshooter signs in to Google as the organizer and asks for two permissions:
- **Google Sheets:** to read the league's form responses and write pick, results and standings tabs to the league's spreadsheet.
- **Google Forms:** to update the league's weekly picks question and open or close the form.

It reads and writes only the Sheet and Form whose IDs the organizer configures. It does not access other files, email, contacts or anything else in the Google account. Google sign-in tokens stay on the organizer's machine.

## Sharing
Data never leaves the organizer's own Google account, Slack workspace and machine. PEAshooter has no analytics, no ads and no third-party data sharing, and nothing is sold. League data is visible to whoever the organizer shares the Sheet or Slack channel with.

## Removing data
Members can ask the organizer to delete their picks from the Sheet and local database. The organizer can revoke PEAshooter's Google access at any time at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).

## Contact
Questions or issues: [github.com/efischer19/peashooter/issues](https://github.com/efischer19/peashooter/issues)
