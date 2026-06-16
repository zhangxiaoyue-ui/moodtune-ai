"""MoodTune AI — SQLite 历史与心情日记。"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "moodtune_history.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                emotion_text TEXT,
                tags TEXT,
                scene TEXT,
                energy INTEGER,
                songs_json TEXT,
                feedback TEXT,
                diary_text TEXT DEFAULT ''
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rec_device_time "
            "ON recommendations(device_id, timestamp DESC)"
        )
        conn.commit()


def insert_recommendation(
    device_id: str,
    emotion_text: str,
    tags: list[str],
    scene: str,
    energy: int,
    songs: list[dict[str, Any]],
    feedback: dict[str, Any] | None = None,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO recommendations
            (device_id, timestamp, emotion_text, tags, scene, energy, songs_json, feedback, diary_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '')
            """,
            (
                device_id,
                time.time(),
                emotion_text,
                json.dumps(tags, ensure_ascii=False),
                scene,
                energy,
                json.dumps(songs, ensure_ascii=False),
                json.dumps(feedback or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def update_diary(record_id: int, device_id: str, diary_text: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE recommendations SET diary_text = ?
            WHERE id = ? AND device_id = ?
            """,
            (diary_text.strip(), record_id, device_id),
        )
        conn.commit()
        return cur.rowcount > 0


def list_history(device_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM recommendations
            WHERE device_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (device_id, limit),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_record(record_id: int, device_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM recommendations WHERE id = ? AND device_id = ?",
            (record_id, device_id),
        ).fetchone()
    return _row_to_dict(row) if row else None


def clear_history(device_id: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM recommendations WHERE device_id = ?",
            (device_id,),
        )
        conn.commit()
        return cur.rowcount


def fetch_trends(device_id: str, days: int = 30) -> list[dict[str, Any]]:
    since = time.time() - days * 86400
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM recommendations
            WHERE device_id = ? AND timestamp >= ?
            ORDER BY timestamp ASC
            """,
            (device_id, since),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    songs = json.loads(row["songs_json"] or "[]")
    tags = json.loads(row["tags"] or "[]")
    feedback = json.loads(row["feedback"] or "{}")
    return {
        "id": row["id"],
        "device_id": row["device_id"],
        "timestamp": row["timestamp"],
        "emotion_text": row["emotion_text"] or "",
        "tags": tags if isinstance(tags, list) else [],
        "scene": row["scene"] or "",
        "energy": row["energy"],
        "songs": songs if isinstance(songs, list) else [],
        "feedback": feedback,
        "diary_text": row["diary_text"] or "",
    }
