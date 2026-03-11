"""
Imports a TBA matches JSON file into a SQLite database.

Usage:
    python import_matches.py [matches.json] [output.db]

Defaults:
    matches.json -> 2026pahat_matches.json
    output.db    -> matches.db
"""

import glob
import json
import os
import sqlite3
import sys

TBA_BASE = "https://www.thebluealliance.com/api/v3"
TBA_MIN_MATCHES = 80


def _tba_headers() -> dict:
    import requests  # noqa: F401 (ensure available)
    secret_path = "../secret"
    with open(secret_path) as f:
        api_key = f.read().strip()
    return {"X-TBA-Auth-Key": api_key}


def _tba_fetch_matches(event_key: str) -> list:
    import requests
    url = f"{TBA_BASE}/event/{event_key}/matches"
    resp = requests.get(url, headers=_tba_headers())
    resp.raise_for_status()
    return resp.json()


def _tba_fetch_district_events(district_key: str) -> list:
    import requests
    url = f"{TBA_BASE}/district/{district_key}/events/keys"
    resp = requests.get(url, headers=_tba_headers())
    resp.raise_for_status()
    return resp.json()  # list of event key strings


def _load_or_fetch(json_path: str) -> list:
    """Load matches from json_path; if under TBA_MIN_MATCHES, fetch fresh from TBA and save."""
    if os.path.exists(json_path):
        with open(json_path) as f:
            matches = json.load(f)
    else:
        matches = []

    if len(matches) < TBA_MIN_MATCHES:
        basename = os.path.basename(json_path)
        # filename format: <event_key>_matches.json
        event_key = basename.replace("_matches.json", "")
        print(f"  {basename} has {len(matches)} matches (<{TBA_MIN_MATCHES}), fetching from TBA for event '{event_key}'...")
        matches = _tba_fetch_matches(event_key)
        with open(json_path, "w") as f:
            json.dump(matches, f, indent=2)
        print(f"  Fetched {len(matches)} matches, saved to {json_path}")

    return matches

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    key              TEXT PRIMARY KEY,
    event_key        TEXT NOT NULL,
    comp_level       TEXT NOT NULL,
    set_number       INTEGER NOT NULL,
    match_number     INTEGER NOT NULL,
    time             INTEGER,
    actual_time      INTEGER,
    predicted_time   INTEGER,
    post_result_time INTEGER,
    winning_alliance TEXT
);

CREATE TABLE IF NOT EXISTS match_alliances (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    match_key TEXT NOT NULL REFERENCES matches(key),
    color     TEXT NOT NULL CHECK (color IN ('blue', 'red')),
    score     INTEGER NOT NULL,
    UNIQUE (match_key, color)
);

