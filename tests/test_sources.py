"""nba_api row parsing, source selection and the sync script. No network: rows are canned."""

from datetime import datetime, timezone

import pytest

import sources
import sync
from conftest import make_season
from schedule import FINAL, POSTPONED, SCHEDULED, FixtureSource
from store import Store


def row(game_id="0022600129", when="2026-10-28T00:00:00Z", away="DET", home="NYK", status=1, text="8:00 pm ET",
        away_score=0, home_score=0, postponed="N"):
    return {"gameId": game_id, "gameDateTimeUTC": when, "awayTeam_teamTricode": away, "homeTeam_teamTricode": home,
            "gameStatus": status, "gameStatusText": text, "awayTeam_score": away_score, "homeTeam_score": home_score,
            "postponedStatus": postponed}


def test_scheduled_row():
    g = sources.game_from_nba_row(row())
    assert (g.id, g.away, g.home, g.status, g.away_score) == ("0022600129", "DET", "NYK", SCHEDULED, None)
    assert g.tip == datetime(2026, 10, 28, 0, 0, tzinfo=timezone.utc)


def test_final_and_postponed_rows():
    g = sources.game_from_nba_row(row(status=3, text="Final", away_score=101, home_score=99))
    assert g.status == FINAL and g.winner == "DET"
    assert sources.game_from_nba_row(row(postponed="Y")).status == POSTPONED
    assert sources.game_from_nba_row(row(text="PPD")).status == POSTPONED


def test_skips_preseason_and_tbd_matchups_keeps_cup_final():
    assert sources.game_from_nba_row(row(game_id="0012600009")) is None  # preseason
    assert sources.game_from_nba_row(row(away=None, home=None)) is None  # Cup knockout before teams are set
    assert sources.game_from_nba_row(row(game_id="0062600001")).id == "0062600001"  # Cup Final


class FakeNbaSource(sources.NbaApiSource):
    def __init__(self, rows):
        super().__init__("2026-27")
        self._rows = rows

    def rows(self):
        return self._rows


def test_nba_source_filters_window():
    src = FakeNbaSource([row(game_id="0022600002", when="2026-11-05T00:00:00Z"), row(),
                         row(game_id="0012600001")])
    games = src.games(datetime(2026, 10, 27, tzinfo=timezone.utc), datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert [g.id for g in games] == ["0022600129"]


def test_load_source(tmp_path):
    f = tmp_path / "s.toml"
    f.write_text('[source]\nkind = "nba_api"\nnba_season = "2026-27"\n')
    assert sources.load_source(f).season == "2026-27"
    f.write_text('[source]\nkind = "fixture"\npath = "games.json"\n')
    assert isinstance(sources.load_source(f), FixtureSource)
    f.write_text('[source]\nkind = "espn"\n')
    with pytest.raises(ValueError, match="unknown"):
        sources.load_source(f)


def test_sync_reports_newly_final_games_once():
    season, store = make_season(), Store(":memory:")
    now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
    pending = FakeNbaSource([row()])
    final = FakeNbaSource([row(status=3, text="Final", away_score=101, home_score=99)])
    assert "Synced 1 games" in sync.run(season, pending, store, now) and "0 newly final" in sync.run(season, pending, store, now)
    out = sync.run(season, final, store, now)
    assert "1 newly final" in out and "DET 101, NYK 99" in out
    assert "0 newly final" in sync.run(season, final, store, now)
