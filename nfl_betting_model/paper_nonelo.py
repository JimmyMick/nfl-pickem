"""Paper-trade ledger for the 'non-Elo substitute' variant of the top-1 play.

Motivation (validated on 2016-2025 walk-forward, see backtest_top1_nonelo.py):
the top-1 model-vs-market disagreement is only profitable on its NON-Elo-driven
plays. Elo-driven top-1 picks were dead money (~+0.1% ROI, 36% win), while
skipping them lifted ROI from ~+10% to ~+23% (bootstrap P(ROI>0)=99.9%).

This variant keeps one play per week but, when the week's biggest disagreement
is Elo-driven, backs the biggest NON-Elo disagreement instead (falling back to
the top-1 only if every game that week is Elo-driven). Tracked FORWARD alongside
the incumbent top-1 — 2026 is the clean out-of-sample scoreboard.

Reuses paper.py's ledger schema + settle/summary (path-generic); only the weekly
pick rule differs. Needs an ``elo_driven`` boolean column on the predict frame.
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

from nfl_betting_model import paper
from nfl_betting_model.cloud import ARTIFACT_DIR

NONELO_PAPER_FILE = "paper_nonelo_plays.csv"
NONELO_LEDGER_PATH = ARTIFACT_DIR / NONELO_PAPER_FILE
DEFAULT_STAKE = paper.DEFAULT_STAKE


def load_ledger(path: Path = NONELO_LEDGER_PATH) -> pd.DataFrame:
    return paper.load_ledger(path)


def settle(graded: pd.DataFrame, season: int,
           path: Path = NONELO_LEDGER_PATH) -> pd.DataFrame:
    return paper.settle(graded, season, path=path)


def summary(ledger: pd.DataFrame | None = None,
            path: Path = NONELO_LEDGER_PATH) -> dict:
    return paper.summary(ledger, path=path)


def log_week(target: pd.DataFrame, season: int, week: int,
             stake: float = DEFAULT_STAKE,
             path: Path = NONELO_LEDGER_PATH) -> dict | None:
    """Log the week's biggest NON-Elo-driven disagreement (substitute rule).

    Idempotent per (season, week). Requires an ``elo_driven`` column on
    ``target``; if it's missing this degrades to the plain top-1 pick.
    """
    if target is None or target.empty:
        return None
    ledger = load_ledger(path)
    existing = ledger[(ledger["season"] == season) & (ledger["week"] == week)]
    if not existing.empty:
        return existing.iloc[0].to_dict()

    t = target.assign(_abs=target["edge"].abs())
    if "elo_driven" in t.columns:
        t["_elo"] = t["elo_driven"].fillna(False).astype(bool)
    else:
        t["_elo"] = False
    t = t.sort_values(["_abs", "game_id"], ascending=[False, True])
    non_elo = t[~t["_elo"]]
    top = non_elo.iloc[0] if not non_elo.empty else t.iloc[0]

    bet_home = bool(top["edge"] > 0)
    model_side = top["home_team"] if bet_home else top["away_team"]
    price_ml = top.get("home_moneyline") if bet_home else top.get("away_moneyline")
    price_ml = float(price_ml) if pd.notna(price_ml) else np.nan
    spread_line = top.get("spread_line")
    spread_line = float(spread_line) if pd.notna(spread_line) else np.nan

    play = {
        "season": int(season), "week": int(week), "game_id": str(top["game_id"]),
        "away_team": top["away_team"], "home_team": top["home_team"],
        "model_side": model_side, "bet_home": bet_home,
        "model_home_prob": round(float(top["model_home_prob"]), 4),
        "market_home_prob": round(float(top["market_home_prob"]), 4),
        "edge": round(float(top["edge"]), 4),
        "price_ml": price_ml, "stake": float(stake),
        "result": "no_price" if np.isnan(price_ml) else "open",
        "profit": np.nan,
        "spread_line": spread_line,
        "spread_result": "no_line" if np.isnan(spread_line) else "open",
        "spread_profit": np.nan,
        "logged_at": paper._now(), "settled_at": np.nan,
    }
    ledger = pd.concat([ledger, pd.DataFrame([play])], ignore_index=True)
    paper._save(ledger, path)
    return play


def render(season: int, week: int, path: Path = NONELO_LEDGER_PATH) -> list[str]:
    """Markdown block for the grade report — moneyline record for this variant."""
    ledger = load_ledger(path)
    if ledger.empty:
        return []
    s = summary(ledger, path=path)
    lines = ["", "## 🧪 Paper play — non-Elo substitute (out-of-sample tracker)", ""]
    rec = f"{s['wins']}-{s['losses']}"
    roi = f"{s['roi']:+.1%}" if s["bets"] else "—"
    lines.append(
        f"**{rec} settled · {s['profit']:+.1f}u on {s['staked']:.0f}u staked · "
        f"ROI {roi}** ({s['open']} open)  ·  flat {DEFAULT_STAKE:.0f}u, the week's "
        f"biggest disagreement whose driver isn't Elo (skips the Elo-driven top-1). "
        f"Validated in backtest (~+23% ROI) but tracked forward to confirm.")
    lines.append("")
    lines.append("| Week | Play | Edge | Price | Result |")
    lines.append("|---|---|---|---|---|")
    for _, r in ledger[ledger["season"] == season].sort_values("week").iterrows():
        matchup = f"{r['away_team']} @ {r['home_team']}"
        edge = f"+{abs(float(r['edge'])):.0%}" if pd.notna(r["edge"]) else "—"
        price = f"{float(r['price_ml']):+.0f}" if pd.notna(r["price_ml"]) else "—"
        if r["result"] == "win":
            res = f"✓ +{float(r['profit']):.1f}u"
        elif r["result"] == "loss":
            res = f"✗ {float(r['profit']):.1f}u"
        elif r["result"] == "no_price":
            res = "no price"
        else:
            res = "open"
        lines.append(f"| {int(r['week'])} | {r['model_side']} ({matchup}) | {edge} | {price} | {res} |")
    return lines
