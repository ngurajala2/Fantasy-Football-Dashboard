"""
Historical weekly fantasy stats using nfl_data_py.
Computes consistency metrics (std, CV, floor, ceiling) per player
over the last N seasons.
"""

import re
import warnings
import numpy as np
import pandas as pd
from pathlib import Path

warnings.filterwarnings("ignore")

CACHE_DIR = Path(__file__).parent / "cache"

# Use the five most recent completed seasons. The 2025 season is especially
# important now because it is the freshest full-season signal.
SEASONS = list(range(2021, 2026))   # 2021-2025
CACHE_FILE = CACHE_DIR / f"historical_consistency_{SEASONS[0]}_{SEASONS[-1]}_last2_weighted.parquet"
LEGACY_CACHE_FILE = CACHE_DIR / "historical_consistency.parquet"
PLAYER_STATS_WEEK_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.parquet"
SEASON_WEIGHTS = {
    2025: 1.00,
    2024: 0.90,
    2023: 0.20,
    2022: 0.10,
    2021: 0.05,
}
WEEKLY_COLUMNS = [
    "player_id", "player_name", "position", "season", "week", "season_type",
    "passing_yards", "passing_tds", "passing_interceptions",
    "rushing_yards", "rushing_tds",
    "receiving_yards", "receiving_tds", "receptions",
    "sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost",
]


def _calc_half_ppr(df: pd.DataFrame) -> pd.Series:
    """
    Calculate half-PPR fantasy points from nfl_data_py weekly columns.
    """
    pts = pd.Series(0.0, index=df.index)

    # Passing
    pts += df.get("passing_yards",            pd.Series(0, index=df.index)).fillna(0) * 0.04
    pts += df.get("passing_tds",              pd.Series(0, index=df.index)).fillna(0) * 4
    pts += df.get("interceptions",            pd.Series(0, index=df.index)).fillna(0) * -1

    # Rushing
    pts += df.get("rushing_yards",            pd.Series(0, index=df.index)).fillna(0) * 0.1
    pts += df.get("rushing_tds",              pd.Series(0, index=df.index)).fillna(0) * 6

    # Receiving (half-PPR)
    pts += df.get("receiving_yards",          pd.Series(0, index=df.index)).fillna(0) * 0.1
    pts += df.get("receiving_tds",            pd.Series(0, index=df.index)).fillna(0) * 6
    pts += df.get("receptions",               pd.Series(0, index=df.index)).fillna(0) * 0.5

    # Fumbles
    pts += df.get("sack_fumbles_lost",        pd.Series(0, index=df.index)).fillna(0) * -2
    pts += df.get("rushing_fumbles_lost",     pd.Series(0, index=df.index)).fillna(0) * -2
    pts += df.get("receiving_fumbles_lost",   pd.Series(0, index=df.index)).fillna(0) * -2

    return pts.round(2)


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    weights = weights.reindex(values.index).fillna(1.0)
    return float(np.average(values, weights=weights))


def _weighted_std(values: pd.Series, weights: pd.Series, mean: float) -> float:
    weights = weights.reindex(values.index).fillna(1.0)
    variance = np.average((values - mean) ** 2, weights=weights)
    return float(np.sqrt(variance))


def _weighted_percentile(values: pd.Series, weights: pd.Series, percentile: float) -> float:
    weights = weights.reindex(values.index).fillna(1.0)
    order = np.argsort(values.to_numpy())
    sorted_values = values.to_numpy()[order]
    sorted_weights = weights.to_numpy()[order]
    cumulative = np.cumsum(sorted_weights)
    cutoff = percentile / 100 * sorted_weights.sum()
    return float(sorted_values[np.searchsorted(cumulative, cutoff, side="left")])


