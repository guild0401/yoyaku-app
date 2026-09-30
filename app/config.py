"""設定ファイル(config.json)の読み込みと検証。

アプリ全体の振る舞い(メニュー・営業時間・カレンダー設定)を 1 つの JSON に集約し、
コードを触らずに運用できるようにしている。起動時に 1 回読み込む。
"""
from __future__ import annotations

import json
from datetime import timezone, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

# プロジェクトルート(= このファイルの 2 つ上)を基準に相対パスを解決する
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

# 日本は夏時間が無いので固定オフセット(+09:00)で十分・zoneinfo 不要でトラブルが少ない
JST = timezone(timedelta(hours=9))


class Menu:
    def __init__(self, raw: Dict[str, Any]):
        self.id: str = raw["id"]
        self.name: str = raw["name"]
        self.duration_min: int = int(raw["duration_min"])
        self.price: Optional[int] = raw.get("price")
        self.description: str = raw.get("description", "")
        self.location: str = raw.get("location", "")

    def public_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "duration_min": self.duration_min,
            "price": self.price,
            "description": self.description,
            "location": self.location,
        }


class Config:
    def __init__(self, raw: Dict[str, Any]):
        self.raw = raw
        biz = raw.get("business", {})
        self.business_name: str = biz.get("name", "予約ページ")
        self.tagline: str = biz.get("tagline", "")
        self.contact_email: str = biz.get("contact_email", "")

        cal = raw.get("calendar", {})
        self.demo_mode: bool = bool(cal.get("demo_mode", True))
        self.calendar_id: str = cal.get("calendar_id", "primary")
        self.service_account_file: str = cal.get(
            "service_account_file", "secrets/service_account.json"
        )
        self.send_invite_to_customer: bool = bool(
            cal.get("send_invite_to_customer", True)
        )

        av = raw.get("availability", {})
        self.weekly_hours: Dict[str, List[List[str]]] = av.get("weekly_hours", {})
        self.slot_granularity_min: int = int(av.get("slot_granularity_min", 30))
        self.buffer_min: int = int(av.get("buffer_min", 0))
        self.min_notice_hours: int = int(av.get("min_notice_hours", 0))
        self.max_advance_days: int = int(av.get("max_advance_days", 30))
        self.blackout_dates: List[str] = av.get("blackout_dates", [])

        self.menus: List[Menu] = [Menu(m) for m in raw.get("menus", [])]
        self._menu_by_id = {m.id: m for m in self.menus}

    def menu(self, menu_id: str) -> Optional[Menu]:
        return self._menu_by_id.get(menu_id)

    def service_account_path(self) -> Path:
        p = Path(self.service_account_file)
        return p if p.is_absolute() else (ROOT / p)


@lru_cache(maxsize=1)
def get_config() -> Config:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)
    return Config(raw)
