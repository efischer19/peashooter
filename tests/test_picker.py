"""The pick helper page: legal picks per shooter (aliases only), copy-text only for now. No network."""

import json
import re
from datetime import date

import admin
import picker
import report
import rules
from conftest import at, make_season, week_schedule
from season import Member, Special


def pick(store, season, member, week, game_id, team):
    store.add_picks(member, week, "regular", "form", [rules.Decision(game_id, team, True)], at(season, week, 0, 12))


def page_data(html: str) -> dict:
    return json.loads(re.search(r"const DATA = (\{.*?\});\n", html).group(1).replace("<\\/", "</"))


def test_pick_text_names_the_opponent_and_day(season):
    g = week_schedule(season, 1)[0]  # a Tuesday game
    assert picker.pick_text(season, g, g.away) == f"{report.nickname(g.away)} @ {report.nickname(g.home)} Tue"
    assert picker.pick_text(season, g, g.home) == f"{report.nickname(g.home)} vs {report.nickname(g.away)} Tue"


def test_weeks_offered_follow_the_deadline_and_skip_off_weeks(season):
    assert picker.picker_weeks(season, at(season, 1, 0, 12)) == [1, 2]  # Monday noon: week 1 is still open
    assert picker.picker_weeks(season, at(season, 1, 0, 19)) == [2, 3]  # after the 6:45pm lock
    assert picker.picker_weeks(season, at(season, 6, 0, 19)) == [8, 10]  # weeks 7 and 9 are off
    assert picker.picker_weeks(season, at(season, 10, 0, 19)) == []


def test_used_teams_are_not_legal_for_that_shooter(store):
    season = make_season(members=(Member("Alice", alias="Ace"), Member("Bob")))
    store.upsert_games(week_schedule(season, 1) + week_schedule(season, 2))
    first = week_schedule(season, 1)[0]
    pick(store, season, "Alice", 1, first.id, first.home)
    data = picker.week_data(season, store, 2)
    ace, bob = data["shooters"]["Ace"], data["shooters"]["Shooter 2"]
    assert ace["used"] == {first.home: 1} and bob["used"] == {}
    assert not any(x.endswith(f"|{first.home}") for x in ace["legal"])
    assert any(x.endswith(f"|{first.home}") for x in bob["legal"])
    assert data["deadlineAt"] == season.deadline(2).isoformat()


def test_special_games_are_left_out(store):
    season = make_season(specials=(Special("Bonus", date(2026, 10, 29), 2),))  # week 1's Thursday
    store.upsert_games(week_schedule(season, 1))
    days = {g["day"] for g in picker.week_data(season, store, 1)["games"]}
    assert days == {"Tuesday, Oct 27", "Saturday, Oct 31"}


def test_page_shows_aliases_only_and_links_no_form(store, monkeypatch):
    monkeypatch.setenv("PEASHOOTER_SITE_URL", "https://example.com/peashooter/")
    season = make_season(members=(Member("Alice", alias="Ace"), Member("Bob")))
    store.upsert_games(week_schedule(season, 1) + week_schedule(season, 2))
    html = admin.picker(season, store, at(season, 1, 0, 12))
    data = page_data(html)
    assert [w["week"] for w in data["weeks"]] == [1, 2]
    assert list(data["weeks"][0]["shooters"]) == ["Ace", "Shooter 2"]
    assert "Alice" not in html and "Bob" not in html
    assert data["formUrl"] == "" and "docs.google.com" not in html
    assert '<a href="https://example.com/peashooter/">Scoreboard</a>' in html


def test_scoreboard_links_the_pick_helper(store, season, monkeypatch):
    store.upsert_games(week_schedule(season, 1))
    assert "Make picks" not in admin.site(season, store, at(season, 1, 2, 9))
    monkeypatch.setenv("PEASHOOTER_SITE_URL", "https://example.com/peashooter/")
    assert '<a href="https://example.com/peashooter/picks">Make picks</a>' in admin.site(season, store, at(season, 1, 2, 9))


def test_every_pick_text_parses_back_to_its_game(store, season):
    games = week_schedule(season, 1)
    for g in games:
        for team in g.teams:
            parsed = rules.parse_picks(picker.pick_text(season, g, team), games, after=season.deadline(1), tz=season.tz)
            assert [(p.game_id, p.team) for p in parsed] == [(g.id, team)]


FORM_ENV = {"PEASHOOTER_FORM_URL": "https://docs.google.com/forms/d/e/x/viewform", "PEASHOOTER_FORM_NAME_ENTRY": "11",
            "PEASHOOTER_FORM_WEEK_ENTRY": "22", "PEASHOOTER_FORM_PICKS_ENTRY": "33", "PEASHOOTER_FORM_WEEK": "1"}


def test_form_stays_off_the_page_until_switched_on(store, monkeypatch):
    season = make_season(members=(Member("Alice", "U123", alias="Ace"), Member("Bob")))
    store.upsert_games(week_schedule(season, 1))
    for key, value in FORM_ENV.items():
        monkeypatch.setenv(key, value)
    html = admin.picker(season, store, at(season, 1, 0, 12))
    assert "docs.google.com" not in html and "Alice" not in html and page_data(html)["roster"] == {}

    monkeypatch.setenv("PEASHOOTER_PICKER_FORM", "1")
    html = admin.picker(season, store, at(season, 1, 0, 12))
    data = page_data(html)
    assert data["formUrl"] == FORM_ENV["PEASHOOTER_FORM_URL"] and data["formWeek"] == 1
    assert data["entries"] == {"name": "11", "week": "22", "picks": "33"}
    assert data["roster"] == {"Ace": {"name": "Alice", "who": picker.who_hash("U123")},
                              "Shooter 2": {"name": "Bob", "who": ""}}
    assert "U123" not in html  # recognised by hash only

    monkeypatch.setenv("PEASHOOTER_FORM_WEEK", "")  # closed
    assert page_data(admin.picker(season, store, at(season, 1, 0, 12)))["formWeek"] is None
    monkeypatch.setenv("PEASHOOTER_FORM_PICKS_ENTRY", "")
    try:
        admin.picker(season, store, at(season, 1, 0, 12))
        raise AssertionError("expected a missing-entry error")
    except ValueError as e:
        assert "google_form.py --status" in str(e)
