"""The season's single Google Form: create it, set it up for a week, open or close it.

    uv run --extra google --extra nba google_form.py --week 1    # create the form if needed, set it to week 1, open it
    uv run --extra google google_form.py --close                 # stop accepting responses (the deadline lock)
    uv run --extra google google_form.py --status

Linking the form to a Sheet is one manual click (Responses → Link to Sheets); the Forms API can't do it.
Once linked, this script records the Sheet's ID in .env and sets the Sheet's time zone to the season's.
"""

import argparse
import os
import re
import sys
from datetime import datetime, timezone

import admin
import pool
import report
from env import load_env_file, set_env_value
from season import Season, load_season
from store import Store

NAME, WEEK, PICKS = "Name", "Week", "Picks"


def plain(text: str) -> str:
    """Slack markdown -> plain text for Forms, which shows descriptions verbatim."""
    return re.sub(r"[*_]", "", text)


def description(season: Season, week: int, games: list, now: datetime) -> str:
    return plain(report.schedule_md(season, week, games, now.date())).strip()


def picks_help(season: Season, week: int) -> str:
    if not season.is_regular(week):
        return "Pick the winner of every special game, one team per line. Each game locks at its own tip-off."
    return (f"{season.picks_per_week} picks, one per line. Name the team AND its game, e.g. "
            "\"Celtics vs Knicks\", \"Celtics @ Knicks\" or \"Celtics Tue\". "
            "Games marked 🔒 can't be picked, and teams you've already used this cycle won't count. "
            "Submitting again replaces your earlier picks.")


def _choice(title: str, options: list) -> dict:
    return {"title": title, "questionItem": {"question": {
        "required": True, "choiceQuestion": {"type": "DROP_DOWN", "options": [{"value": o} for o in options]}}}}


def desired_items(season: Season, week: int) -> list:
    return [
        _choice(NAME, sorted((m.name for m in season.members), key=str.casefold)),
        _choice(WEEK, [f"Week {week}"]),
        {"title": PICKS, "description": picks_help(season, week),
         "questionItem": {"question": {"required": True, "textQuestion": {"paragraph": True}}}},
    ]


def week_requests(form: dict, season: Season, week: int, desc: str) -> list:
    """batchUpdate requests that make `form` match `week`: description, then Name / Week / Picks in order."""
    requests = [{"updateFormInfo": {"info": {"description": desc}, "updateMask": "description"}}]
    existing = {item.get("title"): item for item in form.get("items", [])}
    for index, want in enumerate(desired_items(season, week)):
        have = existing.get(want["title"])
        if have is None:
            requests.append({"createItem": {"item": want, "location": {"index": index}}})
            continue
        item = {**want, "itemId": have["itemId"]}
        item["questionItem"]["question"]["questionId"] = have["questionItem"]["question"]["questionId"]
        requests.append({"updateItem": {"item": item, "location": {"index": index},
                                        "updateMask": "title,description,questionItem.question"}})
    return requests


def publish_body(accepting: bool) -> dict:
    return {"publishSettings": {"publishState": {"isPublished": True, "isAcceptingResponses": accepting}},
            "updateMask": "publishState"}


def services():
    from googleapiclient.discovery import build

    from google_auth import load_credentials

    creds = load_credentials()
    return build("forms", "v1", credentials=creds), build("sheets", "v4", credentials=creds)


def ensure_form(forms, season: Season) -> str:
    form_id = os.environ.get("PEASHOOTER_FORM_ID")
    if form_id:
        return form_id
    title = f"{season.name} picks"
    form_id = forms.forms().create(body={"info": {"title": title, "documentTitle": title}}).execute()["formId"]
    set_env_value("PEASHOOTER_FORM_ID", form_id)
    return form_id


def record_linked_sheet(sheets, season: Season, form: dict) -> str:
    sheet_id = form.get("linkedSheetId")
    if not sheet_id:
        return (f"Not linked to a Sheet yet: open https://docs.google.com/forms/d/{form['formId']}/edit → "
                "Responses → Link to Sheets → Create a new spreadsheet, then run --status.")
    if os.environ.get("PEASHOOTER_SHEET_ID") != sheet_id:
        set_env_value("PEASHOOTER_SHEET_ID", sheet_id)
    sheets.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": [{"updateSpreadsheetProperties": {
        "properties": {"timeZone": season.tz.key}, "fields": "timeZone"}}]}).execute()
    return f"Linked Sheet: https://docs.google.com/spreadsheets/d/{sheet_id}/edit (time zone {season.tz.key})"


