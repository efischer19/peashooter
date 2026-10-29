"""The morning digest: standings, yesterday's results, today's games and who picked what. No network."""

import admin
import rules
from conftest import CODES, at, finish, week_schedule
from schedule import Game
from slack_post import Thread
from teams import TEAMS


def pick(store, season, member, week, game_id, team, kind="regular"):
    store.add_picks(member, week, kind, "form", [rules.Decision(game_id, team, True)], at(season, week, 0, 12))


def name(code):
    return TEAMS[code][1]


def test_yesterday_results_and_no_games_today(store, season):
    games = week_schedule(season, 1)
    store.upsert_games(finish(games[:15]) + games[15:])  # Tuesday's games are final; home teams won
    pick(store, season, "Alice", 1, "w1d1g0", CODES[15])  # win
    pick(store, season, "Alice", 1, "w1d1g1", CODES[16])  # win
    pick(store, season, "Bob", 1, "w1d1g0", CODES[0])     # loss
    pick(store, season, "Bob", 1, "w1d3g0", CODES[0])     # Thursday: pending
    post = admin.digest(season, store, at(season, 1, 2, 9, 30))

    assert isinstance(post, Thread) and post.replies == ()
    lines = post.main.splitlines()
    assert lines[0] == "🏀 *PEAshooter* · Wed Oct 28 · Week 1"
    assert "🥇 *Alice*: 2 pts (2–0) · +2 yesterday" in lines
    assert "🥈 *Bob*: 0 pts (0–1) · +0 yesterday" in lines
    assert "🥈 *Cat*: 0 pts (0–0)" in lines  # no picks yesterday: no "+N"
    assert "*Yesterday*: 3 picks · 2 ✅ 1 ❌" in lines
    assert lines[-1] == "_No games today._"


def test_todays_games_show_pickers_after_the_lock(store, season):
    store.upsert_games(week_schedule(season, 1))
    thu = [g for g in week_schedule(season, 1) if g.id.startswith("w1d3")]
    pick(store, season, "Cat", 1, thu[0].id, thu[0].away)
    pick(store, season, "Alice", 1, thu[0].id, thu[0].away)
    pick(store, season, "Bob", 1, thu[0].id, thu[0].home)
    reply = admin.digest(season, store, at(season, 1, 3, 9, 30)).replies[0]

    lines = reply.splitlines()
    assert lines[0] == "*Today: 15 games* (times ET)"
    assert (f"• 7:30 pm · {name(thu[0].away)} @ {name(thu[0].home)}: "
            f"{name(thu[0].away)} (Alice, Cat) · {name(thu[0].home)} (Bob)") in lines
    assert f"• 7:30 pm · {name(thu[1].away)} @ {name(thu[1].home)}: no picks" in lines
    assert "lock" not in reply


def test_no_results_yet(store, season):
    store.upsert_games(week_schedule(season, 1))
    pick(store, season, "Alice", 1, "w1d1g0", CODES[15])  # tonight: pending
    main = admin.digest(season, store, at(season, 1, 1, 9, 30)).main
    assert main.splitlines()[2:] == ["*Standings*", "_No results yet._"]


def test_picks_hidden_before_the_monday_lock(store, season):
    late = Game("mon2", at(season, 2, 0, 20, 0), "BOS", "MIA")
    store.upsert_games([late])
    pick(store, season, "Bob", 2, "mon2", "BOS")
    reply = admin.digest(season, store, at(season, 2, 0, 9, 30)).replies[0]

    assert "• 8 pm · Celtics @ Heat\n" in reply and "Bob" not in reply
    assert "_Week 2 picks lock Mon 7 pm ET and show after that_" in reply
    after = admin.digest(season, store, at(season, 2, 0, 19, 1)).replies[0]
    assert "• 8 pm · Celtics @ Heat: Celtics (Bob)" in after


def test_off_week_special_game(store, season):
    final = Game("cup", at(season, 7, 4, 20, 30), "OKC", "NYK", event="Emirates NBA Cup")
    store.upsert_games([final])
    pick(store, season, "Alice", 7, "cup", "NYK", kind="special")
    morning = admin.digest(season, store, at(season, 7, 4, 9, 30))

    assert morning.main.splitlines()[0] == "🏀 *PEAshooter* · Fri Dec 11 · Week 7 (Cup Final week)"
    reply = morning.replies[0]
    assert "• 8:30 pm · Thunder @ Knicks 🏆 ⭐ NBA Cup Final, 5 pts\n" in reply and "Alice" not in reply
    assert "_⭐ bonus-game picks show once the game tips_" in reply
    tipped = admin.digest(season, store, at(season, 7, 4, 20, 31)).replies[0]
    assert "🏆 ⭐ NBA Cup Final, 5 pts: Knicks (Alice)" in tipped

    store.upsert_games(finish([final]))
    next_day = admin.digest(season, store, at(season, 7, 5, 9, 30)).main
    assert "🥇 *Alice*: 5 pts (1–0) · +5 yesterday" in next_day


