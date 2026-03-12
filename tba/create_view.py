"""
Generate a dark-themed HTML dashboard (Region Wide.html) from matches.db.

Shows:
  • Overview  — tower-usage leaderboard, top alliance scores, RP/achievement rates
  • Per-team  — match-by-match tower levels, hub scores, win/loss
"""

import json
import sqlite3
from datetime import datetime

import numpy as np

# TBA /district/2026fma/events → short_name, keyed by first-8-chars of event key
EVENT_NAMES: dict[str, str] = {
    "2026mrcm": "Mid-Atlantic Championship",
    "2026njfl": "Mount Olive",
    "2026njro": "Robbinsville",
    "2026njsk": "Montgomery",
    "2026njta": "Seneca",
    "2026njwa": "Warren Hills",
    "2026pabe": "Bensalem",
    "2026paha": "Hatboro-Horsham",
    "2026paph": "Philadelphia",
    "2026pawa": "Centennial",
}


def compute_opr(team_keys: list, alliance_teams: list, scores: list) -> dict:
    """Least-squares OPR.  Returns {team_key: opr_value | None}."""
    idx = {tk: i for i, tk in enumerate(team_keys)}
    rows = [(a, s) for a, s in zip(alliance_teams, scores) if s is not None]
    if len(rows) < len(team_keys):
        return {tk: None for tk in team_keys}
    A = np.zeros((len(rows), len(team_keys)))
    b = np.zeros(len(rows))
    for i, (alliance, score) in enumerate(rows):
        for tk in alliance:
            if tk in idx:
                A[i, idx[tk]] = 1.0
        b[i] = float(score)
    x, *_ = np.linalg.lstsq(A, b, rcond=None)
    return {tk: round(float(x[idx[tk]]), 2) for tk in team_keys}

DB_PATH = "matches.db"


# ── Query helpers ─────────────────────────────────────────────────────────────

def load_data(db_path: str, event_prefix: str | None = None) -> dict:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    ep = event_prefix  # e.g. "2026njwa"
    mk_filter   = "WHERE substr(match_key,1,8)=?"   if ep else ""
    key_filter  = "WHERE substr(key,1,8)=?"          if ep else ""
    args        = (ep,) if ep else ()

    # robot position (1-indexed) for each team per match+color
    team_pos = {}
    for row in con.execute(f"""
        SELECT match_key, color, team_key,
               ROW_NUMBER() OVER (PARTITION BY match_key, color ORDER BY id) AS pos
        FROM alliance_teams {mk_filter}
    """, args):
        team_pos[(row["match_key"], row["color"], row["team_key"])] = row["pos"]

    # all teams and their match counts
    team_rows = con.execute(f"""
        SELECT team_key, COUNT(*) AS played
        FROM alliance_teams {mk_filter}
        GROUP BY team_key
        ORDER BY CAST(SUBSTR(team_key, 4) AS INTEGER)
    """, args).fetchall()

    # score_breakdowns keyed by (match_key, color)
    breakdowns = {}
    for row in con.execute(f"SELECT * FROM score_breakdowns {mk_filter}", args):
        breakdowns[(row["match_key"], row["color"])] = dict(row)

    # hub_scores keyed by (match_key, color)
    hub_scores = {}
    for row in con.execute(f"SELECT * FROM hub_scores {mk_filter}", args):
        hub_scores[(row["match_key"], row["color"])] = dict(row)

    # alliance scores
    alliance_scores = {}
    for row in con.execute(f"SELECT match_key, color, score FROM match_alliances {mk_filter}", args):
        alliance_scores[(row["match_key"], row["color"])] = row["score"]

    # matches metadata
    match_meta = {}
    for row in con.execute(f"SELECT key, event_key, comp_level, set_number, match_number, winning_alliance FROM matches {key_filter}", args):
        match_meta[row["key"]] = dict(row)

    # team names keyed by team_key (no filtering — names are global)
    team_names = {}
    try:
        for row in con.execute("SELECT team_key, nickname FROM teams"):
            team_names[row["team_key"]] = row["nickname"]
    except Exception:
        pass

    # videos keyed by match_key (first youtube video wins)
    match_videos = {}
    for row in con.execute(f"SELECT match_key, type, video_key FROM match_videos {mk_filter}", args):
        if row["match_key"] not in match_videos and row["type"] == "youtube":
            match_videos[row["match_key"]] = f"https://www.youtube.com/watch?v={row['video_key']}"

    # ── Build per-team data ───────────────────────────────────────────────────
    teams = []
    for trow in team_rows:
        tk = trow["team_key"]
        num = tk.replace("frc", "")
        played = trow["played"]

        match_history = []
        tower_matches = auto_tower_count = endgame_tower_count = 0
        events_seen = set()

        # find every match this team played
        for row in con.execute(
            "SELECT match_key, color FROM alliance_teams WHERE team_key = ? ORDER BY match_key",
            (tk,),
        ):
            mk, color = row["match_key"], row["color"]
            meta  = match_meta.get(mk, {})
            bd    = breakdowns.get((mk, color), {})
            hub   = hub_scores.get((mk, color), {})
            score = alliance_scores.get((mk, color))
            won   = meta.get("winning_alliance") == color if meta.get("winning_alliance") else None

            robot_num = team_pos.get((mk, color, tk))
            auto_tower = endgame_tower = None
            if robot_num and bd:
                auto_tower    = bd.get(f"auto_tower_robot{robot_num}")
                endgame_tower = bd.get(f"end_game_tower_robot{robot_num}")

            used_auto    = auto_tower    is not None
            used_endgame = endgame_tower is not None
            if used_auto:
                auto_tower_count += 1
            if used_endgame:
                endgame_tower_count += 1
            if used_auto or used_endgame:
                tower_matches += 1

            events_seen.add(meta.get("event_key", ""))

            match_history.append({
                "match_key":    mk,
                "event":        meta.get("event_key", ""),
                "comp_level":   meta.get("comp_level", ""),
                "match_number": meta.get("match_number"),
                "color":        color,
                "score":        score,
                "won":          won,
                "auto_tower":   auto_tower,
                "endgame_tower": endgame_tower,
                "hub_auto_pts":     hub.get("auto_points"),
                "hub_teleop_pts":   hub.get("teleop_points"),
                "hub_endgame_pts":  hub.get("endgame_points"),
                "hub_total_pts":    hub.get("total_points"),
                "hub_total_count":  hub.get("total_count"),
                "total_tower_pts":  bd.get("total_tower_points"),
                "energized":    bool(bd.get("energized_achieved")) if bd else None,
                "supercharged": bool(bd.get("supercharged_achieved")) if bd else None,
                "traversal":    bool(bd.get("traversal_achieved")) if bd else None,
                "rp":           bd.get("rp"),
                "video_url":    match_videos.get(mk),
            })

        scored = [m["score"] for m in match_history if m["score"] is not None]
        contrib_avg = round(sum(scored) / (len(scored) * 3), 2) if scored else None

        auto_vals   = [m["hub_auto_pts"]   for m in match_history if m["hub_auto_pts"]   is not None]
        teleop_vals = [m["hub_teleop_pts"]  for m in match_history if m["hub_teleop_pts"] is not None]
        auto_avg    = round(sum(auto_vals)   / len(auto_vals),   2) if auto_vals   else None
        teleop_avg  = round(sum(teleop_vals) / len(teleop_vals), 2) if teleop_vals else None

        teams.append({
            "key":          tk,
            "num":          num,
            "nickname":     team_names.get(tk),
            "played":       played,
            "tower_matches":      tower_matches,
            "tower_rate":         round(tower_matches / played, 4) if played else 0,
            "auto_tower_count":   auto_tower_count,
            "endgame_tower_count": endgame_tower_count,
            "contrib_avg":  contrib_avg,
            "auto_avg":     auto_avg,
            "teleop_avg":   teleop_avg,
            "events":       sorted(e for e in events_seen if e),
            "match_history": match_history,
        })

    # ── OPR ───────────────────────────────────────────────────────────────────
    # Group teams per alliance using team_pos keys
    alliances_map: dict = {}
    for (mk, color, tk) in team_pos:
        alliances_map.setdefault((mk, color), []).append(tk)

    alliance_list, score_list, auto_list, teleop_list, endgame_list = [], [], [], [], []
    for (mk, color), members in alliances_map.items():
        alliance_list.append(members)
        score_list.append(alliance_scores.get((mk, color)))
        hub = hub_scores.get((mk, color), {})
        auto_list.append(hub.get("auto_points"))
        teleop_list.append(hub.get("teleop_points"))
        endgame_list.append(hub.get("endgame_points"))

    team_keys_ordered = [trow["team_key"] for trow in team_rows]
    opr_map         = compute_opr(team_keys_ordered, alliance_list, score_list)
    auto_opr_map    = compute_opr(team_keys_ordered, alliance_list, auto_list)
    teleop_opr_map  = compute_opr(team_keys_ordered, alliance_list, teleop_list)
    endgame_opr_map = compute_opr(team_keys_ordered, alliance_list, endgame_list)

    for t in teams:
        tk = t["key"]
        t["opr"]         = opr_map.get(tk)
        t["auto_opr"]    = auto_opr_map.get(tk)
        t["teleop_opr"]  = teleop_opr_map.get(tk)
        t["endgame_opr"] = endgame_opr_map.get(tk)

    # ── Overview stats ────────────────────────────────────────────────────────
    # top alliance scores
    top_scores = sorted(
        [
            {"match_key": mk, "color": c, "score": s}
            for (mk, c), s in alliance_scores.items()
            if s is not None and s > 0
        ],
        key=lambda x: -x["score"],
    )[:20]

    # event breakdown
    event_matches = {}
    for mk, meta in match_meta.items():
        ek = meta.get("event_key", "unknown")
        event_matches[ek] = event_matches.get(ek, 0) + 1

    # achievement rates across all breakdowns
    total_bd = len(breakdowns)
    energized_count    = sum(1 for b in breakdowns.values() if b.get("energized_achieved"))
    supercharged_count = sum(1 for b in breakdowns.values() if b.get("supercharged_achieved"))
    traversal_count    = sum(1 for b in breakdowns.values() if b.get("traversal_achieved"))

    # ── Elimination bracket (event-specific views only) ──────────────────────
    bracket = None
    if ep:
        elim_team_map: dict = {}
        for mk, meta in match_meta.items():
            if meta["comp_level"] == "qm":
                continue
            red, blue = [], []
            for row in con.execute(
                "SELECT color, team_key FROM alliance_teams WHERE match_key = ? ORDER BY id",
                (mk,),
            ):
                (red if row["color"] == "red" else blue).append(
                    row["team_key"].replace("frc", "")
                )
            elim_team_map[mk] = {"red": red, "blue": blue}

        def sf_match(set_num: int) -> dict | None:
            candidates = sorted(
                [(mk, m) for mk, m in match_meta.items()
                 if m["comp_level"] == "sf" and m["set_number"] == set_num],
                key=lambda x: x[1]["match_number"],
            )
            if not candidates:
                return None
            mk, meta = candidates[-1]
            teams = elim_team_map.get(mk, {"red": [], "blue": []})
            return {
                "label":      f"SF{set_num}",
                "red":        teams["red"],
                "blue":       teams["blue"],
                "red_score":  alliance_scores.get((mk, "red")),
                "blue_score": alliance_scores.get((mk, "blue")),
                "winner":     meta["winning_alliance"],
            }

        # 2023+ FRC double-elimination set-number layout:
        #   R1 upper: 1,2,3,4 | R2 upper: 7,8 + lower: 5,6
        #   R3 upper final: 11 + lower: 9,10 | R4 lower/elim final: 12,13
        round_defs = [
            ("Round 1",  "Upper Bracket",             [1, 2, 3, 4]),
            ("Round 2",  "Upper / Lower",             [7, 8, 5, 6]),
            ("Round 3",  "Upper Final / Lower",       [11, 9, 10]),
            ("Round 4",  "Lower Final / Elim Final",  [12, 13]),
        ]
        rounds_data = []
        for rname, rsub, sets in round_defs:
            matches = [sf_match(s) for s in sets if sf_match(s) is not None]
            if matches:
                rounds_data.append({"name": rname, "sub": rsub, "matches": matches})

        final_matches = []
        for mk, meta in sorted(match_meta.items(), key=lambda x: x[1]["match_number"]):
            if meta["comp_level"] != "f":
                continue
            ft = elim_team_map.get(mk, {"red": [], "blue": []})
            final_matches.append({
                "label":      f"Final {meta['match_number']}",
                "red":        ft["red"],
                "blue":       ft["blue"],
                "red_score":  alliance_scores.get((mk, "red")),
                "blue_score": alliance_scores.get((mk, "blue")),
                "winner":     meta["winning_alliance"],
            })

        bracket = {"rounds": rounds_data, "finals": final_matches}

    overview = {
        "total_matches": len(match_meta),
        "total_teams":   len(team_rows),
        "total_breakdowns": total_bd,
        "energized_rate":    round(energized_count    / total_bd, 4) if total_bd else 0,
        "supercharged_rate": round(supercharged_count / total_bd, 4) if total_bd else 0,
        "traversal_rate":    round(traversal_count    / total_bd, 4) if total_bd else 0,
        "top_scores":    top_scores,
        "event_matches": event_matches,
        "bracket":       bracket,
    }

    # ── Schedule: all matches ─────────────────────────────────────────────────
    sched_cond = "AND substr(key,1,8)=?" if ep else ""
    sched_args = (ep,) if ep else ()
    schedule = []
    sched_rows = con.execute(f"""
        SELECT key, event_key, comp_level, set_number, match_number,
               COALESCE(actual_time, time, predicted_time) AS sched_time,
               winning_alliance
        FROM matches
        WHERE 1=1 {sched_cond}
        ORDER BY COALESCE(actual_time, time, predicted_time, 9999999999), comp_level, set_number, match_number
    """, sched_args).fetchall()
    for row in sched_rows:
        mk = row["key"]
        teams_by_color: dict = {"red": [], "blue": []}
        for trow in con.execute(
            "SELECT color, team_key FROM alliance_teams WHERE match_key = ? ORDER BY id", (mk,)
        ):
            teams_by_color[trow["color"]].append(trow["team_key"])
        if teams_by_color["red"] or teams_by_color["blue"]:
            schedule.append({
                "match_key":      mk,
                "event":          row["event_key"],
                "comp_level":     row["comp_level"],
                "set_number":     row["set_number"],
                "match_number":   row["match_number"],
                "sched_time":     row["sched_time"],
                "winner":         row["winning_alliance"] or None,
                "red":            teams_by_color["red"],
                "blue":           teams_by_color["blue"],
                "red_score":      alliance_scores.get((mk, "red")),
                "blue_score":     alliance_scores.get((mk, "blue")),
            })

    con.close()
    return {"teams": teams, "overview": overview, "schedule": schedule}


