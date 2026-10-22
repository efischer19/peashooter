import io
import json
from datetime import datetime

import pytest

import admin
import slack_post
from conftest import ET, make_season


def test_split_message_keeps_paragraphs_and_lines_whole():
    text = "A" * 10 + "\n\n" + "B" * 10 + "\n\n" + "\n".join(["C" * 8] * 4)
    assert slack_post.split_message(text, 25) == ["A" * 10 + "\n\n" + "B" * 10, "C" * 8 + "\n" + "C" * 8,
                                                   "C" * 8 + "\n" + "C" * 8]
    assert slack_post.split_message("short") == ["short"]


def test_post_sends_each_chunk(monkeypatch):
    sent = []

    def fake_urlopen(request, timeout):
        sent.append((request.full_url, request.headers["Authorization"], json.loads(request.data)))
        return io.BytesIO(json.dumps({"ok": True, "ts": str(len(sent))}).encode())

    monkeypatch.setattr(slack_post.urllib.request, "urlopen", fake_urlopen)
    assert slack_post.post("one\n\ntwo", channel="C1", token="xoxb-t") == ["1"]
    url, auth, body = sent[0]
    assert url.endswith("chat.postMessage") and auth == "Bearer xoxb-t"
    assert body == {"channel": "C1", "text": "one\n\ntwo", "unfurl_links": False, "unfurl_media": False}


def test_post_with_blocks_is_one_message(monkeypatch):
    sent = []
    monkeypatch.setattr(slack_post.urllib.request, "urlopen", lambda r, timeout: sent.append(json.loads(r.data))
                        or io.BytesIO(b'{"ok": true, "ts": "1"}'))
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "hi"}}]
    assert slack_post.post("x" * 5000, channel="C1", token="t", blocks=blocks) == ["1"]
    assert len(sent) == 1 and sent[0]["blocks"] == blocks and sent[0]["text"] == "x" * 5000


def test_post_reports_slack_errors(monkeypatch):
    monkeypatch.setattr(slack_post.urllib.request, "urlopen",
                        lambda r, timeout: io.BytesIO(b'{"ok": false, "error": "not_in_channel"}'))
    with pytest.raises(slack_post.SlackError, match="not_in_channel"):
        slack_post.post("hi", channel="C1", token="t")
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    with pytest.raises(slack_post.SlackError, match="SLACK_BOT_TOKEN"):
        slack_post.post("hi", channel="C1")


def test_week_defaults():
    season = make_season()  # week 1 = Mon Oct 26
    assert admin.upcoming_week(season, datetime(2026, 10, 25, 11, tzinfo=ET)) == 1  # Sunday before
    assert admin.current_week(season, datetime(2026, 10, 26, 19, tzinfo=ET)) == 1  # Monday deadline
    assert admin.upcoming_week(season, datetime(2026, 11, 1, 11, tzinfo=ET)) == 2


def test_reminder_lists_who_is_missing(monkeypatch):
    season = make_season()
    rows = [admin.Response(2, datetime(2026, 10, 25, 12, tzinfo=ET), "alice", 1, "x"),
            admin.Response(3, datetime(2026, 10, 26, 20, tzinfo=ET), "Bob", 1, "x")]  # late doesn't count
    monkeypatch.setattr(admin, "google", lambda: (None, None, "sheet"))
    monkeypatch.setattr(admin, "sheet_responses", lambda sheets, sheet_id, s: rows)
    text = admin.reminder(season, None, 1, datetime(2026, 10, 26, 17, tzinfo=ET))
    assert text == "⏰ Week 1 picks lock *Mon 7 pm ET*. Still waiting on: Bob, Cat\n"


def test_threaded_post(monkeypatch):
    calls = []

    def fake_post(text, channel="", token="", thread_ts="", blocks=None):
        calls.append((text, thread_ts))
        return [f"ts{len(calls)}"]

    monkeypatch.setattr(slack_post, "post", fake_post)
    message = slack_post.Thread("main", ("reply one", "reply two"))
    assert str(message).startswith("main\n🧵 (in thread)\nreply one")
    assert slack_post.post_thread(message) == ["ts1", "ts2", "ts3"]
    assert calls == [("main", ""), ("reply one", "ts1"), ("reply two", "ts1")]
    assert slack_post.post_thread("plain") == ["ts4"]
    blocked = []
    monkeypatch.setattr(slack_post, "post", lambda text, channel="", token="", thread_ts="", blocks=None:
                        blocked.append((text, blocks)) or ["ts"])
    slack_post.post_thread(slack_post.Thread("main", ("reply",), ([{"type": "header"}],)))
    assert blocked == [("main", [{"type": "header"}]), ("reply", None)]


def test_announcement_is_short_and_schedule_has_no_header():
    import report
    from conftest import week_schedule
    season = make_season()
    games = week_schedule(season, 1)
    main = report.announcement_md(season, 1, games, "https://form", "https://tab")
    assert main.splitlines()[1] == "Picks due *Mon Oct 26, 7 pm ET* · 10 picks · 45 games"
    assert "<https://form|*Make your picks*>" in main and main.splitlines()[2] == "" and len(main.splitlines()) == 5
    schedule = report.schedule_md(season, 1, games, datetime(2026, 10, 25).date(), header=False)
    assert schedule.startswith("*Tue Oct 27*")
    xmas = report.announcement_md(season, 9, [], "f", "t")
    assert "Christmas week: no regular picks." in xmas
