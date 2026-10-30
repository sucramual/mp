#!/usr/bin/env bash
# Parse every fenced `mermaid` block in a Markdown file with the Mermaid version GitHub renders with.
# Usage: check-mermaid.sh <file.md | ->
# Exit 0 when every block parses, 1 when a block fails, 2 on a usage or setup error.
# The first run installs the pinned packages into check-mermaid/node_modules with `npm ci`.
# After `npm ci` succeeds, the wrapper writes node_modules/.install-complete, which holds the hash of
# package-lock.json. A tree without a matching marker counts as not installed, so no run uses a tree
# that another run is still extracting.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PKG="$HERE/check-mermaid"
LOCK="$PKG/.install.lock"
LOCK_WAIT_SECONDS=600
# Node and npm otherwise leave a node-compile-cache directory in $TMPDIR.
export NODE_DISABLE_COMPILE_CACHE=1

die() {
  printf 'check-mermaid: %s\n' "$1" >&2
  exit 2
}

(( $# == 1 )) || die "usage: check-mermaid.sh <file.md | ->"
command -v node >/dev/null || die "node is not on PATH. Install Node.js 22.22.2+, 24.15+, or 26+, then run again."

# npm ci treats "engines" as advisory, so check the node version here and stop with exit 2.
# The range may use only "^X.Y.Z" and ">=X[.Y.Z]" terms joined by "||"; any other term is a setup error.
node_version="$(node --version)" || die "node --version failed."
if ! engines_error="$(node -e '
  const fs = require("fs");
  const range = JSON.parse(fs.readFileSync(process.argv[1] + "/package.json", "utf8")).engines.node;
  const parse = (text) => {
    const match = /^(\d+)(?:\.(\d+))?(?:\.(\d+))?$/.exec(text);
    return match ? [Number(match[1]), Number(match[2] ?? 0), Number(match[3] ?? 0)] : null;
  };
  const compare = (a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2];
  const version = process.argv[2].replace(/^v/, "").split(/[-+]/)[0];
  const have = parse(version);
  let ok = false;
  for (const term of range.split("||").map((part) => part.trim())) {
    const match = /^(\^|>=)(\S+)$/.exec(term);
    const want = match && parse(match[2]);
    if (!have || !want || (match[1] === "^" && want[0] === 0)) {
      console.log(`cannot compare node ${process.argv[2]} with engines term "${term}" in package.json.`);
      process.exit(1);
    }
    if (compare(have, want) >= 0 && (match[1] === ">=" || have[0] === want[0])) ok = true;
  }
  if (!ok) {
    console.log(`node ${version} does not satisfy engines "${range}". Install a supported Node.js, then run again.`);
    process.exit(1);
  }
' "$PKG" "$node_version")"; then
  die "${engines_error:-node version check failed.}"
fi

# The marker content: the SHA-256 of package-lock.json.
lock_hash() {
  node -e '
    const fs = require("fs");
    process.stdout.write(require("crypto").createHash("sha256").update(fs.readFileSync(process.argv[1])).digest("hex"));
  ' "$PKG/package-lock.json"
}

# Succeed only when the completion marker matches the lockfile and check-mermaid/node_modules holds
# every direct dependency at its pinned version.
installed_matches_pins() {
  [[ -f "$PKG/node_modules/.install-complete" ]] || return 1
  [[ "$(<"$PKG/node_modules/.install-complete")" == "$(lock_hash)" ]] || return 1
  node -e '
    const fs = require("fs");
    const read = (path) => { try { return JSON.parse(fs.readFileSync(path, "utf8")); } catch { return {}; } };
    const pins = read(process.argv[1] + "/package.json").dependencies ?? {};
    const stale = Object.entries(pins).filter(
      ([name, pin]) => read(`${process.argv[1]}/node_modules/${name}/package.json`).version !== pin
    );
    process.exit(Object.keys(pins).length > 0 && stale.length === 0 ? 0 : 1);
  ' "$PKG"
}

if ! installed_matches_pins; then
  command -v npm >/dev/null || die "npm is not on PATH. Install Node.js with npm, then run: cd '$PKG' && npm ci"
  # mkdir is atomic, so it serves as a lock when several checks start at once (macOS has no flock).
  waited=0
  until mkdir "$LOCK" 2>/dev/null; do
    if (( waited >= LOCK_WAIT_SECONDS )); then
      die "waited ${LOCK_WAIT_SECONDS}s for another install. If none runs, remove '$LOCK' and run again."
    fi
    sleep 1
    waited=$((waited + 1))
  done
  trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT
  # Another run may have installed while this one waited.
  if ! installed_matches_pins; then
    printf 'check-mermaid: installing the pinned Mermaid into %s\n' "$PKG/node_modules" >&2
    if ! (cd "$PKG" && npm ci --no-audit --no-fund --loglevel=error >&2); then
      die "npm ci failed. Fix the error above, then run: cd '$PKG' && npm ci --no-audit --no-fund"
    fi
    # Write the marker last, so a reader never sees it on a half-extracted tree.
    lock_hash >"$PKG/node_modules/.install-complete.tmp"
    mv "$PKG/node_modules/.install-complete.tmp" "$PKG/node_modules/.install-complete"
  fi
  rmdir "$LOCK"
  trap - EXIT
fi

exec node "$PKG/check-mermaid.mjs" "$@"
