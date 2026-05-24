# 🏈 Fantasy Football Draft Dashboard

A personalized, interactive draft prep tool for your **14-team, Half-PPR Yahoo league** — optimized for **consistent, high-floor players**.

## Features

| Tab | What it does |
|-----|-------------|
| 📋 **Draft Board** | Full big board — mark players as yours ✅ or drafted by others 🚫 |
| 🏆 **My Team** | Live roster tracker + "what to draft next" recommendations |
| 🔍 **Player Analysis** | Week-by-week history, score distribution, player comparison |
| 📉 **Scarcity & VOR** | Value Over Replacement charts + Consistency vs. Scoring scatter |
| ⚙️ **Yahoo Settings** | Log in to pull exact league scoring rules |

## Data Sources

- **FantasyPros** — consensus half-PPR expert rankings (100+ analysts)
- **Sleeper API** — player metadata, injury status, ADP signal
- **ESPN** — positional ranks (unofficial API)
- **nfl_data_py / nflfastR** — 2021–2025 weekly stats for consistency metrics

## Consistency Metrics Explained

| Metric | Meaning |
|--------|---------|
| **Consistency Score** | 0-100 (higher = less week-to-week variance). `(1 - CV) × 100` |
| **Avg Bad Game (25th pct)** | What they usually score in a weaker game |
| **Avg Good Game (75th pct)** | What they usually score in a stronger game |
| **Bust %** | % of weeks below position-specific bad-game threshold |
| **Boom %** | % of weeks above elite threshold |

Historical metrics are recency-weighted, with 2025 carrying the most weight and each older season carrying less signal:
`2025=1.00`, `2024=0.90`, `2023=0.20`, `2022=0.10`, `2021=0.05`.

## Quick Start

```bash
cd ~/fantasy-draft-dashboard
bash setup.sh

# Then every time:
source .venv/bin/activate
streamlit run app.py
```

Open **http://localhost:8501** in your browser.

## Draft Style Presets

In the sidebar, the **Draft style** preset controls how much your rankings favor consistency versus expert-rank upside:
- **Boom/Bust Heavy** = chase upside and tolerate volatility
- **Upside Lean** = favor upside with some downside protection
- **Balanced** = blend expert rank and consistency evenly
- **Consistency Focused** = prioritize reliable weekly output
- **Safe Floor Heavy** = strongly favor stable players with fewer bad weeks

**Recommendation:** Start with **Consistency Focused** given your stated priority.

## Draft Workflow

1. Set your draft position (1-14) in the sidebar
2. As picks are made, click **🚫** on players taken by others
3. Click **✅** to add players to your team
4. Watch **My Team** tab for roster-needs recommendations
5. Use **Scarcity & VOR** to know when to pivot positions

## League Settings

| Setting | Value |
|---------|-------|
| Teams | 14 |
| Scoring | Half-PPR |
| Platform | Yahoo Fantasy |
| Roster | QB, RB, RB, WR, WR, TE, FLEX, DEF/ST, K + 7 bench |
| Total roster | 15 spots |

## Yahoo Login (Optional)

In the **⚙️ Yahoo Settings** tab, enter your Yahoo email + password to auto-pull your league's exact scoring rules. Requires Playwright (installed in setup).
