"""
Half-PPR scoring engine (Yahoo standard).
Converts raw NFL stats into fantasy points.
"""

import pandas as pd
import numpy as np

# ── Yahoo standard half-PPR scoring ─────────────────────────────────────────
SCORING = {
    # Passing
    "pass_yards":        0.04,   # 1 pt per 25 yds
    "pass_td":           4.0,
    "pass_int":         -1.0,
    "pass_2pt":          2.0,
    # Rushing
    "rush_yards":        0.1,    # 1 pt per 10 yds
    "rush_td":           6.0,
    "rush_2pt":          2.0,
    # Receiving
    "rec_yards":         0.1,
    "rec_td":            6.0,
    "rec_2pt":           2.0,
    "reception":         0.5,    # half-PPR
    # Misc
    "fumble_lost":      -2.0,
    "ret_td":            6.0,
    # Kicker
    "fg_0_19":           3.0,
    "fg_20_29":          3.0,
    "fg_30_39":          3.0,
    "fg_40_49":          4.0,
    "fg_50_plus":        5.0,
    "pat":               1.0,
    "pat_missed":       -1.0,
    # DST — points allowed
    "dst_td":            6.0,
    "dst_sack":          1.0,
    "dst_int":           2.0,
    "dst_fumble_rec":    2.0,
    "dst_safety":        2.0,
    "dst_blk_kick":      2.0,
}

DST_PTS_ALLOWED = {
    # (min, max): fantasy_pts
    (0, 0):   10,
    (1, 6):    7,
    (7, 13):   4,
    (14, 17):  1,
    (18, 21):  0,
    (22, 27): -1,
    (28, 34): -4,
    (35, 45): -7,
    (46, 999):-10,
}


def dst_pts_from_allowed(pts_allowed: int) -> float:
    for (lo, hi), val in DST_PTS_ALLOWED.items():
        if lo <= pts_allowed <= hi:
            return float(val)
    return -10.0


def calc_player_points(row: pd.Series) -> float:
    """
    Calculate half-PPR fantasy points for a player week row.
    Expects columns from nfl_data_py weekly stats.
    """
    pts = 0.0

    # Passing
    pts += row.get("passing_yards", 0) * SCORING["pass_yards"]
    pts += row.get("passing_tds", 0)   * SCORING["pass_td"]
    pts += row.get("interceptions", 0) * SCORING["pass_int"]
    pts += row.get("passing_2pt_conversions", 0) * SCORING["pass_2pt"]

    # Rushing
    pts += row.get("rushing_yards", 0) * SCORING["rush_yards"]
    pts += row.get("rushing_tds", 0)   * SCORING["rush_td"]
    pts += row.get("rushing_2pt_conversions", 0) * SCORING["rush_2pt"]

    # Receiving
    pts += row.get("receiving_yards", 0) * SCORING["rec_yards"]
    pts += row.get("receiving_tds", 0)   * SCORING["rec_td"]
    pts += row.get("receiving_2pt_conversions", 0) * SCORING["rec_2pt"]
    pts += row.get("receptions", 0)      * SCORING["reception"]

    # Misc
    pts += row.get("sack_fumbles_lost", 0)    * SCORING["fumble_lost"]
    pts += row.get("rushing_fumbles_lost", 0) * SCORING["fumble_lost"]

    return round(pts, 2)


def calc_consistency_metrics(weekly_pts: pd.Series) -> dict:
    """
    Given a Series of weekly fantasy point totals for a player, return:
        mean, std, cv, floor (25th pct), ceiling (75th pct),
        consistency_score (0-100, higher = more consistent)
    """
    pts = weekly_pts.dropna()
    pts = pts[pts > 0]   # only games they played

    if len(pts) < 4:
        return {
            "mean_pts":          np.nan,
            "std_pts":           np.nan,
            "cv":                np.nan,
            "floor_pts":         np.nan,
            "ceiling_pts":       np.nan,
            "consistency_score": np.nan,
            "games_played":      len(pts),
        }

    mean = pts.mean()
    std  = pts.std()
    cv   = std / mean if mean > 0 else np.nan

    # Consistency score: inverse-CV mapped to 0-100
    # CV of 0 → 100, CV of 1+ → ~0
    consistency_score = max(0, min(100, round((1 - cv) * 100, 1))) if not np.isnan(cv) else np.nan

    return {
        "mean_pts":          round(mean, 2),
        "std_pts":           round(std, 2),
        "cv":                round(cv, 3),
        "floor_pts":         round(float(np.percentile(pts, 25)), 2),
        "ceiling_pts":       round(float(np.percentile(pts, 75)), 2),
        "consistency_score": consistency_score,
        "games_played":      len(pts),
    }
