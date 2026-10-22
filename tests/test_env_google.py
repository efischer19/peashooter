import os

import pytest

import env
import google_auth


def test_env_file_loads_without_overriding(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# c\nPEASHOOTER_SHEET_ID='abc'\nGOOGLE_TOKEN_FILE=~/t.json\nPEASHOOTER_DB=/from/file\n")
    monkeypatch.delenv("PEASHOOTER_SHEET_ID", raising=False)
    monkeypatch.delenv("GOOGLE_TOKEN_FILE", raising=False)
    monkeypatch.setenv("PEASHOOTER_DB", "/from/env")
    env.load_env_file(f)
    assert os.environ["PEASHOOTER_SHEET_ID"] == "abc"
    assert os.environ["GOOGLE_TOKEN_FILE"] == os.path.expanduser("~/t.json")
    assert os.environ["PEASHOOTER_DB"] == "/from/env"


def test_missing_token_explains_the_fix(tmp_path, monkeypatch):
    pytest.importorskip("google.oauth2.credentials")
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "nope.json"))
    with pytest.raises(google_auth.GoogleAuthError, match="google_auth.py"):
        google_auth.load_credentials()


def test_missing_client_secret_explains_the_fix(tmp_path, monkeypatch):
    pytest.importorskip("google_auth_oauthlib")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET_FILE", str(tmp_path / "nope.json"))
    with pytest.raises(google_auth.GoogleAuthError, match="Download JSON"):
        google_auth.sign_in()
