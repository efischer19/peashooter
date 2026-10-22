"""The public scoreboard page: aliases only, picks only once they lock. No network."""

import admin
import rules
import scoreboard
from conftest import at, finish, make_season, week_schedule
from season import Member


def pick(store, season, member, week, game_id, team):
    store.add_picks(member, week, "regular", "form", [rules.Decision(game_id, team, True)], at(season, week, 0, 12))


def test_page_uses_aliases_never_roster_names(store):
    season = make_season(members=(Member("Alice", alias="Ace"), Member("Bob")))
    games = week_schedule(season, 1)
    store.upsert_games(finish(games[:15]) + games[15:])
    pick(store, season, "Alice", 1, games[0].id, games[0].home)
    pick(store, season, "Bob", 1, games[0].id, games[0].away)
    html = admin.site(season, store, at(season, 1, 2, 9, 30))

    assert "Ace" in html and "Shooter 2" in html
    assert "Alice" not in html and "Bob" not in html
    assert '<b class="who">Ace</b> ✅' in html and '<b class="who">Shooter 2</b> ❌' in html


def test_standings_skip_members_who_never_picked(store):
    season = make_season(members=(Member("Alice", alias="Ace"), Member("Bob", alias="Bee")))
    games = week_schedule(season, 1)
    store.upsert_games(finish(games[:15]) + games[15:])
    pick(store, season, "Alice", 1, games[0].id, games[0].home)
    html = admin.site(season, store, at(season, 1, 2, 9, 30))

    assert '<td class="name">Ace</td>' in html and "Bee" not in html


def test_only_yesterday_and_today_start_expanded(store, season):
    store.upsert_games(week_schedule(season, 1))  # Tue, Thu, Sat
    html = admin.site(season, store, at(season, 1, 3, 9))  # Thursday

    assert '<details class="day" open><summary>Tuesday' not in html
    assert '<details class="day" open><summary>Thursday, Oct 29 <span class="today">' in html
    assert '<details class="day"><summary>Saturday' in html


def test_picks_hidden_until_the_deadline(store):
    season = make_season(members=(Member("Alice", alias="Ace"),))
    games = week_schedule(season, 1)
    store.upsert_games(games)
    pick(store, season, "Alice", 1, games[0].id, games[0].home)

    before = admin.site(season, store, at(season, 1, 0, 12))
    assert "Ace" not in before and "picks lock Mon" in before
    assert "Ace" in admin.site(season, store, at(season, 1, 1, 9))


def test_watch_link_only_for_real_nba_ids():
    from conftest import ET
    from datetime import datetime
    from schedule import Game
    tip = datetime(2026, 10, 21, 20, tzinfo=ET)
    link = scoreboard.watch_html(Game("0022600090", tip, "IND", "NOP"))
    assert 'href="https://www.nba.com/game/ind-vs-nop-0022600090"' in link and 'target="_blank"' in link
    assert scoreboard.watch_html(Game("w1d1g0", tip, "IND", "NOP")) == ""
