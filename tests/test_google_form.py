"""Form request building, offline."""

from datetime import datetime

import env
import google_form
from conftest import ET, make_season, week_schedule
from season import Member


def test_description_is_plain_schedule():
    season = make_season()
    text = google_form.description(season, 1, week_schedule(season, 1), datetime(2026, 10, 25, tzinfo=ET))
    assert text.startswith("🏀 PEAshooter Week 1 · Mon Oct 26") and "*" not in text and "_" not in text


def test_new_form_gets_three_questions():
    season = make_season()
    reqs = google_form.week_requests({"formId": "f"}, season, 1, "desc")
    assert reqs[0]["updateFormInfo"]["info"]["description"] == "desc"
    created = [r["createItem"]["item"] for r in reqs[1:]]
    assert [i["title"] for i in created] == ["Name", "Week", "Picks"]
    names = created[0]["questionItem"]["question"]["choiceQuestion"]["options"]
    assert [o["value"] for o in names] == ["Alice", "Bob", "Cat"]
    mixed = make_season(members=(Member("Zed"), Member("MO"), Member("amy")))
    name_q = google_form.week_requests({"formId": "f"}, mixed, 1, "d")[1]["createItem"]["item"]
    assert [o["value"] for o in name_q["questionItem"]["question"]["choiceQuestion"]["options"]] == ["amy", "MO", "Zed"]
    assert created[1]["questionItem"]["question"]["choiceQuestion"]["options"] == [{"value": "Week 1"}]
    assert created[2]["questionItem"]["question"]["textQuestion"] == {"paragraph": True}


def test_existing_form_is_updated_in_place_for_a_new_week():
    season = make_season()
    form = {"formId": "f", "items": [
        {"itemId": f"i{n}", "title": t, "questionItem": {"question": {"questionId": f"q{n}"}}}
        for n, t in enumerate(["Name", "Week", "Picks"])]}
    reqs = google_form.week_requests(form, season, 9, "desc")
    updates = [r["updateItem"] for r in reqs[1:]]
    assert [(u["item"]["itemId"], u["item"]["questionItem"]["question"]["questionId"], u["location"]["index"])
            for u in updates] == [("i0", "q0", 0), ("i1", "q1", 1), ("i2", "q2", 2)]
    assert updates[1]["item"]["questionItem"]["question"]["choiceQuestion"]["options"] == [{"value": "Week 9"}]
    assert "special game" in updates[2]["item"]["description"]  # week 9 is Christmas week in the test season


def test_publish_body():
    assert google_form.publish_body(False)["publishSettings"]["publishState"] == {
        "isPublished": True, "isAcceptingResponses": False}


def test_set_env_value_replaces_or_appends(tmp_path, monkeypatch):
    for key in ("PEASHOOTER_FORM_ID", "PEASHOOTER_SHEET_ID"):
        monkeypatch.setenv(key, "")  # restored after the test
    f = tmp_path / ".env"
    f.write_text("# keep\nPEASHOOTER_FORM_ID=old\n")
    env.set_env_value("PEASHOOTER_FORM_ID", "new", f)
    env.set_env_value("PEASHOOTER_SHEET_ID", "s1", f)
    assert f.read_text() == "# keep\nPEASHOOTER_FORM_ID=new\nPEASHOOTER_SHEET_ID=s1\n"
