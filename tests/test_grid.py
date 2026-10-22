"""Tracker grid: cell states and the Sheets layout. Offline."""

from dataclasses import replace
from datetime import datetime, timedelta

import grid as g
import google_sheet
import pool
import report
import rules
from conftest import CODES, ET, at, finish, week_schedule
from schedule import AWAY, FINAL, HOME, NATIONAL, Broadcast, Game
from teams import team_name


def tue(store, season, week, teams):
    games = pool.week_games(store, season, week)
    return [(next(x.id for x in games if t in x.teams and x.tip.astimezone(ET).weekday() == 1), t) for t in teams]


def cell(grid, team, member, nth=0):
    rows = [r for r in grid.rows if r.team == team]
    return rows[nth].cells[grid.members.index(member)]


def build(store, season, week, now):
    return g.build_week_grid(season, week, pool.week_games(store, season, week), store.picks(), now)


def test_before_the_deadline_only_availability_shows(store, season):
    store.upsert_games(week_schedule(season, 1) + [Game("mon", at(season, 1, 0, 18), "BOS", "MIA")])
    pool.ingest_form(store, season, "Alice", 1, tue(store, season, 1, CODES[:10]), at(season, 1, 0, 12))
    grid = build(store, season, 1, at(season, 1, 0, 12))
    assert not grid.revealed and grid.members == ["Alice", "Bob", "Cat"]
    assert len(grid.rows) == 3 * 30 + 2  # every team plays 3 games; the Monday game adds a row each for BOS and MIA
    assert [r.team for r in grid.rows[:3]] == ["ATL"] * 3  # Atlanta sorts first by full name
    assert cell(grid, "ATL", "Alice").state == g.OPEN  # Alice's pick stays hidden until the deadline
    bos = [r for r in grid.rows if r.team == "BOS"]
    assert bos[0].game_text.endswith("🔒") and {c.state for c in bos[0].cells} == {g.LOCKED}
    assert grid.summary[0] == ("Picks counted", ["", "", ""]) and grid.summary[2][1] == ["30", "30", "30"]


def test_reveal_shows_picks_early_with_a_preview_label(store, season):
    store.upsert_games(week_schedule(season, 1))
    pool.ingest_form(store, season, "Alice", 1, tue(store, season, 1, ["ATL"]), at(season, 1, 0, 12))
    grid = g.build_week_grid(season, 1, pool.week_games(store, season, 1), store.picks(), at(season, 1, 0, 13),
                             reveal=True)
    assert cell(grid, "ATL", "Alice").state == g.PENDING and "PREVIEW" in grid.subtitle


def test_after_the_deadline_picks_used_and_taken(store, season):
    store.upsert_games(week_schedule(season, 1) + week_schedule(season, 2))
    pool.ingest_form(store, season, "Alice", 1, tue(store, season, 1, CODES[:10]), at(season, 1, 0, 12))
    pool.ingest_form(store, season, "Alice", 2, tue(store, season, 2, CODES[10:20]), at(season, 2, 0, 12))
    pool.ingest_form(store, season, "Bob", 2, [("nope", "ATL")] + tue(store, season, 2, CODES[10:11]),
                     at(season, 2, 0, 12))
    grid = build(store, season, 2, at(season, 2, 0, 20))
    assert grid.revealed
    assert cell(grid, "ATL", "Alice") == g.Cell(g.USED, "wk 1", "Used in week 1")
    hou = CODES[10]
    assert cell(grid, hou, "Alice").state == g.PENDING  # Tuesday game
    assert cell(grid, hou, "Alice", nth=1) == g.Cell(g.TAKEN, "", "Picked in another game this week")
    assert cell(grid, hou, "Bob").state == g.PENDING and cell(grid, "ATL", "Bob").state == g.OPEN
    assert dict(grid.summary)["Picks counted"] == ["10/10", "1/10", "0/10"]
    assert dict(grid.summary)["Teams left in cycle"] == ["10", "29", "30"]

    store.upsert_games(finish(week_schedule(season, 2)))  # home teams (CODES[15:]) win
    grid = build(store, season, 2, at(season, 3, 0))
    assert cell(grid, hou, "Alice").state == g.LOSS and cell(grid, CODES[15], "Alice").state == g.WIN
    assert dict(grid.summary)["Points this week"][0] == "5"


