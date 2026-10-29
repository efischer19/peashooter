"""Where to watch (broadcasters from the schedule feed) and full-game highlights (from a YouTube playlist).
No network: rows and the playlist page are canned."""

import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timezone

import admin
import highlights
import report
import sources
from conftest import at, make_season, week_schedule
from schedule import AWAY, FINAL, HOME, NATIONAL, Broadcast, Game
from store import Store

ESPN = Broadcast(NATIONAL, "ESPN", "https://espn.smart.link/x")
DAZN = Broadcast(AWAY, "DAZN-IND", "https://www.dazn.com/home/abc")
GCSEN = Broadcast(HOME, "GCSEN / WVUE")


def feed_row(**extra):
    return {"gameId": "0022600020", "gameDateTimeUTC": "2026-10-21T23:30:00Z", "awayTeam_teamTricode": "IND",
            "homeTeam_teamTricode": "NOP", "gameStatus": 1, "gameStatusText": "7:30 pm ET", **extra}


def test_broadcasts_from_feed_row_skip_radio_and_keep_links():
    g = sources.game_from_nba_row(feed_row(
        nationalBroadcasters_0_broadcasterDisplay="ESPN", nationalBroadcasters_0_broadcasterMedia="tv",
        nationalBroadcasters_0_broadcasterVideoLink="https://espn.smart.link/x",
        nationalRadioBroadcasters_0_broadcasterDisplay="SiriusXM",
        awayTvBroadcasters_broadcasterDisplay="DAZN-IND", awayTvBroadcasters_broadcasterMedia="tv",
        awayTvBroadcasters_broadcasterVideoLink="https://www.dazn.com/home/abc",
        homeTvBroadcasters_broadcasterDisplay="GCSEN / WVUE", homeTvBroadcasters_broadcasterMedia="tv",
        homeRadioBroadcasters_broadcasterDisplay="WWL 870 AM",
        homeOttBroadcasters_broadcasterDisplay="Pelicans+", homeOttBroadcasters_broadcasterMedia="ott",
        homeOttBroadcasters_broadcasterVideoLink="not a link"))
    assert g.broadcasts == (ESPN, DAZN, GCSEN, Broadcast(HOME, "Pelicans+"))


def test_store_round_trips_broadcasts_and_keeps_them_when_the_feed_drops_them(store):
    g = Game("0022600020", datetime(2026, 10, 21, 23, 30, tzinfo=timezone.utc), "IND", "NOP", broadcasts=(ESPN, DAZN))
    store.upsert_games([g])
    assert store.games()[0].broadcasts == (ESPN, DAZN)
    store.upsert_games([replace(g, status=FINAL, away_score=100, home_score=99, broadcasts=())])
    assert store.games()[0].broadcasts == (ESPN, DAZN) and store.games()[0].status == FINAL


