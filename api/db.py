"""
This DB is the single source of truth for ticket state. ONLY the api process
writes to it; the cv process never opens it - the cv process only ever sees a
ticket_dir path and returns an AnalyzeResponse over HTTP.

Plain sqlite3, no ORM, explicit SQL. A connection is opened and closed per
call - simple and adequate at hackathon scale, no pooling needed.
"""

import sqlite3
from datetime import datetime, timezone

from api.config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  result TEXT
)
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def insert_ticket(ticket_id: str, status: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO tickets (id, status, created_at, result) VALUES (?, ?, ?, ?)",
            (ticket_id, status, datetime.now(timezone.utc).isoformat(), None),
        )
        conn.commit()
    finally:
        conn.close()


def update_ticket(ticket_id: str, status: str, result: str | None = None) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE tickets SET status = ?, result = ? WHERE id = ?",
            (status, result, ticket_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_ticket(ticket_id: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, status, created_at, result FROM tickets WHERE id = ?",
            (ticket_id,),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def list_tickets(limit: int = 50) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, status, created_at, result FROM tickets ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