def test_earlier_week_greys_out_only_once_it_is_locked(store, season):
    store.upsert_games(week_schedule(season, 1) + week_schedule(season, 2))
    pool.ingest_form(store, season, "Alice", 1, tue(store, season, 1, ["ATL"]), at(season, 1, 0, 12))
    before_lock = build(store, season, 2, at(season, 1, 0, 13))  # a Week 2 tab built before week 1 locks
    assert cell(before_lock, "ATL", "Alice").state == g.OPEN
    assert cell(build(store, season, 2, at(season, 1, 0, 20)), "ATL", "Alice").state == g.USED
    revealed = g.build_week_grid(season, 2, pool.week_games(store, season, 2), store.picks(),
                                 at(season, 1, 0, 13), reveal=True)
    assert cell(revealed, "ATL", "Alice").state == g.USED


def test_dropped_picks_and_teams_without_games(store, season):
    games = [x for x in week_schedule(season, 1) if "ATL" not in x.teams]
    store.upsert_games(games)
    pool.ingest_form(store, season, "Cat", 1, tue(store, season, 1, [CODES[1]]) * 2, at(season, 1, 0, 12))
    grid = build(store, season, 1, at(season, 1, 0, 20))
    atl = [r for r in grid.rows if r.team == "ATL"]
    assert len(atl) == 1 and atl[0].game is None and atl[0].game_text == "no games this week"
    assert {c.state for c in atl[0].cells} == {g.NO_GAME}
    assert cell(grid, CODES[1], "Cat").state == g.PENDING  # the duplicate of the same pick doesn't hide it


def test_dropped_pick_cell(store, season):
    store.upsert_games(week_schedule(season, 1) + week_schedule(season, 2))
    pool.ingest_form(store, season, "Cat", 1, tue(store, season, 1, ["ATL"]), at(season, 1, 0, 12))
    pool.ingest_form(store, season, "Cat", 2, tue(store, season, 2, ["ATL"]), at(season, 2, 0, 12))
    grid = build(store, season, 2, at(season, 2, 0, 20))
    assert cell(grid, "ATL", "Cat") == g.Cell(g.DROPPED, "✗", "Didn't count: ATL was already used this cycle")


def test_special_week_shows_each_pick_once_its_game_tips(store, season):
    xmas = [Game("x1", datetime(2026, 12, 25, 12, tzinfo=ET), "SAS", "NYK"),
            Game("x2", datetime(2026, 12, 25, 20, tzinfo=ET), "OKC", "MIN")]
    store.upsert_games(xmas)
    pool.submit_specials(store, season, "Alice", [("x1", "SAS"), ("x2", "MIN")], datetime(2026, 12, 24, tzinfo=ET))
    grid = build(store, season, 9, datetime(2026, 12, 25, 13, tzinfo=ET))
    assert sorted({r.team for r in grid.rows}) == ["MIN", "NYK", "OKC", "SAS"] and grid.summary == []
    assert cell(grid, "SAS", "Alice").state == g.PENDING  # tipped: visible
    assert cell(grid, "MIN", "Alice").state == g.OPEN  # not yet tipped: hidden
    assert "⭐2" in grid.rows[0].game_text


def test_sheet_layout(store, season):
    store.upsert_games(week_schedule(season, 1))
    grid = build(store, season, 1, at(season, 1, 0, 12))
    rows = google_sheet.grid_rows(grid)
    assert len(rows) == 1 + 90 + 1 + 3
    assert [c["userEnteredValue"]["stringValue"] for c in rows[0]["values"][2:]] == ["Alice", "Bob", "Cat", "Watch"]
    assert rows[1]["values"][0]["userEnteredValue"]["stringValue"] == team_name("ATL")
    assert rows[2]["values"][0]["userEnteredValue"]["stringValue"] == ""  # merged into the cell above
    merges = google_sheet.merge_ranges(grid, 7)
    assert len(merges) == 30 and merges[0] == {"sheetId": 7, "startRowIndex": 1, "endRowIndex": 4,
                                               "startColumnIndex": 0, "endColumnIndex": 1}
    reqs = google_sheet.tab_requests(grid, 7)
    props = reqs[2]["updateSheetProperties"]["properties"]
    assert props["index"] == 0 and props["gridProperties"]["frozenColumnCount"] == 2
    assert google_sheet.rgb("#ffffff") == {"red": 1.0, "green": 1.0, "blue": 1.0}


