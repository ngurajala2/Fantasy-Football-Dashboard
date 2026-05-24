"""
🏈 Fantasy Football Draft Dashboard
14-team • Half-PPR • Yahoo scoring
Prioritizes: consistent high-floor players

Run with:  streamlit run app.py
"""

import json
import time
import warnings
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from pathlib import Path

warnings.filterwarnings("ignore")

# ── Page config (must be first Streamlit call) ───────────────────────────────
st.set_page_config(
    page_title="🏈 Fantasy Draft Dashboard",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys_path_added = False
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.draft_state import (
    load_state, save_state, get_my_roster_needs,
    next_pick_round, is_my_pick, LINEUP_SLOTS, BENCH_SLOTS, TOTAL_ROSTER
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Global ── */
[data-testid="stAppViewContainer"] { background: #0d1117; }
[data-testid="stSidebar"]          { background: #161b22; border-right: 1px solid #30363d; }
h1,h2,h3,h4,h5,h6,label,p,li      { color: #e6edf3 !important; }
.stTabs [data-baseweb="tab"]       { color: #8b949e; }
.stTabs [aria-selected="true"]     { color: #58a6ff !important; border-bottom: 2px solid #58a6ff; }

/* ── Metric cards ── */
.metric-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 16px;
    text-align: center;
}
.metric-card .label { color: #8b949e; font-size: 12px; text-transform: uppercase; }
.metric-card .value { color: #e6edf3; font-size: 24px; font-weight: 700; }

/* ── Position badges ── */
.badge-QB  { background:#ef4444; color:#fff; padding:2px 8px; border-radius:4px; font-weight:700; font-size:12px; }
.badge-RB  { background:#22c55e; color:#fff; padding:2px 8px; border-radius:4px; font-weight:700; font-size:12px; }
.badge-WR  { background:#3b82f6; color:#fff; padding:2px 8px; border-radius:4px; font-weight:700; font-size:12px; }
.badge-TE  { background:#f59e0b; color:#fff; padding:2px 8px; border-radius:4px; font-weight:700; font-size:12px; }
.badge-K   { background:#8b5cf6; color:#fff; padding:2px 8px; border-radius:4px; font-weight:700; font-size:12px; }
.badge-DEF { background:#6b7280; color:#fff; padding:2px 8px; border-radius:4px; font-weight:700; font-size:12px; }

/* ── Player row colors ── */
.row-mine     { background: rgba(34,197,94,0.1) !important; border-left: 3px solid #22c55e; }
.row-drafted  { background: rgba(239,68,68,0.08) !important; opacity: 0.5; }
.row-watch    { background: rgba(245,158,11,0.1) !important; border-left: 3px solid #f59e0b; }

/* ── Tier headers ── */
.tier-header {
    background: linear-gradient(90deg, #1f2937, transparent);
    border-left: 4px solid #58a6ff;
    padding: 6px 14px;
    margin: 8px 0 4px 0;
    font-weight: 700;
    font-size: 14px;
    color: #58a6ff !important;
}

/* ── Buttons ── */
.stButton>button {
    border-radius: 6px;
    font-weight: 600;
    transition: all 0.15s;
}
</style>
""", unsafe_allow_html=True)

# ── Helpers ───────────────────────────────────────────────────────────────────

POS_COLORS = {
    "QB": "#ef4444", "RB": "#22c55e", "WR": "#3b82f6",
    "TE": "#f59e0b", "K": "#8b5cf6", "DEF": "#6b7280",
    "FLEX": "#14b8a6",
}
FLEX_POSITIONS = ["RB", "WR", "TE"]

PRIORITY_PRESETS = {
    "Boom/Bust Heavy": {
        "weight": 0.15,
        "caption": "Prioritizes expert rank and big-play upside; tolerates volatility.",
    },
    "Upside Lean": {
        "weight": 0.35,
        "caption": "Still chases upside, with a little protection against weekly duds.",
    },
    "Balanced": {
        "weight": 0.50,
        "caption": "Blends expert rank and week-to-week steadiness evenly.",
    },
    "Consistency Focused": {
        "weight": 0.70,
        "caption": "Prefers reliable weekly output and stronger average bad games.",
    },
    "Safe Floor Heavy": {
        "weight": 0.85,
        "caption": "Strongly favors stable players with fewer low-scoring weeks.",
    },
}

# ── Session state init ────────────────────────────────────────────────────────
DATA_VERSION = "historical_2021_2025_last2_weighted_labels"

if "draft_state" not in st.session_state:
    st.session_state.draft_state = load_state()
if "players_df" not in st.session_state:
    st.session_state.players_df = None
if "consistency_df" not in st.session_state:
    st.session_state.consistency_df = None
if "yahoo_scoring" not in st.session_state:
    st.session_state.yahoo_scoring = None
if "data_loaded" not in st.session_state:
    st.session_state.data_loaded = False
if "priority_preset" not in st.session_state:
    st.session_state.priority_preset = "Balanced"
if "consistency_weight" not in st.session_state:
    st.session_state.consistency_weight = PRIORITY_PRESETS[st.session_state.priority_preset]["weight"]
if "search_term" not in st.session_state:
    st.session_state.search_term = ""
if st.session_state.get("data_version") != DATA_VERSION:
    st.session_state.players_df = None
    st.session_state.consistency_df = None
    st.session_state.data_loaded = False
    st.session_state.data_version = DATA_VERSION

def pos_badge(pos: str) -> str:
    color = POS_COLORS.get(pos, "#6b7280")
    return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700">{pos}</span>'

def color_consistency(score) -> str:
    try:
        v = float(score)
    except (TypeError, ValueError):
        return "—"
    if v >= 75:
        return f'<span style="color:#22c55e;font-weight:700">{v:.0f}</span>'
    elif v >= 55:
        return f'<span style="color:#f59e0b;font-weight:700">{v:.0f}</span>'
    else:
        return f'<span style="color:#ef4444;font-weight:700">{v:.0f}</span>'

def fmt_num(value, decimals=1, suffix="") -> str:
    """Format numeric display values while tolerating missing/string placeholders."""
    try:
        if pd.isna(value):
            return "—"
        return f"{float(value):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return "—"

def fmt_int(value, suffix="") -> str:
    try:
        if pd.isna(value):
            return "—"
        return f"{int(float(value))}{suffix}"
    except (TypeError, ValueError):
        return "—"

def color_injury(status) -> str:
    if not status or pd.isna(status) or str(status).strip() in ("", "nan"):
        return "✅"
    s = str(status).upper()
    if "OUT" in s or "IR" in s:       return f'<span style="color:#ef4444">⛔ {status}</span>'
    if "DOUBT" in s:                  return f'<span style="color:#f59e0b">⚠️ {status}</span>'
    if "QUEST" in s:                  return f'<span style="color:#f59e0b">❓ {status}</span>'
    return f'<span style="color:#8b949e">{status}</span>'


def compute_composite_score(row, w_consistency: float) -> float:
    """
    Weighted composite score balancing ranking and consistency.
    w_consistency ∈ [0, 1]  (1 = pure consistency, 0 = pure rank)
    """
    w_rank = 1 - w_consistency

    # Rank score: invert so rank 1 = 100
    rank_raw   = row.get("composite_rank", 999)
    rank_score = max(0, 100 - (float(rank_raw) / 3))   # rough scale

    cons_score = row.get("consistency_score", 50)
    if pd.isna(cons_score):
        cons_score = 50.0

    return round(w_rank * rank_score + w_consistency * float(cons_score), 1)


@st.cache_data(ttl=3600, show_spinner=False)
def load_rankings_cached():
    from data.fetch_rankings import fetch_all_rankings
    return fetch_all_rankings()


@st.cache_data(ttl=86400, show_spinner=False)
def load_consistency_cached():
    from data.historical_stats import fetch_historical_consistency
    return fetch_historical_consistency()


def merge_data(rankings: pd.DataFrame, consistency: pd.DataFrame) -> pd.DataFrame:
    """
    Merge ranking board with historical consistency metrics.
    nfl_data_py stores names as 'C.McCaffrey'; rankings have 'Christian McCaffrey'.
    We match via first_initial + last_name key: both map to 'c_mccaffrey'.
    """
    import re

    CONS_COLS = ["consistency_score", "mean_pts_hist", "std_pts_hist",
                 "cv_hist", "floor_pts_hist", "ceiling_pts_hist",
                 "bust_rate_pct", "boom_rate_pct", "games_played", "seasons_of_data"]

    if consistency.empty:
        for col in CONS_COLS:
            rankings[col] = 50.0 if col == "consistency_score" else np.nan
        return rankings

    def abbrev_key(name: str) -> str:
        """'Christian McCaffrey' or 'C.McCaffrey' → 'c_mccaffrey'"""
        name = str(name).lower().strip()
        name = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", name)
        name = re.sub(r"['\-]", "", name)
        if re.match(r"^[a-z]\.", name):          # abbreviated: "c.mccaffrey" or "a.st. brown"
            initial, rest = name.split(".", 1)
            parts = re.sub(r"[^a-z ]", " ", rest).split()
            if len(parts) >= 2 and parts[0] == "st":
                last = "st" + parts[-1]
            else:
                last = parts[-1] if parts else ""
            return f"{initial}_{last}"
        parts = re.sub(r"[^a-z ]", " ", name).split()
        if len(parts) >= 2:
            if len(parts) >= 3 and parts[-2] == "st":
                return f"{parts[0][0]}_st{parts[-1]}"
            return f"{parts[0][0]}_{parts[-1]}"
        return re.sub(r"[^a-z]", "", name)

    # De-dupe consistency — keep player with most games played
    cons = consistency.copy()
    cons["name_key"] = cons["player_name"].apply(abbrev_key)

    cons_dedup = cons.sort_values("games_played", ascending=False).drop_duplicates("name_key")

    # Build column→dict lookups (avoids duplicate-index issues with .map())
    lookups = {
        col: cons_dedup.set_index("name_key")[col].to_dict()
        for col in CONS_COLS
        if col in cons_dedup.columns
    }

    # Apply to rankings
    rankings = rankings.copy()
    rankings["abbrev_key"] = rankings["player_name"].apply(abbrev_key)
    for col, lkp in lookups.items():
        rankings[col] = rankings["abbrev_key"].map(lkp)

    matched = rankings["consistency_score"].notna().sum()
    print(f"[merge_data] Matched {matched}/{len(rankings)} players with historical data")

    # Default for unmatched:
    #   Rookies / DEF / K get 50 (unknown), established vets who somehow miss get 55
    rankings["consistency_score"] = rankings["consistency_score"].fillna(50.0)
    return rankings


def apply_draft_filter(df: pd.DataFrame, state: dict) -> pd.DataFrame:
    df = df.copy()
    df["is_mine"]    = df["player_id"].isin(state["my_team"])
    df["is_drafted"] = df["player_id"].isin(state["drafted"])
    df["is_watch"]   = df["player_id"].isin(state["watchlist"])
    return df


def get_best_available(df: pd.DataFrame, state: dict, pos_filter=None, top_n=5) -> pd.DataFrame:
    avail = df[~df["is_drafted"] & ~df["is_mine"]]
    if pos_filter == "FLEX":
        avail = avail[avail["position"].isin(FLEX_POSITIONS)]
    elif pos_filter and pos_filter != "ALL":
        avail = avail[avail["position"] == pos_filter]
    return avail.head(top_n)


# ── Sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar(state: dict):
    with st.sidebar:
        st.markdown("## 🏈 Draft Dashboard")
        st.markdown("---")

        # Draft position setup
        st.markdown("### ⚙️ League Settings")
        if state.get("my_pick_num") is None:
            pick_num = st.number_input(
                "My draft position (1–14)",
                min_value=1, max_value=14, value=7, step=1
            )
            if st.button("💾 Set Draft Position", use_container_width=True):
                state["my_pick_num"] = int(pick_num)
                save_state(state)
                st.rerun()
        else:
            st.success(f"Draft position: **#{state['my_pick_num']}** of 14")
            if st.button("Change position"):
                state["my_pick_num"] = None
                save_state(state)
                st.rerun()

        st.markdown("---")

        # Pick counter
        st.markdown("### 📋 Draft Progress")
        pick = state.get("current_pick", 1)
        rd   = next_pick_round(state)
        col1, col2 = st.columns(2)
        col1.metric("Overall Pick", pick)
        col2.metric("Round", rd)

        if is_my_pick(state):
            st.success("🎯 **YOUR PICK!**")
        else:
            # Calculate picks until next
            if state.get("my_pick_num"):
                teams = state["total_teams"]
                cur   = state["current_pick"]
                my_pos = state["my_pick_num"]

                def my_pick_nums():
                    results = []
                    for r in range(1, 16):
                        if r % 2 == 1:
                            results.append((r-1)*teams + my_pos)
                        else:
                            results.append(r*teams + 1 - my_pos)
                    return results

                upcoming = [p for p in my_pick_nums() if p >= cur]
                if upcoming:
                    st.info(f"⏳ Next pick: **#{upcoming[0]}**  ({upcoming[0]-cur} picks away)")

        col_back, col_fwd = st.columns(2)
        with col_back:
            if st.button("◀ Back", use_container_width=True):
                state["current_pick"] = max(1, state["current_pick"] - 1)
                save_state(state)
                st.rerun()
        with col_fwd:
            if st.button("Fwd ▶", use_container_width=True):
                state["current_pick"] += 1
                save_state(state)
                st.rerun()

        st.markdown("---")

        # Personalization
        st.markdown("### 🎛️ My Priorities")
        preset_names = list(PRIORITY_PRESETS.keys())
        current_preset = st.session_state.get("priority_preset", "Balanced")
        if current_preset not in PRIORITY_PRESETS:
            current_preset = "Balanced"
        selected_preset = st.radio(
            "Draft style",
            preset_names,
            index=preset_names.index(current_preset),
            help="Controls how much the rankings favor consistency versus expert-rank upside."
        )
        if selected_preset != st.session_state.priority_preset:
            st.session_state.priority_preset = selected_preset
            st.session_state.consistency_weight = PRIORITY_PRESETS[selected_preset]["weight"]
            st.session_state.data_loaded = False
            st.rerun()
        st.session_state.consistency_weight = PRIORITY_PRESETS[selected_preset]["weight"]
        st.caption(PRIORITY_PRESETS[selected_preset]["caption"])

        st.markdown("---")

        # Team summary
        if st.session_state.players_df is not None and state["my_team"]:
            df = st.session_state.players_df
            my_players = df[df["player_id"].isin(state["my_team"])]
            st.markdown("### 🏆 My Team")
            for _, row in my_players.iterrows():
                pos   = row.get("position", "?")
                name  = row.get("player_name", "?")
                color = POS_COLORS.get(pos, "#6b7280")
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0">'
                    f'<span style="background:{color};color:#fff;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:700">{pos}</span>'
                    f'<span style="color:#e6edf3;font-size:13px">{name}</span></div>',
                    unsafe_allow_html=True
                )
            remaining = TOTAL_ROSTER - len(state["my_team"])
            st.caption(f"{len(state['my_team'])}/{TOTAL_ROSTER} roster spots filled • {remaining} remaining")

        st.markdown("---")
        # Data controls
        if st.button("🔄 Refresh Rankings", use_container_width=True):
            st.cache_data.clear()
            st.session_state.data_loaded = False
            st.rerun()
        if st.button("🗑️ Reset Draft Board", use_container_width=True):
            if st.session_state.get("confirm_reset"):
                from utils.draft_state import _default_state
                st.session_state.draft_state = _default_state()
                save_state(st.session_state.draft_state)
                st.session_state.confirm_reset = False
                st.rerun()
            else:
                st.session_state.confirm_reset = True
                st.warning("Click again to confirm reset")


# ── Data loading ──────────────────────────────────────────────────────────────

def load_data():
    if st.session_state.data_loaded:
        return

    with st.spinner("📡 Fetching rankings from FantasyPros, Sleeper & ESPN…"):
        rankings = load_rankings_cached()

    with st.spinner("📊 Loading 6-season historical stats for consistency metrics…"):
        consistency = load_consistency_cached()

    with st.spinner("🔀 Merging data…"):
        merged = merge_data(rankings, consistency)
        # Apply composite score
        w = st.session_state.consistency_weight
        merged["my_score"] = merged.apply(
            lambda r: compute_composite_score(r, w), axis=1
        )
        merged = merged.sort_values("my_score", ascending=False).reset_index(drop=True)
        merged["my_rank"] = merged.index + 1

    st.session_state.players_df    = merged
    st.session_state.consistency_df = consistency
    st.session_state.data_loaded    = True


# ── Draft Board tab ──────────────────────────────────────────────────────────

def render_draft_board(state: dict):
    df = st.session_state.players_df.copy()
    df = apply_draft_filter(df, state)

    # Recompute with current draft-style preset
    w = st.session_state.consistency_weight
    df["my_score"] = df.apply(lambda r: compute_composite_score(r, w), axis=1)
    df = df.sort_values("my_score", ascending=False).reset_index(drop=True)
    df["my_rank"] = df.index + 1

    # ── Filters row ────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    with c1:
        search = st.text_input("🔍 Search player", value=st.session_state.search_term,
                               placeholder="e.g. CMC, Tyreek…", key="search_input")
        st.session_state.search_term = search
    with c2:
        pos_filter = st.selectbox("Position", ["ALL", "QB", "RB", "WR", "TE", "FLEX", "K", "DEF"])
    with c3:
        hide_drafted = st.checkbox("Hide drafted", value=True)
    with c4:
        show_watch_only = st.checkbox("Watchlist only")

    # Apply filters
    view = df.copy()
    if search:
        view = view[view["player_name"].str.contains(search, case=False, na=False)]
    if pos_filter == "FLEX":
        view = view[view["position"].isin(FLEX_POSITIONS)]
    elif pos_filter != "ALL":
        view = view[view["position"] == pos_filter]
    if hide_drafted:
        view = view[~view["is_drafted"]]
    if show_watch_only:
        view = view[view["is_watch"]]

    st.caption(f"Showing {len(view):,} players  •  {df['is_drafted'].sum()} drafted  •  {len(state['my_team'])} on my team")

    # ── Column definitions ─────────────────────────────────────────────────
    cols_to_show = [
        "my_rank", "player_name", "position", "team",
        "consistency_score", "floor_pts_hist", "ceiling_pts_hist",
        "mean_pts_hist", "bust_rate_pct", "boom_rate_pct",
        "fp_rank", "injury_status",
    ]
    display_cols = {
        "my_rank":           "My Rank",
        "player_name":       "Player",
        "position":          "Pos",
        "team":              "Team",
        "consistency_score": "Consistency",
        "floor_pts_hist":    "Avg Bad Game",
        "ceiling_pts_hist":  "Avg Good Game",
        "mean_pts_hist":     "Avg Pts",
        "bust_rate_pct":     "Bust %",
        "boom_rate_pct":     "Boom %",
        "fp_rank":           "FP Rank",
        "injury_status":     "Injury",
    }

    # Ensure all columns exist
    for col in cols_to_show:
        if col not in view.columns:
            view[col] = "—"

    # ── Render table in chunks ─────────────────────────────────────────────
    st.markdown("---")
    page_size = 50
    total_pages = max(1, (len(view) - 1) // page_size + 1)

    if "board_page" not in st.session_state:
        st.session_state.board_page = 0

    # Reset page when filters change
    pc1, pc2, pc3 = st.columns([1, 4, 1])
    with pc1:
        if st.button("◀ Prev", disabled=st.session_state.board_page == 0):
            st.session_state.board_page -= 1
            st.rerun()
    with pc2:
        st.markdown(f"<p style='text-align:center;color:#8b949e'>Page {st.session_state.board_page+1} / {total_pages}</p>", unsafe_allow_html=True)
    with pc3:
        if st.button("Next ▶", disabled=st.session_state.board_page >= total_pages - 1):
            st.session_state.board_page += 1
            st.rerun()

    start = st.session_state.board_page * page_size
    page_df = view.iloc[start : start + page_size]

    # ── Render each player row ─────────────────────────────────────────────
    header_cols = st.columns([0.4, 2.2, 0.6, 0.6, 0.9, 0.8, 0.9, 0.8, 0.7, 0.7, 0.6, 0.8, 1.2])
    headers = ["#", "Player", "Pos", "Team", "Consist.", "Avg Bad", "Avg Good", "Avg", "Bust%", "Boom%", "FP Rank", "Injury", "Actions"]
    for h, col in zip(headers, header_cols):
        col.markdown(f"<span style='color:#8b949e;font-size:11px;font-weight:700;text-transform:uppercase'>{h}</span>", unsafe_allow_html=True)

    st.markdown('<hr style="margin:4px 0;border-color:#30363d">', unsafe_allow_html=True)

    for _, row in page_df.iterrows():
        pid     = str(row.get("player_id", ""))
        is_mine = bool(row.get("is_mine", False))
        is_draf = bool(row.get("is_drafted", False))
        is_wat  = bool(row.get("is_watch", False))

        # Row background
        if is_mine:
            bg = "rgba(34,197,94,0.08)"
            border = "border-left:3px solid #22c55e"
        elif is_draf:
            bg = "rgba(239,68,68,0.05)"
            border = ""
        elif is_wat:
            bg = "rgba(245,158,11,0.08)"
            border = "border-left:3px solid #f59e0b"
        else:
            bg = "transparent"
            border = ""

        row_style = f"background:{bg};{border};padding:4px 0;border-radius:4px"

        rc = st.columns([0.4, 2.2, 0.6, 0.6, 0.9, 0.8, 0.9, 0.8, 0.7, 0.7, 0.6, 0.8, 1.2])

        # Rank
        rank_val = row.get("my_rank", "—")
        rank_color = "#58a6ff" if not is_draf else "#555"
        rc[0].markdown(f'<div style="{row_style}"><span style="color:{rank_color};font-weight:700">{rank_val}</span></div>', unsafe_allow_html=True)

        # Name
        name   = str(row.get("player_name", "—"))
        name_s = f'<span style="color:{"#555" if is_draf else "#e6edf3"};{"text-decoration:line-through" if is_draf else ""}">{name}</span>'
        mine_s = ' <span style="font-size:10px;color:#22c55e">✓ MINE</span>' if is_mine else ""
        rc[1].markdown(f'<div style="{row_style}">{name_s}{mine_s}</div>', unsafe_allow_html=True)

        # Position
        pos = str(row.get("position", "—"))
        rc[2].markdown(f'<div style="{row_style}">{pos_badge(pos)}</div>', unsafe_allow_html=True)

        # Team
        team = str(row.get("team", "—")) if row.get("team") else "—"
        rc[3].markdown(f'<div style="{row_style}"><span style="color:#8b949e">{team}</span></div>', unsafe_allow_html=True)

        # Consistency
        cs = row.get("consistency_score", np.nan)
        rc[4].markdown(f'<div style="{row_style}">{color_consistency(cs)}</div>', unsafe_allow_html=True)

        # Average bad game
        fl  = row.get("floor_pts_hist", np.nan)
        rc[5].markdown(f'<div style="{row_style}"><span style="color:#22c55e">{fmt_num(fl)}</span></div>', unsafe_allow_html=True)

        # Average good game
        cl  = row.get("ceiling_pts_hist", np.nan)
        rc[6].markdown(f'<div style="{row_style}"><span style="color:#3b82f6">{fmt_num(cl)}</span></div>', unsafe_allow_html=True)

        # Avg
        avg = row.get("mean_pts_hist", np.nan)
        rc[7].markdown(f'<div style="{row_style}"><span style="color:#e6edf3">{fmt_num(avg)}</span></div>', unsafe_allow_html=True)

        # Bust %
        bust = row.get("bust_rate_pct", np.nan)
        bust_num = pd.to_numeric(bust, errors="coerce")
        bust_color = "#ef4444" if not pd.isna(bust_num) and bust_num > 25 else "#8b949e"
        rc[8].markdown(f'<div style="{row_style}"><span style="color:{bust_color}">{fmt_int(bust, "%")}</span></div>', unsafe_allow_html=True)

        # Boom %
        boom = row.get("boom_rate_pct", np.nan)
        boom_num = pd.to_numeric(boom, errors="coerce")
        boom_color = "#22c55e" if not pd.isna(boom_num) and boom_num > 25 else "#8b949e"
        rc[9].markdown(f'<div style="{row_style}"><span style="color:{boom_color}">{fmt_int(boom, "%")}</span></div>', unsafe_allow_html=True)

        # FP Rank
        fp_r = row.get("fp_rank", np.nan)
        rc[10].markdown(f'<div style="{row_style}"><span style="color:#8b949e">{fmt_int(fp_r)}</span></div>', unsafe_allow_html=True)

        # Injury
        inj = row.get("injury_status", "")
        rc[11].markdown(f'<div style="{row_style}">{color_injury(inj)}</div>', unsafe_allow_html=True)

        # Action buttons
        with rc[12]:
            if is_mine:
                if st.button("❌ Drop", key=f"drop_{pid}", help="Remove from my team"):
                    state["my_team"].remove(pid)
                    save_state(state)
                    st.rerun()
            elif is_draf:
                if st.button("↩ Undraft", key=f"undraft_{pid}", help="Mark as available"):
                    state["drafted"].remove(pid)
                    save_state(state)
                    st.rerun()
            else:
                b1, b2, b3 = st.columns(3)
                with b1:
                    if st.button("✅", key=f"mine_{pid}", help="Add to my team"):
                        if pid not in state["my_team"]:
                            state["my_team"].append(pid)
                        if pid in state["drafted"]:
                            state["drafted"].remove(pid)
                        state["current_pick"] += 1
                        save_state(state)
                        st.rerun()
                with b2:
                    if st.button("🚫", key=f"draf_{pid}", help="Mark as drafted by others"):
                        if pid not in state["drafted"]:
                            state["drafted"].append(pid)
                        state["current_pick"] += 1
                        save_state(state)
                        st.rerun()
                with b3:
                    star = "⭐" if is_wat else "☆"
                    if st.button(star, key=f"watch_{pid}", help="Toggle watchlist"):
                        if pid in state["watchlist"]:
                            state["watchlist"].remove(pid)
                        else:
                            state["watchlist"].append(pid)
                        save_state(state)
                        st.rerun()

        st.markdown('<hr style="margin:2px 0;border-color:#21262d">', unsafe_allow_html=True)


# ── My Team tab ───────────────────────────────────────────────────────────────

def render_my_team(state: dict):
    df = st.session_state.players_df

    if not state["my_team"]:
        st.info("👆 Go to **Draft Board** and click ✅ to add players to your team.")
        return

    my_df = df[df["player_id"].isin(state["my_team"])].copy()

    # ── Summary metrics ────────────────────────────────────────────────────
    st.markdown("### 📊 Team Summary")
    c1, c2, c3, c4, c5 = st.columns(5)

    avg_cons   = my_df["consistency_score"].mean()
    avg_floor  = my_df["floor_pts_hist"].mean()
    avg_ceiling= my_df["ceiling_pts_hist"].mean()
    avg_pts    = my_df["mean_pts_hist"].mean()
    roster_n   = len(my_df)

    for col, label, val, color in [
        (c1, "Players Drafted", roster_n, "#58a6ff"),
        (c2, "Avg Consistency", fmt_int(avg_cons, "/100"), "#22c55e"),
        (c3, "Avg Bad Game", fmt_num(avg_floor), "#22c55e"),
        (c4, "Avg Good Game", fmt_num(avg_ceiling), "#3b82f6"),
        (c5, "Avg Pts/Week", fmt_num(avg_pts), "#f59e0b"),
    ]:
        col.markdown(
            f'<div class="metric-card"><div class="label">{label}</div>'
            f'<div class="value" style="color:{color}">{val}</div></div>',
            unsafe_allow_html=True
        )

    st.markdown("---")

    # ── Roster by position ─────────────────────────────────────────────────
    st.markdown("### 🗂️ Roster Slots")
    slot_order = ["QB", "RB", "WR", "TE", "K", "DEF"]

    for pos in slot_order:
        pos_players = my_df[my_df["position"] == pos]
        needed = LINEUP_SLOTS.get(pos, 0)

        with st.expander(f"{pos_badge(pos)}  {pos}  •  {len(pos_players)}/{needed} starters", expanded=True):
            if pos_players.empty:
                st.caption("No players drafted yet at this position.")
            else:
                for _, row in pos_players.iterrows():
                    pid  = str(row["player_id"])
                    name = row.get("player_name", "?")
                    cs   = row.get("consistency_score", np.nan)
                    fl   = row.get("floor_pts_hist", np.nan)
                    cl   = row.get("ceiling_pts_hist", np.nan)
                    inj  = row.get("injury_status", "")

                    rc = st.columns([3, 1, 1, 1, 1, 0.5])
                    rc[0].markdown(f"**{name}**  {color_injury(inj)}", unsafe_allow_html=True)
                    rc[1].markdown(f"Consistency: {color_consistency(cs)}", unsafe_allow_html=True)
                    rc[2].markdown(f"Avg Bad: <span style='color:#22c55e'>{fmt_num(fl)}</span>", unsafe_allow_html=True)
                    rc[3].markdown(f"Avg Good: <span style='color:#3b82f6'>{fmt_num(cl)}</span>", unsafe_allow_html=True)
                    avg_val = row.get('mean_pts_hist', np.nan)
                    avg_str = fmt_num(avg_val)
                    rc[4].markdown(f"Avg: <span style='color:#e6edf3'>{avg_str}</span>", unsafe_allow_html=True)
                    with rc[5]:
                        if st.button("❌", key=f"teamdrop_{pid}"):
                            state["my_team"].remove(pid)
                            save_state(state)
                            st.rerun()

    # ── Roster needs & recommendations ─────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🎯 Next Pick Recommendations")
    needs = get_my_roster_needs(state, df)

    if not needs:
        st.success("✅ All starter slots are filled! Focus on depth / bench.")
    else:
        st.markdown(f"**Positions still needed:** " + "  ".join([pos_badge(p) for p in needs]), unsafe_allow_html=True)

    avail_df = apply_draft_filter(df, state)
    avail_df = avail_df[~avail_df["is_drafted"] & ~avail_df["is_mine"]]
    w = st.session_state.consistency_weight
    avail_df["my_score"] = avail_df.apply(lambda r: compute_composite_score(r, w), axis=1)

    unique_needs = list(dict.fromkeys(needs))  # preserve order, dedupe
    for pos in unique_needs:
        top = avail_df[avail_df["position"] == pos].sort_values("my_score", ascending=False).head(3)
        if not top.empty:
            st.markdown(f"**Best available {pos_badge(pos)}:**", unsafe_allow_html=True)
            for _, row in top.iterrows():
                name = row.get("player_name", "?")
                cs   = row.get("consistency_score", np.nan)
                fl   = row.get("floor_pts_hist", np.nan)
                score= row.get("my_score", "—")
                st.markdown(
                    f"&nbsp;&nbsp;• **{name}** — Score: {fmt_int(score)} | Consistency: {color_consistency(cs)} | Avg Bad: {fmt_num(fl)}",
                    unsafe_allow_html=True
                )


# ── Analytics / Player Detail tab ─────────────────────────────────────────────

def render_analytics(state: dict):
    df = st.session_state.players_df

    st.markdown("### 🔍 Player Analysis")

    # Player selector
    avail_names = df["player_name"].dropna().sort_values().tolist()
    selected_name = st.selectbox("Select a player to analyze", avail_names)

    if not selected_name:
        return

    row = df[df["player_name"] == selected_name].iloc[0]
    pid = str(row.get("player_id", ""))
    pos = row.get("position", "?")

    # ── Player card ────────────────────────────────────────────────────────
    hdr = st.columns([1, 4])
    with hdr[0]:
        st.markdown(
            f'<div style="text-align:center;padding:20px;background:#161b22;border-radius:10px;border:1px solid #30363d">'
            f'{pos_badge(pos)}'
            f'<div style="font-size:20px;font-weight:700;color:#e6edf3;margin-top:8px">{selected_name}</div>'
            f'<div style="color:#8b949e">{row.get("team","—")} • {row.get("age","?") or "?"} yrs old</div>'
            f'<div style="margin-top:8px">{color_injury(row.get("injury_status",""))}</div>'
            f'</div>',
            unsafe_allow_html=True
        )
    with hdr[1]:
        m1, m2, m3, m4, m5 = st.columns(5)
        metrics = [
            ("My Rank",     row.get("my_rank", "—"),     "#58a6ff"),
            ("Consistency", fmt_int(row.get("consistency_score", np.nan), "/100"), "#22c55e"),
            ("Avg Bad Game", fmt_num(row.get("floor_pts_hist", np.nan)), "#22c55e"),
            ("Avg Good Game", fmt_num(row.get("ceiling_pts_hist", np.nan)), "#3b82f6"),
            ("Avg/Week",    fmt_num(row.get("mean_pts_hist", np.nan)), "#f59e0b"),
        ]
        for col, (label, val, color) in zip([m1, m2, m3, m4, m5], metrics):
            col.markdown(
                f'<div class="metric-card"><div class="label">{label}</div>'
                f'<div class="value" style="color:{color}">{val}</div></div>',
                unsafe_allow_html=True
            )

    st.markdown("---")

    # ── Historical weekly chart ────────────────────────────────────────────
    st.markdown("#### 📈 Weekly Scoring History (2021–2025)")

    with st.spinner("Loading weekly history…"):
        try:
            from data.historical_stats import get_player_weekly_history
            history = get_player_weekly_history(pid)
        except Exception:
            history = pd.DataFrame()

    if history.empty:
        st.info("No detailed weekly history available for this player (may not have data for the recent seasons).")
    else:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=list(range(len(history))),
            y=history["half_ppr_pts"],
            mode="lines+markers",
            line=dict(color=POS_COLORS.get(pos, "#58a6ff"), width=2),
            marker=dict(size=5),
            name="Half-PPR pts",
        ))

        mean_val  = history["half_ppr_pts"].mean()
        floor_val = float(np.percentile(history["half_ppr_pts"], 25))
        ceil_val  = float(np.percentile(history["half_ppr_pts"], 75))

        fig.add_hline(y=mean_val,  line_dash="dash", line_color="#f59e0b", annotation_text=f"Avg {mean_val:.1f}")
        fig.add_hline(y=floor_val, line_dash="dot",  line_color="#22c55e", annotation_text=f"Avg Bad {floor_val:.1f}")
        fig.add_hline(y=ceil_val,  line_dash="dot",  line_color="#3b82f6", annotation_text=f"Avg Good {ceil_val:.1f}")

        fig.update_layout(
            height=320,
            plot_bgcolor="#0d1117",
            paper_bgcolor="#0d1117",
            font_color="#e6edf3",
            xaxis=dict(showgrid=False, color="#8b949e", title="Games (chronological)"),
            yaxis=dict(gridcolor="#21262d", color="#8b949e", title="Fantasy pts"),
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Distribution ──────────────────────────────────────────────────────
    if not history.empty:
        fig2 = px.histogram(
            history, x="half_ppr_pts", nbins=20,
            color_discrete_sequence=[POS_COLORS.get(pos, "#58a6ff")],
            title="Score Distribution",
        )
        fig2.update_layout(
            height=240, plot_bgcolor="#0d1117", paper_bgcolor="#0d1117",
            font_color="#e6edf3", margin=dict(l=10,r=10,t=30,b=10),
            xaxis=dict(gridcolor="#21262d", color="#8b949e"),
            yaxis=dict(gridcolor="#21262d", color="#8b949e"),
        )
        st.plotly_chart(fig2, use_container_width=True)

    # ── Compare players ───────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### ⚖️ Compare Players")
    compare_names = st.multiselect(
        "Add players to compare",
        [n for n in avail_names if n != selected_name],
        max_selections=4,
        key="compare_select"
    )
    all_compare = [selected_name] + compare_names
    compare_df  = df[df["player_name"].isin(all_compare)].copy()

    if len(compare_df) > 1:
        metrics_compare = ["consistency_score", "floor_pts_hist", "ceiling_pts_hist", "mean_pts_hist", "bust_rate_pct", "boom_rate_pct"]
        labels_compare  = ["Consistency", "Avg Bad", "Avg Good", "Avg/Wk", "Bust%", "Boom%"]

        fig3 = go.Figure()
        for _, row2 in compare_df.iterrows():
            vals = [float(row2.get(m, 0) or 0) for m in metrics_compare]
            fig3.add_trace(go.Bar(
                name=row2["player_name"],
                x=labels_compare,
                y=vals,
                text=[f"{v:.1f}" for v in vals],
                textposition="outside",
            ))
        fig3.update_layout(
            barmode="group", height=320,
            plot_bgcolor="#0d1117", paper_bgcolor="#0d1117",
            font_color="#e6edf3",
            xaxis=dict(color="#8b949e"),
            yaxis=dict(gridcolor="#21262d", color="#8b949e"),
            margin=dict(l=10,r=10,t=10,b=10),
            legend=dict(bgcolor="#161b22", bordercolor="#30363d", borderwidth=1),
        )
        st.plotly_chart(fig3, use_container_width=True)


# ── Positional Scarcity tab ───────────────────────────────────────────────────

def render_scarcity(state: dict):
    df = apply_draft_filter(st.session_state.players_df, state)
    avail = df[~df["is_drafted"] & ~df["is_mine"]]

    st.markdown("### 📉 Positional Scarcity — Value Over Replacement (VOR)")
    st.markdown(
        "VOR measures how much better a player is vs. the last \"startable\" player at that position. "
        "In a 14-team league, draft ~14 QBs before the position runs dry, ~28 RBs, etc."
    )

    # Replacement levels (14-team league, 1 QB/team, 2 RB/team etc.)
    replacement_ranks = {"QB": 14, "RB": 28, "WR": 28, "TE": 14, "K": 14, "DEF": 14}

    fig_rows = []
    for pos, repl_rank in replacement_ranks.items():
        pos_avail = avail[avail["position"] == pos].sort_values("my_rank")
        if pos_avail.empty:
            continue
        pos_avail = pos_avail.reset_index(drop=True)
        pos_avail["pos_rank"] = pos_avail.index + 1

        # Replacement player's avg pts
        repl_row = pos_avail[pos_avail["pos_rank"] == min(repl_rank, len(pos_avail))]
        repl_avg = float(repl_row["mean_pts_hist"].iloc[0]) if not repl_row.empty and not pd.isna(repl_row["mean_pts_hist"].iloc[0]) else 0

        top15 = pos_avail.head(15).copy()
        top15["vor"] = top15["mean_pts_hist"].fillna(0) - repl_avg
        fig_rows.append(top15.assign(position=pos))

    if fig_rows:
        scarcity_df = pd.concat(fig_rows, ignore_index=True)
        fig = px.bar(
            scarcity_df, x="player_name", y="vor", color="position",
            facet_col="position", facet_col_wrap=3,
            color_discrete_map=POS_COLORS,
            title="Value Over Replacement (top 15 available at each position)",
            labels={"vor": "VOR (pts/wk above replacement)", "player_name": ""},
        )
        fig.update_xaxes(tickangle=45, showticklabels=True)
        fig.update_layout(
            height=600, plot_bgcolor="#0d1117", paper_bgcolor="#0d1117",
            font_color="#e6edf3", showlegend=False,
            margin=dict(l=10, r=10, t=60, b=10),
        )
        fig.update_xaxes(gridcolor="#21262d")
        fig.update_yaxes(gridcolor="#21262d")
        st.plotly_chart(fig, use_container_width=True)

    # ── Consistency matrix ─────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🎯 Consistency vs. Scoring — Scatter")
    st.markdown("Top-right quadrant = your ideal targets: strong average bad games AND high scoring.")

    scatter_df = avail.dropna(subset=["consistency_score", "mean_pts_hist"]).copy()
    scatter_df = scatter_df[scatter_df["position"].isin(["QB","RB","WR","TE"])]

    if not scatter_df.empty:
        fig2 = px.scatter(
            scatter_df,
            x="mean_pts_hist", y="consistency_score",
            color="position", hover_name="player_name",
            color_discrete_map=POS_COLORS,
            size_max=12, opacity=0.85,
            labels={"mean_pts_hist": "Avg Pts/Week", "consistency_score": "Consistency Score (0-100)"},
        )
        # Quadrant lines
        mx = scatter_df["mean_pts_hist"].median()
        my = scatter_df["consistency_score"].median()
        fig2.add_vline(x=mx, line_dash="dash", line_color="#30363d")
        fig2.add_hline(y=my, line_dash="dash", line_color="#30363d")

        fig2.add_annotation(x=scatter_df["mean_pts_hist"].max()*0.92, y=99,
            text="🎯 TARGET ZONE", showarrow=False, font=dict(color="#22c55e", size=11))

        fig2.update_layout(
            height=450, plot_bgcolor="#0d1117", paper_bgcolor="#0d1117",
            font_color="#e6edf3",
            xaxis=dict(gridcolor="#21262d", color="#8b949e"),
            yaxis=dict(gridcolor="#21262d", color="#8b949e"),
            legend=dict(bgcolor="#161b22", bordercolor="#30363d"),
            margin=dict(l=10,r=10,t=10,b=10),
        )
        st.plotly_chart(fig2, use_container_width=True)


# ── Yahoo scoring tab ─────────────────────────────────────────────────────────

def render_yahoo_settings():
    st.markdown("### 🏈 Yahoo Fantasy Scoring Settings")

    if st.session_state.yahoo_scoring:
        st.success("✅ Yahoo scoring rules loaded!")
        st.json(st.session_state.yahoo_scoring)
    else:
        st.info("Click **Fetch from Yahoo** to log in and pull your league's exact scoring rules via browser automation.")

        col1, col2 = st.columns(2)
        with col1:
            yahoo_email = st.text_input("Yahoo Email", value="", type="default")
        with col2:
            yahoo_pass  = st.text_input("Yahoo Password", value="", type="password")

        league_id = st.text_input("League ID (from Yahoo URL — optional)", value="")

        if st.button("🔐 Fetch Scoring from Yahoo", type="primary"):
            if not yahoo_email or not yahoo_pass:
                st.error("Please enter your Yahoo credentials.")
            else:
                with st.spinner("Logging into Yahoo Fantasy…"):
                    from data.yahoo_auth import fetch_yahoo_scoring
                    result = fetch_yahoo_scoring(yahoo_email, yahoo_pass, league_id)
                    if result:
                        st.session_state.yahoo_scoring = result
                        st.success("Yahoo scoring rules loaded!")
                        st.rerun()
                    else:
                        st.error("Could not fetch Yahoo settings. Check credentials / try again.")

    # Show standard scoring reference
    st.markdown("---")
    st.markdown("### 📋 Standard Yahoo Half-PPR Scoring (applied by default)")

    scoring_ref = {
        "Passing": {"Passing yards": "0.04 pts/yd (1 pt / 25 yds)", "Passing TD": "4 pts", "Interception": "-1 pt", "2-pt conversion": "2 pts"},
        "Rushing": {"Rushing yards": "0.1 pts/yd (1 pt / 10 yds)", "Rushing TD": "6 pts", "2-pt conversion": "2 pts"},
        "Receiving (Half-PPR)": {"Receptions": "0.5 pts each", "Receiving yards": "0.1 pts/yd", "Receiving TD": "6 pts"},
        "Misc": {"Fumble lost": "-2 pts", "Return TD": "6 pts"},
        "Kicker": {"FG 0-39 yds": "3 pts", "FG 40-49 yds": "4 pts", "FG 50+ yds": "5 pts", "PAT made": "1 pt"},
        "DEF/ST": {"Sack": "1 pt", "INT": "2 pts", "Fumble rec": "2 pts", "TD": "6 pts", "Safety": "2 pts", "Pts allowed 0": "10 pts", "Pts allowed 1-6": "7 pts", "Pts allowed 7-13": "4 pts", "Pts allowed 14-17": "1 pt", "Pts allowed 28+": "-4 pts"},
    }

    for category, rules in scoring_ref.items():
        with st.expander(category, expanded=False):
            for rule, pts in rules.items():
                st.markdown(f"- **{rule}:** {pts}")


# ── Yahoo auth helper (stub — real fetch via browser automation) ──────────────

Path(ROOT / "data" / "yahoo_auth.py").parent.mkdir(parents=True, exist_ok=True)


# ── Main app ──────────────────────────────────────────────────────────────────

def main():
    state = st.session_state.draft_state

    render_sidebar(state)
    st.session_state.draft_state = state

    # ── Header ────────────────────────────────────────────────────────────
    st.markdown(
        '<h1 style="color:#e6edf3;margin-bottom:0">🏈 Fantasy Draft Dashboard</h1>'
        '<p style="color:#8b949e;margin-top:4px">14-team · Half-PPR · Prioritizing consistent, high-floor players</p>',
        unsafe_allow_html=True
    )

    # ── Load data ─────────────────────────────────────────────────────────
    load_data()

    if st.session_state.players_df is None or st.session_state.players_df.empty:
        st.error("❌ Failed to load player data. Check your internet connection and try refreshing.")
        return

    df = st.session_state.players_df
    avail_count = len(df) - len(state["my_team"]) - len(state["drafted"])

    # ── Top metrics bar ───────────────────────────────────────────────────
    mc = st.columns(5)
    mc[0].metric("Players Available", avail_count)
    mc[1].metric("My Team",          len(state["my_team"]))
    mc[2].metric("Drafted by Others", len(state["drafted"]))
    mc[3].metric("Watchlist",         len(state["watchlist"]))
    mc[4].metric("Current Pick",      f"#{state.get('current_pick',1)}")

    # ── Tabs ──────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📋 Draft Board",
        "🏆 My Team",
        "🔍 Player Analysis",
        "📉 Scarcity & VOR",
        "⚙️ Yahoo Settings",
    ])

    with tab1:
        render_draft_board(state)
    with tab2:
        render_my_team(state)
    with tab3:
        render_analytics(state)
    with tab4:
        render_scarcity(state)
    with tab5:
        render_yahoo_settings()


if __name__ == "__main__":
    main()
