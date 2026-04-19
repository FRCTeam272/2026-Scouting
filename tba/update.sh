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

get_match_counts() {
    if [[ ! -f "$DB_PATH" ]]; then
        echo "0 0"
        return
    fi

    "$PYTHON" - "$DB_PATH" <<'PY'
import sqlite3
import sys

db_path = sys.argv[1]
try:
    con = sqlite3.connect(db_path)
    total = con.execute("SELECT COUNT(*) FROM matches").fetchone()
    completed = con.execute("SELECT COUNT(*) FROM matches WHERE actual_time IS NOT NULL").fetchone()
    print(f"{total[0] if total else 0} {completed[0] if completed else 0}")
except Exception:
    print("0 0")
finally:
    try:
        con.close()
    except Exception:
        pass
PY
}

log "=== TBA update started ==="

read -r before_count before_completed <<< "$(get_match_counts)"
log "Matches in DB before import: $before_count total, $before_completed completed"

# ── 1. Import match data ──────────────────────────────────────────────────────
log "Running import_matches.py..."
$PYTHON import_matches.py

read -r after_count after_completed <<< "$(get_match_counts)"
log "Matches in DB after import: $after_count total, $after_completed completed"

# ── 2. Regenerate HTML dashboards (always, so upcoming pages stay current) ───
log "Running create_view.py..."
$PYTHON create_view.py

# ── 3. Commit and push ───────────────────────────────────────────────────────
log "Staging changes..."
git add *.html update.log

delta_total="$(printf "%+d" "$((after_count - before_count))")"
delta_completed="$(printf "%+d" "$((after_completed - before_completed))")"
msg="Auto-update: matches $before_count->$after_count ($delta_total), completed $before_completed->$after_completed ($delta_completed) [$TIMESTAMP]"
git commit -m "$msg"
log "Pushing to origin (match data updated)..."
git push origin main
log "Push complete."

log "=== TBA update finished ==="