def test_status_tab_formulas():
    headers = ["Timestamp", "Name", "Week", "Picks"]
    rows = google_sheet.status_rows("Form Responses 1", headers, 3, ["Alice", "Bob"],
                                    datetime(2026, 11, 9, 18, 45), "Picks lock Mon")
    assert rows[0]["values"][0]["userEnteredValue"]["stringValue"] == "Week 3: who's in"
    status = rows[2]["values"][1]["userEnteredValue"]["formulaValue"]
    assert status == ("=IF(COUNTIFS('Form Responses 1'!$B:$B,$A3,'Form Responses 1'!$C:$C,\"Week 3\","
                      "'Form Responses 1'!$A:$A,\"<=\"&DATE(2026,11,9)+TIME(18,45,0))>0,\"✅ In\","
                      "IF(COUNTIFS('Form Responses 1'!$B:$B,$A3,'Form Responses 1'!$C:$C,\"Week 3\")>0,"
                      "\"⚠️ Late\",\"—\"))")
    assert rows[3]["values"][0]["userEnteredValue"]["stringValue"] == "Bob"
    assert "MAXIFS('Form Responses 1'!$A:$A" in rows[3]["values"][2]["userEnteredValue"]["formulaValue"]
    assert rows[-1]["values"][1]["userEnteredValue"]["formulaValue"] == '=COUNTIF(B3:B4,"✅ In")&" of 2 in"'
    special = google_sheet.status_rows("Form Responses 1", headers, 7, ["Alice"], None, "Cup week")
    assert "Late" not in special[2]["values"][1]["userEnteredValue"]["formulaValue"]
    assert google_sheet._column_letter(0) == "A" and google_sheet._column_letter(27) == "AB"


def test_grid_text_preview(store, season):
    store.upsert_games(week_schedule(season, 1))
    text = g.grid_text(build(store, season, 1, at(season, 1, 0, 12)))
    assert text.startswith("Week 1 · Mon Oct 26 – Sun Nov 1 · cycle 1")
    assert "Atlanta Hawks" in text and "Teams left in cycle" in text


def test_sheet_hides_members_who_never_picked(store, season):
    games = week_schedule(season, 1)
    store.upsert_games(games)
    assert build(store, season, 1, at(season, 1, 2, 9)).idle == {"Alice", "Bob", "Cat"}
    store.add_picks("Bob", 1, "regular", "form", [rules.Decision(games[0].id, games[0].home, True)],
                    at(season, 1, 0, 12))
    grid = build(store, season, 1, at(season, 1, 2, 9))
    assert grid.idle == {"Alice", "Cat"}
    widths = [r["updateDimensionProperties"] for r in google_sheet.tab_requests(grid, 7)
              if "updateDimensionProperties" in r]
    assert [w["properties"]["hiddenByUser"] for w in widths] == [False, False, True, False, True, False]


def test_watch_cell_feeds_before_the_game_and_highlights_after():
    tip = datetime(2026, 10, 21, 23, 30, tzinfo=ET)
    espn = Broadcast(NATIONAL, "ESPN", "https://espn.smart.link/x")
    upcoming = Game("0022600020", tip, "IND", "NOP", broadcasts=(
        espn, Broadcast(AWAY, "DAZN-IND", "https://dazn.com/ind"), Broadcast(HOME, "GCSEN / WVUE")))
    cell = google_sheet.watch_cell(report.watch_links(upcoming, "NOP"))
    assert cell["userEnteredValue"]["stringValue"] == "NBA.com · ESPN · GCSEN / WVUE"
    runs = cell["textFormatRuns"]
    assert [r["startIndex"] for r in runs] == [0, 7, 10, 14, 17]
    assert runs[0]["format"]["link"]["uri"] == report.nba_url(upcoming)
    assert runs[2]["format"]["link"]["uri"] == "https://espn.smart.link/x" and runs[4]["format"] == {}
    assert "DAZN-IND" in google_sheet.watch_cell(report.watch_links(upcoming, "IND"))["userEnteredValue"]["stringValue"]

    final = replace(upcoming, status=FINAL, away_score=1, home_score=2)
    assert report.watch_links(final, "NOP") == [("NBA.com", report.nba_url(final))]
    video = replace(final, highlights="https://www.youtube.com/watch?v=abc")
    cell = google_sheet.watch_cell(report.watch_links(video, "NOP"))
    assert cell["userEnteredValue"]["stringValue"] == "▶ Highlights"
    assert cell["textFormatRuns"][0]["format"]["link"]["uri"] == "https://www.youtube.com/watch?v=abc"
    assert google_sheet.watch_cell([]) == google_sheet._cell("")  # synthetic test games have no NBA id
