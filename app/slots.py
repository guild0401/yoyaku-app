"""空き枠の計算。

考え方(引き算):
   営業時間(config) − カレンダーの予定(busy) − 既存予約(DB) − 受付下限/上限
   = 予約できる開始時刻の一覧

すべて tz 付き datetime で扱う。営業時間の "10:00" 等はその日の JST の壁時計時刻として解釈し、
重なり判定・保存は UTC に揃える(カレンダー API も UTC ベースのため)。
"""
from __future__ import annotations

from datetime import datetime, date, time, timedelta
from typing import Dict, List, Tuple

from .config import Config, JST

Interval = Tuple[datetime, datetime]

_WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]


def _merge(intervals: List[Interval]) -> List[Interval]:
    """重なる/隣接する区間をまとめる。"""
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda iv: iv[0])
    merged = [ordered[0]]
    for s, e in ordered[1:]:
        ls, le = merged[-1]
        if s <= le:
            merged[-1] = (ls, max(le, e))
        else:
            merged.append((s, e))
    return merged


def _overlaps(a: Interval, blocked: List[Interval]) -> bool:
    s, e = a
    for bs, be in blocked:
        if s < be and e > bs:  # 端が触れるだけ(=隣接)は重なり扱いしない
            return True
    return False


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def compute_slots(
    cfg: Config,
    duration_min: int,
    now_utc: datetime,
    busy: List[Interval],
    bookings: List[Interval],
) -> List[Dict]:
    """日付ごとの空き枠を返す。

    返り値: [{ "date": "2026-06-20", "weekday": "金", "slots": [
                {"start": "<ISO UTC>", "time": "14:00"}, ... ] }, ... ]
    空きが 0 件の日も date は返す(カレンダー表示で「×」を出せるように)。
    """
    duration = timedelta(minutes=duration_min)
    buffer_td = timedelta(minutes=cfg.buffer_min)
    granularity = timedelta(minutes=max(5, cfg.slot_granularity_min))
    earliest = now_utc + timedelta(hours=cfg.min_notice_hours)

    # 予定・予約をバッファ分だけ前後に膨らませて 1 本化(前後の間隔を確保)
    blocked = _merge(
        [(s - buffer_td, e + buffer_td) for s, e in busy]
        + [(s - buffer_td, e + buffer_td) for s, e in bookings]
    )

    today_jst = now_utc.astimezone(JST).date()
    out: List[Dict] = []

    for day_offset in range(cfg.max_advance_days + 1):
        d: date = today_jst + timedelta(days=day_offset)
        iso_day = d.isoformat()
        if iso_day in cfg.blackout_dates:
            out.append({"date": iso_day, "weekday": _WEEKDAY_JA[d.weekday()], "slots": []})
            continue

        windows = cfg.weekly_hours.get(_WEEKDAY_KEYS[d.weekday()], [])
        day_slots: List[Dict] = []

        for win in windows:
            open_t = _parse_hhmm(win[0])
            close_t = _parse_hhmm(win[1])
            win_open = datetime.combine(d, open_t, tzinfo=JST)
            win_close = datetime.combine(d, close_t, tzinfo=JST)

            cursor = win_open
            while cursor + duration <= win_close:
                start_utc = cursor.astimezone(now_utc.tzinfo)
                end_utc = start_utc + duration
                if start_utc >= earliest and not _overlaps((start_utc, end_utc), blocked):
                    day_slots.append(
                        {
                            "start": start_utc.isoformat(),
                            "time": cursor.strftime("%H:%M"),
                        }
                    )
                cursor += granularity

        out.append(
            {"date": iso_day, "weekday": _WEEKDAY_JA[d.weekday()], "slots": day_slots}
        )

    return out


def validate_slot_free(
    cfg: Config,
    start_utc: datetime,
    duration_min: int,
    now_utc: datetime,
    busy: List[Interval],
    bookings: List[Interval],
) -> Tuple[bool, str]:
    """予約確定の直前に「その枠がまだ空いているか」を厳密に再判定する。"""
    duration = timedelta(minutes=duration_min)
    end_utc = start_utc + duration
    buffer_td = timedelta(minutes=cfg.buffer_min)
    earliest = now_utc + timedelta(hours=cfg.min_notice_hours)
    latest = now_utc + timedelta(days=cfg.max_advance_days + 1)

    if start_utc < earliest:
        return False, "受付できる最短時刻より前です。"
    if start_utc > latest:
        return False, "受付できる期間を過ぎています。"

    # 営業時間内か(JST の壁時計で判定)
    start_jst = start_utc.astimezone(JST)
    end_jst = end_utc.astimezone(JST)
    windows = cfg.weekly_hours.get(_WEEKDAY_KEYS[start_jst.weekday()], [])
    if start_jst.date().isoformat() in cfg.blackout_dates:
        return False, "その日は受付しておりません。"
    in_window = False
    for win in windows:
        w_open = datetime.combine(start_jst.date(), _parse_hhmm(win[0]), tzinfo=JST)
        w_close = datetime.combine(start_jst.date(), _parse_hhmm(win[1]), tzinfo=JST)
        if start_jst >= w_open and end_jst <= w_close:
            in_window = True
            break
    if not in_window:
        return False, "受付時間外です。"

    blocked = _merge(
        [(s - buffer_td, e + buffer_td) for s, e in busy]
        + [(s - buffer_td, e + buffer_td) for s, e in bookings]
    )
    if _overlaps((start_utc, end_utc), blocked):
        return False, "その時間はすでに埋まっています。別の時間をお選びください。"
    return True, ""