def cells(table_block):
    """Table rows as plain strings (rich-text cells flattened)."""
    flat = lambda c: c["text"] if "text" in c else "".join(e["text"] for s in c["elements"] for e in s["elements"])
    return [[flat(c) for c in row] for row in table_block["rows"]]


def test_blocks_mirror_the_text(store, season, monkeypatch):
    monkeypatch.setenv("PEASHOOTER_SITE_URL", "https://example.com/peashooter/")
    monkeypatch.setattr(admin.highlights, "playlist_url", lambda: "https://www.youtube.com/playlist?list=PLtest")
    games = week_schedule(season, 1)
    wed = [Game("wed0", at(season, 1, 2, 19, 30), "BOS", "MIA"), Game("wed1", at(season, 1, 2, 20), "NYK", "LAL")]
    store.upsert_games(finish(games[:15]) + games[15:] + wed)
    pick(store, season, "Alice", 1, "w1d1g0", CODES[15])
    pick(store, season, "Bob", 1, wed[0].id, wed[0].home)
    post = admin.digest(season, store, at(season, 1, 2, 9, 30))
    main, reply = post.blocks

    assert main[0]["type"] == "header" and main[0]["text"]["text"] == "🏀 PEAshooter · Wed Oct 28 · Week 1"
    standings = cells(main[1])
    assert standings[0] == ["#", "Shooter", "Pts", "W–L", "Yday"]
    assert standings[1:] == [["🥇", "Alice", "1", "1–0", "+1"]]  # 0-point rows are left out
    context = [e["text"] for e in main[2]["elements"]]
    assert context == ["<https://example.com/peashooter/|PEAshooter leaderboard ↗>\n"
                       "*Yesterday:* 1 picks · 1 ✅ 0 ❌\n"
                       "<https://www.youtube.com/playlist?list=PLtest|Game highlights (YouTube) ↗>"]
    rows = cells(reply[1])
    assert rows[0] == ["ET", "Game", "Picks", "Watch"] and len(rows) == 1 + len(wed)
    assert rows[1] == ["7:30 pm", f"{wed[0].away} @ {wed[0].home}", f"{name(wed[0].home)} — Bob", "–"]
    assert rows[2][2] == "–"


def test_blocks_hide_unlocked_picks(store, season, monkeypatch):
    monkeypatch.delenv("PEASHOOTER_SITE_URL", raising=False)
    store.upsert_games([Game("mon2", at(season, 2, 0, 20, 0), "BOS", "MIA")])
    pick(store, season, "Bob", 2, "mon2", "BOS")
    main, reply = admin.digest(season, store, at(season, 2, 0, 9, 30)).blocks
    assert cells(reply[1])[1] == ["8 pm", "BOS @ MIA", "🔒", "–"]
    assert reply[2]["elements"][0]["text"] == "_Week 2 picks lock Mon 7 pm ET and show after that_"
    assert "Full scoreboard" not in str(main)


def test_digest_links_the_pick_helper_while_the_form_is_open(store, season, monkeypatch):
    monkeypatch.setenv("PEASHOOTER_SITE_URL", "https://example.com/peashooter/")
    monkeypatch.setenv("PEASHOOTER_PICKER_FORM", "1")
    monkeypatch.setenv("PEASHOOTER_FORM_WEEK", "2")
    monkeypatch.setattr(admin.highlights, "playlist_url", lambda: "")
    store.upsert_games(week_schedule(season, 1))
    notes = lambda now: admin.digest(season, store, now).blocks[0][-1]["elements"][0]["text"]
    assert "<https://example.com/peashooter/picks|Make your Week 2 picks ↗> · due Mon 7 pm ET" in notes(at(season, 1, 5, 9))
    assert "Make your" not in notes(at(season, 2, 1, 9))  # week 2's deadline has passed
    monkeypatch.setenv("PEASHOOTER_FORM_WEEK", "")  # closed
    assert "Make your" not in notes(at(season, 1, 5, 9))
