"""Optional SQLite-only memory backend; no embedding model or FAISS required.

This store is intentionally independent from the existing vector runtime so it can
be tested and migrated before switching the production kernel to sqlite_fts.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any


def _tokens(text: str) -> str:
    """Produce searchable terms for mixed Chinese/Japanese/Latin messages."""
    text = str(text or "").casefold()
    words = re.findall(r"[a-z0-9_]+|[\u3400-\u9fff\u3040-\u30ff]+", text)
    terms: list[str] = []
    for word in words:
        if re.search(r"[\u3400-\u9fff\u3040-\u30ff]", word):
            terms.extend(word[i:i + 2] for i in range(len(word) - 1))
            if len(word) == 1:
                terms.append(word)
        else:
            terms.append(word)
    return " ".join(terms)


class SQLiteFTSMemoryStore:
    """Owns a separate SQLite database; never modifies existing metadata.db."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS person_profiles (
                qq_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                group_name TEXT NOT NULL DEFAULT '',
                group_nickname TEXT NOT NULL DEFAULT '',
                original_nickname TEXT NOT NULL DEFAULT '',
                aliases_json TEXT NOT NULL DEFAULT '[]',
                notes_json TEXT NOT NULL DEFAULT '{}',
                updated_at REAL NOT NULL,
                PRIMARY KEY (qq_id, group_id)
            );
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qq_id TEXT NOT NULL DEFAULT '',
                group_id TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                search_terms TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                search_terms, content='memories', content_rowid='id'
            );
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, search_terms)
                VALUES (new.id, new.search_terms);
            END;
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, search_terms)
                VALUES ('delete', old.id, old.search_terms);
            END;
            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, search_terms)
                VALUES ('delete', old.id, old.search_terms);
                INSERT INTO memories_fts(rowid, search_terms)
                VALUES (new.id, new.search_terms);
            END;
        """)
        self.db.commit()

    def upsert_profile(
        self, *, qq_id: str, group_id: str, group_name: str = "",
        group_nickname: str = "", original_nickname: str = "",
        aliases: list[str] | None = None, notes: dict[str, Any] | None = None,
    ) -> None:
        if not qq_id or not group_id:
            raise ValueError("qq_id and group_id are required")
        existing = self.get_profile(qq_id=qq_id, group_id=group_id)
        old_aliases = existing["aliases"] if existing else []
        old_notes = existing["notes"] if existing else {}
        merged_aliases = list(dict.fromkeys(
            str(x).strip() for x in [*old_aliases, *(aliases or [])] if str(x).strip()
        ))
        merged_notes = {**old_notes, **(notes or {})}
        self.db.execute("""
            INSERT INTO person_profiles
            (qq_id, group_id, group_name, group_nickname, original_nickname,
             aliases_json, notes_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(qq_id, group_id) DO UPDATE SET
                group_name=excluded.group_name,
                group_nickname=excluded.group_nickname,
                original_nickname=excluded.original_nickname,
                aliases_json=excluded.aliases_json,
                notes_json=excluded.notes_json,
                updated_at=excluded.updated_at
        """, (
            str(qq_id), str(group_id),
            group_name or (existing["group_name"] if existing else ""),
            group_nickname or (existing["group_nickname"] if existing else ""),
            original_nickname or (existing["original_nickname"] if existing else ""),
            json.dumps(merged_aliases, ensure_ascii=False),
            json.dumps(merged_notes, ensure_ascii=False), time.time(),
        ))
        self.db.commit()

    def get_profile(self, *, qq_id: str, group_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT * FROM person_profiles WHERE qq_id=? AND group_id=?",
            (str(qq_id), str(group_id)),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["aliases"] = json.loads(result.pop("aliases_json"))
        result["notes"] = json.loads(result.pop("notes_json"))
        return result

    def add_memory(self, content: str, *, qq_id: str = "", group_id: str = "") -> int:
        if not content.strip():
            raise ValueError("memory content must not be empty")
        cursor = self.db.execute(
            "INSERT INTO memories (qq_id, group_id, content, search_terms, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (str(qq_id), str(group_id), content, _tokens(content), time.time()),
        )
        self.db.commit()
        return int(cursor.lastrowid)

    def search(self, query: str, *, qq_id: str = "", group_id: str = "",
               limit: int = 10) -> list[dict[str, Any]]:
        tokens = list(dict.fromkeys(_tokens(query).split()))
        if not tokens:
            return []
        expression = " OR ".join(f'"{token}"' for token in tokens)
        sql = """
            SELECT m.id, m.qq_id, m.group_id, m.content, m.created_at,
                   bm25(memories_fts) AS score
            FROM memories_fts
            JOIN memories AS m ON m.id=memories_fts.rowid
            WHERE memories_fts MATCH ?
        """
        params: list[Any] = [expression]
        if qq_id:
            sql += " AND m.qq_id=?"
            params.append(str(qq_id))
        if group_id:
            sql += " AND m.group_id=?"
            params.append(str(group_id))
        sql += " ORDER BY score ASC, m.created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 100)))
        return [dict(row) for row in self.db.execute(sql, params)]

    def close(self) -> None:
        self.db.close()
