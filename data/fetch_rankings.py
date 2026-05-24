"""
Multi-source ranking fetcher.

Sources:
  1. FantasyPros — consensus half-PPR rankings (scraped)
  2. Sleeper     — ADP and player meta (public API, no key needed)
  3. ESPN        — positional rankings (unofficial API)

Results are merged into a single DataFrame and cached locally.
"""

import time
import json
import warnings
import requests
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

warnings.filterwarnings("ignore")

CACHE_DIR  = Path(__file__).parent / "cache"
CACHE_FILE = CACHE_DIR / "rankings.parquet"
CACHE_TTL  = 6 * 3600   # 6 hours

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html,*/*",
}

POSITION_MAP = {
    "QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE",
    "K": "K", "DEF": "DEF", "DST": "DEF",
}


# ── FantasyPros ──────────────────────────────────────────────────────────────

def fetch_fantasypros() -> pd.DataFrame:
    """
    Fetch FantasyPros half-PPR consensus rankings.
    Tries the JSON API first, then falls back to HTML scraping.
    """
    import re
    from bs4 import BeautifulSoup

    # ── Attempt 1: FantasyPros public JSON API ─────────────────────────────
    # They expose an ECR (Expert Consensus Rankings) JSON endpoint
    fp_json_urls = [
        "https://partners.fantasypros.com/api/v1/consensus-rankings.php?sport=NFL&year=2025&week=0&id=1&position=ALL&type=ST&scoring=HALF&rank_type=avg",
        "https://www.fantasypros.com/api/v1/consensus-rankings.json?sport=nfl&scoring=HALF&position=ALL&year=2025",
    ]
    for url in fp_json_urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.ok:
                data = resp.json()
                players_raw = data.get("players", data.get("data", []))
                if players_raw:
                    rows = []
                    for i, p in enumerate(players_raw, 1):
                        name = p.get("player_name", p.get("name", ""))
                        pos  = POSITION_MAP.get(p.get("player_position_id", p.get("position", "")), "")
                        rows.append({
                            "fp_rank":     p.get("rank_ecr", p.get("rank", i)),
                            "player_name": name,
                            "position":    pos,
                            "team":        p.get("player_team_id", p.get("team", "")),
                        })
                    df = pd.DataFrame(rows)
                    df = df[df["player_name"] != ""]
                    if len(df) > 50:
                        return df
        except Exception:
            pass

    # ── Attempt 2: Scrape the HTML page and parse embedded JS ─────────────
    url = "https://www.fantasypros.com/nfl/rankings/half-point-ppr-cheatsheets.php"
    try:
        resp = requests.get(url, headers={**HEADERS, "Accept": "text/html"}, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        for script in soup.find_all("script"):
            text = script.string or ""
            if "ecrData" not in text and "player_name" not in text:
                continue
            # Try to extract players array
            for pattern in [
                r'var ecrData\s*=\s*\{[^}]*"players"\s*:\s*(\[.*?\])\s*[,}]',
                r'"players"\s*:\s*(\[.*?\])',
            ]:
                m = re.search(pattern, text, re.DOTALL)
                if m:
                    try:
                        players_raw = json.loads(m.group(1))
                        rows = []
                        for i, p in enumerate(players_raw, 1):
                            rows.append({
                                "fp_rank":     p.get("rank_ecr", i),
                                "player_name": p.get("player_name", ""),
                                "position":    POSITION_MAP.get(p.get("player_position_id", ""), ""),
                                "team":        p.get("player_team_id", ""),
                            })
                        df = pd.DataFrame(rows)
                        df = df[df["player_name"] != ""]
                        if len(df) > 50:
                            return df
                    except Exception:
                        pass

    except Exception as e:
        print(f"[FantasyPros HTML] {e}")

    # ── Attempt 3: Positional CSV exports ─────────────────────────────────
    return fetch_fantasypros_csv()


# ── Sleeper API ──────────────────────────────────────────────────────────────

def fetch_sleeper_players() -> pd.DataFrame:
    """Fetch all NFL players from Sleeper's public API."""
    url = "https://api.sleeper.app/v1/players/nfl"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        rows = []
        for pid, p in data.items():
            pos = p.get("fantasy_positions") or []
            pos = pos[0] if pos else p.get("position", "")
            pos = POSITION_MAP.get(pos, pos)
            if pos not in ("QB", "RB", "WR", "TE", "K", "DEF"):
                continue
            rows.append({
                "sleeper_id":  pid,
                "player_name": f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
                "position":    pos,
                "team":        p.get("team", "FA"),
                "age":         p.get("age"),
                "years_exp":   p.get("years_exp"),
                "injury_status": p.get("injury_status", ""),
                "status":      p.get("status", ""),
            })

        return pd.DataFrame(rows)

    except Exception as e:
        print(f"[Sleeper] Error: {e}")
        return pd.DataFrame()


def fetch_sleeper_adp(scoring: str = "half_ppr") -> pd.DataFrame:
    """Fetch Sleeper's ADP data for the current season."""
    url = f"https://api.sleeper.app/v1/players/nfl/trending/add?lookback_hours=168&limit=100"
    # For full ADP we use a different approach:
    adp_url = "https://api.sleeper.app/v1/players/nfl/trending/add"
    try:
        # Sleeper doesn't have a direct ADP endpoint — use player stats as proxy
        # trending data gives us popularity signal
        resp = requests.get(adp_url, params={"lookback_hours": 168, "limit": 200}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        rows = []
        for i, item in enumerate(data, 1):
            rows.append({
                "sleeper_id":    str(item.get("player_id", "")),
                "sleeper_trend": i,  # lower = more added = higher demand
            })
        return pd.DataFrame(rows)
    except Exception as e:
        print(f"[Sleeper ADP] Error: {e}")
        return pd.DataFrame()


# ── ESPN Unofficial API ──────────────────────────────────────────────────────

def fetch_espn_rankings() -> pd.DataFrame:
    """
    Pull ESPN's pre-draft player rankings via the unofficial ESPN Fantasy API.
    No auth required for default/public rankings.
    """
    espn_pos_map = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}
    rows = []

    # ESPN uses paginated requests — fetch in batches of 100
    for offset in range(0, 500, 100):
        espn_filter = json.dumps({
            "players": {
                "filterSlotIds":                    {"value": [0, 2, 4, 6, 17, 16, 23]},
                "filterRanksForScoringPeriodIds":   {"value": [1]},
                "filterRanksForRankTypes":          {"value": ["PPR"]},
                "limit":                            100,
                "offset":                           offset,
                "sortAdp":                          {"sortPriority": 1, "sortAsc": True},
            }
        })
        headers = {
            **HEADERS,
            "x-fantasy-filter": espn_filter,
            "x-fantasy-platform": "kona-PROD-f4dd189e80fc7b882d27e59dfc7ac5c2cccdc80c",
        }
        url = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2025/segments/0/leaguedefaults/1"
        try:
            resp = requests.get(url, params={"view": "kona_player_info"}, headers=headers, timeout=15)
            if not resp.ok:
                break
            data = resp.json()
            batch = data.get("players", [])
            if not batch:
                break
            for p in batch:
                entry = p.get("playerPoolEntry", {})
                info  = entry.get("player", {})
                pos_id = info.get("defaultPositionId", 0)
                pos    = espn_pos_map.get(pos_id, "")
                if not pos:
                    continue
                # ESPN stores ranks in onTeamId or averageAuctionValue
                adp = entry.get("averageAuctionValue") or entry.get("onTeamId")
                rows.append({
                    "player_name": info.get("fullName", ""),
                    "position":    pos,
                    "espn_rank":   len(rows) + 1,
                })
        except Exception as e:
            print(f"[ESPN offset={offset}] {e}")
            break

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ── FantasyPros CSV (backup) ─────────────────────────────────────────────────

def fetch_fantasypros_csv() -> pd.DataFrame:
    """
    Download FantasyPros half-PPR position rankings via their free CSV endpoint.
    Works without an API key.
    """
    positions = {
        "QB":  "https://www.fantasypros.com/nfl/rankings/qb.php?export=xls",
        "RB":  "https://www.fantasypros.com/nfl/rankings/half-point-ppr-rb.php?export=xls",
        "WR":  "https://www.fantasypros.com/nfl/rankings/half-point-ppr-wr.php?export=xls",
        "TE":  "https://www.fantasypros.com/nfl/rankings/half-point-ppr-te.php?export=xls",
        "K":   "https://www.fantasypros.com/nfl/rankings/k.php?export=xls",
        "DEF": "https://www.fantasypros.com/nfl/rankings/dst.php?export=xls",
    }
    frames = []
    for pos, url in positions.items():
        try:
            df = pd.read_excel(url)
            df["position"] = pos
            frames.append(df)
            time.sleep(0.3)
        except Exception:
            pass

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined.columns = [c.lower().strip().replace(" ", "_") for c in combined.columns]
    return combined


# ── Merge & Deduplicate ──────────────────────────────────────────────────────

def _normalize_name(name: str) -> str:
    """Lowercase, strip suffixes, remove punctuation for fuzzy matching."""
    import re
    name = str(name).lower().strip()
    name = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", name)
    name = re.sub(r"[^a-z ]", "", name)
    return " ".join(name.split())


def build_master_rankings(
    fp: pd.DataFrame,
    sleeper: pd.DataFrame,
    espn: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge all sources into a canonical player DataFrame.
    Assigns an overall composite rank.
    """

    # ── Normalize column names ──────────────────────────────────────────────
    def get_col(df, *candidates):
        for c in candidates:
            if c in df.columns:
                return c
        return None

    # Build base from Sleeper (has the most player metadata)
    base = sleeper.copy() if not sleeper.empty else pd.DataFrame()

    if base.empty:
        # fall back to FantasyPros
        base = fp.copy()
        base["player_id"] = base.get("sleeper_id", range(len(base)))
    else:
        base["name_key"] = base["player_name"].apply(_normalize_name)

    # ── Attach FantasyPros rank ─────────────────────────────────────────────
    if not fp.empty and "player_name" in fp.columns:
        fp2 = fp.copy()
        fp2["name_key"] = fp2["player_name"].apply(_normalize_name)
        rank_col = get_col(fp2, "fp_rank", "rank", "rk", "overall_rank")
        if rank_col:
            fp2 = fp2.rename(columns={rank_col: "fp_rank"})
        fp2 = fp2[["name_key"] + [c for c in ["fp_rank", "fp_adp"] if c in fp2.columns]]
        fp2 = fp2.drop_duplicates("name_key")
        if "name_key" in base.columns:
            base = base.merge(fp2, on="name_key", how="left")

    # ── Attach ESPN rank ────────────────────────────────────────────────────
    if not espn.empty and "player_name" in espn.columns:
        espn2 = espn.copy()
        espn2["name_key"] = espn2["player_name"].apply(_normalize_name)
        espn2 = espn2[["name_key"] + [c for c in ["espn_rank"] if c in espn2.columns]]
        espn2 = espn2.drop_duplicates("name_key")
        if "name_key" in base.columns:
            base = base.merge(espn2, on="name_key", how="left")

    # ── Filter to active / relevant players ────────────────────────────────
    if "status" in base.columns:
        base = base[base["status"].isin(["Active", "Inactive", ""])]

    # ── Create composite rank ───────────────────────────────────────────────
    rank_cols = [c for c in ["fp_rank", "espn_rank"] if c in base.columns]
    if rank_cols:
        # Average available ranks; missing = 999
        for c in rank_cols:
            base[c] = pd.to_numeric(base[c], errors="coerce")
        base["composite_rank"] = base[rank_cols].mean(axis=1).fillna(999)
    else:
        base["composite_rank"] = range(1, len(base) + 1)

    base = base.sort_values("composite_rank").reset_index(drop=True)
    base["overall_rank"] = base.index + 1

    # Ensure required columns exist
    for col in ["player_id", "sleeper_id", "fp_rank", "espn_rank", "age", "years_exp",
                "injury_status", "team"]:
        if col not in base.columns:
            base[col] = np.nan

    # Canonical player_id
    if "sleeper_id" in base.columns:
        fallback = base.index.astype(str).tolist()
        base["player_id"] = base["sleeper_id"].where(
            base["sleeper_id"].notna(), other=pd.Series(fallback, index=base.index)
        )
    else:
        base["player_id"] = base.index.astype(str)

    return base


# ── Public entry point ────────────────────────────────────────────────────────

def fetch_all_rankings(force_refresh: bool = False) -> pd.DataFrame:
    """
    Fetch rankings from all sources, merge, and cache.
    Returns a master DataFrame.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Use cache if fresh
    if not force_refresh and CACHE_FILE.exists():
        age = time.time() - CACHE_FILE.stat().st_mtime
        if age < CACHE_TTL:
            try:
                return pd.read_parquet(CACHE_FILE)
            except Exception:
                pass

    print("Fetching rankings from all sources…")
    sleeper = fetch_sleeper_players()
    print(f"  Sleeper: {len(sleeper)} players")

    fp = fetch_fantasypros()
    if fp.empty:
        print("  FantasyPros scrape failed, trying CSV backup…")
        fp = fetch_fantasypros_csv()
    print(f"  FantasyPros: {len(fp)} players")

    espn = fetch_espn_rankings()
    print(f"  ESPN: {len(espn)} players")

    master = build_master_rankings(fp, sleeper, espn)
    print(f"  Master board: {len(master)} players")

    master.to_parquet(CACHE_FILE, index=False)
    return master
