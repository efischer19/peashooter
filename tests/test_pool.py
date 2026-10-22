"""Store-backed pool flow, including a simulated multi-week fixture season."""

import json
from datetime import timedelta

import pool
import rules
from conftest import CODES, at, finish, week_schedule
from schedule import FixtureSource, Game


def load_weeks(store, season, *weeks):
    for w in weeks:
        store.upsert_games(week_schedule(season, w))


def picks_for(store, season, week, teams):
    """One pick per team, in that team's first game of the week."""
    games = pool.week_games(store, season, week)
    return [(next(g.id for g in games if t in g.teams), t) for t in teams]


def submit(store, season, member, week, teams):
    return pool.ingest_form(store, season, member, week, picks_for(store, season, week, teams),
                            at(season, week, 0, 12))


def test_fixture_source_round_trip(tmp_path, season):
    games = week_schedule(season, 1)[:3]
    f = tmp_path / "games.json"
    f.write_text(json.dumps([g.to_dict() for g in games]))
    start, end = season.week_bounds(1)
    assert FixtureSource(f).games(start, end) == games
    assert FixtureSource(f).games(end, end + timedelta(days=7)) == []


def test_late_resubmission_and_latest_wins(store, season):
    load_weeks(store, season, 1)
    submit(store, season, "Alice", 1, CODES[:10])
    submit(store, season, "Alice", 1, CODES[10:20])
    assert {p.team for p in store.picks(member="Alice", accepted=True)} == set(CODES[10:20])
    late = pool.ingest_form(store, season, "Alice", 1, picks_for(store, season, 1, CODES[:10]),
                            season.deadline(1) + timedelta(minutes=1))
    assert {d.code for d in late} == {rules.LATE}
    assert pool.open_slots(store, season, "Alice", 1) == 0  # late submissions don't open DM slots


def test_rejected_picks_can_be_replaced_by_dm_during_grace(store, season):
    load_weeks(store, season, 1, 2)
    submit(store, season, "Alice", 1, CODES[:10])
    # Week 2: two picks reuse week-1 teams, so two slots open
    decisions = submit(store, season, "Alice", 2, CODES[:2] + CODES[10:18])
    assert sum(not d.accepted for d in decisions) == 2
    assert pool.open_slots(store, season, "Alice", 2) == 2

    tue_night = at(season, 2, 1, 12)  # Tuesday noon: Tuesday 19:30 games haven't tipped
    out = pool.submit_replacements(store, season, "Alice", 2, picks_for(store, season, 2, [CODES[0], CODES[10], CODES[20]]),
                                   tue_night)
    assert [(d.team, d.accepted, d.code) for d in out] == [
        (CODES[0], False, rules.USED_THIS_CYCLE), (CODES[10], False, rules.USED_THIS_CYCLE), (CODES[20], True, "")]
    assert pool.open_slots(store, season, "Alice", 2) == 1

    after_grace = season.grace_end(2) + timedelta(minutes=1)
    out = pool.submit_replacements(store, season, "Alice", 2, picks_for(store, season, 2, [CODES[21]]), after_grace)
    assert out[0].code == rules.LATE


def test_replacement_cannot_use_tipped_game(store, season):
    load_weeks(store, season, 1)
    monday_night = Game("mon", at(season, 1, 0, 19, 30), "ATL", "MIA")  # tips after the deadline, inside grace
    store.upsert_games([monday_night])
    pool.ingest_form(store, season, "Alice", 1, [("bogus", "BOS")] + picks_for(store, season, 1, CODES[1:10]),
                     at(season, 1, 0, 12))
    assert pool.open_slots(store, season, "Alice", 1) == 1
    out = pool.submit_replacements(store, season, "Alice", 1, [("mon", "ATL")], at(season, 1, 0, 21))
    assert out[0].code == rules.TIPPED
    assert pool.open_slots(store, season, "Alice", 1) == 1  # a rejected replacement doesn't use up the slot


def test_simulated_season_cycles_standings_and_grid(store, season):
    """Three members, weeks 1-4 (cycle 1 plus the start of cycle 2)."""
    load_weeks(store, season, 1, 2, 3, 4)
    for week, chunk in ((1, CODES[:10]), (2, CODES[10:20]), (3, CODES[20:])):
        assert all(d.accepted for d in submit(store, season, "Alice", week, chunk))
        assert all(d.accepted for d in submit(store, season, "Bob", week, chunk[:5]))  # Bob only ever picks 5
    # Cat repeats a team inside cycle 1
    submit(store, season, "Cat", 1, CODES[:10])
    assert sum(d.accepted for d in submit(store, season, "Cat", 2, CODES[5:15])) == 5

    assert pool.remaining_teams(store, season, "Alice", 3) == []
    assert pool.remaining_teams(store, season, "Bob", 3) == sorted(set(CODES) - set(CODES[:5] + CODES[10:15] + CODES[20:25]))
    # New cycle: everything is legal again
    assert all(d.accepted for d in submit(store, season, "Alice", 4, CODES[:10]))
    assert len(pool.form_options(store, season, "Alice", 4)) == 3 * 30 - 3 * 10 + 30  # unused teams, plus this week's own picks

    grid = pool.cycle_grid(store, season, 1)
    assert grid["Alice"] == {**{t: 1 for t in CODES[:10]}, **{t: 2 for t in CODES[10:20]}, **{t: 3 for t in CODES[20:]}}

    # Nothing final yet: all pending
    assert all(r["points"] == 0 for r in pool.standings(store, season))
    # Finish weeks 1-3. Home teams (CODES[15:]) always win.
    for w in (1, 2, 3):
        store.upsert_games(finish(week_schedule(season, w)))
    table = {r["member"]: r for r in pool.standings(store, season)}
    assert table["Alice"]["points"] == 15  # CODES[15:20] in week 2 + CODES[20:] in week 3
    assert table["Bob"]["points"] == 5  # only CODES[20:25] (week 3) were home teams
    assert table["Cat"]["points"] == 0  # all away teams
    assert table["Alice"]["pending"] == 10  # week 4 not final
    assert table["Alice"]["rank"] == 1
