#!/usr/bin/env bash
# Vendored auto-install hook: a copy per plugin, not shared at runtime. See
# davdittrich/ponytail-everywhere's hooks/capability-auto-install.sh for the sibling copy.
#
# The bundle files sit at the plugin root so that `gsd-tools capability install
# <git url>` also works (URL import reads capability.json at the repo root).
# Only BUNDLE_FILES are hashed and staged, never the rest of the checkout
# (.git, hooks, tests, README, __pycache__).
#
# Detects bundle drift via a hash of the bundle files and re-installs the
# capability at global ("user") scope when the hash changed.
# Never aborts the session: no `set -e`.
set -u

CAP_ID="${1:-}"

# Defense in depth (ASVS V5): call sites only ever pass a hard-coded literal,
# but validate the id shape gsd-core itself enforces before it reaches any
# path construction.
[[ "$CAP_ID" =~ ^[a-z][a-z0-9-]*$ ]] || exit 0

# No home directory to install under (set -u would abort with a leaked error).
[ -n "${GSD_HOME:-${HOME:-}}" ] || exit 0

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
BUNDLE_SRC="$PLUGIN_ROOT"
[ -f "$BUNDLE_SRC/capability.json" ] || exit 0
BUNDLE_FILES=(capability.json config scripts skills)

# Portable hash tool selection (macOS ships no sha256sum).
if command -v sha256sum >/dev/null 2>&1; then
  HASH_CMD=(sha256sum)
elif command -v shasum >/dev/null 2>&1; then
  HASH_CMD=(shasum -a 256)
else
  exit 0
fi

# Every path under the bundle files, relative to BUNDLE_SRC, minus
# __pycache__ (running the tests in the plugin root writes one).
bundle_paths() {
  (cd "$BUNDLE_SRC" && find -L "${BUNDLE_FILES[@]}" -name __pycache__ -prune -o "$@" -print 2>/dev/null) | LC_ALL=C sort
}

# Bundle hash over exactly the staged files: LC_ALL=C-sorted list of every
# path (files and directories, so an added empty directory is caught), then
# one content hash per sorted regular file. Symlinks are followed (find -L),
# matching the `cp -RL` staging, so a changed link target's content is caught. Per-file hashes keep file boundaries: raw concatenation hashed
# identically when bytes moved between files.
bundle_hash() {
  {
    bundle_paths \( -type f -o -type d \)
    bundle_paths -type f | while IFS= read -r _f; do (cd "$BUNDLE_SRC" && "${HASH_CMD[@]}" "$_f"); done
  } | "${HASH_CMD[@]}" | awk '{print $1}'
}

# One sidecar file per capability id so vendored copies in
# different plugins cannot race or stomp each other's cached hash. Never
# gsd-core's own .gsd-capabilities.json / ~/.gsd/consent.json -- those are
# gsd-core-owned schemas this script must not write into.
STATE_FILE="${GSD_HOME:-$HOME}/.gsd/capability-auto-install-$CAP_ID.hash"

OLD_HASH=""
[ -r "$STATE_FILE" ] && OLD_HASH="$(cat "$STATE_FILE" 2>/dev/null)"
NEW_HASH="$(bundle_hash)"

# Fast path: unchanged bundle exits silently, never spawns node.
[ "$NEW_HASH" = "$OLD_HASH" ] && exit 0

# gsd-tools resolver, adapted from
# davdittrich/ponytail-everywhere's hooks/gsd-tools.sh rather than sourced --
# the root plugin ships no gsd-tools.sh, and an inline copy keeps this script
# dependency-free within its own plugin. Deliberately omits that
# copy's git-toplevel tier: this install is machine-wide, so a stale
# gsd-core checkout in whatever repo the session opened must not perform it.
if command -v gsd-tools >/dev/null 2>&1; then
  GSD_TOOLS=(gsd-tools)
elif [ -f "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/gsd-core/bin/gsd-tools.cjs" ]; then
  GSD_TOOLS=(node "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/gsd-core/bin/gsd-tools.cjs")
else
  # Deliberate divergence from this repo's usual silent `|| true`
  # fail-open convention -- this path is unattended, so silence would leave
  # a capability permanently inactive with nobody the wiser. Do not "fix"
  # this back to silent. Do NOT write STATE_FILE, so the next session retries.
  echo "capability-auto-install: gsd-tools not found; $CAP_ID not installed" >&2
  exit 0
fi

# Stage the bundle files into a persistent clean directory; gsd-core records
# the install source, so it must outlive this run. -L because gsd-core refuses
# symlinks in a bundle.
BUNDLE_DIR="${GSD_HOME:-$HOME}/.gsd/capability-bundle-$CAP_ID"
if ! { rm -rf "$BUNDLE_DIR" && mkdir -p "$BUNDLE_DIR" \
    && (cd "$BUNDLE_SRC" && cp -RL "${BUNDLE_FILES[@]}" "$BUNDLE_DIR"/) \
    && find "$BUNDLE_DIR" -name __pycache__ -prune -exec rm -rf {} +; } 2>/dev/null; then
  # Same rationale as above: never install a partial bundle, never record the hash.
  echo "capability-auto-install: staging failed for $CAP_ID; not installed" >&2
  exit 0
fi

# Spec is always the absolute bundle dir -- a relative spec would
# resolve against the end user's cwd, not the plugin. User scope maps to the CLI's literal --scope global value.
"${GSD_TOOLS[@]}" capability install "$BUNDLE_DIR" --scope global --yes >/dev/null 2>&1
INSTALL_STATUS=$?

if [ "$INSTALL_STATUS" -eq 0 ]; then
  printf 'Auto-installed capability: %s (user scope)\n' "$CAP_ID"
  printf '%s' "$NEW_HASH" > "$STATE_FILE" 2>/dev/null
else
  # Same rationale as above: install command ran and failed.
  echo "capability-auto-install: capability install failed for $CAP_ID (exit $INSTALL_STATUS)" >&2
fi

exit 0