def fetch_historical_consistency() -> pd.DataFrame:
    """
    Returns a DataFrame indexed by player_id (gsis_id) with consistency metrics.
    Caches to disk to avoid re-fetching on every load.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if CACHE_FILE.exists():
        try:
            return pd.read_parquet(CACHE_FILE)
        except Exception:
            pass

    try:
        import nfl_data_py as nfl
    except ImportError:
        print("[Historical] nfl_data_py not installed. Run: pip install nfl-data-py")
        return pd.DataFrame()

    print(f"Loading weekly stats for seasons {SEASONS[0]}–{SEASONS[-1]}…")
    weekly_frames = []
    missing_seasons = []
    for season in SEASONS:
        try:
            weekly_frames.append(nfl.import_weekly_data([season]))
        except Exception as e:
            print(f"[Historical] Skipping {season}: {e}")
            missing_seasons.append(season)

    if missing_seasons:
        for season in missing_seasons:
            try:
                weekly = pd.read_parquet(
                    PLAYER_STATS_WEEK_URL.format(season=season),
                    columns=WEEKLY_COLUMNS,
                )
                weekly = weekly.rename(columns={"passing_interceptions": "interceptions"})
                print(f"[Historical] Loaded {season} from current stats_player release.")
                weekly_frames.append(weekly)
            except Exception as e:
                print(f"[Historical] stats_player fallback failed for {season}: {e}")

    if not weekly_frames:
        if LEGACY_CACHE_FILE.exists():
            try:
                print("[Historical] Falling back to legacy cached consistency data.")
                return pd.read_parquet(LEGACY_CACHE_FILE)
            except Exception:
                pass
        return pd.DataFrame()

    weekly = pd.concat(weekly_frames, ignore_index=True)

    # Filter to skill positions
    weekly = weekly[weekly["position"].isin(["QB", "RB", "WR", "TE"])]

    # Keep only regular season (week 1-17/18)
    if "week" in weekly.columns:
        weekly = weekly[weekly["week"] <= 18]
    if "season_type" in weekly.columns:
        weekly = weekly[weekly["season_type"] == "REG"]

    # Calculate half-PPR points per week
    weekly["half_ppr_pts"] = _calc_half_ppr(weekly)

    # Group by player
    grouped = weekly.groupby(["player_id", "player_name", "position"])

    metrics_rows = []
    for (pid, name, pos), grp in grouped:
        pts_series = grp["half_ppr_pts"]
        played     = pts_series[pts_series > 0]   # non-zero = played

        games_played = len(played)
        if games_played < 6:
            continue   # not enough data

        season_weights = grp.loc[played.index, "season"].map(SEASON_WEIGHTS).fillna(1.0)
        mean_pts  = _weighted_mean(played, season_weights)
        std_pts   = _weighted_std(played, season_weights, mean_pts)
        cv        = std_pts / mean_pts if mean_pts > 0 else np.nan
        floor_25  = _weighted_percentile(played, season_weights, 25)
        ceiling_75= _weighted_percentile(played, season_weights, 75)

        # Consistency score: 0-100, higher = more consistent
        # Use inverse CV, capped so QBs with very low CV don't dominate
        consistency_score = max(0, min(100, round((1 - cv) * 100, 1))) if not np.isnan(cv) else 50.0

        # Bust rate: % of games below 10 pts (position-specific thresholds)
        bust_thresholds = {"QB": 15, "RB": 8, "WR": 8, "TE": 5}
        threshold = bust_thresholds.get(pos, 8)
        bust_rate = round(_weighted_mean((played < threshold).astype(float), season_weights) * 100, 1)

        # Boom rate: % of games above elite threshold
        elite_thresholds = {"QB": 25, "RB": 20, "WR": 20, "TE": 15}
        elite_threshold  = elite_thresholds.get(pos, 20)
        boom_rate = round(_weighted_mean((played >= elite_threshold).astype(float), season_weights) * 100, 1)

        metrics_rows.append({
            "player_id":          pid,
            "player_name":        name,
            "position":           pos,
            "seasons_of_data":    grp["season"].nunique() if "season" in grp.columns else 1,
            "games_played":       games_played,
            "mean_pts_hist":      round(mean_pts, 2),
            "std_pts_hist":       round(std_pts, 2),
            "cv_hist":            round(cv, 3) if not np.isnan(cv) else None,
            "floor_pts_hist":     round(floor_25, 2),
            "ceiling_pts_hist":   round(ceiling_75, 2),
            "consistency_score":  consistency_score,
            "bust_rate_pct":      bust_rate,
            "boom_rate_pct":      boom_rate,
        })

    result = pd.DataFrame(metrics_rows)
    result = result.sort_values("mean_pts_hist", ascending=False).reset_index(drop=True)

    # Add a name_key for matching against full-name sources.
    # nfl_data_py stores names as "F.LastName" — we produce "f_lastname"
    # AND try to expand to "firstname_lastname" via nfl_data_py roster data.
    result["name_key"] = result["player_name"].apply(_abbrev_to_key)

    # Also store last name only as secondary key
    result["last_name_key"] = result["player_name"].apply(_last_name_key)

    result.to_parquet(CACHE_FILE, index=False)
    print(f"[Historical] Computed consistency for {len(result)} players.")
    return result


def _abbrev_to_key(name: str) -> str:
    """
    Convert 'C.McCaffrey' → 'c_mccaffrey' for matching.
    Handles: 'C.McCaffrey', 'Christian McCaffrey', "Ja'Marr Chase", 'Amon-Ra St. Brown'
    """
    name = str(name).lower().strip()
    # Remove suffixes
    name = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", name)
    # Remove punctuation except spaces and dots
    name = re.sub(r"['\-]", "", name)
    # Abbreviated format: "c.mccaffrey" → keep first initial + last name
    if re.match(r"^[a-z]\.", name):
        initial, rest = name.split(".", 1)
        parts = re.sub(r"[^a-z ]", " ", rest).split()
        if len(parts) >= 2 and parts[0] == "st":
            last = "st" + parts[-1]
        else:
            last = parts[-1] if parts else ""
        return f"{initial}_{last}"
    # Full name: "christian mccaffrey" → "c_mccaffrey"
    parts = re.sub(r"[^a-z ]", " ", name).split()
    if len(parts) >= 2:
        if len(parts) >= 3 and parts[-2] == "st":
            return f"{parts[0][0]}_st{parts[-1]}"
        return f"{parts[0][0]}_{parts[-1]}"
    return re.sub(r"[^a-z]", "", name)


def _last_name_key(name: str) -> str:
    """Extract normalized last name for secondary matching."""
    name = str(name).lower().strip()
    name = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", name)
    name = re.sub(r"['\-]", "", name)
    if re.match(r"^[a-z]\.", name):
        _, rest = name.split(".", 1)
        parts = re.sub(r"[^a-z ]", " ", rest).split()
        if len(parts) >= 2 and parts[0] == "st":
            return "st" + parts[-1]
        return parts[-1] if parts else ""
    parts = re.sub(r"[^a-z ]", " ", name).split()
    if len(parts) >= 2 and parts[-2] == "st":
        return "st" + parts[-1]
    return parts[-1] if parts else ""


def get_player_weekly_history(player_id: str, seasons: list[int] = None) -> pd.DataFrame:
    """
    Return week-by-week half-PPR points for a specific player.
    Used for the player detail chart in the dashboard.
    """
    if seasons is None:
        seasons = SEASONS

    try:
        import nfl_data_py as nfl
        weekly = nfl.import_weekly_data(seasons)
        player_data = weekly[weekly["player_id"] == player_id].copy()
        if player_data.empty:
            return pd.DataFrame()
        player_data["half_ppr_pts"] = _calc_half_ppr(player_data)
        cols = [c for c in ["season", "week", "opponent_team", "half_ppr_pts"] if c in player_data.columns]
        return player_data[cols].sort_values(["season", "week"] if "season" in player_data.columns else ["week"])
    except Exception as e:
        print(f"[get_player_weekly_history] {e}")
        return pd.DataFrame()
