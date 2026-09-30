"""空き枠計算・重複判定・管理画面認証の最小テスト。

外部（Googleカレンダー）には触れない。DBは一時ファイルに向ける。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from app import db
from app.config import JST, Config
from app.slots import _merge, compute_slots, validate_slot_free

UTC = timezone.utc


def make_config(**availability) -> Config:
    av = {
        "weekly_hours": {
            "mon": [["10:00", "18:00"]],
            "tue": [["10:00", "18:00"]],
            "wed": [],
            "thu": [["10:00", "18:00"]],
            "fri": [["10:00", "18:00"]],
            "sat": [],
            "sun": [],
        },
        "slot_granularity_min": 30,
        "buffer_min": 15,
        "min_notice_hours": 0,
        "max_advance_days": 2,
        "blackout_dates": [],
    }
    av.update(availability)
    return Config({"availability": av, "menus": []})


def jst(y, m, d, hh, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=JST)


# 2026-10-05 は月曜。日本時間 0:00 を「今」とする
NOW = jst(2026, 10, 5, 0).astimezone(UTC)


def slot_times(days, iso_day):
    for d in days:
        if d["date"] == iso_day:
            return [s["time"] for s in d["slots"]]
    raise AssertionError(f"{iso_day} が返っていない")


# ---- 空き枠計算 ----------------------------------------------------------------

def test_slots_exclude_busy_with_buffer():
    cfg = make_config()
    busy = [(jst(2026, 10, 5, 12), jst(2026, 10, 5, 13))]  # 12:00-13:00 の予定
    days = compute_slots(cfg, 30, NOW, busy, [])
    times = slot_times(days, "2026-10-05")
    # 30分枠・10:00〜18:00 なら 16 枠。バッファ15分込みで 11:30/12:00/12:30/13:00 の4枠が消える
    assert len(times) == 12
    for t in ("11:30", "12:00", "12:30", "13:00"):
        assert t not in times
    for t in ("10:00", "11:00", "13:30", "17:30"):
        assert t in times


def test_slots_respect_blackout_and_closed_days():
    cfg = make_config(blackout_dates=["2026-10-06"])
    days = compute_slots(cfg, 30, NOW, [], [])
    assert slot_times(days, "2026-10-06") == []   # 休業日
    assert slot_times(days, "2026-10-07") == []   # 水曜は weekly_hours が空
    assert len(days) == 3                          # 空きゼロの日も date は返す


def test_slots_respect_min_notice():
    cfg = make_config(min_notice_hours=2)
    now = jst(2026, 10, 5, 10).astimezone(UTC)     # 月曜 10:00 に見ている
    times = slot_times(compute_slots(cfg, 30, now, [], []), "2026-10-05")
    assert "11:30" not in times
    assert times[0] == "12:00"


def test_merge_joins_overlapping_and_adjacent():
    a = (jst(2026, 10, 5, 10), jst(2026, 10, 5, 11))
    b = (jst(2026, 10, 5, 11), jst(2026, 10, 5, 12))   # 隣接
    c = (jst(2026, 10, 5, 15), jst(2026, 10, 5, 16))   # 離れている
    merged = _merge([c, b, a])
    assert merged == [(a[0], b[1]), c]


# ---- 確定直前の再判定 ------------------------------------------------------------

def test_validate_slot_free_rejects_overlap_and_out_of_hours():
    cfg = make_config()
    start = jst(2026, 10, 5, 14).astimezone(UTC)
    ok, reason = validate_slot_free(cfg, start, 30, NOW, [], [])
    assert ok and reason == ""

    existing = [(jst(2026, 10, 5, 14, 30).astimezone(UTC), jst(2026, 10, 5, 15).astimezone(UTC))]
    ok, reason = validate_slot_free(cfg, start, 60, NOW, [], existing)
    assert not ok and "埋まって" in reason

    late = jst(2026, 10, 5, 17, 45).astimezone(UTC)   # 17:45 開始の30分は 18:00 を超える
    ok, reason = validate_slot_free(cfg, late, 30, NOW, [], [])
    assert not ok and "時間外" in reason


# ---- SQLite の重複判定 ------------------------------------------------------------

def _booking(start: datetime, minutes: int = 30) -> dict:
    return {
        "menu_id": "m", "menu_name": "menu",
        "start_utc": start.isoformat(),
        "end_utc": (start + timedelta(minutes=minutes)).isoformat(),
        "customer_name": "テスト", "customer_email": "test@example.com",
        "customer_phone": "", "note": "", "gcal_event_id": None,
        "created_at": NOW.isoformat(),
    }


def test_overlapping_bookings(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    s = jst(2026, 10, 5, 14).astimezone(UTC)
    booking_id = db.create_booking(_booking(s, 30))            # 14:00-14:30

    assert len(db.overlapping_bookings(s + timedelta(minutes=15), s + timedelta(minutes=45))) == 1
    assert db.overlapping_bookings(s + timedelta(minutes=30), s + timedelta(minutes=60)) == []  # 隣接は重ならない
    assert db.overlapping_bookings(s - timedelta(minutes=30), s) == []

    with db._connect() as con:                                   # キャンセル済みは数えない
        con.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
    assert db.overlapping_bookings(s, s + timedelta(minutes=30)) == []


# ---- /admin の認証 ------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    with TestClient(app) as c:
        yield c


def test_admin_disabled_without_env(client, monkeypatch):
    monkeypatch.delenv("YOYAKU_ADMIN_TOKEN", raising=False)
    assert client.get("/admin?token=anything").status_code == 404


def test_admin_accepts_bearer_and_query(client, monkeypatch):
    monkeypatch.setenv("YOYAKU_ADMIN_TOKEN", "correct-token")
    assert client.get("/admin").status_code == 403
    assert client.get("/admin", headers={"Authorization": "Bearer wrong"}).status_code == 403
    assert client.get("/admin?token=wrong").status_code == 403
    assert client.get("/admin", headers={"Authorization": "Bearer correct-token"}).status_code == 200
    assert client.get("/admin?token=correct-token").status_code == 200
    # ヘッダが正しければクエリの値は見ない
    assert client.get("/admin?token=wrong", headers={"Authorization": "Bearer correct-token"}).status_code == 200