CREATE TABLE IF NOT EXISTS alliance_teams (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    match_key    TEXT NOT NULL REFERENCES matches(key),
    color        TEXT NOT NULL CHECK (color IN ('blue', 'red')),
    team_key     TEXT NOT NULL,
    is_surrogate INTEGER NOT NULL DEFAULT 0,
    is_dq        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS hub_scores (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    match_key         TEXT NOT NULL REFERENCES matches(key),
    color             TEXT NOT NULL CHECK (color IN ('blue', 'red')),
    auto_count        INTEGER,
    auto_points       INTEGER,
    endgame_count     INTEGER,
    endgame_points    INTEGER,
    shift1_count      INTEGER,
    shift1_points     INTEGER,
    shift2_count      INTEGER,
    shift2_points     INTEGER,
    shift3_count      INTEGER,
    shift3_points     INTEGER,
    shift4_count      INTEGER,
    shift4_points     INTEGER,
    teleop_count      INTEGER,
    teleop_points     INTEGER,
    transition_count  INTEGER,
    transition_points INTEGER,
    total_count       INTEGER,
    total_points      INTEGER,
    uncounted         INTEGER,
    UNIQUE (match_key, color)
);

CREATE TABLE IF NOT EXISTS score_breakdowns (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    match_key             TEXT NOT NULL REFERENCES matches(key),
    color                 TEXT NOT NULL CHECK (color IN ('blue', 'red')),
    auto_tower_robot1     TEXT,
    auto_tower_robot2     TEXT,
    auto_tower_robot3     TEXT,
    auto_tower_points     INTEGER,
    end_game_tower_robot1 TEXT,
    end_game_tower_robot2 TEXT,
    end_game_tower_robot3 TEXT,
    end_game_tower_points INTEGER,
    foul_points           INTEGER,
    major_foul_count      INTEGER,
    minor_foul_count      INTEGER,
    g206_penalty          INTEGER,
    penalties             TEXT,
    energized_achieved    INTEGER,
    supercharged_achieved INTEGER,
    traversal_achieved    INTEGER,
    adjust_points         INTEGER,
    rp                    INTEGER,
    total_auto_points     INTEGER,
    total_teleop_points   INTEGER,
    total_tower_points    INTEGER,
    total_points          INTEGER,
    UNIQUE (match_key, color)
);

CREATE TABLE IF NOT EXISTS match_videos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    match_key TEXT NOT NULL REFERENCES matches(key),
    type      TEXT NOT NULL,
    video_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
    team_key TEXT PRIMARY KEY,
    nickname TEXT,
    name     TEXT,
    city     TEXT,
    state    TEXT,
    country  TEXT
);
"""


def _insert_matches(matches: list, source_label: str, db_path: str) -> None:
    """Insert a list of match dicts into the database."""

    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)

    inserted = 0
    skipped = 0

    with con:
        for match in matches:
            key = match["key"]

            # Check for duplicate
            exists = con.execute("SELECT 1 FROM matches WHERE key = ?", (key,)).fetchone()
            if exists:
                skipped += 1
                continue

            # matches
            con.execute(
                """INSERT INTO matches
                   (key, event_key, comp_level, set_number, match_number,
                    time, actual_time, predicted_time, post_result_time, winning_alliance)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    key,
                    match["event_key"],
                    match["comp_level"],
                    match["set_number"],
                    match["match_number"],
                    match.get("time"),
                    match.get("actual_time"),
                    match.get("predicted_time"),
                    match.get("post_result_time"),
                    match.get("winning_alliance"),
                ),
            )

            for color, alliance in match["alliances"].items():
                # match_alliances
                con.execute(
                    "INSERT INTO match_alliances (match_key, color, score) VALUES (?, ?, ?)",
                    (key, color, alliance["score"]),
                )

                surrogate_set = set(alliance.get("surrogate_team_keys", []))
                dq_set = set(alliance.get("dq_team_keys", []))

                # alliance_teams
                for team_key in alliance["team_keys"]:
                    con.execute(
                        """INSERT INTO alliance_teams
                           (match_key, color, team_key, is_surrogate, is_dq)
                           VALUES (?, ?, ?, ?, ?)""",
                        (
                            key,
                            color,
                            team_key,
                            int(team_key in surrogate_set),
                            int(team_key in dq_set),
                        ),
                    )

            breakdown = match.get("score_breakdown") or {}
            for color, sb in breakdown.items():
                hub = sb.get("hubScore", {})

                # hub_scores
                con.execute(
                    """INSERT INTO hub_scores
                       (match_key, color,
                        auto_count, auto_points,
                        endgame_count, endgame_points,
                        shift1_count, shift1_points,
                        shift2_count, shift2_points,
                        shift3_count, shift3_points,
                        shift4_count, shift4_points,
                        teleop_count, teleop_points,
                        transition_count, transition_points,
                        total_count, total_points, uncounted)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        key, color,
                        hub.get("autoCount"), hub.get("autoPoints"),
                        hub.get("endgameCount"), hub.get("endgamePoints"),
                        hub.get("shift1Count"), hub.get("shift1Points"),
                        hub.get("shift2Count"), hub.get("shift2Points"),
                        hub.get("shift3Count"), hub.get("shift3Points"),
                        hub.get("shift4Count"), hub.get("shift4Points"),
                        hub.get("teleopCount"), hub.get("teleopPoints"),
                        hub.get("transitionCount"), hub.get("transitionPoints"),
                        hub.get("totalCount"), hub.get("totalPoints"),
                        hub.get("uncounted"),
                    ),
                )

                # score_breakdowns
                def _none(val):
                    # TBA sends the string "None" for missing tower levels
                    return None if val == "None" else val

                con.execute(
                    """INSERT INTO score_breakdowns
                       (match_key, color,
                        auto_tower_robot1, auto_tower_robot2, auto_tower_robot3, auto_tower_points,
                        end_game_tower_robot1, end_game_tower_robot2, end_game_tower_robot3, end_game_tower_points,
                        foul_points, major_foul_count, minor_foul_count, g206_penalty, penalties,
                        energized_achieved, supercharged_achieved, traversal_achieved,
                        adjust_points, rp,
                        total_auto_points, total_teleop_points, total_tower_points, total_points)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        key, color,
                        _none(sb.get("autoTowerRobot1")),
                        _none(sb.get("autoTowerRobot2")),
                        _none(sb.get("autoTowerRobot3")),
                        sb.get("autoTowerPoints"),
                        _none(sb.get("endGameTowerRobot1")),
                        _none(sb.get("endGameTowerRobot2")),
                        _none(sb.get("endGameTowerRobot3")),
                        sb.get("endGameTowerPoints"),
                        sb.get("foulPoints"),
                        sb.get("majorFoulCount"),
                        sb.get("minorFoulCount"),
                        int(bool(sb.get("g206Penalty"))),
                        _none(sb.get("penalties")),
                        int(bool(sb.get("energizedAchieved"))),
                        int(bool(sb.get("superchargedAchieved"))),
                        int(bool(sb.get("traversalAchieved"))),
                        sb.get("adjustPoints"),
                        sb.get("rp"),
                        sb.get("totalAutoPoints"),
                        sb.get("totalTeleopPoints"),
                        sb.get("totalTowerPoints"),
                        sb.get("totalPoints"),
                    ),
                )

            # match_videos
            for video in match.get("videos", []):
                con.execute(
                    "INSERT INTO match_videos (match_key, type, video_key) VALUES (?, ?, ?)",
                    (key, video["type"], video["key"]),
                )

            inserted += 1

    con.close()
    print(f"Done {source_label}. Inserted {inserted} matches, skipped {skipped} duplicates -> {db_path}")


