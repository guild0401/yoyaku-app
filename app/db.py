"""予約データの保存(SQLite)。

Google カレンダーが予約台帳の本体だが、アプリ側でも予約を持つ理由は 2 つ:
 1) ダブルブッキング判定を自前でも行い、カレンダー連携が一時的に切れても破綻しない
 2) 管理用に「誰がいつ何を予約したか」を素早く一覧できる
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, List, Optional

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "bookings.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    menu_id         TEXT    NOT NULL,
    menu_name       TEXT    NOT NULL,
    start_utc       TEXT    NOT NULL,   -- ISO8601(UTC) 開始
    end_utc         TEXT    NOT NULL,   -- ISO8601(UTC) 終了(バッファ含まず)
    customer_name   TEXT    NOT NULL,
    customer_email  TEXT    NOT NULL,
    customer_phone  TEXT,
    note            TEXT,
    status          TEXT    NOT NULL DEFAULT 'confirmed',  -- confirmed / cancelled
    gcal_event_id   TEXT,
    created_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bookings_start ON bookings(start_utc);
CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);
"""


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as con:
        con.executescript(SCHEMA)


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def overlapping_bookings(start_utc: datetime, end_utc: datetime) -> List[sqlite3.Row]:
    """[start, end) と時間が重なる confirmed 予約を返す(バッファ込みの判定は呼び出し側)。"""
    s = start_utc.isoformat()
    e = end_utc.isoformat()
    with _connect() as con:
        cur = con.execute(
            """
            SELECT * FROM bookings
            WHERE status = 'confirmed'
              AND start_utc < ?   -- 既存開始 < 新規終了
              AND end_utc   > ?   -- 既存終了 > 新規開始
            """,
            (e, s),
        )
        return cur.fetchall()


def all_confirmed_between(start_utc: datetime, end_utc: datetime) -> List[sqlite3.Row]:
    with _connect() as con:
        cur = con.execute(
            """
            SELECT * FROM bookings
            WHERE status = 'confirmed' AND end_utc > ? AND start_utc < ?
            ORDER BY start_utc
            """,
            (start_utc.isoformat(), end_utc.isoformat()),
        )
        return cur.fetchall()


def create_booking(data: Dict) -> int:
    with _connect() as con:
        cur = con.execute(
            """
            INSERT INTO bookings
              (menu_id, menu_name, start_utc, end_utc, customer_name,
               customer_email, customer_phone, note, status, gcal_event_id, created_at)
            VALUES (:menu_id, :menu_name, :start_utc, :end_utc, :customer_name,
                    :customer_email, :customer_phone, :note, 'confirmed',
                    :gcal_event_id, :created_at)
            """,
            data,
        )
        return cur.lastrowid


def set_event_id(booking_id: int, event_id: str) -> None:
    with _connect() as con:
        con.execute(
            "UPDATE bookings SET gcal_event_id = ? WHERE id = ?",
            (event_id, booking_id),
        )


def get_booking(booking_id: int) -> Optional[sqlite3.Row]:
    with _connect() as con:
        cur = con.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
        return cur.fetchone()


def list_recent(limit: int = 200) -> List[sqlite3.Row]:
    with _connect() as con:
        cur = con.execute(
            "SELECT * FROM bookings ORDER BY start_utc DESC LIMIT ?", (limit,)
        )
        return cur.fetchall()
