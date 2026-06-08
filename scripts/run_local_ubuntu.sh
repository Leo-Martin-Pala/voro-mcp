#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_APT="${SKIP_APT:-0}"
SKIP_DATA_FETCH="${SKIP_DATA_FETCH:-0}"
SKIP_GIELLA="${SKIP_GIELLA:-0}"
GIELLA_FROM_SOURCE="${GIELLA_FROM_SOURCE:-0}"

need_file() {
  if [[ ! -r "$1" ]]; then
    echo "missing required file: $1" >&2
    exit 1
  fi
}

cd "$ROOT"

if [[ "$SKIP_APT" != "1" ]]; then
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends curl ca-certificates gnupg lsb-release

  # hfst/hfst-ospell/cg3/divvun-gramcheck come from the Apertium/Divvun nightly
  # repo. Add it only if no apt source already provides divvun-gramcheck;
  # install-nightly.sh overwrites its own source entry, so this stays idempotent
  # and is skipped entirely once the package is installable.
  cand="$(apt-cache policy divvun-gramcheck 2>/dev/null | awk -F': ' '/Candidate:/{print $2}')"
  if [[ -z "$cand" || "$cand" == "(none)" ]]; then
    curl -fsSL https://apertium.projectjj.com/apt/install-nightly.sh | sudo bash
    sudo apt-get update
  fi

  sudo apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip git \
    autoconf automake libtool make pkg-config \
    hfst hfst-ospell cg3 divvun-gramcheck perl gawk bash
fi

if [[ ! -r "$ROOT/data/vro_dictionary.sqlite" \
   || ! -r "$ROOT/data/vro_corpus.sqlite" \
   || ! -r "$ROOT/data/vro_word_bag.sqlite" ]]; then
  if [[ "$SKIP_DATA_FETCH" == "1" ]]; then
    echo "SQLite datasets are missing and SKIP_DATA_FETCH=1; aborting." >&2
    exit 1
  fi
  "$ROOT/scripts/fetch_data.sh"
fi

need_file "$ROOT/data/vro_dictionary.sqlite"
need_file "$ROOT/data/vro_corpus.sqlite"
need_file "$ROOT/data/vro_word_bag.sqlite"

if [[ ! -r "$ROOT/data/giella-share/giella/vro/analyser-gt-desc.hfstol" ]]; then
  if [[ "$SKIP_GIELLA" == "1" ]]; then
    echo "Giella artifacts are missing; Giella-backed MCP tools will report unavailable." >&2
  elif [[ "$GIELLA_FROM_SOURCE" == "1" ]]; then
    "$ROOT/scripts/install_giella_artifacts.sh"
  else
    "$ROOT/scripts/fetch_giella.sh"
  fi
fi

python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -U pip
"$ROOT/.venv/bin/pip" install -e "$ROOT"

"$ROOT/.venv/bin/vro-mcp-check" || true

cat <<EOF

Setup complete. Start the server with:
  make run        (or: .venv/bin/vro-mcp-server)

It speaks MCP over stdio and waits for a client, so running it in a plain
terminal just blocks, so point your MCP client at it instead.
EOF
