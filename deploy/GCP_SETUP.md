# Googleカレンダー連携の初回設定

予約アプリが「カレンダーの空きを読む」「予約が入ったら予定を作る」ためには、
アプリ専用のGoogle認証情報（サービスアカウント）が1つ必要です。**初回だけ**の作業で、
一度やれば以降は自動で動きます。

> なぜサービスアカウントか：24時間動くアプリには、人のログインに依存しないアプリ自身の鍵が要るためです。

---

## 手順A：サービスアカウントと鍵を作る

1. **Google Cloud Console** を開く → https://console.cloud.google.com/
   （ログインは予約に使いたいカレンダーのGoogleアカウントで）
2. 画面上部でプロジェクトを作成（名前は何でも可：例 `yoyaku-app`）。
3. **Google Calendar API を有効化**：
   https://console.cloud.google.com/apis/library/calendar-json.googleapis.com
   → 「有効にする」をクリック。
4. **サービスアカウントを作成**：
   https://console.cloud.google.com/iam-admin/serviceaccounts
   → 「サービスアカウントを作成」→ 名前（例 `yoyaku-bot`）→ 作成して完了。
   役割（ロール）は付けなくてOK（カレンダー共有側で権限を渡すため）。
5. 作ったサービスアカウントをクリック → **「キー」タブ → 「鍵を追加」→「新しい鍵を作成」→ JSON** を選び作成。
   → JSONファイルが**ダウンロード**されます。
6. そのJSONファイルを、このリポジトリの **`secrets/service_account.json`** という名前で保存。
7. JSONの中の **`client_email`**（`〜@〜.iam.gserviceaccount.com` の形）をコピーしておく。次で使います。

---

## 手順B：カレンダーをサービスアカウントに共有する

サービスアカウントは「別人」です。カレンダーを見せるには共有設定が要ります。

1. **Googleカレンダー** を開く → https://calendar.google.com/
2. 左側「マイカレンダー」で、予約を入れたいカレンダーにマウスを乗せ「⋮」→ **「設定と共有」**。
3. **「特定のユーザーやグループと共有する」→「ユーザーを追加」** に、手順A-7の `client_email` を貼り付け。
4. 権限を **「予定の変更権限」**（Make changes to events）にして保存。
5. 同じ設定画面の下の方「カレンダーの統合」にある **「カレンダーID」** をコピー。
   - 普段使っているメインのカレンダーなら、カレンダーIDは**そのGoogleアカウントのメールアドレス**です。
   - 専用カレンダーを作った場合は `〜@group.calendar.google.com` の形。

---

## 手順C：アプリの設定を本番に切り替える

`config.json` の `calendar` を編集：

```json
"calendar": {
  "demo_mode": false,
  "calendar_id": "ここに手順B-5のカレンダーID",
  "service_account_file": "secrets/service_account.json",
  "send_invite_to_customer": true
}
```

保存したらアプリを再起動（`./run.sh`）。これで：
- 空き枠 ＝ カレンダーの予定を避けて表示
- 予約確定 ＝ カレンダーに予定作成＋お客様へ招待メール

---

## 動作確認

```bash
./run.sh
# 別ターミナルで
curl "http://127.0.0.1:8200/api/slots?menu_id=consult30" | head
```
カレンダーに予定を1件入れてみて、その時間帯が空き枠から消えれば連携成功です。

---

## つまずきポイント

- **招待メールがお客様に届かない場合**：Google Workspace（独自ドメイン）環境では、サービスアカウントが
  参加者へ招待を送るのに追加設定（ドメイン全体の委任 / Domain-Wide Delegation）が要ることがあります。
  個人のGmailで作ったカレンダーを共有する方式なら通常は届きます。
  届かなければ、`send_invite_to_customer` を `false` にして別経路で案内するか、OAuth方式への切り替えを検討してください。
- **`secrets/service_account.json` は秘密鍵です。** GitHubや他人に渡さないこと。`secrets/` は
  `.gitignore` 対象にしています。
- **カレンダーIDを間違えると 404 / 空き0** になります。手順B-5を再確認してください。
