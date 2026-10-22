from datetime import date, datetime
from pathlib import Path

import pytest

from conftest import ET, at, make_season
import store
from season import load_season
from teams import find_teams, resolve_team


@pytest.mark.parametrize("text,code", [
    ("BOS", "BOS"), ("celtics", "BOS"), ("Sixers", "PHI"), ("76ers", "PHI"), ("golden state", "GSW"),
    ("LA Clippers", "LAC"), ("Lakers", "LAL"), ("Timberwovles", "MIN"), ("trail blazers", "POR"),
])
def test_resolve_team(text, code):
    assert resolve_team(text) == code


def test_ambiguous_or_unknown_names_resolve_to_nothing():
    assert resolve_team("Los Angeles") is None
    assert resolve_team("no") is None
    assert resolve_team("xyz") is None


def test_find_teams_prefers_longest_name():
    assert find_teams("Golden State over the Trail Blazers") == ["GSW", "POR"]
    assert find_teams("Lakers vs Nuggets Fri") == ["LAL", "DEN"]


def test_week_and_cycle_math(season):
    assert season.week_for(datetime(2026, 10, 26, 0, 1, tzinfo=ET)) == 1
    assert season.week_for(datetime(2026, 11, 1, 23, 59, tzinfo=ET)) == 1
    assert season.week_for(datetime(2026, 10, 25, 23, 59, tzinfo=ET)) is None
    assert [season.cycle_for(w) for w in range(1, 11)] == [1, 1, 1, 2, 2, 2, None, 3, None, 3]
    assert season.weeks_in_cycle(3) == [8, 10]
    assert season.deadline(1) == datetime(2026, 10, 26, 19, 0, tzinfo=ET)
    assert season.grace_end(1) == datetime(2026, 10, 27, 19, 0, tzinfo=ET)


def test_special_for_matches_local_date(season):
    assert season.special_for(datetime(2026, 12, 25, 22, 0, tzinfo=ET)).points == 2
    assert season.special_for(at(season, 1, 1)) is None


EXAMPLE = Path(__file__).resolve().parent.parent / "season.example.toml"


def test_example_season_file_loads():
    s = load_season(EXAMPLE)
    assert s.week1_start == date(2026, 10, 19) and s.deadline_day == 0 and s.points_per_win == 1
    assert s.week_for(datetime(2026, 10, 20, 19, 30, tzinfo=ET)) == 1  # opening night
    assert s.week_for(datetime(2027, 4, 11, 20, 0, tzinfo=ET)) == 25  # last regular-season day
    week_of = {sp.name: s.week_for(datetime.combine(sp.date, datetime.min.time(), ET)) for sp in s.specials}
    assert s.off_week_label(week_of["NBA Cup Final"]) == "NBA Cup Final week"
    assert s.is_regular(week_of["Christmas Day"])  # Christmas games are bonus picks in a normal week
    assert (s.picks_per_week, s.cycle_weeks, len(s.regular_weeks())) == (5, 6, 24)
    assert [s.weeks_in_cycle(c) for c in (1, 4)] == [[1, 2, 3, 4, 5, 6], [20, 21, 22, 23, 24, 25]]
    assert len(s.members) == 2


def test_season_and_db_paths_come_from_env(tmp_path, monkeypatch):
    f = tmp_path / "s.toml"
    f.write_text('[season]\nname = "Elsewhere"\nweek1_start = 2026-10-26\nweeks = 3\n')
    monkeypatch.setenv("PEASHOOTER_SEASON", str(f))
    assert load_season().name == "Elsewhere"
    monkeypatch.setenv("PEASHOOTER_DB", str(tmp_path / "x" / "p.db"))
    store.Store()
    assert (tmp_path / "x" / "p.db").exists()


def test_changing_a_future_off_week_leaves_earlier_cycles_alone(season):
    later = make_season(off_weeks=((9, "Christmas week"),))  # week 7 un-skipped mid-season
    assert [season.cycle_for(w) for w in range(1, 7)] == [later.cycle_for(w) for w in range(1, 7)]
    assert later.cycle_for(7) == 3


def test_deadline_day_and_time_are_configurable(tmp_path):
    f = tmp_path / "s.toml"
    f.write_text('[season]\nname = "x"\nweek1_start = 2026-10-27\nweeks = 3\n'  # Tuesday-start weeks
                 'deadline_day = "Thursday"\ndeadline_time = "12:30"\npoints_per_win = 2\n')
    s = load_season(f)
    assert s.deadline(1) == datetime(2026, 10, 29, 12, 30, tzinfo=ET)
    assert s.points_per_win == 2


def test_member_lookup_and_unique_names(season, tmp_path):
    assert season.member("alice").name == "Alice" and season.member("U1").name == "Alice"
    assert season.member("U2") is None and season.member("Zed") is None
    f = tmp_path / "s.toml"
    f.write_text('[season]\nname = "x"\nweek1_start = 2026-10-19\nweeks = 3\n'
                 '[[members]]\nname = "TD"\n[[members]]\nname = "td"\n')
    with pytest.raises(ValueError, match="unique"):
        load_season(f)


def test_off_week_out_of_range_rejected(tmp_path):
    f = tmp_path / "s.toml"
    f.write_text('[season]\nname = "x"\nweek1_start = 2026-10-26\nweeks = 3\n[off_weeks]\n5 = "nope"\n')
    with pytest.raises(ValueError, match="outside weeks"):
        load_season(f)
