"""Manual-mode CLI: CSV ingest, replacements, reports. Synthetic schedule; no network."""

from datetime import datetime

import admin
import pool
import rules
from conftest import CODES, ET, at, finish, make_season, week_schedule
from schedule import Game
from season import Member
from store import Store

HEADER = "Timestamp,Your name,Week,Your 10 picks (one per line)\n"


def tue_pick(i: int) -> str:
    """Team CODES[i] (i < 15) in its Tuesday game, written the way a person would."""
    return f"{CODES[i]} vs {CODES[15 + i]}"


def csv_row(when: datetime, name: str, week: str, picks: list) -> str:
    body = "\n".join(picks).replace('"', '""')
    return f'{when:%m/%d/%Y %H:%M:%S},{name},{week},"{body}"\n'


def setup(tmp_path, rows):
    season = make_season(members=(Member("Alice"), Member("Bob"), Member("Cat"), Member("Dan")))
    store = Store(":memory:")
    store.upsert_games(week_schedule(season, 1) + [Game("mon", at(season, 1, 0, 18, 0), "BOS", "MIA")])
    f = tmp_path / "responses.csv"
    f.write_text(HEADER + "".join(rows))
    return season, store, admin.read_responses(f, season)


def test_read_responses_handles_google_export(tmp_path):
    season, _, responses = setup(tmp_path, [csv_row(at(make_season(), 1, 0, 12), "Alice", "Week 1",
                                                    [tue_pick(0), tue_pick(1)])])
    r = responses[0]
    assert (r.name, r.week, r.row) == ("Alice", 1, 2)
    assert r.submitted_at == datetime(2026, 10, 26, 12, 30, tzinfo=ET)
    assert r.picks.splitlines() == [tue_pick(0), tue_pick(1)]


def test_ingest_week(tmp_path):
    s = make_season()
    noon, late = at(s, 1, 0, 12), at(s, 1, 0, 19, 30)
    rows = [
        csv_row(noon, "Alice", "Week 1", [tue_pick(i) for i in range(10)]),
        csv_row(noon, "bob", "Week 1", [tue_pick(i) for i in range(9)] + ["Warriors"]),  # which game?
        csv_row(noon, "Cat", "Week 1", [tue_pick(i) for i in range(10)]),
        csv_row(late, "Cat", "Week 1", [tue_pick(i) for i in range(5, 15)]),  # after the deadline: ignored
        csv_row(noon, "Zed", "Week 1", [tue_pick(0)]),
        csv_row(noon, "Alice", "Week 2", [tue_pick(0)]),  # other week: ignored
    ]
    season, store, responses = setup(tmp_path, rows)
    text = admin.ingest(season, store, responses, 1)

    assert "picks are in* (3/4)" in text
    assert "✅ All 10 good: Alice, Cat" in text
    assert "*Bob*: 9/10 picks count" in text and '"Warriors": GSW has 3 games left' in text
    assert "Dan" not in text
    assert "after the deadline (not counted): Cat" in text
    assert "Zed (row 6)" in text
    assert {p.team for p in store.picks(member="Cat", accepted=True)} == set(CODES[:10])
    assert pool.open_slots(store, season, "Bob", 1) == 1

    # Bob fixes it by DM on Tuesday morning; a second replacement has no slot left
    out = admin.replace(season, store, 1, "Bob", f"Warriors tue, {tue_pick(10)}", at(season, 1, 1, 9))
    assert out.startswith(f"✅ Warriors (Tue @ {CODES[24]})")
    assert "over the weekly pick limit" in out and out.endswith("Open slots left: 0\n")

    # Re-running the same CSV is safe: the same picks, no duplicates
    admin.ingest(season, store, responses, 1)
    assert len(store.picks(member="Alice", accepted=True)) == 10


def test_unparseable_and_tipped_picks(tmp_path):
    s = make_season()
    rows = [csv_row(at(s, 1, 0, 12), "Alice", "1", ["Celtics vs Heat", "the purple team", tue_pick(1)])]
    season, store, responses = setup(tmp_path, rows)
    text = admin.ingest(season, store, responses, 1)
    assert "no upcoming BOS game matches that" in text  # the Monday 6pm game tips before the deadline
    assert "couldn't find a team" in text
    assert "*Alice*: 1/10 picks count" in text


def test_reports_after_games_finish(tmp_path):
    s = make_season()
    season, store, responses = setup(tmp_path, [csv_row(at(s, 1, 0, 12), "Alice", "1",
                                                        [tue_pick(i) for i in range(10)])])
    admin.ingest(season, store, responses, 1)
    store.upsert_games(finish(week_schedule(season, 1)))  # home teams win, so Alice's away picks all lose
    sheet = admin.picks(season, store, 1)
    assert "*Alice* (0 pts)" in sheet and f"❌ Hawks (Tue @ {CODES[15]})" in sheet and "*Bob*: no picks" in sheet
    table = admin.standings(season, store, at(season, 2, 0))
    assert "🥇 *Bob*: 0 pts (0–0)" in table and "*Alice*: 0 pts (0–10)" in table
    left = admin.remaining(season, store, 2)
    assert "*Alice* (20):" in left and "ATL" not in left.split("*Alice* (20):")[1].splitlines()[0]
    assert "*Bob* (30):" in left


