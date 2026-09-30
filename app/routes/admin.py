"""管理用の予約一覧(おまけ)。

本来の「管理画面」は Google カレンダーそのもの。ここはカレンダーを見ない時用の簡易一覧。
環境変数 YOYAKU_ADMIN_TOKEN を設定したときだけ有効。未設定なら 404(=無効)。

認証は次の順で見る:
  1) Authorization: Bearer <token> ヘッダ(推奨。URL・ブラウザ履歴・アクセスログにトークンが残らない)
  2) クエリ ?token=<token>(互換のため残す。ブラウザで直接開く用途)
"""
from __future__ import annotations

import hmac
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from markupsafe import escape

from ..config import JST
from .. import db

router = APIRouter()


def _extract_token(authorization: Optional[str], query_token: str) -> str:
    """Bearer ヘッダがあればそれを、無ければクエリの値を返す。"""
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    return query_token


def _check(token: str) -> None:
    expected = os.environ.get("YOYAKU_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=404, detail="Not found")
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="トークンが違います")


@router.get("/admin", response_class=HTMLResponse)
def admin_page(
    token: str = Query(""),
    authorization: Optional[str] = Header(default=None),
) -> str:
    _check(_extract_token(authorization, token))
    rows = db.list_recent(300)
    body = []
    for r in rows:
        start_jst = datetime.fromisoformat(r["start_utc"]).astimezone(JST)
        body.append(
            "<tr>"
            f"<td>{r['id']}</td>"
            f"<td>{escape(start_jst.strftime('%Y-%m-%d %H:%M'))}</td>"
            f"<td>{escape(r['menu_name'])}</td>"
            f"<td>{escape(r['customer_name'])}</td>"
            f"<td>{escape(r['customer_email'])}</td>"
            f"<td>{escape(r['customer_phone'] or '')}</td>"
            f"<td>{escape(r['status'])}</td>"
            "</tr>"
        )
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>予約一覧</title>
<style>
 body{{font-family:-apple-system,sans-serif;margin:24px;color:#1a1a1a}}
 table{{border-collapse:collapse;width:100%;font-size:14px}}
 th,td{{border:1px solid #ddd;padding:8px;text-align:left}}
 th{{background:#f4f4f6}}
</style></head><body>
<h1>予約一覧（{len(rows)}件）</h1>
<p style="color:#666">本来の管理は Google カレンダーで。これは予備の一覧です。</p>
<table>
<tr><th>ID</th><th>開始(JST)</th><th>メニュー</th><th>お名前</th><th>メール</th><th>電話</th><th>状態</th></tr>
{''.join(body)}
</table></body></html>"""