# ── HTML template ─────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>__TITLE__</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
  <style>
    :root {
      --bg:#0f1117; --surface:#1a1d27; --surface2:#22263a; --border:#2e334d;
      --accent:#4f8ef7; --accent2:#f7a84f; --text:#e4e6f0; --muted:#7b82a0;
      --green:#4caf82; --red:#e05c5c; --yellow:#e0c45c; --purple:#9c6cf7; --teal:#4fc5cf;
      --sidebar-w:260px;
    }
    *{box-sizing:border-box;margin:0;padding:0;}
    body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);display:flex;flex-direction:column;height:100vh;overflow:hidden;}

    header{background:var(--surface);border-bottom:1px solid var(--border);padding:12px 16px;display:flex;align-items:center;gap:12px;flex-shrink:0;}
    header h1{font-size:1.1rem;font-weight:700;color:var(--accent);letter-spacing:.04em;white-space:nowrap;}
    #team-count{color:var(--muted);font-size:.8rem;white-space:nowrap;}
    #search{margin-left:auto;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:6px 10px;color:var(--text);font-size:.85rem;width:180px;outline:none;}
    #search:focus{border-color:var(--accent);}
    #sort-by{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:6px 8px;color:var(--text);font-size:.8rem;outline:none;cursor:pointer;}
    #sort-by:focus{border-color:var(--accent);}

    .layout{display:flex;flex:1;overflow:hidden;}
    aside{width:var(--sidebar-w);flex-shrink:0;background:var(--surface);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden;}
    #sidebar-scroll{flex:1;overflow-y:auto;padding-bottom:8px;}

    .overview-btn{display:flex;align-items:center;gap:8px;width:100%;padding:11px 16px;background:none;border:none;border-left:3px solid transparent;border-bottom:1px solid var(--border);color:var(--text);font-size:.9rem;font-weight:600;cursor:pointer;}
    .overview-btn:hover{background:var(--surface2);}
    .overview-btn.active{background:var(--surface2);border-left-color:var(--accent2);color:var(--accent2);}

    .team-item{display:flex;align-items:center;gap:8px;padding:8px 12px;border-left:3px solid transparent;cursor:pointer;}
    .team-item:hover{background:var(--surface2);}
    .team-item.active{background:var(--surface2);border-left-color:var(--accent);}
    .team-num{font-weight:700;font-size:.9rem;color:var(--accent);}
    .team-sub{font-size:.72rem;color:var(--muted);margin-top:1px;}
    .team-badge{margin-left:auto;font-size:.68rem;background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:1px 6px;color:var(--muted);white-space:nowrap;}
    .badge-tower{background:rgba(79,197,207,.15);border-color:var(--teal);color:var(--teal);}

    footer{background:var(--surface);border-top:1px solid var(--border);padding:10px 20px;font-size:.75rem;color:var(--muted);text-align:center;flex-shrink:0;}

    main{flex:1;overflow-y:auto;padding:20px;min-width:0;}
    #placeholder{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:var(--muted);gap:8px;}
    #placeholder svg{opacity:.2;}
    #team-view,#overview-view{display:none;}

    .section-title{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:12px;margin-top:24px;}
    .section-title:first-child{margin-top:0;}
    .page-header{margin-bottom:20px;}
    .page-header h2{font-size:1.4rem;font-weight:700;}
    .page-header h2 span{color:var(--accent);}
    .page-header p{color:var(--muted);font-size:.85rem;margin-top:4px;}
    .data-warning{display:flex;align-items:center;gap:8px;background:rgba(224,196,92,.08);border:1px solid rgba(224,196,92,.35);border-radius:8px;padding:9px 14px;margin-bottom:16px;font-size:.82rem;color:var(--yellow);}
    .ext-link{display:inline-flex;align-items:center;gap:4px;font-size:.78rem;color:var(--accent);text-decoration:none;}
    .ext-link:hover{text-decoration:underline;}

    .charts-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;}
    .charts-grid.single{grid-template-columns:1fr;}
    .charts-grid.triple{grid-template-columns:1fr 1fr 1fr;}
    .chart-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;}
    .chart-card h3{font-size:.75rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:12px;}
    .chart-wrap{position:relative;}
    .chart-wrap.tall{height:320px;}
    .chart-wrap.medium{height:200px;}
    .chart-wrap.short{height:140px;}
    .chart-wrap canvas{width:100%!important;}
    .no-data{color:var(--muted);font-size:.85rem;font-style:italic;padding:20px 0;}

    .stat-row{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:12px;margin-bottom:16px;}
    .stat-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;}
    .stat-label{font-size:.68rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:6px;}
    .stat-value{font-size:1.6rem;font-weight:700;color:var(--accent);}
    .stat-sub{font-size:.75rem;color:var(--muted);margin-top:2px;}

    .matches-grid{display:flex;flex-direction:column;gap:10px;}
    .match-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden;}
    .match-card-header{background:var(--surface2);padding:8px 14px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px;}
    .match-label{font-weight:700;font-size:.9rem;color:var(--accent2);}
    .match-color{font-size:.72rem;font-weight:700;padding:2px 6px;border-radius:4px;}
    .match-color.red{background:rgba(224,92,92,.2);color:var(--red);}
    .match-color.blue{background:rgba(79,142,247,.2);color:var(--accent);}
    .result-win{color:var(--green);font-weight:700;font-size:.75rem;}
    .result-loss{color:var(--red);font-weight:700;font-size:.75rem;}
    .result-tbd{color:var(--muted);font-size:.75rem;}
    .event-tag{font-size:.7rem;color:var(--muted);background:var(--surface2);border:1px solid var(--border);border-radius:4px;padding:1px 6px;}
    .match-score{margin-left:auto;font-size:.85rem;font-weight:700;color:var(--text);}
    .video-link{font-size:.75rem;font-weight:600;color:var(--red);text-decoration:none;padding:2px 7px;border-radius:4px;background:rgba(224,92,92,.12);border:1px solid rgba(224,92,92,.3);white-space:nowrap;}
    .video-link:hover{background:rgba(224,92,92,.25);}
    .match-fields{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:1px;background:var(--border);}
    .field{background:var(--surface);padding:8px 12px;}
    .field-label{font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:2px;}
    .field-value{font-size:.88rem;font-weight:600;}
    .tower-level{display:inline-block;font-size:.7rem;font-weight:700;padding:2px 7px;border-radius:4px;background:rgba(79,197,207,.15);color:var(--teal);border:1px solid rgba(79,197,207,.4);}
    .tower-none{color:var(--muted);font-style:italic;font-weight:400;}
    .val-yes{color:var(--green);}
    .val-no{color:var(--red);}
    .val-num{color:var(--accent);}
    .val-null{color:var(--muted);font-style:italic;font-weight:400;}

    .leaderboard{display:flex;flex-direction:column;gap:6px;}
    .lb-row{display:flex;align-items:center;gap:10px;padding:8px 12px;background:var(--surface2);border-radius:8px;border:1px solid var(--border);}
    .lb-rank{font-size:.75rem;font-weight:700;color:var(--muted);width:20px;text-align:right;flex-shrink:0;}
    .lb-team{font-weight:700;color:var(--accent);min-width:50px;}
    .lb-bar-wrap{flex:1;background:var(--border);border-radius:4px;height:8px;overflow:hidden;}
    .lb-bar{height:100%;border-radius:4px;background:var(--teal);}
    .lb-pct{font-size:.75rem;color:var(--text);font-weight:600;min-width:42px;text-align:right;}
    .lb-counts{font-size:.7rem;color:var(--muted);}

    /* Compare bar */
    #compare-bar{background:var(--surface2);border-bottom:1px solid var(--border);padding:8px 12px;display:none;flex-direction:column;gap:6px;flex-shrink:0;}
    #compare-chips{display:flex;flex-wrap:wrap;gap:4px;}
    .chip{display:inline-flex;align-items:center;gap:4px;background:var(--accent);color:#fff;border-radius:12px;padding:2px 8px;font-size:.75rem;font-weight:600;}
    .chip button{background:none;border:none;color:#fff;cursor:pointer;font-size:.85rem;line-height:1;padding:0 0 0 2px;opacity:.8;}
    .chip button:hover{opacity:1;}
    .compare-actions{display:flex;gap:6px;}
    .compare-actions button{flex:1;padding:5px 8px;border-radius:6px;border:none;cursor:pointer;font-size:.78rem;font-weight:600;}
    #btn-do-compare{background:var(--accent);color:#fff;}
    #btn-do-compare:hover{opacity:.85;}
    #btn-clear-compare{background:var(--surface);color:var(--muted);border:1px solid var(--border);}
    #btn-clear-compare:hover{color:var(--text);}
    /* Hide & compare controls on team items */
    .team-item{position:relative;}
    .team-item:hover .hide-btn{opacity:1;}
    .compare-check{width:14px;height:14px;flex-shrink:0;accent-color:var(--accent);cursor:pointer;}
    .compare-check:disabled{opacity:.3;cursor:not-allowed;}
    .hide-btn{background:none;border:none;color:var(--muted);cursor:pointer;font-size:1rem;line-height:1;padding:2px 4px;opacity:0;border-radius:4px;flex-shrink:0;}
    .hide-btn:hover{color:var(--red);}
    #show-hidden-btn{display:none;width:100%;padding:10px 16px;background:none;border:none;border-top:1px solid var(--border);color:var(--muted);font-size:.8rem;cursor:pointer;text-align:left;}
    #show-hidden-btn:hover{color:var(--text);background:var(--surface2);}
    /* Compare view */
    #compare-view{display:none;}
    .compare-blocks{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;}
    .compare-block{border:1px solid var(--border);border-radius:10px;overflow:hidden;}
    .compare-block-header{font-size:.9rem;font-weight:700;color:var(--accent);padding:9px 14px;background:var(--surface2);border-bottom:1px solid var(--border);}

    #menu-btn{display:none;background:none;border:none;color:var(--text);cursor:pointer;padding:4px;flex-shrink:0;line-height:0;}
    .sidebar-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:99;}
    .sidebar-overlay.open{display:block;}

    @media(max-width:768px){
      body{height:100dvh;}
      header{flex-wrap:wrap;gap:8px;}
      header h1{font-size:1rem;}
      #menu-btn{display:block;}
      #team-count,#ts-label{display:none;}
      #search{width:100%;margin-left:0;order:10;flex:1 1 100%;}
      #sort-by{order:11;flex:1 1 100%;}
      aside{position:fixed;top:0;left:0;height:100%;z-index:100;transform:translateX(-100%);transition:transform .25s ease;width:min(var(--sidebar-w),85vw);}
      aside.open{transform:translateX(0);}
      main{padding:12px;}
      .charts-grid,.charts-grid.triple{grid-template-columns:1fr;}
      .stat-row{grid-template-columns:1fr 1fr;}
      .compare-blocks{grid-template-columns:1fr;}
      .match-fields{grid-template-columns:repeat(auto-fill,minmax(120px,1fr));}
    }

    /* Elimination bracket */
    .bracket-wrap{overflow-x:auto;margin-bottom:16px;padding-bottom:8px;}
    .bracket{display:flex;gap:14px;align-items:flex-start;min-width:max-content;}
    .bracket-round{display:flex;flex-direction:column;gap:8px;width:210px;}
    .bracket-round-header{margin-bottom:4px;}
    .bracket-round-name{font-size:.75rem;font-weight:700;color:var(--text);}
    .bracket-round-sub{font-size:.63rem;color:var(--muted);}
    .bracket-match{background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;}
    .bracket-match-label{font-size:.62rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;padding:3px 8px;background:var(--surface2);border-bottom:1px solid var(--border);}
    .bracket-alliance{display:flex;align-items:center;gap:6px;padding:5px 8px;border-bottom:1px solid var(--border);}
    .bracket-alliance:last-child{border-bottom:none;}
    .bracket-alliance.winner{background:rgba(76,175,130,.12);}
    .bracket-alliance.loser{opacity:.5;}
    .bracket-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;}
    .bracket-dot.red{background:var(--red);}
    .bracket-dot.blue{background:var(--accent);}
    .bracket-teams{flex:1;font-size:.7rem;color:var(--text);}
    .bracket-score{font-size:.78rem;font-weight:700;color:var(--text);min-width:26px;text-align:right;}

    /* Schedule view */
    #schedule-view{display:none;}
    .schedule-alliances{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--border);}
    .schedule-alliance{padding:10px 14px;}
    .schedule-alliance.red{background:rgba(224,92,92,.06);}
    .schedule-alliance.blue{background:rgba(79,142,247,.06);}
    .alliance-label{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px;}
    .alliance-label.red{color:var(--red);}
    .alliance-label.blue{color:var(--accent);}
    .alliance-team{display:flex;align-items:center;gap:8px;padding:3px 0;}
    .alliance-team-num{font-weight:700;font-size:.88rem;color:var(--text);cursor:pointer;}
    .alliance-team-num:hover{color:var(--accent);}
    .alliance-team-stat{font-size:.72rem;color:var(--muted);}
    .compare-match-btn{font-size:.75rem;font-weight:600;color:var(--accent);background:rgba(79,142,247,.12);border:1px solid rgba(79,142,247,.3);border-radius:4px;padding:2px 7px;white-space:nowrap;cursor:pointer;}
    .compare-match-btn:hover{background:rgba(79,142,247,.25);}
    .winner-alliance{background:rgba(76,175,130,.1)!important;}
  </style>
