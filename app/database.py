from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .parser import ParsedMessage


CREATOR_FIELDS = {
    "name",
    "handle",
    "status",
    "product",
    "terms",
    "notes",
    "style_notes",
    "summary",
    "next_action",
}


def _message_comparison_key(body: str) -> str:
    normalised = unicodedata.normalize("NFKC", body).casefold()
    return re.sub(r"[\W_]+", "", normalised, flags=re.UNICODE)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialise()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialise(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS creators (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    handle TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '洽谈中',
                    product TEXT NOT NULL DEFAULT '',
                    terms TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    style_notes TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    next_action TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    creator_id INTEGER NOT NULL REFERENCES creators(id) ON DELETE CASCADE,
                    sent_at TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    body TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(creator_id, fingerprint)
                );
                CREATE INDEX IF NOT EXISTS idx_messages_creator
                    ON messages(creator_id, sent_at, id);
                CREATE TABLE IF NOT EXISTS drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    creator_id INTEGER NOT NULL REFERENCES creators(id) ON DELETE CASCADE,
                    intent TEXT NOT NULL,
                    tone TEXT NOT NULL,
                    english_reply TEXT NOT NULL,
                    chinese_translation TEXT NOT NULL DEFAULT '',
                    strategy TEXT NOT NULL DEFAULT '',
                    risk_notes TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
        self.remove_visual_duplicates()

    def remove_visual_duplicates(self) -> int:
        duplicate_ids: list[int] = []
        seen: set[tuple[int, str, str, str]] = set()
        with self.connect() as db:
            rows = db.execute(
                "SELECT id, creator_id, sent_at, sender, body FROM messages ORDER BY id"
            ).fetchall()
            for row in rows:
                key = (
                    int(row["creator_id"]),
                    str(row["sent_at"]),
                    str(row["sender"]).casefold().strip(),
                    _message_comparison_key(str(row["body"])),
                )
                if key in seen:
                    duplicate_ids.append(int(row["id"]))
                else:
                    seen.add(key)
            if duplicate_ids:
                db.executemany("DELETE FROM messages WHERE id = ?", ((value,) for value in duplicate_ids))
        return len(duplicate_ids)

    @staticmethod
    def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None

    def list_creators(self, query: str = "") -> list[dict[str, Any]]:
        wildcard = f"%{query.strip()}%"
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT c.*, COUNT(m.id) AS message_count, MAX(m.sent_at) AS last_message_at
                FROM creators c
                LEFT JOIN messages m ON m.creator_id = c.id
                WHERE c.name LIKE ? OR c.handle LIKE ? OR c.product LIKE ?
                GROUP BY c.id
                ORDER BY COALESCE(MAX(m.sent_at), c.updated_at) DESC, c.id DESC
                """,
                (wildcard, wildcard, wildcard),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_creator(self, creator_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM creators WHERE id = ?", (creator_id,)).fetchone()
        return self._dict(row)

    def create_creator(self, values: dict[str, Any]) -> dict[str, Any]:
        name = str(values.get("name", "")).strip()
        if not name:
            raise ValueError("达人名称不能为空")
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT INTO creators(name, handle, status, product, terms, notes, style_notes,
                                     summary, next_action, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    str(values.get("handle", "")).strip(),
                    str(values.get("status", "洽谈中")).strip() or "洽谈中",
                    str(values.get("product", "")).strip(),
                    str(values.get("terms", "")).strip(),
                    str(values.get("notes", "")).strip(),
                    str(values.get("style_notes", "")).strip(),
                    str(values.get("summary", "")).strip(),
                    str(values.get("next_action", "")).strip(),
                    now,
                    now,
                ),
            )
            creator_id = int(cursor.lastrowid)
        return self.get_creator(creator_id) or {}

    def update_creator(self, creator_id: int, values: dict[str, Any]) -> dict[str, Any]:
        updates = {key: str(value).strip() for key, value in values.items() if key in CREATOR_FIELDS}
        if "name" in updates and not updates["name"]:
            raise ValueError("达人名称不能为空")
        if not updates:
            creator = self.get_creator(creator_id)
            if not creator:
                raise KeyError("达人不存在")
            return creator
        updates["updated_at"] = datetime.now().isoformat(timespec="seconds")
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self.connect() as db:
            cursor = db.execute(
                f"UPDATE creators SET {assignments} WHERE id = ?",
                (*updates.values(), creator_id),
            )
            if cursor.rowcount == 0:
                raise KeyError("达人不存在")
        return self.get_creator(creator_id) or {}

    def delete_creator(self, creator_id: int) -> None:
        with self.connect() as db:
            cursor = db.execute("DELETE FROM creators WHERE id = ?", (creator_id,))
            if cursor.rowcount == 0:
                raise KeyError("达人不存在")

    def add_messages(
        self, creator_id: int, messages: list[ParsedMessage], business_name: str
    ) -> tuple[int, int]:
        if not self.get_creator(creator_id):
            raise KeyError("达人不存在")
        added = 0
        now = datetime.now().isoformat(timespec="seconds")
        business_key = business_name.casefold().strip()
        with self.connect() as db:
            for message in messages:
                direction = "outgoing" if message.sender.casefold().strip() == business_key else "incoming"
                same_time = db.execute(
                    "SELECT body FROM messages WHERE creator_id = ? AND sent_at = ? AND sender = ?",
                    (creator_id, message.sent_at, message.sender),
                ).fetchall()
                comparison_key = _message_comparison_key(message.body)
                if any(_message_comparison_key(str(row["body"])) == comparison_key for row in same_time):
                    continue
                cursor = db.execute(
                    """
                    INSERT OR IGNORE INTO messages
                        (creator_id, sent_at, sender, body, direction, fingerprint, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        creator_id,
                        message.sent_at,
                        message.sender,
                        message.body,
                        direction,
                        message.fingerprint,
                        now,
                    ),
                )
                added += cursor.rowcount
            db.execute(
                "UPDATE creators SET updated_at = ? WHERE id = ?", (now, creator_id)
            )
        return added, len(messages) - added

    def list_messages(self, creator_id: int, limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM (
                    SELECT * FROM messages WHERE creator_id = ?
                    ORDER BY sent_at DESC, id DESC LIMIT ?
                ) ORDER BY sent_at ASC, id ASC
                """,
                (creator_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_context(self, creator_id: int, max_chars: int = 18000) -> list[dict[str, Any]]:
        messages = self.list_messages(creator_id, 120)
        selected: list[dict[str, Any]] = []
        used = 0
        for message in reversed(messages):
            cost = len(message["body"]) + len(message["sender"]) + 40
            if selected and used + cost > max_chars:
                break
            selected.append(message)
            used += cost
        return list(reversed(selected))

    def save_draft(self, creator_id: int, values: dict[str, str]) -> dict[str, Any]:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT INTO drafts(creator_id, intent, tone, english_reply, chinese_translation,
                                   strategy, risk_notes, provider, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    creator_id,
                    values.get("intent", ""),
                    values.get("tone", ""),
                    values.get("english_reply", ""),
                    values.get("chinese_translation", ""),
                    values.get("strategy", ""),
                    values.get("risk_notes", ""),
                    values.get("provider", ""),
                    now,
                ),
            )
            row = db.execute("SELECT * FROM drafts WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return dict(row) if row else {}

    def get_settings(self) -> dict[str, Any]:
        with self.connect() as db:
            rows = db.execute("SELECT key, value FROM settings").fetchall()
        result: dict[str, Any] = {}
        for row in rows:
            try:
                result[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                result[row["key"]] = row["value"]
        return result

    def set_settings(self, values: dict[str, Any]) -> None:
        with self.connect() as db:
            for key, value in values.items():
                db.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, json.dumps(value, ensure_ascii=False)),
                )
