#!/usr/bin/env bash
# Assemble the custom_components the Docker end-to-end tier mounts: this glue, the real
# Home Keeper, and a *fake* Bambu Lab that stands in a controllable firmware update
# entity (a real printer can't run in CI). Separately, stage the *real* ha-bambulab
# source under tests/docker/upstream_src/ for the static firmware-surface contract test.
# Needs network access to clone the upstreams; pin refs via HK_REF / BAMBU_REF.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../" && pwd)"
STAGE="$ROOT/tests/docker/custom_components"
SRC="$ROOT/tests/docker/upstream_src"
HK_REPO="${HK_REPO:-https://github.com/prestomation/ha-home-keeper}"
# Pinned to main until ha-home-keeper cuts the release this glue depends on.
HK_REF="${HK_REF:-main}"
# The Bambu Lab integration this glue bridges to (our fork), used for the contract test.
BAMBU_REPO="${BAMBU_REPO:-https://github.com/prestomation/ha-bambulab}"
BAMBU_REF="${BAMBU_REF:-main}"

rm -rf "$STAGE" "$SRC"
mkdir -p "$STAGE" "$SRC"

echo "[fetch-upstreams] staging this integration..."
cp -r "$ROOT/custom_components/home_keeper_bambu_lab" "$STAGE/"

echo "[fetch-upstreams] staging the fake Bambu Lab (runtime firmware entity)..."
cp -r "$ROOT/tests/docker/fake_components/bambu_lab" "$STAGE/"

# Clone *repo*@*ref* into a temp dir and print ONLY that dir on stdout. All logging and
# git output is redirected to stderr so command substitution captures just the path.
fetch() {
  local repo="$1" ref="$2" tmp
  tmp="$(mktemp -d)"
  {
    echo "[fetch-upstreams] cloning $repo@$ref ..."
    git clone --depth 1 --branch "$ref" "$repo" "$tmp" 2>/dev/null \
      || git clone --depth 1 "$repo" "$tmp"
  } >&2
  echo "$tmp"
}

# Home Keeper — the real integration, mounted + set up.
HK_TMP="$(fetch "$HK_REPO" "$HK_REF")"
cp -r "$HK_TMP/custom_components/home_keeper" "$STAGE/"

# ha-bambulab — real source, source-only (NOT mounted/set up; needs a printer). Used by
# the docker contract test to assert the firmware update entity still exists.
BAMBU_TMP="$(fetch "$BAMBU_REPO" "$BAMBU_REF")"
cp -r "$BAMBU_TMP/custom_components/bambu_lab" "$SRC/"
rm -rf "$HK_TMP" "$BAMBU_TMP"

# Home Keeper ships its panel JS as a build artifact (gitignored), so a fresh clone has
# only the TypeScript source. Build it here so the panel actually renders in the
# container — required for the browser/screenshot tier. Skipped gracefully if there's no
# frontend so the REST-only tier still works.
HK_FRONTEND="$STAGE/home_keeper/frontend"
if [ -f "$HK_FRONTEND/package.json" ] && [ "${SKIP_PANEL_BUILD:-0}" != "1" ]; then
  echo "[fetch-upstreams] building Home Keeper panel..."
  (cd "$HK_FRONTEND" && (npm ci --no-audit --no-fund || npm install --no-audit --no-fund) && npm run build)
fi

echo "[fetch-upstreams] staged custom_components:"
ls -1 "$STAGE"
echo "[fetch-upstreams] real ha-bambulab source for contract test:"
ls -1 "$SRC"