</head>
<body>
<header>
  <button id="menu-btn" onclick="toggleSidebar()" title="Menu">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>
    </svg>
  </button>
  <h1>__TITLE__</h1>
  <span id="team-count"></span>
  <span id="ts-label" style="color:var(--muted);font-size:.75rem;white-space:nowrap;">Generated __TIMESTAMP__</span>
  <input id="search" type="text" placeholder="Search team..."/>
  <select id="sort-by" title="Sort teams by">
    <option value="tower">Tower usage</option>
    <option value="num" selected>Team number</option>
    <option value="opr">OPR</option>
    <option value="auto_opr">Auto OPR</option>
    <option value="teleop_opr">Teleop OPR</option>
    <option value="endgame_opr">Endgame OPR</option>
    <option value="auto">Auto avg</option>
    <option value="teleop">Teleop avg</option>
    <option value="combined">Combined avg</option>
  </select>
</header>
<div class="layout">
  <aside>
    <div id="compare-bar">
      <div id="compare-chips"></div>
      <div class="compare-actions">
        <button id="btn-do-compare" onclick="showComparison()">Compare (<span id="compare-count">0</span>)</button>
        <button id="btn-clear-compare" onclick="clearCompare()">Clear</button>
      </div>
    </div>
    <div id="sidebar-scroll">
      <button class="overview-btn" id="overview-btn" onclick="showOverview()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
          <rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>
        </svg>
        Overview
      </button>
      <button class="overview-btn" id="schedule-btn" onclick="showSchedule()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/>
          <line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>
        </svg>
        Schedule
        <span id="schedule-count" style="margin-left:auto;font-size:.7rem;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:1px 6px;color:var(--muted);"></span>
      </button>
      <div id="team-list"></div>
    </div>
    <button id="show-hidden-btn" onclick="showAllHidden()"></button>
  </aside>
  <main>
    <div id="placeholder">
      <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2"/>
        <rect x="9" y="3" width="6" height="4" rx="1"/>
        <path d="M9 12h6M9 16h4"/>
      </svg>
      <p>Select a team or view Overview</p>
    </div>
    <div id="team-view"></div>
    <div id="overview-view"></div>
    <div id="compare-view"></div>
    <div id="schedule-view"></div>
  </main>
