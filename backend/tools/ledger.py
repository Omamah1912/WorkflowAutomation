"""The 'system entry': an idempotent SQLite ledger keyed on (doc_id, track_id).
Writing the same track twice is a no-op, so retries and re-runs can never double-book."""
import json
import os
import sqlite3
import threading
from pathlib import Path

from state import now_iso
from tools.config import RUNTIME

_lock = threading.Lock()


def _db_path() -> Path:
    return Path(os.environ.get("LEDGER_PATH", RUNTIME / "ledger.sqlite"))


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE IF NOT EXISTS entries (
        doc_id TEXT NOT NULL, track_id TEXT NOT NULL, payload TEXT NOT NULL,
        approved_by TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY (doc_id, track_id))""")
    return conn


def write(doc_id: str, track_id: str, payload: dict, approved_by: str) -> bool:
    """Insert once. Returns True if a new row was written, False if it already existed."""
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO entries VALUES (?, ?, ?, ?, ?)",
            (doc_id, track_id, json.dumps(payload, default=str), approved_by, now_iso()))
        return cur.rowcount == 1


def entries(doc_id: str | None = None) -> list[dict]:
    with _lock, _connect() as conn:
        sql, args = "SELECT doc_id, track_id, payload, approved_by, created_at FROM entries", ()
        if doc_id:
            sql, args = sql + " WHERE doc_id = ?", (doc_id,)
        rows = conn.execute(sql, args).fetchall()
    return [{"doc_id": r[0], "track_id": r[1], "payload": json.loads(r[2]),
             "approved_by": r[3], "created_at": r[4]} for r in rows]
