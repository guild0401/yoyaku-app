"""Google カレンダー連携。

役割は 2 つだけ:
  1) busy_intervals(): 指定期間の「埋まっている時間帯」を返す → 空き枠計算に使う
  2) create_event():   予約確定時に予定を作成し、お客さんを参加者として招待する

demo_mode(config.json)が true の間は Google に一切アクセスせず、
busy は空・予定作成はスキップする。サービスアカウントを設定して false にすると本番動作。

認証はサービスアカウント方式:
  - GCP でサービスアカウントを作成し JSON 鍵を secrets/service_account.json に置く
  - その鍵のメールアドレスに、対象カレンダーを「予定の変更権限」付きで共有する
  詳細手順は deploy/GCP_SETUP.md。
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from .config import Config, get_config

# Google ライブラリは demo_mode のときは読み込まなくても動くよう遅延 import する
_SCOPES = ["https://www.googleapis.com/auth/calendar"]

# (start_utc, end_utc) の組で「埋まっている時間帯」を表す
Interval = Tuple[datetime, datetime]


class CalendarError(RuntimeError):
    pass


class CalendarClient:
    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or get_config()
        self._service = None  # 実サービスは初回利用時に生成(遅延)

    # ---- 内部: Google API サービスを用意 -------------------------------------
    def _get_service(self):
        if self._service is not None:
            return self._service
        path = self.cfg.service_account_path()
        if not path.exists():
            raise CalendarError(
                f"サービスアカウント鍵が見つかりません: {path}\n"
                "demo_mode を true にするか、deploy/GCP_SETUP.md の手順で鍵を設置してください。"
            )
        # 遅延 import(demo_mode のみで使う環境ではライブラリ不要)
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(
            str(path), scopes=_SCOPES
        )
        self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return self._service

    # ---- 1) 埋まっている時間帯 ------------------------------------------------
    def busy_intervals(self, time_min: datetime, time_max: datetime) -> List[Interval]:
        """time_min〜time_max の busy 区間。demo_mode では空リスト。"""
        if self.cfg.demo_mode:
            return []
        service = self._get_service()
        body = {
            "timeMin": _rfc3339(time_min),
            "timeMax": _rfc3339(time_max),
            "items": [{"id": self.cfg.calendar_id}],
        }
        try:
            resp = service.freebusy().query(body=body).execute()
        except Exception as e:  # noqa: BLE001 - API 由来の例外をまとめて包む
            raise CalendarError(f"freebusy 取得に失敗: {e}") from e
        cal = resp.get("calendars", {}).get(self.cfg.calendar_id, {})
        out: List[Interval] = []
        for b in cal.get("busy", []):
            out.append((_parse(b["start"]), _parse(b["end"])))
        return out

    # ---- 2) 予定作成 ----------------------------------------------------------
    def create_event(
        self,
        *,
        summary: str,
        description: str,
        start_utc: datetime,
        end_utc: datetime,
        customer_email: str,
        location: str = "",
    ) -> Optional[str]:
        """予定を作成し event_id を返す。demo_mode では None(作成スキップ)。"""
        if self.cfg.demo_mode:
            return None
        service = self._get_service()
        event = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {"dateTime": _rfc3339(start_utc), "timeZone": "Asia/Tokyo"},
            "end": {"dateTime": _rfc3339(end_utc), "timeZone": "Asia/Tokyo"},
        }
        if self.cfg.send_invite_to_customer and customer_email:
            event["attendees"] = [{"email": customer_email}]
        send_updates = "all" if self.cfg.send_invite_to_customer else "none"
        try:
            created = (
                service.events()
                .insert(
                    calendarId=self.cfg.calendar_id,
                    body=event,
                    sendUpdates=send_updates,
                )
                .execute()
            )
        except Exception as e:  # noqa: BLE001
            raise CalendarError(f"予定作成に失敗: {e}") from e
        return created.get("id")


# ---- 時刻変換ヘルパ -----------------------------------------------------------
def _rfc3339(dt: datetime) -> str:
    """tz 付き datetime を RFC3339 文字列へ。"""
    return dt.isoformat()


def _parse(s: str) -> datetime:
    """Google が返す RFC3339(末尾 Z 含む)を datetime に。"""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)