</div>
<footer>FRC 272 · TBA Match Data 2026</footer>

<script>
const DATA = __DATA__;

const activeCharts = {};
let compareSet = new Set();
let hiddenSet  = new Set(JSON.parse(localStorage.getItem('tba_hidden') || '[]'));
Chart.defaults.color = '#7b82a0';
Chart.defaults.borderColor = '#2e334d';
Chart.defaults.font.family = "'Segoe UI',system-ui,sans-serif";

const P = { blue:'#4f8ef7', orange:'#f7a84f', green:'#4caf82', red:'#e05c5c',
            purple:'#9c6cf7', teal:'#4fc5cf', yellow:'#e0c45c' };

function baseOpts(extra={}) {
  return { responsive:true, maintainAspectRatio:false, ...extra,
    plugins:{ legend:{ labels:{ boxWidth:12, padding:12, font:{size:11} } },
              tooltip:{ backgroundColor:'#1a1d27', borderColor:'#2e334d', borderWidth:1,
                        titleColor:'#e4e6f0', bodyColor:'#7b82a0', padding:10 } },
    scales:{ x:{ grid:{color:'#2e334d'}, ticks:{color:'#7b82a0'} },
             y:{ grid:{color:'#2e334d'}, ticks:{color:'#7b82a0'} } } };
}
function makeChart(id, cfg) {
  if (activeCharts[id]) { activeCharts[id].destroy(); delete activeCharts[id]; }
  const el = document.getElementById(id);
  if (el) activeCharts[id] = new Chart(el, cfg);
}

function hideAll() {
  ['placeholder','team-view','overview-view','compare-view','schedule-view'].forEach(id => document.getElementById(id).style.display='none');
  document.querySelectorAll('.team-item').forEach(el => el.classList.remove('active'));
  document.getElementById('overview-btn').classList.remove('active');
  document.getElementById('schedule-btn').classList.remove('active');
}

// ── Compare ───────────────────────────────────────────────────────────────────
function toggleCompare(key, checked) {
  if (checked && compareSet.size < 6) compareSet.add(key); else compareSet.delete(key);
  updateCompareBar(); updateCheckboxStates();
}
function removeFromCompare(key) {
  compareSet.delete(key);
  const cb = document.querySelector(`.compare-check[data-key="${key}"]`);
  if (cb) cb.checked = false;
  updateCompareBar(); updateCheckboxStates();
}
function clearCompare() {
  compareSet.clear();
  document.querySelectorAll('.compare-check').forEach(cb => { cb.checked = false; cb.disabled = false; });
  updateCompareBar();
}
function updateCompareBar() {
  const bar = document.getElementById('compare-bar');
  if (compareSet.size === 0) { bar.style.display = 'none'; return; }
  bar.style.display = 'flex';
  document.getElementById('compare-chips').innerHTML = DATA.teams
    .filter(t => compareSet.has(t.key))
    .map(t => `<span class="chip">#${t.num} <button onclick="removeFromCompare('${t.key}')">×</button></span>`)
    .join('');
  document.getElementById('compare-count').textContent = compareSet.size;
}
function updateCheckboxStates() {
  document.querySelectorAll('.compare-check').forEach(cb => {
    cb.disabled = !cb.checked && compareSet.size >= 6;
  });
}

// ── Hide ──────────────────────────────────────────────────────────────────────
function hideTeam(e, key) {
  e.stopPropagation();
  hiddenSet.add(key); compareSet.delete(key);
  localStorage.setItem('tba_hidden', JSON.stringify([...hiddenSet]));
  updateCompareBar(); rebuildSidebar();
}
function showAllHidden() {
  hiddenSet.clear(); localStorage.setItem('tba_hidden', JSON.stringify([])); rebuildSidebar();
}
function rebuildSidebar() {
  const q = document.getElementById('search').value.toLowerCase();
  const sortBy = document.getElementById('sort-by').value;
  const sorters = {
    tower:       (a,b) => (b.tower_rate - a.tower_rate) || (b.tower_matches - a.tower_matches),
    num:         (a,b) => parseInt(a.num) - parseInt(b.num),
    opr:         (a,b) => (b.opr         ?? -Infinity) - (a.opr         ?? -Infinity),
    auto_opr:    (a,b) => (b.auto_opr    ?? -Infinity) - (a.auto_opr    ?? -Infinity),
    teleop_opr:  (a,b) => (b.teleop_opr  ?? -Infinity) - (a.teleop_opr  ?? -Infinity),
    endgame_opr: (a,b) => (b.endgame_opr ?? -Infinity) - (a.endgame_opr ?? -Infinity),
    auto:        (a,b) => (b.auto_avg    ?? -1) - (a.auto_avg    ?? -1),
    teleop:      (a,b) => (b.teleop_avg  ?? -1) - (a.teleop_avg  ?? -1),
    combined:    (a,b) => ((b.auto_avg??0)+(b.teleop_avg??0)) - ((a.auto_avg??0)+(a.teleop_avg??0)),
  };
  const visible = DATA.teams
    .filter(t => !hiddenSet.has(t.key) && (t.num.includes(q) || (t.nickname||'').toLowerCase().includes(q)))
    .sort(sorters[sortBy] || sorters.tower);
  buildSidebar(visible);
  const btn = document.getElementById('show-hidden-btn');
  btn.style.display = hiddenSet.size > 0 ? 'block' : 'none';
  if (hiddenSet.size > 0) btn.textContent = `Show ${hiddenSet.size} hidden team${hiddenSet.size !== 1 ? 's' : ''}`;
}