def test_schedule_md(tmp_path):
    season, store, _ = setup(tmp_path, [])
    text = admin.schedule_md(season, store, [1], at(season, 1, 0))
    assert "Picks due *Mon Oct 26, 7 pm ET*" in text and "46 games" in text
    assert "• 6 pm · Celtics @ Heat 🔒" in text
    files = admin.schedule_md(season, store, [1, 2], at(season, 1, 0), out=tmp_path / "out")
    assert (tmp_path / "out" / "week1.md").exists() and "week2.md" in files


def test_special_week_ingest(tmp_path):
    s = make_season()
    xmas = [Game("x1", datetime(2026, 12, 25, 12, tzinfo=ET), "SAS", "NYK"),
            Game("x2", datetime(2026, 12, 25, 20, tzinfo=ET), "OKC", "MIN")]
    season, store, _ = setup(tmp_path, [])
    store.upsert_games(xmas)
    f = tmp_path / "x.csv"
    f.write_text(HEADER + csv_row(datetime(2026, 12, 24, 9, tzinfo=ET), "Alice", "9", ["Spurs", "Thunder"])
                 + csv_row(datetime(2026, 12, 25, 13, tzinfo=ET), "Alice", "9", ["Knicks", "Wolves"]))
    text = admin.ingest(season, store, admin.read_responses(f, season), 9)
    # The change to Knicks came after that game tipped, so Spurs stands; Wolves replaces Thunder
    assert {p.team for p in store.picks(member="Alice", kind="special", accepted=True)} == {"SAS", "MIN"}
    assert "had already tipped" in text
    assert rules.TIPPED


def test_responses_from_sheet_rows():
    season = make_season()
    headers = ["Timestamp", "Name", "Week", "Picks"]
    rows = [["10/13/2026 9:59:17", "Alice", "Week 1", "celtics, BOS @ DET\nwiz"], ["10/13/2026 10:00:00", "Bob"], []]
    out = admin.responses_from_rows(headers, rows, season)
    assert [(r.row, r.name, r.week) for r in out] == [(2, "Alice", 1), (3, "Bob", None)]
    assert out[0].submitted_at == datetime(2026, 10, 13, 9, 59, 17, tzinfo=ET) and out[1].picks == ""


def test_tab_plan_shows_the_cycle_and_hides_older_tabs():
    season = make_season(cycle_weeks=6, weeks=20, off_weeks=((8, "Cup Final week"),))
    assert admin.tab_plan(season, 1, []) == ([1, 2, 3, 4, 5, 6], [])
    assert admin.tab_plan(season, 3, [1, 2, 3, 4, 5, 6]) == ([3, 1, 2, 4, 5, 6], [])
    # New cycle (weeks 7, 9-13): last week's tab stays while its results finish; older ones are hidden
    assert admin.tab_plan(season, 7, [1, 2, 3, 4, 5, 6]) == ([7, 6, 9, 10, 11, 12, 13], [1, 2, 3, 4, 5])
    assert admin.tab_plan(season, 8, [1, 2, 3, 4, 5, 6, 7, 9]) == ([8, 7, 9, 10, 11, 12, 13], [1, 2, 3, 4, 5, 6])
    assert admin.tab_plan(season, 9, [6, 7, 8, 9]) == ([9, 7, 8, 10, 11, 12, 13], [6])


def test_rebuild_tabs_writes_the_plan_and_arranges(monkeypatch):
    import google_sheet
    season = make_season(cycle_weeks=6, weeks=20)
    written, arranged = [], []
    monkeypatch.setattr(google_sheet, "week_tabs", lambda sheets, sid: [1, 2, 3])
    monkeypatch.setattr(google_sheet, "write_week_tab",
                        lambda sheets, sid, grid: written.append(grid.week) or f"link{grid.week}")
    monkeypatch.setattr(google_sheet, "arrange_tabs", lambda sheets, sid, order, hidden: arranged.append((order, hidden)))
    status = []
    monkeypatch.setattr(google_sheet, "write_status_tab", lambda sheets, sid, week, members, deadline, subtitle:
                        status.append((week, members, deadline)))
    links = admin.rebuild_tabs(season, Store(":memory:"), None, "s", 2, at(season, 2, 0))
    assert written == [2, 1, 3, 4, 5, 6] and links[2] == "link2"
    assert arranged == [([2, 1, 3, 4, 5, 6], [])]
    assert status == [(2, ["Alice", "Bob", "Cat"], season.deadline(2).replace(tzinfo=None))]


def test_override_accepts_a_ruling_after_tip_and_grace(tmp_path):
    s = make_season()
    season, store, responses = setup(tmp_path, [
        csv_row(at(s, 1, 0, 12), "Bob", "Week 1", [tue_pick(i) for i in range(9)] + ["Warriors"])])
    admin.ingest(season, store, responses, 1)
    wed = at(season, 1, 2, 9)  # Tuesday's games have tipped and the grace window has closed

    out = admin.replace(season, store, 1, "Bob", "Warriors tue", wed)
    assert "❌" in out and pool.open_slots(store, season, "Bob", 1) == 1

    out = admin.replace(season, store, 1, "Bob", "Warriors tue", wed, override="form named the team, game clarified late")
    assert out.startswith("✅ Warriors (Tue") and out.endswith("Open slots left: 0\n")
    pick = store.picks(member="Bob", source="admin", accepted=True)[0]
    assert pick.team == "GSW" and pick.note == "Override: form named the team, game clarified late"
    # other rules still apply: no slot left, and the Monday game tipped before the form deadline
    out = admin.replace(season, store, 1, "Bob", "Celtics mon", wed, override="x")
    assert "✅" not in out
