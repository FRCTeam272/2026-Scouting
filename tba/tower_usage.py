"""
Analyze matches.db to find which teams most commonly use the tower
(auto or endgame) across all stored matches.
"""

import os
import sqlite3
from collections import defaultdict

DB_PATH = "matches.db"

if not os.path.exists(DB_PATH):
    print(f"Database file '{DB_PATH}' does not exist.")
    from import_matches import main
    main()

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row

# For each match+color, get the ordered list of teams (robot1=idx0, robot2=idx1, robot3=idx2)
# We need a stable ordering — use the rowid/id from alliance_teams (insertion order matches TBA team_keys order)
teams_query = """
    SELECT match_key, color, team_key,
           ROW_NUMBER() OVER (PARTITION BY match_key, color ORDER BY id) AS robot_num
    FROM alliance_teams
"""

# Pull all tower values per match+color
breakdowns_query = """
    SELECT match_key, color,
           auto_tower_robot1, auto_tower_robot2, auto_tower_robot3,
           end_game_tower_robot1, end_game_tower_robot2, end_game_tower_robot3
    FROM score_breakdowns
"""

# Build lookup: (match_key, color, robot_num) -> team_key
team_lookup: dict[tuple, str] = {}
for row in con.execute(teams_query):
    team_lookup[(row["match_key"], row["color"], row["robot_num"])] = row["team_key"]

# Count tower usage per team
matches_played: dict[str, int] = defaultdict(int)
tower_matches: dict[str, int] = defaultdict(int)  # any tower use in that match
auto_uses: dict[str, int] = defaultdict(int)
endgame_uses: dict[str, int] = defaultdict(int)

# Count total matches per team (denominator)
for row in con.execute("SELECT match_key, color, team_key FROM alliance_teams"):
    matches_played[row["team_key"]] += 1

for row in con.execute(breakdowns_query):
    mk, color = row["match_key"], row["color"]
    for robot_num in (1, 2, 3):
        team = team_lookup.get((mk, color, robot_num))
        if team is None:
            continue
        auto_val = row[f"auto_tower_robot{robot_num}"]
        eg_val   = row[f"end_game_tower_robot{robot_num}"]
        used_auto    = auto_val is not None
        used_endgame = eg_val   is not None
        if used_auto:
            auto_uses[team] += 1
        if used_endgame:
            endgame_uses[team] += 1
        if used_auto or used_endgame:
            tower_matches[team] += 1

con.close()

# Gather all teams that have any breakdown data
all_teams = set(tower_matches) | set(auto_uses) | set(endgame_uses)

# Build result rows
results = []
for team in all_teams:
    played = matches_played.get(team, 0)
    tower  = tower_matches.get(team, 0)
    auto   = auto_uses.get(team, 0)
    eg     = endgame_uses.get(team, 0)
    rate   = tower / played if played else 0.0
    results.append((team, played, tower, rate, auto, eg))

# Sort by usage rate desc, then absolute count desc
results.sort(key=lambda r: (-r[3], -r[2]))

print(f"{'Team':<12} {'Played':>7} {'Tower':>7} {'Rate':>7}  {'Auto':>6} {'EndGame':>8}")
print("-" * 55)
for team, played, tower, rate, auto, eg in results:
    print(f"{team:<12} {played:>7} {tower:>7} {rate:>6.1%}  {auto:>6} {eg:>8}")
