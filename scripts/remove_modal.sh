#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${MODAL_APP_NAME:-vro-mcp}"
VOLUME_NAME="${MODAL_VOLUME_NAME:-vro-data}"
SECRET_NAME="${MODAL_SECRET_NAME:-vro-mcp-secret}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v modal >/dev/null; then
  MODAL_BIN="modal"
elif [[ -x "$ROOT/.venv/bin/modal" ]]; then
  MODAL_BIN="$ROOT/.venv/bin/modal"
else
  echo "missing required command: modal" >&2
  echo "Run scripts/deploy_modal.sh first, or install Modal with: python3 -m pip install modal" >&2
  exit 1
fi

"$MODAL_BIN" app stop "$APP_NAME" --yes || true
"$MODAL_BIN" volume delete "$VOLUME_NAME" --yes --allow-missing
"$MODAL_BIN" secret delete "$SECRET_NAME" --yes --allow-missing

echo "Removed Modal app '$APP_NAME', volume '$VOLUME_NAME', and secret '$SECRET_NAME'."
