#!/usr/bin/env sh
# Download the Võro SQLite datasets from the GitHub release and extract them
# into data/. The archive bundles the dataset LICENSE and NOTICE.
set -eu

# Bump this default tag whenever you publish a new dataset release.
REPO="${VRO_DATA_REPO:-Leo-Martin-Pala/voro-mcp}"
TAG="${VRO_DATA_TAG:-data-v1}"
ASSET="vro-data.tar.xz"

cd "$(dirname "$0")/.."
mkdir -p data

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

echo "Fetching $ASSET from $REPO@$TAG ..."
if command -v gh >/dev/null 2>&1; then
    gh release download "$TAG" --repo "$REPO" --pattern "$ASSET" --output "$tmp" --clobber
else
    curl -fL "https://github.com/$REPO/releases/download/$TAG/$ASSET" -o "$tmp"
fi

tar xJf "$tmp" -C data
echo "Done. data/ now contains:"
ls -1 data/*.sqlite
