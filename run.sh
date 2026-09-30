#!/usr/bin/env bash
# 予約アプリをローカル起動する。初回は venv 作成＋依存インストールも行う。
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8200}"

if [ ! -d ".venv" ]; then
  echo "[setup] 仮想環境を作成しています…"
  python3 -m venv .venv
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt
fi

echo "[run] http://127.0.0.1:${PORT} で起動します (停止: Ctrl+C)"
exec ./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "${PORT}" "$@"
