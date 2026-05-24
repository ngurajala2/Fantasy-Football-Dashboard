"""
Draft state management — persisted to JSON so it survives page reloads.
Tracks: my team, drafted-by-others, watchlist, notes.
"""

import json
import streamlit as st
from pathlib import Path

STATE_FILE = Path(__file__).parent.parent / "data" / "cache" / "draft_state.json"

LINEUP_SLOTS = {
    "QB":  1,
    "RB":  2,
    "WR":  2,
    "TE":  1,
    "FLEX": 1,   # RB/WR/TE
    "DEF": 1,
    "K":   1,
}

BENCH_SLOTS = 7   # adjust if your league differs
TOTAL_ROSTER = sum(LINEUP_SLOTS.values()) + BENCH_SLOTS   # 15

FLEX_ELIGIBLE = {"RB", "WR", "TE"}


def _default_state() -> dict:
    return {
        "my_team":   [],       # list of player_ids
        "drafted":   [],       # picked by others
        "watchlist": [],       # flagged for later
        "notes":     {},       # player_id -> str
        "my_pick_num": None,   # 1-14 snake draft position
        "current_pick": 1,     # overall pick counter
        "total_teams": 14,
    }


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            data = json.load(f)
        # merge any missing keys from default
        defaults = _default_state()
        for k, v in defaults.items():
            data.setdefault(k, v)
        return data
    return _default_state()


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_my_roster_needs(state: dict, players_df) -> list[str]:
    """
    Return list of positions still needed (starters only, no bench).
    """
    my_ids   = state["my_team"]
    my_rows  = players_df[players_df["player_id"].isin(my_ids)]
    my_positions = my_rows["position"].value_counts().to_dict()

    needs = []
    for pos, count in LINEUP_SLOTS.items():
        if pos == "FLEX":
            continue   # handled separately
        filled = my_positions.get(pos, 0)
        for _ in range(max(0, count - filled)):
            needs.append(pos)

    # FLEX: need one RB/WR/TE beyond the starting 2/2/1
    flex_eligible_filled = sum(
        my_positions.get(p, 0) for p in FLEX_ELIGIBLE
    )
    baseline = LINEUP_SLOTS["RB"] + LINEUP_SLOTS["WR"] + LINEUP_SLOTS["TE"]
    if flex_eligible_filled <= baseline:
        needs.append("FLEX")

    return needs


def next_pick_round(state: dict) -> int:
    return ((state["current_pick"] - 1) // state["total_teams"]) + 1


def is_my_pick(state: dict) -> bool:
    """True if the current overall pick belongs to me (snake draft)."""
    if state["my_pick_num"] is None:
        return False
    pick = state["current_pick"]
    teams = state["total_teams"]
    round_num = ((pick - 1) // teams) + 1
    pick_in_round = ((pick - 1) % teams) + 1
    if round_num % 2 == 1:
        return pick_in_round == state["my_pick_num"]
    else:
        return pick_in_round == (teams + 1 - state["my_pick_num"])