// ── Compare View ──────────────────────────────────────────────────────────────
function showComparison() {
  if (compareSet.size < 2) return;
  hideAll();
  saveNav({view: 'compare', keys: [...compareSet]});
  const teams = [...compareSet].map(k => DATA.teams.find(t => t.key === k)).filter(Boolean);

  const cv = document.getElementById('compare-view');
  cv.innerHTML = `
    <div class="page-header">
      <h2>Comparing <span>${teams.length} Teams</span></h2>
      <p>${teams.map(t => '#'+t.num).join(' · ')}</p>
    </div>
    <div class="charts-grid">
      <div class="chart-card"><h3>Pt Contribution Avg</h3>
        <div class="chart-wrap medium"><canvas id="cmp-contrib"></canvas></div></div>
      <div class="chart-card"><h3>Tower Usage %</h3>
        <div class="chart-wrap medium"><canvas id="cmp-tower"></canvas></div></div>
    </div>
    <div class="charts-grid">
      <div class="chart-card"><h3>Auto Tower Matches</h3>
        <div class="chart-wrap medium"><canvas id="cmp-auto-tower"></canvas></div></div>
      <div class="chart-card"><h3>Endgame Tower Matches</h3>
        <div class="chart-wrap medium"><canvas id="cmp-eg-tower"></canvas></div></div>
    </div>
    <p class="section-title">Match Records</p>
    <div class="compare-blocks">
      ${teams.map(t => `
        <div class="compare-block">
          <div class="compare-block-header">#${t.num}${t.nickname ? ' · '+t.nickname : ''} · ${t.played}m</div>
          ${t.match_history.map(m => {
            const lbl = matchLabel(m);
            const resultCls = m.won===true?'result-win':m.won===false?'result-loss':'result-tbd';
            const resultText = m.won===true?'WIN':m.won===false?'LOSS':'TBD';
            const videoLink = m.video_url ? `<a class="video-link" href="${m.video_url}" target="_blank">▶</a>` : '';
            return `<div class="match-card" style="border-radius:0;border-left:none;border-right:none;border-top:none;">
              <div class="match-card-header">
                <span class="match-label">${lbl}</span>
                <span class="match-color ${m.color}">${m.color.toUpperCase()}</span>
                <span class="${resultCls}">${resultText}</span>
                <span class="event-tag">${eventShort(m.event)}</span>
                <span class="match-score">${m.score ?? '—'} pts</span>
                ${videoLink}
              </div>
              <div class="match-fields">
                <div class="field"><div class="field-label">Auto Tower</div><div class="field-value">${towerBadge(m.auto_tower)}</div></div>
                <div class="field"><div class="field-label">Endgame Tower</div><div class="field-value">${towerBadge(m.endgame_tower)}</div></div>
                <div class="field"><div class="field-label">Hub Total Pts</div><div class="field-value val-num">${num(m.hub_total_pts)}</div></div>
                <div class="field"><div class="field-label">Tower Pts</div><div class="field-value val-num">${num(m.total_tower_pts)}</div></div>
              </div>
            </div>`;
          }).join('')}
        </div>`).join('')}
    </div>`;
  cv.style.display = 'block';

  const labels = teams.map(t => '#'+t.num);
  const COLORS = [P.blue, P.orange, P.teal, P.purple, P.green, P.red];

  makeChart('cmp-contrib', { type:'bar', data:{ labels, datasets:[{
    label:'Pt Contribution Avg',
    data: teams.map(t => t.contrib_avg ?? 0),
    backgroundColor: teams.map((_,i) => COLORS[i%COLORS.length]+'cc'),
    borderColor:     teams.map((_,i) => COLORS[i%COLORS.length]),
    borderWidth:1 }]}, options: baseOpts()});

  makeChart('cmp-tower', { type:'bar', data:{ labels, datasets:[{
    label:'Tower Usage %',
    data: teams.map(t => Math.round(t.tower_rate*100)),
    backgroundColor: teams.map((_,i) => COLORS[i%COLORS.length]+'cc'),
    borderColor:     teams.map((_,i) => COLORS[i%COLORS.length]),
    borderWidth:1 }]}, options: baseOpts({ scales:{ x:{grid:{color:'#2e334d'},ticks:{color:'#7b82a0'}}, y:{grid:{color:'#2e334d'},ticks:{color:'#7b82a0'},min:0,max:100} }})});

  makeChart('cmp-auto-tower', { type:'bar', data:{ labels, datasets:[{
    label:'Auto Tower Matches',
    data: teams.map(t => t.auto_tower_count),
    backgroundColor: teams.map((_,i) => COLORS[i%COLORS.length]+'cc'),
    borderColor:     teams.map((_,i) => COLORS[i%COLORS.length]),
    borderWidth:1 }]}, options: baseOpts()});

  makeChart('cmp-eg-tower', { type:'bar', data:{ labels, datasets:[{
    label:'Endgame Tower Matches',
    data: teams.map(t => t.endgame_tower_count),
    backgroundColor: teams.map((_,i) => COLORS[i%COLORS.length]+'cc'),
    borderColor:     teams.map((_,i) => COLORS[i%COLORS.length]),
    borderWidth:1 }]}, options: baseOpts()});
}

// ── Schedule View ─────────────────────────────────────────────────────────────
function renderAllianceTeam(key) {
  const t = DATA.teams.find(t => t.key === key);
  const n = key.replace('frc','');
  const stat = t ? (t.opr !== null ? `OPR ${t.opr}` : t.contrib_avg !== null ? `Avg ${t.contrib_avg}` : '') : '';
  return `<div class="alliance-team">
    <span class="alliance-team-num" onclick="loadTeam('${key}')">#${n}${t&&t.nickname?` <span style="font-weight:400;color:var(--muted);font-size:.75rem;">${t.nickname}</span>`:''}
    </span>
    ${stat ? `<span class="alliance-team-stat">${stat}</span>` : ''}
  </div>`;
}
function compareMatch(matchKey) {
  const m = DATA.schedule.find(m => m.match_key === matchKey);
  if (!m) return;
  clearCompare();
  [...m.red, ...m.blue].forEach(k => { if (DATA.teams.find(t => t.key === k)) compareSet.add(k); });
  updateCompareBar(); updateCheckboxStates();
  showComparison();
}
function scheduleMatchCard(m) {
  const lbl = matchLabel(m);
  const timeStr = m.sched_time
    ? new Date(m.sched_time * 1000).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})
    : '';
  const compareBtn = `<button class="compare-match-btn" style="margin-left:auto;" onclick="compareMatch('${m.match_key}')">Compare</button>`;
  const redWin  = m.winner === 'red';
  const blueWin = m.winner === 'blue';
  const decided = m.winner != null;
  const allNums = [...m.red, ...m.blue].map(k => k.replace('frc','')).join(' ');
  return `<div class="match-card" data-teams="${allNums}">
    <div class="match-card-header">
      <span class="match-label">${lbl}</span>
      <span class="event-tag">${eventShort(m.event)}</span>
      ${timeStr ? `<span style="font-size:.78rem;color:var(--muted);">${timeStr}</span>` : ''}
      ${compareBtn}
    </div>
    <div class="schedule-alliances">
      <div class="schedule-alliance red${redWin?' winner-alliance':''}">
        <div class="alliance-label red" style="display:flex;align-items:center;gap:6px;">
          Red Alliance
          ${decided ? `<span style="margin-left:auto;font-weight:700;font-size:.78rem;color:${redWin?'var(--green)':'var(--muted)'};">${m.red_score ?? '—'}</span>` : ''}
          ${redWin ? `<span class="result-win" style="font-size:.7rem;">WIN</span>` : ''}
        </div>
        ${m.red.map(renderAllianceTeam).join('')}
      </div>
      <div class="schedule-alliance blue${blueWin?' winner-alliance':''}">
        <div class="alliance-label blue" style="display:flex;align-items:center;gap:6px;">
          Blue Alliance
          ${decided ? `<span style="margin-left:auto;font-weight:700;font-size:.78rem;color:${blueWin?'var(--green)':'var(--muted)'};">${m.blue_score ?? '—'}</span>` : ''}
          ${blueWin ? `<span class="result-win" style="font-size:.7rem;">WIN</span>` : ''}
        </div>
        ${m.blue.map(renderAllianceTeam).join('')}
      </div>
    </div>
  </div>`;
}
function filterSchedule(q) {
  const term = q.trim().replace(/^frc/i, '');
  let shown = 0;
  document.querySelectorAll('#sched-matches .match-card').forEach(card => {
    const visible = !term || card.dataset.teams.split(' ').some(n => n.startsWith(term));
    card.style.display = visible ? '' : 'none';
    if (visible) shown++;
  });
  document.getElementById('sched-shown').textContent = shown;
}
function showSchedule() {
  hideAll();
  saveNav({view: 'schedule'});
  closeSidebar();
  document.getElementById('schedule-btn').classList.add('active');
  const sched = DATA.schedule || [];
  const sv = document.getElementById('schedule-view');
  if (sched.length === 0) {
    sv.innerHTML = `<div class="page-header"><h2>Schedule</h2><p style="color:var(--muted)">No matches found.</p></div>`;
    sv.style.display = 'block';
    return;
  }
  const played = sched.filter(m => m.winner).length;
  const upcoming = sched.length - played;
  sv.innerHTML = `
    <div class="page-header">
      <h2>Schedule</h2>
      <p>${sched.length} match${sched.length !== 1 ? 'es' : ''} · ${played} played · ${upcoming} upcoming</p>
    </div>
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;">
      <input id="sched-filter" type="text" placeholder="Filter by team number…"
             style="background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:7px 11px;color:var(--text);font-size:.85rem;width:220px;outline:none;"
             oninput="filterSchedule(this.value)"
             onfocus="this.style.borderColor='var(--accent)'" onblur="this.style.borderColor='var(--border)'">
      <span style="font-size:.8rem;color:var(--muted);"><span id="sched-shown">${sched.length}</span> shown</span>
    </div>
    <div class="matches-grid" id="sched-matches">
      ${sched.map(scheduleMatchCard).join('')}
    </div>`;
  sv.style.display = 'block';
}