def import_matches(json_path: str, db_path: str) -> None:
    matches = _load_or_fetch(json_path)
    _insert_matches(matches, json_path, db_path)


def _sync_team_names(con: sqlite3.Connection) -> None:
    """Fetch TBA team info for any team_key not yet in the teams table."""
    import requests
    known = {row[0] for row in con.execute("SELECT team_key FROM teams")}
    needed = {row[0] for row in con.execute("SELECT DISTINCT team_key FROM alliance_teams")} - known
    if not needed:
        return
    headers = _tba_headers()
    for tk in sorted(needed):
        try:
            resp = requests.get(f"{TBA_BASE}/team/{tk}", headers=headers)
            resp.raise_for_status()
            d = resp.json()
            con.execute(
                """INSERT OR REPLACE INTO teams (team_key, nickname, name, city, state, country)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (tk, d.get("nickname"), d.get("name"), d.get("city"),
                 d.get("state_prov"), d.get("country")),
            )
            con.commit()
            print(f"  Stored team info for {tk}: {d.get('nickname')}")
        except Exception as e:
            print(f"  Warning: could not fetch {tk}: {e}")


def _finals_count(con: sqlite3.Connection, event_key: str) -> int:
    """Return the number of finals (f1) matches stored for an event."""
    row = con.execute(
        "SELECT COUNT(*) FROM matches WHERE event_key = ? AND comp_level = 'f' AND set_number = 1",
        (event_key,),
    ).fetchone()
    return row[0] if row else 0


def main() -> None:
    db_path = "matches.db"

    # Ensure DB + schema exist
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)

    # Get every 2026 FMA event from TBA
    print("Fetching 2026fma event list from TBA...")
    event_keys = _tba_fetch_district_events("2026fma")
    print(f"  {len(event_keys)} events: {event_keys}\n")

    for event_key in event_keys:
        finals = _finals_count(con, event_key)
        if finals < 2:
            print(f"  {event_key}: {finals} finals match(es) in DB — fetching from TBA...")
            matches = _tba_fetch_matches(event_key)
            # Save/overwrite local JSON
            json_path = f"{event_key}_matches.json"
            with open(json_path, "w") as f:
                json.dump(matches, f, indent=2)
            print(f"    Saved {len(matches)} matches to {json_path}")
            _insert_matches(matches, event_key, db_path)
        else:
            print(f"  {event_key}: {finals} finals match(es) already in DB — skipping fetch")

    print("\nSyncing team names...")
    _sync_team_names(con)
    con.close()

if __name__ == "__main__":
    main()
