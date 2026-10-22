"""SQLite storage: the source of truth for games, picks and forms. The Google Sheet is only a view of this."""

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from schedule import Broadcast, Game

DB_FILE = Path(__file__).resolve().parent / "data" / "peashooter.db"


def db_path() -> Path:
    """PEASHOOTER_DB overrides the default data/peashooter.db next to this file."""
    return Path(os.environ.get("PEASHOOTER_DB") or DB_FILE)

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id TEXT PRIMARY KEY, tip TEXT NOT NULL, away TEXT NOT NULL, home TEXT NOT NULL,
    status TEXT NOT NULL, away_score INTEGER, home_score INTEGER, event TEXT NOT NULL DEFAULT '',
    broadcasts TEXT NOT NULL DEFAULT '[]'   -- JSON list of Broadcast dicts
);
CREATE TABLE IF NOT EXISTS highlights (
    game_id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member TEXT NOT NULL, week INTEGER NOT NULL, game_id TEXT NOT NULL, team TEXT NOT NULL,
    kind TEXT NOT NULL,      -- regular | special
    source TEXT NOT NULL,    -- form | dm | admin
    accepted INTEGER NOT NULL, code TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
    submitted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS picks_member_week ON picks (member, week);
CREATE TABLE IF NOT EXISTS forms (
    member TEXT NOT NULL, week INTEGER NOT NULL, form_id TEXT NOT NULL, url TEXT NOT NULL,
    PRIMARY KEY (member, week)
);
"""


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class Pick:
    id: int
    member: str
    week: int
    game_id: str
    team: str
    kind: str
    source: str
    accepted: bool
    code: str
    note: str
    submitted_at: datetime


class Store:
    def __init__(self, path: Path | None = None):
        path = path or db_path()
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Columns added after a database was created."""
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(games)")}
        if "broadcasts" not in cols:
            with self.db:
                self.db.execute("ALTER TABLE games ADD COLUMN broadcasts TEXT NOT NULL DEFAULT '[]'")

    # games
    def upsert_games(self, games: list) -> None:
        with self.db:
            self.db.executemany(
                "INSERT INTO games VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET tip=excluded.tip, "
                "away=excluded.away, home=excluded.home, status=excluded.status, away_score=excluded.away_score, "
                "home_score=excluded.home_score, event=excluded.event, "
                # keep known feeds if the source stops listing them after the game
                "broadcasts=CASE WHEN excluded.broadcasts = '[]' THEN games.broadcasts ELSE excluded.broadcasts END",
                [(g.id, _utc(g.tip), g.away, g.home, g.status, g.away_score, g.home_score, g.event,
                  json.dumps([b.to_dict() for b in g.broadcasts])) for g in games])

    def games(self, start: Optional[datetime] = None, end: Optional[datetime] = None) -> list:
        sql, args = "SELECT g.*, h.url AS highlights FROM games g LEFT JOIN highlights h ON h.game_id = g.id WHERE 1=1", []
        if start:
            sql, args = sql + " AND tip >= ?", args + [_utc(start)]
        if end:
            sql, args = sql + " AND tip < ?", args + [_utc(end)]
        return [Game(r["id"], datetime.fromisoformat(r["tip"]), r["away"], r["home"], r["status"],
                     r["away_score"], r["home_score"], r["event"],
                     tuple(Broadcast(**b) for b in json.loads(r["broadcasts"])), r["highlights"] or "")
                for r in self.db.execute(sql + " ORDER BY tip", args)]

    def games_by_id(self) -> dict:
        return {g.id: g for g in self.games()}

    def save_highlights(self, videos: dict) -> None:
        """{game_id: (url, title)}; a later match for the same game replaces the earlier one."""
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO highlights VALUES (?, ?, ?)",
                                [(gid, url, title) for gid, (url, title) in videos.items()])

    # picks
    def add_picks(self, member: str, week: int, kind: str, source: str, decisions: list, submitted_at: datetime) -> None:
        with self.db:
            self._insert(member, week, kind, source, decisions, submitted_at)

    def replace_picks(self, member: str, week: int, kind: str, source: str, decisions: list,
                      submitted_at: datetime) -> None:
        """Swap in a new submission (latest form response wins)."""
        with self.db:
            self.db.execute("DELETE FROM picks WHERE member=? AND week=? AND kind=? AND source=?",
                            (member, week, kind, source))
            self._insert(member, week, kind, source, decisions, submitted_at)

    def delete_picks(self, member: str, kind: str, game_ids: list) -> None:
        with self.db:
            self.db.executemany("DELETE FROM picks WHERE member=? AND kind=? AND game_id=?",
                                [(member, kind, g) for g in game_ids])

    def _insert(self, member, week, kind, source, decisions, submitted_at):
        self.db.executemany(
            "INSERT INTO picks (member, week, game_id, team, kind, source, accepted, code, note, submitted_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(member, week, d.game_id, d.team, kind, source, int(d.accepted), d.code, d.note, _utc(submitted_at))
             for d in decisions])

    def picks(self, member: Optional[str] = None, weeks: Optional[list] = None, kind: Optional[str] = None,
              source: Optional[str] = None, accepted: Optional[bool] = None) -> list:
        sql, args = "SELECT * FROM picks WHERE 1=1", []
        for col, val in (("member", member), ("kind", kind), ("source", source)):
            if val is not None:
                sql, args = sql + f" AND {col} = ?", args + [val]
        if accepted is not None:
            sql, args = sql + " AND accepted = ?", args + [int(accepted)]
        if weeks is not None:
            sql, args = sql + f" AND week IN ({','.join('?' * len(weeks))})", args + list(weeks)
        return [Pick(r["id"], r["member"], r["week"], r["game_id"], r["team"], r["kind"], r["source"],
                     bool(r["accepted"]), r["code"], r["note"], datetime.fromisoformat(r["submitted_at"]))
                for r in self.db.execute(sql + " ORDER BY id", args)]

    # forms
    def save_form(self, member: str, week: int, form_id: str, url: str) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO forms VALUES (?, ?, ?, ?)", (member, week, form_id, url))

    def forms(self, week: int) -> dict:
        return {r["member"]: {"form_id": r["form_id"], "url": r["url"]}
                for r in self.db.execute("SELECT * FROM forms WHERE week = ?", (week,))}
