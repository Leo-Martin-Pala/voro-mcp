#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${VRO_GIELLA_BUILD_DIR:-$ROOT/.cache/giella-build}"
ARTIFACT_DIR="${VRO_GIELLA_ARTIFACT_DIR:-$ROOT/data/giella-share}"
INSTALL_PREFIX="$BUILD_DIR/install"
JOBS="${JOBS:-2}"
CLEAN="${CLEAN:-0}"

need_cmd() {
  command -v "$1" >/dev/null || {
    echo "missing required command: $1" >&2
    exit 1
  }
}

clone_or_update() {
  repo="$1"
  url="$2"
  dest="$BUILD_DIR/$repo"
  if [[ -d "$dest/.git" ]]; then
    git -C "$dest" fetch --depth 1 origin main
    git -C "$dest" checkout --quiet FETCH_HEAD
  else
    git clone --depth 1 "$url" "$dest"
  fi
}

need_cmd git
need_cmd make
need_cmd pkg-config
need_cmd autoconf
need_cmd automake
need_cmd libtoolize
need_cmd hfst-optimized-lookup
need_cmd hfst-ospell

mkdir -p "$BUILD_DIR" "$ROOT/data"

clone_or_update giella-core https://github.com/giellalt/giella-core.git
clone_or_update shared-mul https://github.com/giellalt/shared-mul.git
clone_or_update shared-smi https://github.com/giellalt/shared-smi.git
clone_or_update lang-vro https://github.com/giellalt/lang-vro.git

# giella-core must be configured so its generated scripts (e.g. the NFC/NFD
# regex generators) and pkg-config file exist before lang-vro is built. Its
# configure hard-requires the divvun test tools; install the pip-installable
# ones into a local venv and stub the rest with GTMORPHTEST -- those tools are
# only used by `make check`, never to build the FSTs.
TOOLS_VENV="$BUILD_DIR/.tools-venv"
if [[ ! -x "$TOOLS_VENV/bin/gtgramtool" ]]; then
  python3 -m venv "$TOOLS_VENV"
  "$TOOLS_VENV/bin/pip" install -q -U pip
  "$TOOLS_VENV/bin/pip" install -q \
    "git+https://github.com/divvun/GiellaLTGramTools/" \
    "git+https://github.com/divvun/GiellaLTLexTools/"
fi
export PATH="$TOOLS_VENV/bin:$PATH"

cd "$BUILD_DIR/giella-core"
if [[ ! -x ./configure ]]; then
  ./autogen.sh
fi
GTMORPHTEST="${GTMORPHTEST:-/usr/bin/true}" MORPH_TEST2="${MORPH_TEST2:-/usr/bin/true}" \
  ./configure --prefix="$INSTALL_PREFIX"

cd "$BUILD_DIR/lang-vro"
if [[ ! -x ./configure ]]; then
  ./autogen.sh
fi

PKG_CONFIG_PATH="$BUILD_DIR/giella-core:$BUILD_DIR/shared-mul:$BUILD_DIR/shared-smi" \
  ./configure \
    --prefix="$INSTALL_PREFIX" \
    --disable-configure-errors \
    --enable-tokenisers \
    --enable-analyser-tool \
    --enable-spellers \
    --enable-grammarchecker

make -j"$JOBS"
make install

rm -rf "$ARTIFACT_DIR"
mkdir -p "$ARTIFACT_DIR"
cp -a "$INSTALL_PREFIX/share/." "$ARTIFACT_DIR/"

# Record licensing + provenance. The compiled output combines GPL-3.0 sources
# (giella-core, shared-mul, shared-smi) with LGPL-3.0 lang-vro, so the bundle is
# distributed under GPL-3.0. Record the upstream commits as corresponding source.
cp -f "$BUILD_DIR/giella-core/LICENSE" "$ARTIFACT_DIR/LICENSE"
{
  echo "# GiellaLT runtime artifacts: notices"
  echo
  echo "Compiled GiellaLT/Divvun runtime artifacts (FSTs, CG grammars, spellers)"
  echo "for Võro, generated from the GiellaLT source repositories below. These"
  echo "files are not part of the vro-mcp-server code (MIT) or dataset"
  echo "(CC-BY-SA-4.0)."
  echo
  echo "## License"
  echo
  echo "Distributed under GPL-3.0 (see LICENSE in this archive). The artifacts"
  echo "combine GPL-3.0 sources with LGPL-3.0 lang-vro; because GPL-3.0 material"
  echo "is incorporated, the combined artifacts are GPL-3.0."
  echo
  echo "## Corresponding source"
  echo
  echo "Built $(date -u +%Y-%m-%d) from:"
  for r in giella-core shared-mul shared-smi lang-vro; do
    sha="$(git -C "$BUILD_DIR/$r" rev-parse HEAD 2>/dev/null || echo unknown)"
    printf -- "- giellalt/%s  https://github.com/giellalt/%s  @ %s\n" "$r" "$r" "$sha"
  done
  echo
  echo "Licenses: giella-core, shared-mul, shared-smi = GPL-3.0; lang-vro = LGPL-3.0."
} > "$ARTIFACT_DIR/NOTICE"

if [[ "$CLEAN" == "1" ]]; then
  rm -rf "$BUILD_DIR"
fi

echo "Giella runtime artifacts installed in $ARTIFACT_DIR"
