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
