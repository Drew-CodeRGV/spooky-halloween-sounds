#!/usr/bin/env bash
# Spooky Halloween Sounds: self-repair, run by systemd before the app starts.
#
# Power can get cut at any moment out in the yard. If that happens while files are
# being written (an update, an upload, a settings change), they can end up empty or
# broken. This checks the app on every start and restores anything damaged from the
# last known-good copy, then refreshes that copy once everything checks out.
#
# The installer copies this script to /usr/local/bin/spooky-selfheal so an update
# can never damage the repair tool itself.
#
# Usage: spooky-selfheal /path/to/spooky-halloween-sounds
set -u

APP_DIR="${1:-$(cd "$(dirname "$0")" && pwd)}"
GOOD="$(dirname "$APP_DIR")/.spooky-known-good"
REPO_URL="https://github.com/Drew-CodeRGV/spooky-halloween-sounds.git"
CORE=(app.py engine.py denon.py static/index.html static/app.js static/style.css
      static/remote.html static/remote.js static/remote.css static/sw.js static/manifest.webmanifest)

log() { echo "selfheal: $*"; }

valid_json() { python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$1" 2>/dev/null; }

problems() {  # prints what's wrong with a copy of the app; prints nothing if it's fine
  local d="$1" f
  for f in "${CORE[@]}"; do
    [[ -s "$d/$f" ]] || echo "$f is missing or empty"
  done
  python3 - "$d" <<'PY' 2>/dev/null || echo "Python code doesn't parse"
import ast, sys
for f in ("app.py", "engine.py", "denon.py"):
    ast.parse(open(f"{sys.argv[1]}/{f}").read())
PY
  if [[ -d "$d/sounds" ]]; then
    find "$d/sounds" -type f -size 0 -printf "%P is empty\n" 2>/dev/null | sed 's/^/sounds\//'
  fi
  if [[ -f "$d/config.json" ]] && ! valid_json "$d/config.json"; then
    echo "config.json is damaged"
  fi
}

ISSUES="$(problems "$APP_DIR")"

if [[ -n "$ISSUES" ]]; then
  log "found damage:"
  echo "$ISSUES" | sed 's/^/  - /'
  if [[ -d "$GOOD" ]] && [[ -z "$(problems "$GOOD")" ]]; then
    log "restoring from the last known-good copy"
    KEEP=()   # keep settings saved since the last start, as long as they're intact
    [[ -f "$APP_DIR/config.json" ]] && valid_json "$APP_DIR/config.json" && KEEP=(--exclude config.json)
    rsync -a --exclude .git "${KEEP[@]}" "$GOOD/" "$APP_DIR/"
    sync
  else
    log "no usable known-good copy; trying a fresh download"
    TMP="$(mktemp -d)"
    if git clone -q --depth 1 "$REPO_URL" "$TMP/app" 2>/dev/null; then
      [[ -f "$APP_DIR/config.json" ]] && valid_json "$APP_DIR/config.json" && cp "$APP_DIR/config.json" "$TMP/app/"
      rsync -a --exclude .git "$TMP/app/" "$APP_DIR/"
      sync
    else
      log "couldn't download (no internet?)"
    fi
    rm -rf "$TMP"
  fi
  # Whatever is still broken can't be recovered: clear it so the app can start cleanly.
  if [[ -d "$APP_DIR/sounds" ]]; then
    find "$APP_DIR/sounds" -type f -size 0 -print -delete 2>/dev/null | sed 's/^/selfheal: removed empty /'
  fi
  if [[ -f "$APP_DIR/config.json" ]] && ! valid_json "$APP_DIR/config.json"; then
    mv "$APP_DIR/config.json" "$APP_DIR/config.json.damaged"
    log "settings were damaged and unrecoverable; starting with defaults (old file: config.json.damaged)"
  fi
  sync
  ISSUES="$(problems "$APP_DIR")"
  if [[ -n "$ISSUES" ]]; then
    log "still damaged after repair:"
    echo "$ISSUES" | sed 's/^/  - /'
  else
    log "repaired"
  fi
fi

# Git's own files can get damaged too; if so, re-download just the history (needs internet).
if [[ -d "$APP_DIR/.git" ]] && ! git -C "$APP_DIR" status --short >/dev/null 2>&1; then
  log "git history is damaged; re-downloading it"
  TMP="$(mktemp -d)"
  if git clone -q --no-checkout "$REPO_URL" "$TMP/app" 2>/dev/null; then
    rm -rf "$APP_DIR/.git.broken"
    mv "$APP_DIR/.git" "$APP_DIR/.git.broken"
    mv "$TMP/app/.git" "$APP_DIR/.git"
    git -C "$APP_DIR" reset -q   # match the index to the files on disk; leaves files alone
    rm -rf "$APP_DIR/.git.broken"
    sync
    log "git history restored"
  else
    log "couldn't re-download git history (no internet?); the app still runs"
  fi
  rm -rf "$TMP"
fi

# Everything checks out: refresh the known-good copy (only changed files get copied).
if [[ -z "$(problems "$APP_DIR")" ]]; then
  mkdir -p "$GOOD"
  rsync -a --delete --exclude .git --exclude .venv --exclude __pycache__ --exclude '*.tmp' "$APP_DIR/" "$GOOD/"
  sync
fi
exit 0
