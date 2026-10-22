"""Google sign-in for PEAshooter: OAuth as you (not a service account, which can't own Drive files).

    uv run --extra google google_auth.py           # one-time: opens a browser, saves the token
    uv run --extra google google_auth.py --check   # confirm the token works and the Sheet/Form are reachable

Needs a Desktop OAuth client from Google Cloud (see README). File locations come from .env:
GOOGLE_CLIENT_SECRET_FILE and GOOGLE_TOKEN_FILE, defaulting to ~/.config/peashooter/.
"""

import argparse
import os
import sys
from pathlib import Path

from env import load_env_file

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",  # read responses, write the derived tabs
    "https://www.googleapis.com/auth/forms.body",  # update the weekly picks question, open/close the form
]
CONFIG_DIR = Path.home() / ".config" / "peashooter"


def client_secret_file() -> Path:
    return Path(os.environ.get("GOOGLE_CLIENT_SECRET_FILE") or CONFIG_DIR / "client_secret.json")


def token_file() -> Path:
    return Path(os.environ.get("GOOGLE_TOKEN_FILE") or CONFIG_DIR / "token.json")


class GoogleAuthError(Exception):
    pass


def sign_in() -> Path:
    from google_auth_oauthlib.flow import InstalledAppFlow

    secret = client_secret_file()
    if not secret.exists():
        raise GoogleAuthError(f"OAuth client file not found at {secret}. Download it from Google Cloud "
                              "(Clients → your Desktop client → Download JSON) or set GOOGLE_CLIENT_SECRET_FILE.")
    creds = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES).run_local_server(port=0)
    path = token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(creds.to_json())
    path.chmod(0o600)
    return path


def load_credentials():
    """Saved credentials, refreshed if needed. Raises GoogleAuthError with the fix if they're missing or revoked."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    path = token_file()
    if not path.exists():
        raise GoogleAuthError(f"No Google token at {path}. Run: uv run --extra google google_auth.py")
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise GoogleAuthError(f"Google token was revoked or expired ({e}). "
                                  "Re-run: uv run --extra google google_auth.py") from e
        path.write_text(creds.to_json())
    return creds


def check() -> list:
    """Lines describing what the saved token can reach."""
    from googleapiclient.discovery import build

    creds = load_credentials()
    lines = [f"OK: token at {token_file()}"]
    sheet_id, form_id = os.environ.get("PEASHOOTER_SHEET_ID"), os.environ.get("PEASHOOTER_FORM_ID")
    if sheet_id:
        sheet = build("sheets", "v4", credentials=creds).spreadsheets().get(spreadsheetId=sheet_id).execute()
        tabs = ", ".join(s["properties"]["title"] for s in sheet["sheets"])
        lines.append(f"OK: Sheet '{sheet['properties']['title']}' ({sheet['properties'].get('timeZone')}); tabs: {tabs}")
    else:
        lines.append("skip: PEASHOOTER_SHEET_ID not set")
    if form_id:
        form = build("forms", "v1", credentials=creds).forms().get(formId=form_id).execute()
        lines.append(f"OK: Form '{form['info'].get('title')}' with {len(form.get('items', []))} questions")
    else:
        lines.append("skip: PEASHOOTER_FORM_ID not set")
    return lines


def main(argv=None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="test the saved token instead of signing in")
    args = parser.parse_args(argv)
    try:
        if args.check:
            print("\n".join(check()))
        else:
            print(f"Saved Google token to {sign_in()}")
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
