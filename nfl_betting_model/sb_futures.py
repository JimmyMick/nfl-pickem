"""Vegas Super Bowl futures — a static, dated snapshot for side-by-side compare.

We don't ingest futures (nflverse carries game spreads/moneylines, not season
championship markets), and the key-free cloud app can't fetch, so the sportsbook
Super Bowl odds are baked here as a small table and shown next to our model's
simulated Super Bowl %. It's a *reference column*, not a live feed.

Odds are American (all positive here — long championship prices). ``sb_market_probs``
converts them to implied probabilities and, by default, **de-vigs**: raw futures
imply far more than 100% total (the book's overround — ~22% here), so we normalize
to sum to 1.0 so the numbers compare apples-to-apples with our sim, where exactly
one team wins.

To refresh: replace ``SB_FUTURES`` with a current book's table and bump
``AS_OF`` / ``SOURCE``. Team keys are nflverse abbreviations (Rams = ``LA``).
"""

from __future__ import annotations

AS_OF = "2026-09-08"
SOURCE = "DraftKings (via SI.com)"

# nflverse abbr -> American odds to win Super Bowl LXI.
SB_FUTURES: dict[str, int] = {
    "LA": 550, "BUF": 1000, "BAL": 1000, "SEA": 1100, "PHI": 1600, "NE": 1600,
    "KC": 1600, "LAC": 1700, "HOU": 1800, "GB": 1800, "SF": 1900, "DET": 1900,
    "DEN": 2000, "CIN": 2000, "CHI": 2400, "DAL": 2500, "JAX": 3000, "PIT": 5000,
    "MIN": 5000, "TB": 5500, "WAS": 6000, "IND": 6000, "NYG": 7000, "NO": 9000,
    "CAR": 9000, "TEN": 13000, "ATL": 13000, "LV": 15000, "NYJ": 20000,
    "CLE": 20000, "MIA": 35000, "ARI": 50000,
}


def implied_prob(american: float) -> float:
    """Implied win probability from American odds (with the book's vig baked in)."""
    if american >= 0:
        return 100.0 / (american + 100.0)
    return -american / (-american + 100.0)


def sb_market_probs(devig: bool = True) -> dict[str, float]:
    """Team -> implied Super Bowl probability. De-vigged (normalized to 1.0) by
    default so it's comparable to the sim's win-probabilities."""
    raw = {t: implied_prob(o) for t, o in SB_FUTURES.items()}
    if not devig:
        return raw
    total = sum(raw.values())
    return {t: p / total for t, p in raw.items()} if total else raw
