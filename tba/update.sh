#!/usr/bin/env bash
# update.sh — fetch latest match data, regenerate dashboards, and push to GitHub.
# Designed to be run manually or via cron, e.g.:
#   */15 * * * * update.sh >> update.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="${PYTHON:-python3}"
TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"
LOG_FILE="${LOG_FILE:-update.log}"

# Clear log file if it exceeds 500 lines
if [[ -f "$LOG_FILE" ]] && (( "$(wc -l < "$LOG_FILE")" > 500 )); then
    > "$LOG_FILE"
fi
DB_PATH="${DB_PATH:-matches.db}"
COUNT_FILE="${COUNT_FILE:-matches-count}"

log() { echo "[$TIMESTAMP] $*"; }

get_match_count() {
    if [[ ! -f "$DB_PATH" ]]; then
        echo 0
        return
    fi

    "$PYTHON" - "$DB_PATH" <<'PY'
import sqlite3
import sys

db_path = sys.argv[1]
try:
    con = sqlite3.connect(db_path)
    row = con.execute("SELECT COUNT(*) FROM matches").fetchone()
    print(row[0] if row else 0)
except Exception:
    print(0)
finally:
    try:
        con.close()
    except Exception:
        pass
PY
}

log "=== TBA update started ==="

before_count="$(get_match_count)"
log "Matches in DB before import: $before_count"

# ── 1. Import match data ──────────────────────────────────────────────────────
log "Running import_matches.py..."
$PYTHON import_matches.py

after_count="$(get_match_count)"
log "Matches in DB after import: $after_count"

# ── 2. Regenerate HTML dashboards (always, so upcoming pages stay current) ───
log "Running create_view.py..."
$PYTHON create_view.py

# ── 3. Commit and push ───────────────────────────────────────────────────────
log "Staging changes..."
git add *.html update.log

if [[ "$before_count" != "$after_count" ]]; then
    echo "$after_count" > "$COUNT_FILE"
    git add "$COUNT_FILE"
fi

if git diff --cached --quiet; then
    log "Nothing changed — skipping commit."
else
    if [[ "$before_count" != "$after_count" ]]; then
        delta_count="$((after_count - before_count))"
        delta_str="$(printf "%+d" "$delta_count")"
        msg="Auto-update: matches $before_count->$after_count ($delta_str), dashboards [$TIMESTAMP]"
    else
        msg="Auto-update: dashboards [$TIMESTAMP]"
    fi
    git commit -m "$msg"
    if [[ "$before_count" != "$after_count" ]]; then
        log "Pushing to origin (match updates detected)..."
        git push origin main
        log "Push complete."
    else
        log "No match updates — skipping push."
    fi
fi

log "=== TBA update finished ==="
