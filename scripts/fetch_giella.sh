#!/usr/bin/env sh
# Download the prebuilt GiellaLT runtime artifacts from the GitHub release and
# extract them into data/giella-share/. These artifacts are GPL-3.0 (see the
# bundled LICENSE/NOTICE). To build them from source instead, use
# scripts/install_giella_artifacts.sh (make giella-build).
set -eu

# Bump this default tag whenever you publish a new giella-share release.
REPO="${VRO_DATA_REPO:-Leo-Martin-Pala/voro-mcp}"
TAG="${VRO_GIELLA_TAG:-giella-v1}"
ASSET="giella-share.tar.xz"

cd "$(dirname "$0")/.."
mkdir -p data/giella-share

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

echo "Fetching $ASSET from $REPO@$TAG ..."
if command -v gh >/dev/null 2>&1; then
    gh release download "$TAG" --repo "$REPO" --pattern "$ASSET" --output "$tmp" --clobber
else
    curl -fL "https://github.com/$REPO/releases/download/$TAG/$ASSET" -o "$tmp"
fi

tar xJf "$tmp" -C data/giella-share
echo "Done. data/giella-share/ populated."