def test_old_database_gets_the_broadcasts_column(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE games (id TEXT PRIMARY KEY, tip TEXT NOT NULL, away TEXT NOT NULL, home TEXT NOT NULL, "
               "status TEXT NOT NULL, away_score INTEGER, home_score INTEGER, event TEXT NOT NULL DEFAULT '')")
    db.execute("INSERT INTO games VALUES ('g1', '2026-10-21T23:30:00+00:00', 'IND', 'NOP', 'scheduled', NULL, NULL, '')")
    db.commit()
    db.close()
    games = Store(path).games()
    assert games[0].broadcasts == () and games[0].highlights == ""


def test_parse_highlight_titles():
    assert highlights.parse_title("TRAIL BLAZERS at 76ERS | FULL GAME HIGHLIGHTS | October 21, 2026") == \
        ("POR", "PHI", date(2026, 10, 21))
    assert highlights.parse_title("New York Knicks FULL NBA Championship Banner Raising Ceremony!") is None
    assert highlights.parse_title("KINGS at KINGS | FULL GAME HIGHLIGHTS | October 21, 2026") is None


def playlist_page(videos):
    data = {"contents": [{"lockupViewModel": {"contentId": vid, "metadata": {"lockupMetadataViewModel": {
        "title": {"content": title}}}}} for vid, title in videos]}
    return f"<html><script>var ytInitialData = {json.dumps(data)};</script></html>"


def test_videos_from_page():
    page = playlist_page([("abc", "KINGS at CLIPPERS | FULL GAME HIGHLIGHTS | October 21, 2026"), ("def", "Other")])
    assert highlights.videos_from_page(page) == [
        ("abc", "KINGS at CLIPPERS | FULL GAME HIGHLIGHTS | October 21, 2026"), ("def", "Other")]


def test_match_uses_the_local_date_and_skips_preseason(store, season):
    late = Game("0022600030", datetime(2026, 10, 22, 2, 0, tzinfo=timezone.utc), "SAC", "LAC")  # 10 pm ET Oct 21
    store.upsert_games([late])
    videos = [("new", "KINGS at CLIPPERS | FULL GAME HIGHLIGHTS | October 21, 2026"),
              ("pre", "KINGS at CLIPPERS | NBA PRESEASON FULL GAME HIGHLIGHTS | October 5, 2026")]
    note = highlights.sync_highlights(store, season, "PLx", fetch=lambda _: videos)
    assert note == "Highlights: 2 videos in the playlist, 1 newly matched."
    assert store.games()[0].highlights == "https://www.youtube.com/watch?v=new"
    assert highlights.sync_highlights(store, season, "PLx", fetch=lambda _: videos).endswith("0 newly matched.")
    assert highlights.sync_highlights(store, season, "") == ""


def test_refresh_never_raises(store, season, monkeypatch):
    monkeypatch.setattr(highlights, "playlist_id", lambda: "PLx")
    monkeypatch.setattr(highlights, "fetch_playlist", lambda _: (_ for _ in ()).throw(OSError("offline")))
    assert highlights.refresh(store, season) == "Highlights: skipped (OSError: offline)"


def real_ids(games):
    return [replace(g, id=f"00226{i:05d}") for i, g in enumerate(games)]


def test_page_menu_lists_every_feed_before_the_game(store, season):
    games = real_ids(week_schedule(season, 1))
    store.upsert_games([replace(games[0], broadcasts=(ESPN, DAZN, GCSEN))] + games[1:])
    html = admin.site(season, store, at(season, 1, 1, 9))
    g = games[0]
    assert '<details class="tv">' in html
    assert f'href="{report.nba_url(g)}"' in html and ">NBA.com · League Pass ↗</a>" in html
    assert '<a href="https://espn.smart.link/x" target="_blank" rel="noopener">ESPN ↗</a>' in html
    assert f">{report.nickname(g.away)}: DAZN-IND ↗</a>" in html
    assert f"<span>{report.nickname(g.home)}: GCSEN / WVUE</span>" in html
    assert "in-market only" in html


def test_page_links_highlights_once_final(store, season):
    games = real_ids(week_schedule(season, 1))
    done = replace(games[0], status=FINAL, away_score=100, home_score=110, broadcasts=(ESPN,))
    store.upsert_games([done] + games[1:])
    store.save_highlights({done.id: ("https://www.youtube.com/watch?v=abc", "title")})
    html = admin.site(season, store, at(season, 1, 2, 9))
    assert '<summary title="Replays"' in html
    assert '<a href="https://www.youtube.com/watch?v=abc" target="_blank" rel="noopener">Full-game highlights' in html
    assert f'<a href="{report.nba_url(done)}" target="_blank" rel="noopener">NBA.com · League Pass replay ↗</a>' in html
    # a final game without a video falls back to its NBA.com page
    store.upsert_games([replace(games[1], status=FINAL, away_score=100, home_score=110)])
    assert f'href="{report.nba_url(games[1])}"' in admin.site(season, store, at(season, 1, 2, 9))


def test_digest_names_the_national_network(store):
    season = make_season()
    games = week_schedule(season, 1)
    store.upsert_games([replace(games[15], broadcasts=(ESPN, DAZN))] + games[16:])
    post = admin.digest(season, store, at(season, 1, 3, 9, 30))
    lines = post.replies[0].splitlines()
    assert lines[1].endswith(" · 📺 ESPN: no picks") and "DAZN" not in post.replies[0]
    table = next(b for b in post.blocks[1] if b["type"] == "table")
    assert [c["elements"][0]["elements"][0]["text"] for c in table["rows"][0]] == ["ET", "Game", "Picks", "Watch"]
    assert table["rows"][1][3]["type"] == "raw_text" and table["rows"][1][3]["text"] == "–"  # no NBA id: no links
    real = replace(games[16], id="0022600020", broadcasts=(ESPN, DAZN, GCSEN))
    assert report._links_cell(report.watch_links(real))["elements"][0]["elements"] == [
        {"type": "link", "url": report.nba_url(real), "text": "NBA.com"}, {"type": "text", "text": " · "},
        {"type": "link", "url": "https://espn.smart.link/x", "text": "ESPN"}, {"type": "text", "text": " · "},
        {"type": "link", "url": "https://www.dazn.com/home/abc", "text": f"{report.nickname(real.away)}: DAZN-IND"},
        {"type": "text", "text": " · "}, {"type": "text", "text": f"{report.nickname(real.home)}: GCSEN / WVUE"}]