function towerBadge(val) {
  if (!val) return '<span class="tower-none">—</span>';
  return `<span class="tower-level">${val}</span>`;
}
function levelNum(val) {
  if (!val) return 0;
  const m = val.match(/\d+/);
  return m ? parseInt(m[0]) : 0;
}
function eventShort(event) {
  // e.g. "2026njwas" -> "njwas"
  return event ? event.replace(/^\d{4}/, '') : '';
}
function matchLabel(m) {
  if (m.comp_level === 'qm') return `Qual ${m.match_number}`;
  if (m.comp_level === 'sf') return `Semi ${m.match_number}`;
  if (m.comp_level === 'f')  return `Final ${m.match_number}`;
  return `Match ${m.match_number}`;
}
function pct(n) { return n !== null && n !== undefined ? Math.round(n*100)+'%' : '—'; }
function num(n) { return n !== null && n !== undefined ? n : '—'; }

// ── Team View ─────────────────────────────────────────────────────────────────
function loadTeam(key) {
  hideAll();
  const t = DATA.teams.find(t => t.key === key);
  if (!t) return;
  saveNav({view: 'team', key});
  closeSidebar();
  document.querySelector(`.team-item[data-key="${key}"]`)?.classList.add('active');

  const hasBreakdowns = t.match_history.some(m => m.auto_tower !== null || m.endgame_tower !== null);
  const hasHub = t.match_history.some(m => m.hub_total_pts !== null);
  const contribRanked = [...DATA.teams].filter(x => x.contrib_avg !== null)
                                        .sort((a,b) => b.contrib_avg - a.contrib_avg);
  const contribRank = contribRanked.findIndex(x => x.key === t.key) + 1;
  const contribTotal = contribRanked.length;
  const oprRanked = [...DATA.teams].filter(x => x.opr !== null).sort((a,b) => b.opr - a.opr);
  const oprRank = oprRanked.findIndex(x => x.key === t.key) + 1;
  const oprTotal = oprRanked.length;

  const tv = document.getElementById('team-view');
  tv.innerHTML = `
    ${t.played < 3 ? `<div class="data-warning"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>Only ${t.played} match${t.played !== 1 ? 'es' : ''} played — data may not be actionable</div>` : ''}
    <div class="page-header">
      <h2><span>#${t.num}</span>${t.nickname ? ' ' + t.nickname : ''}</h2>
      <p>${t.played} match${t.played!==1?'es':''} · ${t.events.join(', ')}</p>
      <div style="display:flex;gap:12px;margin-top:6px;flex-wrap:wrap;">
        <a class="ext-link" href="https://www.thebluealliance.com/team/${t.num}" target="_blank">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
          The Blue Alliance
        </a>
        <a class="ext-link" href="https://www.statbotics.io/team/${t.num}" target="_blank">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
          Statbotics
        </a>
      </div>
    </div>

    <div class="stat-row">
      <div class="stat-card"><div class="stat-label">Tower Usage Rate</div>
        <div class="stat-value">${pct(t.tower_rate)}</div>
        <div class="stat-sub">${t.tower_matches} of ${t.played} matches</div></div>
      <div class="stat-card"><div class="stat-label">Auto Tower</div>
        <div class="stat-value">${t.auto_tower_count}</div>
        <div class="stat-sub">matches with auto climb</div></div>
      <div class="stat-card"><div class="stat-label">Endgame Tower</div>
        <div class="stat-value">${t.endgame_tower_count}</div>
        <div class="stat-sub">matches with endgame climb</div></div>
      <div class="stat-card"><div class="stat-label">Pt Contribution Avg</div>
        <div class="stat-value">${t.contrib_avg !== null ? t.contrib_avg : '—'}</div>
        <div class="stat-sub">alliance score ÷ 3${contribRank ? ` · #${contribRank} of ${contribTotal}` : ''}</div></div>
      <div class="stat-card"><div class="stat-label">OPR</div>
        <div class="stat-value">${t.opr !== null ? t.opr : '—'}</div>
        <div class="stat-sub">overall${oprRank ? ` · #${oprRank} of ${oprTotal}` : ''}</div></div>
      <div class="stat-card"><div class="stat-label">Auto OPR</div>
        <div class="stat-value">${t.auto_opr !== null ? t.auto_opr : '—'}</div>
        <div class="stat-sub">hub auto pts</div></div>
      <div class="stat-card"><div class="stat-label">Teleop OPR</div>
        <div class="stat-value">${t.teleop_opr !== null ? t.teleop_opr : '—'}</div>
        <div class="stat-sub">hub teleop pts</div></div>
      <div class="stat-card"><div class="stat-label">Endgame OPR</div>
        <div class="stat-value">${t.endgame_opr !== null ? t.endgame_opr : '—'}</div>
        <div class="stat-sub">hub endgame pts</div></div>
    </div>

    ${hasBreakdowns ? `
    <p class="section-title">Tower Levels Per Match</p>
    <div class="charts-grid single">
      <div class="chart-card"><h3>Tower Level Achieved (Auto &amp; Endgame)</h3>
        <div class="chart-wrap medium"><canvas id="tc-tower"></canvas></div></div>
    </div>` : ''}

    ${hasHub ? `
    <p class="section-title">Hub Scores Per Match</p>
    <div class="charts-grid single">
      <div class="chart-card"><h3>Hub Points Breakdown</h3>
        <div class="chart-wrap medium"><canvas id="tc-hub"></canvas></div></div>
    </div>` : ''}

    <p class="section-title">Match History</p>
    <div class="matches-grid">
      ${t.match_history.map(m => {
        const lbl = matchLabel(m);
        const resultCls  = m.won === true ? 'result-win' : m.won === false ? 'result-loss' : 'result-tbd';
        const resultText = m.won === true ? 'WIN' : m.won === false ? 'LOSS' : 'TBD';
        const videoLink  = m.video_url ? `<a class="video-link" href="${m.video_url}" target="_blank">▶ Video</a>` : '';
        return `<div class="match-card">
          <div class="match-card-header">
            <span class="match-label">${lbl}</span>
            <span class="match-color ${m.color}">${m.color.toUpperCase()}</span>
            <span class="${resultCls}">${resultText}</span>
            <span class="event-tag">${eventShort(m.event)}</span>
            <span class="match-score">${m.score ?? '—'} pts</span>
            ${videoLink}
            <button class="compare-match-btn" onclick="compareMatch('${m.match_key}')">Compare</button>
          </div>
          <div class="match-fields">
            <div class="field"><div class="field-label">Auto Tower</div>
              <div class="field-value">${towerBadge(m.auto_tower)}</div></div>
            <div class="field"><div class="field-label">Endgame Tower</div>
              <div class="field-value">${towerBadge(m.endgame_tower)}</div></div>
            <div class="field"><div class="field-label">Hub Auto Pts</div>
              <div class="field-value val-num">${num(m.hub_auto_pts)}</div></div>
            <div class="field"><div class="field-label">Hub Teleop Pts</div>
              <div class="field-value val-num">${num(m.hub_teleop_pts)}</div></div>
            <div class="field"><div class="field-label">Hub Endgame Pts</div>
              <div class="field-value val-num">${num(m.hub_endgame_pts)}</div></div>
            <div class="field"><div class="field-label">Tower Pts</div>
              <div class="field-value val-num">${num(m.total_tower_pts)}</div></div>
            <div class="field"><div class="field-label">Energized</div>
              <div class="field-value ${m.energized===null?'val-null':m.energized?'val-yes':'val-no'}">${m.energized===null?'—':m.energized?'Yes':'No'}</div></div>
            <div class="field"><div class="field-label">RP</div>
              <div class="field-value val-num">${num(m.rp)}</div></div>
          </div>
        </div>`;
      }).join('')}
    </div>`;
  tv.style.display = 'block';

  // Tower level chart
  if (hasBreakdowns) {
    const labels = t.match_history.map(m => [eventShort(m.event), matchLabel(m)]);
    makeChart('tc-tower', { type:'bar', data:{ labels, datasets:[
      { label:'Auto Tower Level', data: t.match_history.map(m => levelNum(m.auto_tower)),
        backgroundColor: P.blue+'cc', borderColor: P.blue, borderWidth:1 },
      { label:'Endgame Tower Level', data: t.match_history.map(m => levelNum(m.endgame_tower)),
        backgroundColor: P.teal+'cc', borderColor: P.teal, borderWidth:1 },
    ]}, options: baseOpts({ scales:{ x:{grid:{color:'#2e334d'},ticks:{color:'#7b82a0'}},
      y:{grid:{color:'#2e334d'},ticks:{color:'#7b82a0'},min:0,max:4,stepSize:1,
         callback: v => v===0?'None':`L${v}`} }})});
  }

  // Hub score chart
  if (hasHub) {
    const labels = t.match_history.map(m => [eventShort(m.event), matchLabel(m)]);
    makeChart('tc-hub', { type:'bar', data:{ labels, datasets:[
      { label:'Auto',    data: t.match_history.map(m => m.hub_auto_pts   ?? 0), backgroundColor: P.blue  +'cc', borderColor: P.blue,   borderWidth:1 },
      { label:'Teleop',  data: t.match_history.map(m => m.hub_teleop_pts ?? 0), backgroundColor: P.orange+'cc', borderColor: P.orange, borderWidth:1 },
      { label:'Endgame', data: t.match_history.map(m => m.hub_endgame_pts?? 0), backgroundColor: P.purple+'cc', borderColor: P.purple, borderWidth:1 },
    ]}, options: baseOpts({
      scales:{ x:{grid:{color:'#2e334d'},ticks:{color:'#7b82a0'}},
               y:{grid:{color:'#2e334d'},ticks:{color:'#7b82a0'},stacked:false} }
    })});
  }
}

// ── Bracket helper ────────────────────────────────────────────────────────────
function bracketMatch(m) {
  const redWin  = m.winner === 'red';
  const blueWin = m.winner === 'blue';
  const decided = m.winner != null && m.winner !== '';
  return `<div class="bracket-match">
    <div class="bracket-match-label">${m.label}</div>
    <div class="bracket-alliance ${redWin?'winner':decided?'loser':''}">
      <span class="bracket-dot red"></span>
      <span class="bracket-teams">${m.red.join(' · ')}</span>
      <span class="bracket-score">${m.red_score ?? '—'}</span>
    </div>
    <div class="bracket-alliance ${blueWin?'winner':decided?'loser':''}">
      <span class="bracket-dot blue"></span>
      <span class="bracket-teams">${m.blue.join(' · ')}</span>
      <span class="bracket-score">${m.blue_score ?? '—'}</span>
    </div>
  </div>`;
}

// ── Overview ──────────────────────────────────────────────────────────────────
function showOverview() {
  hideAll();
  saveNav({view: 'overview'});
  closeSidebar();
  document.getElementById('overview-btn').classList.add('active');
  const ov = DATA.overview;
  const towerTeams = [...DATA.teams].filter(t => t.tower_matches > 0)
                                    .sort((a,b) => b.tower_rate - a.tower_rate);
  const allTeams = DATA.teams;

  // top-scoring alliances
  const topScores = ov.top_scores.slice(0,10);

  // event match counts
  const events     = Object.keys(ov.event_matches).sort();
  const eventCounts = events.map(e => ov.event_matches[e]);

  const div = document.getElementById('overview-view');
  div.innerHTML = `
    <div class="page-header">
      <h2>Overview</h2>
      <p>All ${ov.total_teams} teams · ${ov.total_matches} matches across ${events.length} events</p>
    </div>

    <div class="stat-row">
      <div class="stat-card"><div class="stat-label">Total Matches</div>
        <div class="stat-value">${ov.total_matches}</div></div>
      <div class="stat-card"><div class="stat-label">Teams</div>
        <div class="stat-value">${ov.total_teams}</div></div>
      <div class="stat-card"><div class="stat-label">Tower Users</div>
        <div class="stat-value">${towerTeams.length}</div>
        <div class="stat-sub">of ${ov.total_teams} total</div></div>
      <div class="stat-card"><div class="stat-label">Energized Rate</div>
        <div class="stat-value">${pct(ov.energized_rate)}</div>
        <div class="stat-sub">of scored alliances</div></div>
      <div class="stat-card"><div class="stat-label">Supercharged Rate</div>
        <div class="stat-value">${pct(ov.supercharged_rate)}</div></div>
    </div>

    ${ov.bracket ? `
    <p class="section-title">Elimination Bracket</p>
    <div class="bracket-wrap">
      <div class="bracket">
        ${ov.bracket.rounds.map(r => `
          <div class="bracket-round">
            <div class="bracket-round-header">
              <div class="bracket-round-name">${r.name}</div>
              <div class="bracket-round-sub">${r.sub}</div>
            </div>
            ${r.matches.map(m => bracketMatch(m)).join('')}
          </div>`).join('')}
        ${ov.bracket.finals.length > 0 ? `
          <div class="bracket-round">
            <div class="bracket-round-header">
              <div class="bracket-round-name">Finals</div>
              <div class="bracket-round-sub">Championship</div>
            </div>
            ${ov.bracket.finals.map(m => bracketMatch(m)).join('')}
          </div>` : ''}
      </div>
    </div>` : ''}

    <p class="section-title">Tower Usage Leaderboard</p>
    <div class="leaderboard">
      ${towerTeams.map((t, i) => `
        <div class="lb-row">
          <span class="lb-rank">${i+1}</span>
          <span class="lb-team">#${t.num}</span>
          <div class="lb-bar-wrap"><div class="lb-bar" style="width:${Math.round(t.tower_rate*100)}%"></div></div>
          <span class="lb-pct">${pct(t.tower_rate)}</span>
          <span class="lb-counts">${t.tower_matches}/${t.played} · A:${t.auto_tower_count} E:${t.endgame_tower_count}</span>
        </div>`).join('')}
    </div>

    <p class="section-title">Matches Per Event</p>
    <div class="charts-grid single">
      <div class="chart-card"><h3>Match Count by Event</h3>
        <div class="chart-wrap medium"><canvas id="ov-events"></canvas></div></div>
    </div>

    <p class="section-title">Top Alliance Scores</p>
    <div class="charts-grid single">
      <div class="chart-card"><h3>Highest Scoring Alliances</h3>
        <div class="chart-wrap medium"><canvas id="ov-scores"></canvas></div></div>
    </div>

    <p class="section-title">OPR — All Teams</p>
    <div class="charts-grid single">
      <div class="chart-card"><h3>OPR (Offensive Power Rating)</h3>
        <div class="chart-wrap tall"><canvas id="ov-opr"></canvas></div></div>
    </div>

    <div class="charts-grid triple">
      <div class="chart-card"><h3>Auto OPR</h3>
        <div class="chart-wrap medium"><canvas id="ov-auto-opr"></canvas></div></div>
      <div class="chart-card"><h3>Teleop OPR</h3>
        <div class="chart-wrap medium"><canvas id="ov-teleop-opr"></canvas></div></div>
      <div class="chart-card"><h3>Endgame OPR</h3>
        <div class="chart-wrap medium"><canvas id="ov-endgame-opr"></canvas></div></div>
    </div>

    <p class="section-title">Point Contribution Average — All Teams</p>
    <div class="charts-grid single">
      <div class="chart-card"><h3>Avg Pt Contribution per Match (alliance score ÷ 3)</h3>
        <div class="chart-wrap tall"><canvas id="ov-contrib"></canvas></div></div>
    </div>

    <p class="section-title">Tower Usage Rate — All Teams</p>
    <div class="charts-grid single">
      <div class="chart-card"><h3>Tower Usage % by Team (all matches)</h3>
        <div class="chart-wrap tall"><canvas id="ov-tower"></canvas></div></div>
    </div>`;

  div.style.display = 'block';

  // Events chart
  makeChart('ov-events', { type:'bar', data:{ labels:events, datasets:[{
    label:'Matches', data: eventCounts,
    backgroundColor: P.blue+'cc', borderColor: P.blue, borderWidth:1,
  }]}, options: baseOpts()});

  // Top scores
  makeChart('ov-scores', { type:'bar', data:{
    labels: topScores.map(s => s.match_key.replace(/^2026[a-z]+_/,'')+' '+s.color),
    datasets:[{ label:'Alliance Score', data: topScores.map(s=>s.score),
      backgroundColor: topScores.map(s => s.color==='red' ? P.red+'cc' : P.blue+'cc'),
      borderColor:     topScores.map(s => s.color==='red' ? P.red      : P.blue),
      borderWidth:1 }]},
    options: baseOpts()});

  // OPR charts
  const oprScaleOpts = { scales:{
    x:{grid:{color:'#2e334d'},ticks:{color:'#7b82a0',maxRotation:90,font:{size:9}}},
    y:{grid:{color:'#2e334d'},ticks:{color:'#7b82a0'}} }};
  function makeOprChart(canvasId, field, color) {
    const sorted = [...allTeams].filter(t => t[field] !== null).sort((a,b) => b[field] - a[field]);
    makeChart(canvasId, { type:'bar', data:{
      labels: sorted.map(t => '#'+t.num),
      datasets:[{ label: field.replace('_',' ').replace('opr','OPR'),
        data: sorted.map(t => t[field]),
        backgroundColor: color+'cc', borderColor: color, borderWidth:1 }]},
      options: baseOpts(oprScaleOpts)});
  }
  makeOprChart('ov-opr',         'opr',         P.accent);
  makeOprChart('ov-auto-opr',    'auto_opr',     P.blue);
  makeOprChart('ov-teleop-opr',  'teleop_opr',   P.orange);
  makeOprChart('ov-endgame-opr', 'endgame_opr',  P.purple);

  // Point contribution avg all teams
  const contribSorted = [...allTeams].filter(t => t.contrib_avg !== null)
                                      .sort((a,b) => b.contrib_avg - a.contrib_avg);
  makeChart('ov-contrib', { type:'bar', data:{
    labels: contribSorted.map(t => '#'+t.num),
    datasets:[{ label:'Pt Contribution Avg',
      data: contribSorted.map(t => t.contrib_avg),
      backgroundColor: P.orange+'cc', borderColor: P.orange, borderWidth:1 }]},
    options: baseOpts({ scales:{
      x:{grid:{color:'#2e334d'},ticks:{color:'#7b82a0',maxRotation:90,font:{size:9}}},
      y:{grid:{color:'#2e334d'},ticks:{color:'#7b82a0'}} }})});

  // Tower usage all teams (horizontal bar)
  const towerSorted = [...allTeams].sort((a,b) => b.tower_rate - a.tower_rate);
  makeChart('ov-tower', { type:'bar', data:{
    labels: towerSorted.map(t => '#'+t.num),
    datasets:[{ label:'Tower Usage %',
      data: towerSorted.map(t => Math.round(t.tower_rate*100)),
      backgroundColor: towerSorted.map(t => t.tower_rate > 0 ? P.teal+'cc' : P.muted+'33'),
      borderColor:     towerSorted.map(t => t.tower_rate > 0 ? P.teal      : '#2e334d'),
      borderWidth:1 }]},
    options: baseOpts({ scales:{
      x:{grid:{color:'#2e334d'},ticks:{color:'#7b82a0',maxRotation:90,font:{size:9}}},
      y:{grid:{color:'#2e334d'},ticks:{color:'#7b82a0'},min:0,max:100} }})});
}

// ── Sidebar ───────────────────────────────────────────────────────────────────
function buildSidebar(teams) {
  document.getElementById('team-list').innerHTML = teams.map(t => {
    const badgeCls = t.tower_rate > 0 ? 'team-badge badge-tower' : 'team-badge';
    const checked  = compareSet.has(t.key) ? 'checked' : '';
    const disabled = !compareSet.has(t.key) && compareSet.size >= 6 ? 'disabled' : '';
    return `<div class="team-item" data-key="${t.key}">
      <input type="checkbox" class="compare-check" data-key="${t.key}" ${checked} ${disabled}
             onclick="event.stopPropagation(); toggleCompare('${t.key}', this.checked)">
      <div style="flex:1;min-width:0;cursor:pointer;" onclick="loadTeam('${t.key}')">
        <div class="team-num">#${t.num}${t.nickname ? ' <span style="font-weight:400;color:var(--muted);font-size:.8rem;">' + t.nickname + '</span>' : ''}</div>
        <div class="team-sub">${t.played}m · tower ${pct(t.tower_rate)}</div>
      </div>
      <span class="${badgeCls}">${t.tower_matches > 0 ? '🗼 '+t.tower_matches : t.played+'m'}</span>
      <button class="hide-btn" title="Hide" onclick="hideTeam(event,'${t.key}')">×</button>
    </div>`;
  }).join('');
}

document.getElementById('search').addEventListener('input', rebuildSidebar);
document.getElementById('search').addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  const first = document.querySelector('.team-item[data-key]');
  if (first) { loadTeam(first.dataset.key); document.getElementById('search').blur(); }
});
document.getElementById('sort-by').addEventListener('change', rebuildSidebar);

// ── State persistence ─────────────────────────────────────────────────────────
function saveNav(state) { localStorage.setItem('tba_nav', JSON.stringify(state)); }

function restoreNav() {
  let state;
  try { state = JSON.parse(localStorage.getItem('tba_nav')); } catch { return; }
  if (!state) return;
  if (state.view === 'overview') {
    showOverview();
  } else if (state.view === 'team' && state.key) {
    const t = DATA.teams.find(t => t.key === state.key);
    if (t) loadTeam(state.key);
  } else if (state.view === 'compare' && state.keys?.length >= 2) {
    state.keys.forEach(k => { if (DATA.teams.find(t => t.key === k)) compareSet.add(k); });
    updateCompareBar(); updateCheckboxStates();
    showComparison();
  } else if (state.view === 'schedule') {
    showSchedule();
  }
}

// ── Mobile sidebar ────────────────────────────────────────────────────────────
function toggleSidebar() {
  document.querySelector('aside').classList.toggle('open');
  document.querySelector('.sidebar-overlay').classList.toggle('open');
}
function closeSidebar() {
  document.querySelector('aside').classList.remove('open');
  document.querySelector('.sidebar-overlay').classList.remove('open');
}

// Boot
document.getElementById('team-count').textContent = `${DATA.teams.length} teams`;
const _schedUpcoming = (DATA.schedule || []).filter(m => !m.winner).length;
if (_schedUpcoming > 0) document.getElementById('schedule-count').textContent = _schedUpcoming;
rebuildSidebar();
restoreNav() || showOverview();
</script>
<div class="sidebar-overlay" onclick="closeSidebar()"></div>
</body>
</html>
"""


def build_html(data: dict, title: str, timestamp: str) -> str:
    embedded = json.dumps(data, separators=(",", ":"))
    return (HTML_TEMPLATE
            .replace("__DATA__", embedded)
            .replace("__TITLE__", title)
            .replace("__TIMESTAMP__", timestamp))


def write_view(event_prefix: str | None, out_path: str, title: str, timestamp: str) -> None:
    data = load_data(DB_PATH, event_prefix)
    print(f"  {data['overview']['total_teams']} teams, {data['overview']['total_matches']} matches  →  {out_path}")
    html = build_html(data, title, timestamp)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)


INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>TBA 2026 — Dashboard Index</title>
  <style>
    :root{{--bg:#0f1117;--surface:#1a1d27;--surface2:#22263a;--border:#2e334d;
          --accent:#4f8ef7;--text:#e4e6f0;--muted:#7b82a0;}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    body{{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);
          min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:48px 16px;}}
    h1{{font-size:1.5rem;font-weight:700;color:var(--accent);margin-bottom:6px;}}
    .ts{{color:var(--muted);font-size:.8rem;margin-bottom:36px;}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px;width:100%;max-width:800px;}}
    a.card{{display:block;background:var(--surface);border:1px solid var(--border);border-radius:10px;
            padding:20px 22px;text-decoration:none;color:var(--text);transition:border-color .15s,background .15s;}}
    a.card:hover{{border-color:var(--accent);background:var(--surface2);}}
    .card-title{{font-weight:700;font-size:1rem;color:var(--accent);margin-bottom:4px;}}
    .card-sub{{font-size:.78rem;color:var(--muted);}}
  </style>
</head>
<body>
  <h1>TBA 2026 Dashboard</h1>
  <div class="ts">Generated {timestamp}</div>
  <div class="grid">
{cards}
  </div>
</body>
</html>
"""


def build_index(pages: list[tuple[str, str, str]], timestamp: str) -> str:
    """pages: list of (filename, title, subtitle)"""
    cards = "\n".join(
        f'    <a class="card" href="{fname}">'
        f'<div class="card-title">{title}</div>'
        f'<div class="card-sub">{sub}</div></a>'
        for fname, title, sub in pages
    )
    return INDEX_TEMPLATE.format(timestamp=timestamp, cards=cards)


def main():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"Loading data from {DB_PATH}...")

    # discover all event prefixes (first 8 chars of match_key)
    con = sqlite3.connect(DB_PATH)
    event_prefixes = [r[0] for r in con.execute(
        "SELECT DISTINCT substr(match_key,1,8) FROM score_breakdowns ORDER BY 1"
    ).fetchall()]
    con.close()

    pages = []

    write_view(None, "Region Wide.html", "TBA 2026 — Region Wide", timestamp)
    data_rw = load_data(DB_PATH)
    pages.append(("Region Wide.html", "Region Wide",
                  f"{data_rw['overview']['total_teams']} teams · {data_rw['overview']['total_matches']} matches"))

    for ep in event_prefixes:
        fname = f"{ep}.html"
        display = EVENT_NAMES.get(ep, ep)
        title = f"TBA 2026 — {display}"
        write_view(ep, fname, title, timestamp)
        d = load_data(DB_PATH, ep)
        pages.append((fname, display,
                      f"{d['overview']['total_teams']} teams · {d['overview']['total_matches']} matches"))

    index_html = build_index(pages, timestamp)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(index_html)
    print(f"  index.html  →  {len(pages)} pages listed")

    print(f"Done. Generated {2 + len(event_prefixes)} file(s).")


if __name__ == "__main__":
    main()
