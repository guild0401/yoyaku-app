# yoyaku-app — Googleカレンダー連携の予約ページ

メニュー（相談の種類）を選ぶ → 空き時間を選ぶ → お客様情報を入れて予約、の3ステップで完結する
予約ページです。予約が入ると受け手のGoogleカレンダーに予定が作られ、お客様には招待（確認）が届きます。

- 受け手は1人（設定ファイルで複数メニューを持てる）
- 空き枠は「営業時間 − Googleカレンダーの予定 − 既存予約」から自動で計算
- 管理画面はGoogleカレンダーそのもの。予備として簡易一覧 `/admin` あり
- **デモモード**ではGoogleカレンダーなしで動く（見た目と操作感の確認用）

## 技術構成

| 層 | 内容 |
|---|---|
| サーバー | Python 3.9+ / FastAPI / uvicorn |
| 保存 | SQLite（`data/bookings.db`・標準ライブラリの `sqlite3`） |
| 外部連携 | Google Calendar API v3（サービスアカウント認証・`freebusy` と `events.insert`） |
| 画面 | Jinja2テンプレート1枚＋素のJavaScript（フレームワークなし） |
| 検証 | pydantic v2（入力値の検証） |

```
app/
  main.py            FastAPI 本体（ページ・静的ファイル・API のまとめ）
  config.py          config.json の読み込み
  db.py              予約のSQLite保存・重複判定
  calendar_client.py Googleカレンダー連携（busy取得・予定作成）
  slots.py           空き枠の計算（営業時間 − 予定 − 既存予約）
  routes/public.py   予約フローのAPI
  routes/admin.py    予備の予約一覧（/admin・要トークン）
  templates/ static/ 画面
tests/               pytest
config.json          運用設定（メニュー・営業時間・カレンダー）
deploy/GCP_SETUP.md  Googleカレンダー連携の初回設定手順
```

## 設計の要点

- **空き枠計算（`app/slots.py`）**：営業時間の枠を候補時刻の刻みで走査し、「カレンダーの予定」と
  「既存予約」をバッファ分だけ前後に膨らませて1本にまとめてから重なりを判定します。
  時刻はすべてタイムゾーン付きの `datetime` で扱い、営業時間は日本時間（JST）の壁時計、保存と比較はUTCに揃えます。
- **二重予約の防止**：確定直前に `validate_slot_free()` でもう一度、受付期間・営業時間・休業日・重なりを
  判定し、通ったものだけをDBに書きます。DBには `[start, end)` の重なり判定（`overlapping_bookings`）も持ち、
  カレンダー連携が一時的に切れても自前で破綻しないようにしています。
- **カレンダー障害時の扱い**：予定作成に失敗しても予約自体は有効として残し、画面には「担当者が手動で確認します」
  と出します（予約を取りこぼさない方を優先）。
- **管理一覧の認証**：環境変数 `YOYAKU_ADMIN_TOKEN` を設定したときだけ `/admin` が有効になります。
  トークンは `Authorization: Bearer <token>` ヘッダを優先して読み（URL・履歴・ログに残らない）、
  互換のためクエリ `?token=` も受け付けます。比較は定数時間（`hmac.compare_digest`）。
- **入力の検証・抑止**：名前・メール・相談内容の長さと形式を pydantic で検証。同一IPからの予約は10分に5件まで
  （プロセス内メモリの簡易レート制限）。
- **デモモード**：`config.json` の `calendar.demo_mode` が `true` の間はGoogleへ一切アクセスしません
  （Googleのライブラリは遅延importなので、デモだけなら未インストールでも動きます）。

## 動かし方（デモモード）

```bash
./run.sh
```

初回は仮想環境の作成と依存インストールを自動で行います。ブラウザで http://127.0.0.1:8200 を開いてください。

## 本番にする

1. `config.json` のメニュー・営業時間・料金・連絡先を実際の内容に書き換える
2. `deploy/GCP_SETUP.md` の手順でサービスアカウントを作り、鍵を `secrets/service_account.json` に置く
3. `config.json` の `calendar.demo_mode` を `false` にして再起動

公開するときは、127.0.0.1 で動かしたまま前段にリバースプロキシやトンネル（HTTPS終端）を置いてください。

### 設定（config.json）

- `business.name` / `tagline` / `contact_email`：表示名・ひとこと・連絡先
- `menus[]`：`id` / `name` / `duration_min`（分） / `price`（円・未定なら `null`） / `description` / `location`
- `availability.weekly_hours`：曜日ごとの受付時間帯（`[]` は休み・複数帯OK）
- `availability.slot_granularity_min`：候補時刻の刻み（分）
- `availability.buffer_min`：予約と予約の間に空ける時間（分）
- `availability.min_notice_hours`：何時間前まで予約を受けるか
- `availability.max_advance_days`：何日先まで予約可能か
- `availability.blackout_dates`：休業日（`"2026-08-13"` 形式）

### 予備の管理一覧 `/admin`

```bash
YOYAKU_ADMIN_TOKEN=<長いランダム文字列> ./run.sh
curl -H "Authorization: Bearer <長いランダム文字列>" http://127.0.0.1:8200/admin
# ブラウザから開くときは互換のクエリも使える: http://127.0.0.1:8200/admin?token=<...>
```

## テスト

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
./.venv/bin/python -m pytest -q
```

空き枠計算（バッファ込みの重なり除外・休業日・受付下限）、確定直前の再判定、SQLiteの重複判定
（重なる／隣接／キャンセル済み）、`/admin` の認証（Bearer・クエリ・誤トークン・未設定時404）を確認します。

## 作者・ライセンス

山口竜太（株式会社ヘルスギルド）。MIT License（`LICENSE` を参照）。