def status_lines(sheets, season: Season, form: dict) -> list:
    state = form.get("publishSettings", {}).get("publishState", {})
    week_item = next((i for i in form.get("items", []) if i.get("title") == WEEK), None)
    week = (week_item["questionItem"]["question"]["choiceQuestion"]["options"][0]["value"]
            if week_item else "not set up")
    return [
        f"Form: {form['info'].get('title')} · {week} · "
        f"{'OPEN' if state.get('isAcceptingResponses') else 'closed'}",
        f"Responders: {form.get('responderUri')}",
        f"Edit: https://docs.google.com/forms/d/{form['formId']}/edit",
        record_linked_sheet(sheets, season, form),
    ]


def set_up_week(forms, season: Season, store: Store, week: int, now: datetime) -> dict:
    """Point the form at `week` (creating it if needed), open it, and return the updated form."""
    form_id = ensure_form(forms, season)
    form = forms.forms().get(formId=form_id).execute()
    desc = description(season, week, pool.week_games(store, season, week), now)
    forms.forms().batchUpdate(formId=form_id, body={"requests": week_requests(form, season, week, desc)}).execute()
    return set_accepting(forms, form_id, True)


def set_accepting(forms, form_id: str, accepting: bool) -> dict:
    forms.forms().setPublishSettings(formId=form_id, body=publish_body(accepting)).execute()
    return record_form_settings(forms.forms().get(formId=form_id).execute())


def form_settings(form: dict) -> dict:
    """What the pick helper needs, as .env settings: the responder URL, the prefill entry ids (a question id is hex;
    its entry id is the same number in decimal), and the week the form is open for ("" while it's closed)."""
    questions = {i.get("title"): i["questionItem"]["question"] for i in form.get("items", []) if "questionItem" in i}
    out = {"PEASHOOTER_FORM_URL": form.get("responderUri", "")}
    for title in (NAME, WEEK, PICKS):
        if title in questions:
            out[f"PEASHOOTER_FORM_{title.upper()}_ENTRY"] = str(int(questions[title]["questionId"], 16))
    accepting = form.get("publishSettings", {}).get("publishState", {}).get("isAcceptingResponses", False)
    options = questions.get(WEEK, {}).get("choiceQuestion", {}).get("options", [])
    week = options[0]["value"] if options else ""
    out["PEASHOOTER_FORM_WEEK"] = week.removeprefix("Week ") if accepting and week.startswith("Week ") else ""
    return out


def record_form_settings(form: dict) -> dict:
    """Save form_settings to .env, so the pick helper's next build knows them. Returns the form."""
    for key, value in form_settings(form).items():
        if os.environ.get(key) != value:
            set_env_value(key, value)
    return form


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--week", type=int, help="set the form up for this week and open it")
    group.add_argument("--open", action="store_true", help="start accepting responses")
    group.add_argument("--close", action="store_true", help="stop accepting responses")
    group.add_argument("--status", action="store_true")
    parser.add_argument("--no-sync", action="store_true", help="don't refresh games from the schedule source")
    args = parser.parse_args(argv)
    load_env_file()
    try:
        season = load_season()
        forms, sheets = services()
        if args.week:
            store = Store()
            if not args.no_sync:
                from sources import load_source
                admin.refresh(store, season, load_source(), [args.week])
            form = set_up_week(forms, season, store, args.week, datetime.now(timezone.utc).astimezone(season.tz))
        else:
            form_id = os.environ.get("PEASHOOTER_FORM_ID")
            if not form_id:
                raise ValueError("no PEASHOOTER_FORM_ID yet; run with --week N to create the form")
            form = set_accepting(forms, form_id, args.open) if (args.open or args.close) \
                else record_form_settings(forms.forms().get(formId=form_id).execute())
        print("\n".join(status_lines(sheets, season, form)))
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
