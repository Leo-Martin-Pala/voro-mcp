#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="${MODAL_APP_NAME:-vro-mcp}"
VOLUME_NAME="${MODAL_VOLUME_NAME:-vro-data}"
SECRET_NAME="${MODAL_SECRET_NAME:-vro-mcp-secret}"
MCP_PATH_VALUE="${MCP_PATH:-}"
ENV_FILE="$ROOT/.env"

need_cmd() {
  command -v "$1" >/dev/null || {
    echo "missing required command: $1" >&2
    exit 1
  }
}

need_file() {
  if [[ ! -r "$1" ]]; then
    echo "missing required file: $1" >&2
    exit 1
  fi
}

env_file_value() {
  local key="$1"
  if [[ -r "$ENV_FILE" ]]; then
    grep "^$key=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true
  fi
}

setting() {
  local key="$1"
  local default_value="$2"
  local value="${!key:-}"
  if [[ -z "$value" ]]; then
    value="$(env_file_value "$key")"
  fi
  if [[ -n "$value" ]]; then
    printf '%s' "$value"
  else
    printf '%s' "$default_value"
  fi
}

volume_state() {
  "$MODAL_BIN" volume ls "$VOLUME_NAME" / 2>/dev/null || true
}

volume_has_data() {
  local remote_root="$1"
  echo "$remote_root" | grep -q 'dictionary.sqlite' \
    && echo "$remote_root" | grep -q 'corpus.sqlite' \
    && echo "$remote_root" | grep -q 'word_bag.sqlite' \
    && echo "$remote_root" | grep -q 'giella-share'
}

upload_local_data() {
  local data_dir="$1"
  local force_data="$2"
  local remote_root="$3"

  if [[ "$force_data" != "1" ]] && volume_has_data "$remote_root"; then
    echo "Data already exists on volume '$VOLUME_NAME'; skipping (FORCE_DATA=1 to overwrite)."
    return
  fi

  need_file "$data_dir/vro_dictionary.sqlite"
  need_file "$data_dir/vro_corpus.sqlite"
  need_file "$data_dir/vro_word_bag.sqlite"
  "$MODAL_BIN" volume put "$VOLUME_NAME" "$data_dir/vro_dictionary.sqlite" /dictionary.sqlite --force
  "$MODAL_BIN" volume put "$VOLUME_NAME" "$data_dir/vro_corpus.sqlite" /corpus.sqlite --force
  "$MODAL_BIN" volume put "$VOLUME_NAME" "$data_dir/vro_word_bag.sqlite" /word_bag.sqlite --force

  if [[ -d "$data_dir/giella-share" ]]; then
    "$MODAL_BIN" volume put "$VOLUME_NAME" "$data_dir/giella-share" /giella-share --force
  else
    echo "$data_dir/giella-share is missing; deploying without Giella runtime artifacts." >&2
  fi
}

need_cmd python3

if command -v modal >/dev/null; then
  MODAL_BIN="modal"
else
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -U pip modal
  MODAL_BIN="$ROOT/.venv/bin/modal"
fi

MCP_PATH_VALUE="$(setting MCP_PATH "")"
NEW_SECRET="$(setting NEW_SECRET "0")"
LOCAL_SECRET="$(setting LOCAL_SECRET "0")"
DATA_SOURCE="$(setting DATA_SOURCE "release")"
FORCE_DATA="$(setting FORCE_DATA "0")"
DATA_DIR="$(setting DATA_DIR "$ROOT/data")"
VRO_DATA_REPO_VALUE="$(setting VRO_DATA_REPO "Leo-Martin-Pala/voro-mcp")"
VRO_DATA_TAG_VALUE="$(setting VRO_DATA_TAG "data-v1")"
VRO_GIELLA_TAG_VALUE="$(setting VRO_GIELLA_TAG "giella-v1")"

if [[ "$LOCAL_SECRET" == "1" ]]; then
  if [[ -z "$MCP_PATH_VALUE" ]]; then
    echo "LOCAL_SECRET=1 but MCP_PATH is empty; set MCP_PATH in $ENV_FILE (or the environment) to your chosen secret path." >&2
    exit 1
  fi
elif [[ -z "$MCP_PATH_VALUE" || "$NEW_SECRET" == "1" ]]; then
  MCP_PATH_VALUE="$(python3 -c "import secrets; print('/' + secrets.token_urlsafe(24) + '/mcp')")"
  {
    if [[ -r "$ENV_FILE" ]]; then
      grep -v '^MCP_PATH=' "$ENV_FILE" || true
    fi
    printf 'MCP_PATH=%s\n' "$MCP_PATH_VALUE"
  } > "$ENV_FILE.tmp"
  mv "$ENV_FILE.tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

"$MODAL_BIN" secret create "$SECRET_NAME" --force "MCP_PATH=$MCP_PATH_VALUE"
"$MODAL_BIN" volume create "$VOLUME_NAME" || true

remote_root="$(volume_state)"
case "$DATA_SOURCE" in
  none)
    echo "DATA_SOURCE=none; skipping Modal Volume data changes."
    ;;
  local)
    upload_local_data "$DATA_DIR" "$FORCE_DATA" "$remote_root"
    ;;
  release)
    FORCE_DATA="$FORCE_DATA" \
      VRO_DATA_REPO="$VRO_DATA_REPO_VALUE" \
      VRO_DATA_TAG="$VRO_DATA_TAG_VALUE" \
      VRO_GIELLA_TAG="$VRO_GIELLA_TAG_VALUE" \
      "$MODAL_BIN" run modal_app.py::hydrate_release
    ;;
  *)
    echo "invalid DATA_SOURCE=$DATA_SOURCE; expected release, local, or none" >&2
    exit 1
    ;;
esac

cd "$ROOT"
DEPLOY_LOG="$(mktemp)"
if "$MODAL_BIN" deploy modal_app.py 2>&1 | tee "$DEPLOY_LOG"; then
  MODAL_APP_URL="$(sed -nE 's/.*serve => (https:\/\/[^[:space:]]+).*/\1/p' "$DEPLOY_LOG" | tail -n 1)"
else
  status=$?
  rm -f "$DEPLOY_LOG"
  exit "$status"
fi
rm -f "$DEPLOY_LOG"

cat <<EOF

Deployed $APP_NAME.
MCP secret path:
$MCP_PATH_VALUE
EOF

if [[ -n "$MODAL_APP_URL" ]]; then
  cat <<EOF

Full MCP endpoint:
$MODAL_APP_URL$MCP_PATH_VALUE
EOF
else
  cat <<EOF

Your full endpoint is the Modal app URL printed above plus that path.
EOF
fi
