"""お客さん向けの API(予約フロー)。

  GET  /api/config         画面に出す事業名・メニュー一覧
  GET  /api/slots          指定メニューの空き枠
  POST /api/bookings       予約確定
"""
from __future__ import annotations

import logging
import re
import time as _time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from ..calendar_client import CalendarClient, CalendarError
from ..config import JST, get_config
from .. import db
from ..slots import compute_slots, validate_slot_free

log = logging.getLogger("yoyaku")
router = APIRouter()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# 簡易レート制限(同一 IP からの予約連打/スパム抑止)。1 プロセス内のメモリのみ。
_RATE: Dict[str, List[float]] = defaultdict(list)
_RATE_WINDOW_SEC = 600     # 10 分
_RATE_MAX = 5              # 10 分で 5 件まで


def _client_ip(req: Request) -> str:
    # リバースプロキシ・トンネル経由を考慮して実 IP ヘッダを優先(前段が信頼できる場合のみ有効)
    fwd = req.headers.get("cf-connecting-ip") or req.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return req.client.host if req.client else "unknown"


def _rate_ok(ip: str) -> bool:
    now = _time.monotonic()
    hits = [t for t in _RATE[ip] if now - t < _RATE_WINDOW_SEC]
    hits.append(now)
    _RATE[ip] = hits
    return len(hits) <= _RATE_MAX


# ---- GET /api/config ----------------------------------------------------------
@router.get("/api/config")
def api_config() -> Dict:
    cfg = get_config()
    return {
        "business_name": cfg.business_name,
        "tagline": cfg.tagline,
        "menus": [m.public_dict() for m in cfg.menus],
    }


# ---- GET /api/slots -----------------------------------------------------------
@router.get("/api/slots")
def api_slots(menu_id: str) -> Dict:
    cfg = get_config()
    menu = cfg.menu(menu_id)
    if not menu:
        raise HTTPException(status_code=404, detail="メニューが見つかりません")

    now_utc = datetime.now(timezone.utc)
    window_start = now_utc
    window_end = now_utc + timedelta(days=cfg.max_advance_days + 1)

    cal = CalendarClient(cfg)
    try:
        busy = cal.busy_intervals(window_start, window_end)
    except CalendarError as e:
        log.error("busy 取得失敗: %s", e)
        raise HTTPException(status_code=503, detail="カレンダーに接続できませんでした。時間をおいてお試しください。")

    bookings = _booking_intervals(window_start, window_end)
    days = compute_slots(cfg, menu.duration_min, now_utc, busy, bookings)
    return {"menu": menu.public_dict(), "days": days}


# ---- POST /api/bookings -------------------------------------------------------
class BookingIn(BaseModel):
    menu_id: str
    start: str  # ISO8601 (tz 付き)
    name: str
    email: str
    phone: Optional[str] = ""
    note: Optional[str] = ""

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = (v or "").strip()
        if not (1 <= len(v) <= 100):
            raise ValueError("お名前を入力してください(100文字以内)")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = (v or "").strip()
        if not _EMAIL_RE.match(v):
            raise ValueError("メールアドレスの形式が正しくありません")
        return v

    @field_validator("note")
    @classmethod
    def _note(cls, v: Optional[str]) -> str:
        v = (v or "").strip()
        if len(v) > 2000:
            raise ValueError("ご相談内容は2000文字以内で入力してください")
        return v


@router.post("/api/bookings")
def api_create_booking(payload: BookingIn, request: Request) -> Dict:
    cfg = get_config()
    menu = cfg.menu(payload.menu_id)
    if not menu:
        raise HTTPException(status_code=404, detail="メニューが見つかりません")

    if not _rate_ok(_client_ip(request)):
        raise HTTPException(status_code=429, detail="短時間に予約が集中しています。少し時間をおいてください。")

    # 開始時刻のパース(tz 付き必須)→ UTC へ
    try:
        start_dt = datetime.fromisoformat(payload.start)
    except ValueError:
        raise HTTPException(status_code=400, detail="日時の形式が不正です")
    if start_dt.tzinfo is None:
        raise HTTPException(status_code=400, detail="タイムゾーン付きの日時を指定してください")
    start_utc = start_dt.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(minutes=menu.duration_min)
    now_utc = datetime.now(timezone.utc)

    # 直前の空き再判定(カレンダー busy + 既存予約)
    cal = CalendarClient(cfg)
    pad = timedelta(minutes=cfg.buffer_min + menu.duration_min)
    try:
        busy = cal.busy_intervals(start_utc - pad, end_utc + pad)
    except CalendarError as e:
        log.error("確定時 busy 取得失敗: %s", e)
        raise HTTPException(status_code=503, detail="カレンダーに接続できませんでした。時間をおいてお試しください。")
    bookings = _booking_intervals(start_utc - pad, end_utc + pad)

    ok, reason = validate_slot_free(cfg, start_utc, menu.duration_min, now_utc, busy, bookings)
    if not ok:
        raise HTTPException(status_code=409, detail=reason)

    # DB に先に確保(自分のアプリ内での二重取りを防ぐ)
    booking_id = db.create_booking(
        {
            "menu_id": menu.id,
            "menu_name": menu.name,
            "start_utc": start_utc.isoformat(),
            "end_utc": end_utc.isoformat(),
            "customer_name": payload.name,
            "customer_email": payload.email,
            "customer_phone": (payload.phone or "").strip(),
            "note": payload.note or "",
            "gcal_event_id": None,
            "created_at": now_utc.isoformat(),
        }
    )

    # カレンダーに予定作成(招待送信)。失敗しても予約自体は有効として残す。
    event_warning = None
    try:
        summary = f"{menu.name} / {payload.name}様"
        description = (
            f"メニュー: {menu.name}\n"
            f"お名前: {payload.name}様\n"
            f"メール: {payload.email}\n"
            f"電話: {(payload.phone or '').strip() or '—'}\n"
            f"ご相談内容:\n{payload.note or '—'}\n\n"
            f"(予約アプリより自動作成 / 予約ID {booking_id})"
        )
        event_id = cal.create_event(
            summary=summary,
            description=description,
            start_utc=start_utc,
            end_utc=end_utc,
            customer_email=payload.email,
            location=menu.location,
        )
        if event_id:
            db.set_event_id(booking_id, event_id)
    except CalendarError as e:
        log.error("予定作成失敗(予約ID %s): %s", booking_id, e)
        event_warning = "予約は確定しましたが、カレンダー登録に失敗しました。担当者が手動で確認します。"

    start_jst = start_utc.astimezone(JST)
    return {
        "booking_id": booking_id,
        "menu_name": menu.name,
        "start_jst": start_jst.isoformat(),
        "display": start_jst.strftime("%Y年%-m月%-d日 %H:%M"),
        "duration_min": menu.duration_min,
        "location": menu.location,
        "warning": event_warning,
    }


def _booking_intervals(start_utc: datetime, end_utc: datetime) -> List[Tuple[datetime, datetime]]:
    rows = db.all_confirmed_between(start_utc, end_utc)
    out: List[Tuple[datetime, datetime]] = []
    for r in rows:
        out.append(
            (
                datetime.fromisoformat(r["start_utc"]),
                datetime.fromisoformat(r["end_utc"]),
            )
        )
    return out
