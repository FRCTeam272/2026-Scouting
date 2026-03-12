#!/usr/bin/env bash
# update.sh — fetch latest match data, regenerate dashboards, and push to GitHub.
# Designed to be run manually or via cron, e.g.:
#   */15 * * * * update.sh >> update.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="${PYTHON:-python3}"
TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"

log() { echo "[$TIMESTAMP] $*"; }

log "=== TBA update started ==="

# ── 1. Import match data ──────────────────────────────────────────────────────
log "Running import_matches.py..."
$PYTHON import_matches.py

# ── 2. Regenerate HTML dashboards ────────────────────────────────────────────
log "Running create_view.py..."
$PYTHON create_view.py

# ── 3. Commit and push ───────────────────────────────────────────────────────
log "Staging changes..."
git add *.html

if git diff --cached --quiet; then
    log "Nothing changed — skipping commit."
else
    git commit -m "Auto-update: match data and dashboards [$TIMESTAMP]"
    log "Pushing to origin..."
    git push origin main
    log "Push complete."
fi

log "=== TBA update finished ==="
