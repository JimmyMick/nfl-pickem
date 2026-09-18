"""Cloud (read-only) dashboard for the NFL model — Streamlit Community Cloud.

Renders the artifacts exported by the local weekly runs (see
``nfl_betting_model/cloud.py``): the pick'em leaderboard, the season tracker, and
the latest weekly preview. It does **no** training and never fetches data, so it
runs comfortably in the free tier's ~1 GB. The full, live-training app is
``dashboard.py`` (run locally).

Deploy: point Streamlit Community Cloud at this repo and this file
(``streamlit_app.py``). Dependencies come from ``requirements.txt`` (the light
set — pandas / numpy / sklearn / altair / streamlit).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
from sklearn.metrics import brier_score_loss, log_loss

from nfl_betting_model import (
    cloud, paper as paper_mod, paper_spread as paper_spread_mod,
    picks as picks_mod, sb_futures, submit as submit_mod, teams as teams_mod)

st.set_page_config(page_title="NFL model — leaderboard", page_icon="🏈",
                   layout="wide")


# ── Team-logo helpers (small helmet icons next to abbreviations) ───────────────
def _logo_col(label: str = "") -> "st.column_config.ImageColumn":
    return st.column_config.ImageColumn(label, width="small")


def team_logos(abbrs) -> pd.Series:
    """Map a series/list of team abbreviations to their logo URLs."""
    return pd.Series(abbrs).map(teams_mod.logo).values


def matchup_frame(away, home) -> dict:
    """Columns for an ``away @ home`` row: away logo/abbr then home logo/abbr."""
    return {"": team_logos(away), "Away": list(away),
            " ": team_logos(home), "Home": list(home)}


def logo_cfg(*keys) -> dict:
    """column_config mapping each (whitespace) key to a small logo image column."""
    return {k: _logo_col() for k in keys}


MATCHUP_CFG = logo_cfg("", " ")


# ── Optional Descope (OIDC) sign-in gate ──────────────────────────────────────
# Uses Streamlit's native OIDC login. Entirely inert until an [auth] block is
# configured in the app's secrets, so the app keeps working open before setup.
# Configure a provider named [auth.descope] and (optionally) an
# [access] allowed_emails list to restrict who gets in.
def _auth_configured() -> bool:
    try:
        return "auth" in st.secrets
    except Exception:
        return False


def _require_login() -> None:
    if not _auth_configured():
        return  # open mode — no auth secrets configured yet
    if not st.user.is_logged_in:
        st.title("🏈 NFL model — pick'em & tracker")
        st.write("This leaderboard is private. Sign in to continue.")
        st.button("Log in with Descope", type="primary",
                  on_click=st.login, args=["descope"])
        st.stop()

    email = getattr(st.user, "email", None)
    try:
        allowed = list(st.secrets.get("access", {}).get("allowed_emails", []))
    except Exception:
        allowed = []
    if allowed and email not in allowed:
        st.error(f"{email or 'This account'} isn't on the access list for this app.")
        st.button("Log out", on_click=st.logout)
        st.stop()

    with st.sidebar:
        st.caption(f"Signed in as {getattr(st.user, 'name', None) or email}")
        st.button("Log out", on_click=st.logout)


# ── Small grade helpers (reimplemented here to keep cloud imports light — the
#    originals live in grade.py, which pulls in the heavy training stack). ──────
def _record(correct: pd.Series) -> str:
    w = int(correct.sum())
    n = len(correct)
    return f"{w}-{n - w} ({w / n:.0%})" if n else "0-0 (—)"


def _prob_str(home_team: str, away_team: str, home_prob: float) -> str:
    if home_prob >= 0.5:
        return f"{home_team} {home_prob:.0%}"
    return f"{away_team} {1 - home_prob:.0%}"


# A "short" underdog spread — small enough that taking the points is a live
# decision when the model also leans that dog. From the paper-play ATS study,
# the model's disagreement dogs cluster at +1.5 to +3.
SHORT_DOG_PTS = 3.0

# Light amber tint (low alpha so it reads on both light and dark themes) for
# rows where the model favours the market underdog.
DOG_ROW_STYLE = "background-color: rgba(240, 173, 78, 0.16)"


def _model_favors_dog(df: pd.DataFrame, min_edge: float = 0.005) -> pd.Series:
    """True where the model's pick is the market's underdog — i.e. model and
    market land on opposite sides of 50%, by more than rounding noise."""
    model_home = df["model_home_prob"] >= 0.5
    market_home = df["market_home_prob"] >= 0.5
    disagree = model_home != market_home
    real = (df["model_home_prob"] - df["market_home_prob"]).abs() >= min_edge
    return disagree & real


def dog_spread_label(spread_line: float, home_team: str, away_team: str,
                     model_home_prob: float) -> str:
    """The market underdog's number, flagged 🎯 when the model also leans that
    dog and the spread is short (≤ SHORT_DOG_PTS) — i.e. take-the-points territory."""
    if pd.isna(spread_line):
        return "—"
    if spread_line == 0:
        return "PK"
    # nflverse spread_line is home-relative (positive = home favored), so the
    # underdog is the away team when it's positive, the home team when negative.
    dog = away_team if spread_line > 0 else home_team
    pts = abs(float(spread_line))
    model_pick = home_team if model_home_prob >= 0.5 else away_team
    flag = "  🎯" if (model_pick == dog and pts <= SHORT_DOG_PTS) else ""
    return f"{dog} +{pts:g}{flag}"


def _calibration(g: pd.DataFrame) -> tuple[float, float, float, float]:
    y = g["home_win"].to_numpy()
    pm = g["model_home_prob"].to_numpy()
    m_ll = log_loss(y, pm, labels=[0, 1])
    m_br = brier_score_loss(y, pm)
    mkt = g["market_home_prob"].to_numpy()
    mask = ~np.isnan(mkt)
    if mask.sum():
        k_ll = log_loss(y[mask], mkt[mask], labels=[0, 1])
        k_br = brier_score_loss(y[mask], mkt[mask])
    else:
        k_ll = k_br = float("nan")
    return m_ll, m_br, k_ll, k_br


def _top_picks(g: pd.DataFrame) -> pd.DataFrame:
    """The model's most-confident pick in each week, with the actual result."""
    conf = g["model_home_prob"].apply(lambda p: max(p, 1 - p))
    g = g.assign(_conf=conf)
    rows = []
    for wk, grp in g.groupby("week"):
        r = grp.loc[grp["_conf"].idxmax()]
        rows.append({
            "Week": str(int(wk)),
            **matchup_frame([r["away_team"]], [r["home_team"]]),
            "  ": teams_mod.logo(r["model_pick"]), "Top pick": r["model_pick"],
            "Confidence": f"{r['_conf']:.0%}",
            "   ": teams_mod.logo(r["winner"]) if pd.notna(r["winner"]) else None,
            "Actual": r["winner"],
            "Result": "✓" if r["model_correct"] else "✗",
        })
    return pd.DataFrame(rows)


def _topn_correct(g: pd.DataFrame, n: int) -> pd.Series:
    """model_correct for the n most-confident games in each week."""
    conf = g["model_home_prob"].apply(lambda p: max(p, 1 - p))
    g = g.assign(_conf=conf)
    parts = [grp.sort_values("_conf", ascending=False).head(n)
             for _, grp in g.groupby("week")]
    return pd.concat(parts)["model_correct"]


def _disagreement_bet(row) -> tuple[str, bool]:
    """The model's side of a model-vs-market gap (the team the model is higher on
    than the market — the paper play), and whether it won straight up."""
    bet_home = (row["model_home_prob"] - row["market_home_prob"]) >= 0
    team = row["home_team"] if bet_home else row["away_team"]
    won = bool(row["winner"] == team) if pd.notna(row.get("winner")) else False
    return team, won


def _top_disagreements(g: pd.DataFrame) -> pd.DataFrame:
    """Each week's single biggest model-vs-market gap — the model's side (the
    paper play) vs the actual result."""
    g = g.assign(_edge=(g["model_home_prob"] - g["market_home_prob"]).abs())
    rows = []
    for wk, grp in g.groupby("week"):
        r = grp.loc[grp["_edge"].idxmax()]
        team, won = _disagreement_bet(r)
        rows.append({
            "Week": str(int(wk)),
            **matchup_frame([r["away_team"]], [r["home_team"]]),
            "  ": teams_mod.logo(team), "Model side": team,
            "Edge": f"+{r['_edge']:.0%}",
            "   ": teams_mod.logo(r["winner"]) if pd.notna(r["winner"]) else None,
            "Actual": r["winner"],
            "Result": "✓" if won else "✗",
        })
    return pd.DataFrame(rows)


def _topn_disagreement_correct(g: pd.DataFrame, n: int) -> pd.Series:
    """Won/lost for the model's side of the n biggest gaps in each week."""
    g = g.assign(_edge=(g["model_home_prob"] - g["market_home_prob"]).abs())
    parts = []
    for _, grp in g.groupby("week"):
        top = grp.sort_values("_edge", ascending=False).head(n)
        parts.append(top.apply(lambda r: _disagreement_bet(r)[1], axis=1))
    return pd.concat(parts)


def _weekly_summary(g: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for wk, grp in g.groupby("week"):
        rows.append({"Week": str(int(wk)), "Games": len(grp),
                     "Model": _record(grp["model_correct"]),
                     "Market": _record(grp["market_correct"])})
    out = pd.DataFrame(rows)
    out.loc[len(out)] = {"Week": "Season", "Games": len(g),
                         "Model": _record(g["model_correct"]),
                         "Market": _record(g["market_correct"])}
    return out


# ── Tab renderers ─────────────────────────────────────────────────────────────
def render_leaderboard(scored: pd.DataFrame | None, graded: pd.DataFrame) -> None:
    st.caption("👋 New here? The **📖 Guide** tab covers how to enter your picks "
               "and read everything below.")
    if scored is None or scored.empty:
        st.info("No picks recorded yet. Once the Urban Platform Experts submit picks and a week is "
                "graded, the leaderboard populates here — each expert scored "
                "against the model on the games they picked.")
        return

    board = picks_mod.leaderboard(scored, graded)
    leader = board.iloc[0]

    st.subheader("Standings")
    cols = st.columns(min(len(board), 5))
    for col, (_, r) in zip(cols, board.iterrows()):
        col.metric(r["Player"], r["Record"], f"vs model {r['vs Model']}",
                   delta_color="off")
    st.caption(f"🏆 Leading: **{leader['Player']}** ({leader['Record']}). "
               "“vs Model” = an expert’s accuracy minus the model’s over the same "
               "games they picked.")
    st.dataframe(board, width="stretch", hide_index=True)

    chart_df = board.copy()
    chart_df["AccPct"] = scored.groupby("player")["correct"].mean().reindex(
        chart_df["Player"]).to_numpy() * 100
    bar = (
        alt.Chart(chart_df).mark_bar().encode(
            x=alt.X("AccPct:Q", title="Straight-up accuracy (%)"),
            y=alt.Y("Player:N", sort="-x", title=None),
            color=alt.Color("AccPct:Q", scale=alt.Scale(scheme="greens"),
                            legend=None),
            tooltip=["Player", "Record", "vs Model", "Brier", "Log loss"],
        ).properties(height=max(140, 34 * len(chart_df)))
    )
    st.altair_chart(bar, width="stretch")

    last_week = int(scored["week"].max())
    this_week = scored[scored["week"] == last_week]
    if not this_week.empty:
        st.subheader(f"Week {last_week} — game by game")
        wk = this_week.assign(
            Matchup=this_week["away_team"] + " @ " + this_week["home_team"],
            Result=this_week.apply(
                lambda r: f"{r['pick']} {'✓' if r['correct'] else '✗'}", axis=1))
        pivot = wk.pivot_table(index=["Matchup"], columns="player",
                               values="Result", aggfunc="first").reset_index()
        st.dataframe(pivot, width="stretch", hide_index=True)

        # AI expert reasoning (any pick that carried a written rationale).
        if "rationale" in this_week.columns:
            rat = this_week[this_week["rationale"].notna()
                            & this_week["rationale"].astype(str).str.strip().ne("")]
            if not rat.empty:
                with st.expander("🤖 AI expert — why it picked what it did"):
                    rr = rat.assign(
                        Matchup=rat["away_team"] + " @ " + rat["home_team"],
                        Pick=rat.apply(
                            lambda r: f"{r['pick']} {'✓' if r['correct'] else '✗'}",
                            axis=1)).rename(columns={"player": "Player",
                                                     "rationale": "Rationale"})
                    st.dataframe(rr[["Player", "Matchup", "Pick", "Rationale"]],
                                 width="stretch", hide_index=True)
    st.caption("Brier / log loss use only picks that carried a confidence.")


def render_tracker(graded: pd.DataFrame) -> None:
    m_acc = graded["model_correct"].mean()
    k_acc = graded["market_correct"].mean()
    m_ll, m_br, k_ll, k_br = _calibration(graded)

    st.subheader(f"Season-to-date — through Week {int(graded['week'].max())}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Model straight-up", _record(graded["model_correct"]))
    c2.metric("Market straight-up", _record(graded["market_correct"]))
    c3.metric("vs market", f"{m_acc - k_acc:+.0%}")
    c4, c5 = st.columns(2)
    c4.metric("Model calibration", f"logloss {m_ll:.3f}", f"Brier {m_br:.3f}",
              delta_color="off")
    c5.metric("Market calibration", f"logloss {k_ll:.3f}", f"Brier {k_br:.3f}",
              delta_color="off")

    st.subheader("Accuracy ticker (cumulative)")
    wk = graded.sort_values(["week"]).copy()
    wk["Model"] = wk["model_correct"].expanding().mean()
    wk["Market"] = wk["market_correct"].expanding().mean()
    cum = wk.groupby("week")[["Model", "Market"]].last().reset_index()
    long = cum.melt("week", var_name="Series", value_name="Accuracy")
    line = (
        alt.Chart(long).mark_line(point=True).encode(
            x=alt.X("week:O", title="Week"),
            y=alt.Y("Accuracy:Q", scale=alt.Scale(zero=False),
                    axis=alt.Axis(format="%")),
            color=alt.Color("Series:N", scale=alt.Scale(
                domain=["Model", "Market"], range=["#1f77b4", "#999999"])),
            tooltip=["week", "Series", alt.Tooltip("Accuracy:Q", format=".1%")],
        ).properties(height=320)
    )
    st.altair_chart(line, width="stretch")

    st.subheader("Biggest model-vs-market disagreements (paper play)")
    dis = _top_disagreements(graded)
    g1, g3 = st.columns(2)
    g1.metric("Biggest gap record", _record(dis["Result"] == "✓"))
    g3.metric("Top-3 gaps record", _record(_topn_disagreement_correct(graded, 3)))
    st.dataframe(dis, width="stretch", hide_index=True,
                 column_config=logo_cfg("", " ", "  ", "   "))
    st.caption("Each week's single largest model-vs-market gap — we back the "
               "model's side (the paper play) and track how it ended up. The "
               "Top-3 record pools the model's side of the three biggest gaps "
               "each week.")

    st.subheader("Top pick of the week (most confident)")
    top = _top_picks(graded)
    t1, t3 = st.columns(2)
    t1.metric("Top pick record", _record(top["Result"] == "✓"))
    t3.metric("Top-3 picks record", _record(_topn_correct(graded, 3)))
    st.dataframe(top, width="stretch", hide_index=True,
                 column_config=logo_cfg("", " ", "  ", "   "))
    st.caption("Each week's single highest-confidence model pick vs. the actual "
               "result — the model's “lock of the week.” The Top-3 record pools "
               "the three most-confident games each week.")

    st.subheader("Week-by-week")
    st.dataframe(_weekly_summary(graded), width="stretch", hide_index=True)
    st.caption("Scorekeeping companion to the preview. Market-grade calibration "
               "is expected — the model is a forecaster, not a beater.")


# A sub-0.5% edge rounds to 0% — the model and market agree and the sign is
# noise, so render a dash instead of a spurious "TEAM +0%". (Mirrors
# predict.edge_label; kept local so the cloud app avoids the heavy predict import.)
_EDGE_ZERO = 0.005


def _edge_label(edge: float, home_team: str, away_team: str) -> str:
    if pd.isna(edge) or abs(edge) < _EDGE_ZERO:
        return "—"
    side = home_team if edge > 0 else away_team
    return f"{side} +{abs(edge):.0%}"


def render_preview(preview: pd.DataFrame) -> None:
    df = preview.copy()
    df["fav"] = np.where(df["edge"] > 0, df["home_team"], df["away_team"])
    by_edge = df.reindex(df["edge"].abs().sort_values(ascending=False).index)

    st.subheader("Biggest model-vs-market disagreements")
    for col, (_, r) in zip(st.columns(3), by_edge.head(3).iterrows()):
        col.metric(f"{r['away_team']} @ {r['home_team']}",
                   f"{r['fav']} +{abs(r['edge']):.0%}", r["driver"],
                   delta_color="off")

    st.subheader("Slate")
    conf = df["model_home_prob"].apply(lambda p: max(p, 1 - p))
    bp = df.reindex(conf.sort_values(ascending=False).index).copy()
    bp["Model"] = bp.apply(
        lambda r: _prob_str(r["home_team"], r["away_team"], r["model_home_prob"]), axis=1)
    bp["Market"] = bp.apply(
        lambda r: _prob_str(r["home_team"], r["away_team"], r["market_home_prob"]), axis=1)
    bp["Edge"] = bp.apply(
        lambda r: _edge_label(r["edge"], r["home_team"], r["away_team"]), axis=1)
    has_spread = "spread_line" in bp.columns
    cols = {
        **matchup_frame(bp["away_team"], bp["home_team"]),
        "Model": bp["Model"].values, "Market": bp["Market"].values,
        "Edge": bp["Edge"].values,
    }
    if has_spread:
        cols["Spread"] = bp.apply(
            lambda r: dog_spread_label(r["spread_line"], r["home_team"],
                                       r["away_team"], r["model_home_prob"]),
            axis=1).values
    cols["Key driver"] = bp["driver"].values
    show = pd.DataFrame(cols)
    # Lightly tint rows where the model favours the market underdog (its pick is
    # the opposite side from the market's — i.e. it likes a live dog >50%).
    dog_mask = _model_favors_dog(bp).to_numpy()
    styler = show.style.apply(
        lambda row: [DOG_ROW_STYLE if dog_mask[row.name] else ""] * len(row),
        axis=1)
    st.dataframe(styler, width="stretch", hide_index=True,
                 column_config=MATCHUP_CFG)
    st.caption("Rows tinted 🟡 = the **model favours the underdog** (its pick is "
               "the market's dog). **Edge** = the side the model values *more than "
               "the market prices it* — a mispricing, not a winner pick. It can "
               "name the underdog even when the model still expects the favourite "
               "to win (it just rates the favourite lower than Vegas). **Spread** "
               "shows the underdog's points; a **🎯** marks a *short dog the model "
               "also leans* (≤ 3 pts) — the take-the-points spot from the Paper "
               "Play study. Preview tool, not a betting signal.")


def _schedule_rows(sched: pd.DataFrame, tz: "ZoneInfo | None" = None) -> pd.DataFrame:
    """Shape a raw schedule frame into a display table (Date / Matchup / Result).

    ``tz`` (the viewer's timezone) localizes the kickoff time in the Date column;
    without a gametime it falls back to the date alone.
    """
    tz = tz or _ET
    df = sched.copy()
    df["week"] = pd.to_numeric(df["week"], errors="coerce").astype("Int64")
    gt = df.get("gametime")
    df["Date"] = [
        _kickoff_label(gd, gt.iloc[i] if gt is not None else None, tz)
        for i, gd in enumerate(df.get("gameday"))]
    df["Matchup"] = df["away_team"].astype(str) + " @ " + df["home_team"].astype(str)

    aw = pd.to_numeric(df.get("away_score"), errors="coerce")
    hm = pd.to_numeric(df.get("home_score"), errors="coerce")

    def _result(r) -> str:
        a, h = aw.get(r.name), hm.get(r.name)
        if pd.isna(a) or pd.isna(h):
            return "—"
        winner = r["home_team"] if h > a else r["away_team"] if a > h else "Tie"
        return f"{r['away_team']} {int(a)}–{int(h)} {r['home_team']}  ✓ {winner}"

    df["Result"] = df.apply(_result, axis=1)
    played = aw.notna() & hm.notna()

    spread = pd.to_numeric(df.get("spread_line"), errors="coerce")
    total = pd.to_numeric(df.get("total_line"), errors="coerce")
    away_ml = pd.to_numeric(df.get("away_moneyline"), errors="coerce")
    home_ml = pd.to_numeric(df.get("home_moneyline"), errors="coerce")

    def _spread(r) -> str:
        s = spread.get(r.name)
        if pd.isna(s):
            return "—"
        if s > 0:      # nflverse: positive spread_line = home favored
            return f"{r['home_team']} -{s:g}"
        if s < 0:
            return f"{r['away_team']} -{abs(s):g}"
        return "PK"

    def _ml(v) -> str:
        if pd.isna(v):
            return "—"
        return f"{'+' if v > 0 else ''}{int(v)}"

    df["Spread"] = df.apply(_spread, axis=1)
    df["O/U"] = total.map(lambda v: "—" if pd.isna(v) else f"{v:g}")
    df["Moneyline"] = [
        "—" if pd.isna(a) and pd.isna(h)
        else f"{r.away_team} {_ml(a)} · {r.home_team} {_ml(h)}"
        for (a, h), (_, r) in zip(zip(away_ml, home_ml), df.iterrows())
    ]
    return df, played


def render_schedule(sched: pd.DataFrame | None, season) -> None:
    """Full-season matchup schedule, filterable by week (defaults to the next
    unplayed week)."""
    st.subheader(f"{season} schedule" if season else "Schedule")
    if sched is None or sched.empty:
        st.info("Schedule hasn't been published yet.")
        return

    tz = _user_tz()
    df, played = _schedule_rows(sched, tz)
    weeks = sorted(int(w) for w in df["week"].dropna().unique())
    upcoming = [w for w in weeks if not played[df["week"] == w].all()]
    default_week = upcoming[0] if upcoming else (weeks[-1] if weeks else 1)

    labels = ["All weeks"] + [f"Week {w}" for w in weeks]
    default_label = f"Week {default_week}" if default_week in weeks else "All weeks"
    choice = st.selectbox("Week", labels, index=labels.index(default_label))

    view = df if choice == "All weeks" else df[df["week"] == int(choice.split()[1])]
    show = pd.DataFrame({
        "Wk": view["week"].values, "Date": view["Date"].values,
        **matchup_frame(view["away_team"], view["home_team"]),
        "Spread": view["Spread"].values, "O/U": view["O/U"].values,
        "Moneyline": view["Moneyline"].values,
        "Result": view["Result"].values,
    })
    st.dataframe(show, width="stretch", hide_index=True, column_config={
        **MATCHUP_CFG,
        "Date": st.column_config.TextColumn("Date", width="medium"),
        "Moneyline": st.column_config.TextColumn("Moneyline", width="medium"),
        "Result": st.column_config.TextColumn("Result", width="large"),
    })
    n_played = int(played[view.index].sum())
    tzname = dt.datetime.now(tz).strftime("%Z") or "ET"
    st.caption(f"{len(view)} games · {n_played} played · kickoff times in **your "
               f"timezone ({tzname})** · odds are the latest published market line "
               "· results fill in as the weekly runs refresh.")


def render_playoff_odds(sim, sim_history, meta, season, sim_market=None) -> None:
    """Monte Carlo playoff-odds projection + week-to-week trend."""
    through = meta.get("sim_through_week")
    when = "preseason" if through in (0, None) else f"through Week {int(through)}"
    st.subheader(f"Playoff odds — {season} ({when})")
    if sim is None or sim.empty:
        st.info("No simulation published yet.")
        return

    source = sim
    market_on = False
    if sim_market is not None and not sim_market.empty:
        w = meta.get("sim_market_weight", 0.5)
        view = st.radio(
            "Ratings", ["Pure model", f"Market-anchored ({int(w * 100)}%)"],
            horizontal=True, index=0,
            help="Pure model = our Elo/EPA/QB ratings. Market-anchored blends "
                 "them toward a rating fit from the posted point spreads — the "
                 "market's forward-looking view (offseason moves, QB, coaching) "
                 "that our backward-looking Elo hasn't caught up to yet.")
        market_on = view.startswith("Market")
        if market_on:
            source = sim_market
            st.caption(f"🎯 **Market-anchored** — team ratings blended "
                       f"{int(w * 100)}% toward the spread-implied market prior. "
                       "This pulls forward-looking teams (offseason risers) up "
                       "toward where the futures market has them.")

    df = source.sort_values("win_sb", ascending=False).reset_index(drop=True)
    vegas = sb_futures.sb_market_probs()
    # Keep the numbers numeric (percentages as 0–100) so header-click sorting is
    # numeric, not lexical; NumberColumn handles the % display.
    show = pd.DataFrame({
        "": team_logos(df["team"]),
        "Team": df["team"].values, "Conf": df["conference"].values,
        "Proj W": df["proj_wins"].values,
        "Playoffs": (df["make_playoffs"] * 100).values,
        "Division": (df["win_division"] * 100).values,
        "#1 Seed": (df["top_seed"] * 100).values,
        "Conf ": (df["win_conference"] * 100).values,
        "Super Bowl": (df["win_sb"] * 100).values,
        "Vegas SB": [vegas[t] * 100 if t in vegas else None for t in df["team"]],
    })
    pct = lambda label: st.column_config.NumberColumn(label, format="%.0f%%")
    st.dataframe(show, width="stretch", hide_index=True, column_config={
        "": _logo_col(),
        "Proj W": st.column_config.NumberColumn("Proj W", format="%.1f"),
        "Playoffs": pct("Playoffs"), "Division": pct("Division"),
        "#1 Seed": pct("#1 Seed"), "Conf ": pct("Conf "),
        "Super Bowl": pct("Super Bowl"), "Vegas SB": pct("Vegas SB"),
    })
    st.caption(f"**Vegas SB** = de-vigged sportsbook Super Bowl futures "
               f"({sb_futures.SOURCE}, as of {sb_futures.AS_OF}) — a fixed market "
               "reference to compare our model's number against.")

    top = df.head(12)
    chart = alt.Chart(top).mark_bar().encode(
        x=alt.X("win_sb:Q", title="Super Bowl odds", axis=alt.Axis(format="%")),
        y=alt.Y("team:N", sort="-x", title=None),
        color=alt.Color("conference:N", legend=None),
        tooltip=["team", alt.Tooltip("win_sb:Q", format=".1%")],
    ).properties(height=320)
    st.altair_chart(chart, use_container_width=True)

    # Week-to-week trend once more than one snapshot exists (pure-model history).
    if not market_on and sim_history is not None and not sim_history.empty:
        hist = sim_history[sim_history["season"] == season]
        if hist["through_week"].nunique() > 1:
            st.subheader("Week-to-week trend")
            team = st.selectbox("Team", sorted(hist["team"].unique()))
            th = hist[hist["team"] == team]
            melt = th.melt(id_vars="through_week",
                           value_vars=["make_playoffs", "win_sb"],
                           var_name="metric", value_name="prob")
            line = alt.Chart(melt).mark_line(point=True).encode(
                x=alt.X("through_week:Q", title="through week"),
                y=alt.Y("prob:Q", axis=alt.Axis(format="%")),
                color="metric:N",
            ).properties(height=260)
            st.altair_chart(line, use_container_width=True)

    st.caption("Monte Carlo of the rest of the season. Ratings held fixed across "
               "each sim; playoff games use current (optionally market-blended) "
               "Elo + home field. Our own Elo is backward-looking (it reverts "
               "only ~⅓ each offseason), so early on it can lag the market on "
               "teams that improved in the offseason — the **Market-anchored** "
               "view shows what happens as you trust the spreads more. "
               "**Just for fun — not a betting product.**")


def _matchup_segments(unit: pd.DataFrame, matchups) -> "pd.DataFrame | None":
    """Two rows per game (both teams' coords, shared game id) so a line connects
    each of this week's matchups on the scatter."""
    if matchups is None or matchups.empty:
        return None
    coord = unit.set_index("team")[["off_elo", "def_elo"]]
    rows = []
    for i, (_, g) in enumerate(matchups.iterrows()):
        a, h = g.get("away_team"), g.get("home_team")
        if a in coord.index and h in coord.index:
            for t in (a, h):
                rows.append({"g": i, "team": t, "matchup": f"{a} @ {h}",
                             "off_elo": float(coord.loc[t, "off_elo"]),
                             "def_elo": float(coord.loc[t, "def_elo"])})
    return pd.DataFrame(rows) if rows else None


def render_unit_elo(unit, matchups=None) -> None:
    """Offense vs defense Elo — scatter (both axes) + a sortable table.

    Reads the exported unit_elo artifact; no computation here. If ``matchups``
    (this week's slate) is given, a light line connects each pair of opponents.
    """
    st.subheader("Unit Elo — offense vs defense")
    if unit is None or unit.empty:
        st.info("Unit ratings haven't been published yet.")
        return
    st.caption("Each team split into an **offense** rating (points it scores) "
               "and a **defense** rating (points it prevents), opponent-adjusted, "
               "on the ~1500 Elo scale. **1500 = league average.**")

    base = 1500.0
    layers = [
        alt.Chart(pd.DataFrame({"x": [base]})).mark_rule(
            strokeDash=[4, 4], color="gray").encode(x="x:Q"),
        alt.Chart(pd.DataFrame({"y": [base]})).mark_rule(
            strokeDash=[4, 4], color="gray").encode(y="y:Q"),
    ]
    seg = _matchup_segments(unit, matchups)
    if seg is not None:
        layers.append(alt.Chart(seg).mark_line(
            color="#888", opacity=0.4, strokeWidth=1).encode(
            x="off_elo:Q", y="def_elo:Q", detail="g:N",
            tooltip=[alt.Tooltip("matchup:N", title="This week")]))
    layers.append(alt.Chart(unit).mark_circle(size=90, opacity=0.7).encode(
        x=alt.X("off_elo:Q", title="Offense Elo  →  (better)",
                scale=alt.Scale(zero=False)),
        y=alt.Y("def_elo:Q", title="Defense Elo  →  (better)",
                scale=alt.Scale(zero=False)),
        tooltip=["team",
                 alt.Tooltip("off_elo:Q", title="Off Elo", format=".0f"),
                 alt.Tooltip("def_elo:Q", title="Def Elo", format=".0f")]))
    layers.append(alt.Chart(unit).mark_text(dy=-11, fontSize=10).encode(
        x="off_elo:Q", y="def_elo:Q", text="team:N"))
    st.altair_chart(alt.layer(*layers).properties(height=460),
                    use_container_width=True)
    hint = (" · gray lines connect **this week's matchups** (a long line = a big "
            "unit mismatch)" if seg is not None else "")
    st.caption("Top-right = strong on **both** sides · bottom-left = weak on both "
               "· top-left = defense-carried · bottom-right = shootout team" + hint
               + ".")

    d = unit.sort_values("off_elo", ascending=False)
    show = pd.DataFrame({
        "": team_logos(d["team"]), "Team": d["team"].values,
        "Off Elo": d["off_elo"].round(0).values,
        "Def Elo": d["def_elo"].round(0).values,
        "Off (pts vs avg)": d["off_pts"].round(1).values,
        "Def (pts vs avg)": d["def_pts"].round(1).values,
    })
    num = lambda lbl, fmt: st.column_config.NumberColumn(lbl, format=fmt)
    st.dataframe(show, width="stretch", hide_index=True, column_config={
        "": _logo_col(),
        "Off Elo": num("Off Elo", "%.0f"), "Def Elo": num("Def Elo", "%.0f"),
        "Off (pts vs avg)": num("Off (pts vs avg)", "%+.1f"),
        "Def (pts vs avg)": num("Def (pts vs avg)", "%+.1f"),
    })
    st.caption("Ratings through the latest played game. **pts vs avg** = points "
               "per game above/below an average unit. Derived from final scores, "
               "so special-teams scoring is folded in.")


def render_paper(ledger: pd.DataFrame) -> None:
    """The out-of-sample paper-trade tracker for the single biggest disagreement.

    Each week the model backs its side of the largest model-vs-market gap, flat
    10 units at the previewed moneyline. A 2016-2025 backtest returned +23% here
    (bootstrap-clear of zero) but that's in-sample; this is the forward test.
    """
    st.subheader("Paper play — biggest disagreement of the week")
    st.caption("A flat **10u** paper bet on the model's side of the single "
               "largest model-vs-market disagreement each week. No real money — "
               "this is the honest **out-of-sample** test of a signal that "
               "looked strong (+23% ROI) in a 2016-2025 backtest.")

    if ledger is None or ledger.empty:
        st.info("No paper plays logged yet. The first one posts when a weekly "
                "preview runs — one play per week, graded the following Tuesday.")
        return

    s = paper_mod.summary(ledger)
    sp = paper_mod.spread_summary(ledger)
    w = paper_mod.whatif_summary(ledger)
    st.markdown("**Moneyline** — back the model's side to win outright:")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Record", f"{s['wins']}-{s['losses']}")
    c2.metric("Profit", f"{s['profit']:+.1f}u")
    c3.metric("ROI", f"{s['roi']:+.1%}" if s["bets"] else "—")
    c4.metric("Open", s["open"])
    st.markdown("**Spread** — *same play*, the model's side against the number "
                "(-110). Steadier than the moneyline in backtest (2016-25: 57% "
                "ATS, ~+8% ROI, but the bootstrap CI still touched zero):")
    d1, d2, d3, d4 = st.columns(4)
    rec = f"{sp['wins']}-{sp['losses']}" + (f"-{sp['pushes']}" if sp["pushes"] else "")
    d1.metric("ATS record", rec)
    d2.metric("Profit", f"{sp['profit']:+.1f}u")
    d3.metric("ROI", f"{sp['roi']:+.1%}" if sp["bets"] else "—")
    d4.metric("Open", sp["open"])
    if w["bets"]:
        st.caption(f"**What-if ({paper_mod.WHATIF_NAME}):** {w['profit']:+.1f}u on "
                   f"{w['staked']:.0f}u staked · ROI {w['roi']:+.1%} — a *derived* "
                   "alternative where the stake scales with the size of the edge "
                   "(capped at 3×). The flat 10u line stays the tracked baseline.")

    led = paper_mod.add_whatif(ledger.sort_values(["season", "week"]).copy())
    settled = led[led["result"].isin(["win", "loss", "push"])]
    if not settled.empty:
        settled = settled.assign(
            label=settled["season"].astype(int).astype(str)
            + " Wk" + settled["week"].astype(int).astype(str))
        settled["Moneyline (flat 10u)"] = settled["profit"].cumsum()
        settled["Spread (flat 10u)"] = \
            settled["spread_profit"].fillna(0).cumsum()
        settled[f"What-if ({paper_mod.WHATIF_NAME})"] = \
            settled["whatif_profit"].cumsum()
        curves = ["Moneyline (flat 10u)", "Spread (flat 10u)",
                  f"What-if ({paper_mod.WHATIF_NAME})"]
        long = settled.melt(
            id_vars=["label"], value_vars=curves,
            var_name="Curve", value_name="cum")
        line = (
            alt.Chart(long).mark_line(point=True).encode(
                x=alt.X("label:N", sort=None, title=None),
                y=alt.Y("cum:Q", title="Cumulative units"),
                color=alt.Color("Curve:N", title=None,
                                scale=alt.Scale(
                                    domain=curves,
                                    range=["#3987e5", "#e5893a", "#199e70"])),
                tooltip=["label", "Curve",
                         alt.Tooltip("cum:Q", title="Units", format="+.1f")],
            ).properties(height=280)
        )
        st.altair_chart(line, width="stretch")

    rows = []
    for _, r in led.iterrows():
        if r["result"] == "win":
            res = f"✓ +{float(r['profit']):.1f}u"
        elif r["result"] == "loss":
            res = f"✗ {float(r['profit']):.1f}u"
        elif r["result"] == "open":
            res = "open"
        else:
            res = str(r["result"])
        price = f"{int(r['price_ml']):+d}" if pd.notna(r["price_ml"]) else "n/a"
        if pd.notna(r["whatif_profit"]):
            wi = f"{float(r['whatif_stake']):.0f}u → {float(r['whatif_profit']):+.1f}u"
        elif r["result"] == "open" and pd.notna(r["whatif_stake"]):
            wi = f"{float(r['whatif_stake']):.0f}u staked"
        else:
            wi = "—"
        rows.append({
            "Week": int(r["week"]),
            "": teams_mod.logo(r["model_side"]),
            "Play": f"{r['model_side']} ({r['away_team']} @ {r['home_team']})",
            "Edge": f"+{abs(float(r['edge'])):.0%}" if pd.notna(r["edge"]) else "—",
            "Price": price,
            "Result": res,
            "Spread": paper_mod._spread_cell(r),
            "What-if": wi,
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True,
                 column_config=logo_cfg(""))
    st.caption("One bet per week, priced when the preview ran (Thursday). "
               "**Moneyline** and **Spread** are the same weekly play graded two "
               "ways; the **What-if** column is a derived edge-proportional "
               "stake, not a second real tracker. Backtest was in-sample — trust "
               "the forward record.")

    render_spread_divergence(paper_spread_mod.load_ledger())


def render_spread_divergence(ledger: pd.DataFrame) -> None:
    """Second, independent forward tracker: the spread-divergence ATS screen.

    Distinct strategy from the top-1 play above — it bets the model's side ATS
    on *every* game where the model's implied spread diverges from the market
    line by >= 2 points, so several bets a week. Backtested weaker (~+2% ROI,
    53.4% cover, fails the season-block bootstrap), tracked forward in parallel.
    """
    st.divider()
    st.subheader("📐 Spread-divergence screen — the other forward test")
    st.caption("A **separate** strategy from the play above: bet the model's "
               "side against the number on *every* game where the model's "
               "implied spread differs from the market line by **≥ 2 pts** "
               "(so several bets a week, flat 10u at -110). Weaker in backtest "
               "(~+2% ROI, 53% cover, didn't clear the bootstrap) — tracked "
               "forward on its own to see if it holds up.")

    if ledger is None or ledger.empty:
        st.info("No spread-divergence bets logged yet. They post when a weekly "
                "preview runs and settle the following Tuesday.")
        return

    s = paper_spread_mod.summary(ledger)
    c1, c2, c3, c4 = st.columns(4)
    rec = f"{s['wins']}-{s['losses']}" + (f"-{s['push']}" if s["push"] else "")
    c1.metric("ATS record", rec)
    c2.metric("Profit", f"{s['profit']:+.1f}u")
    c3.metric("ROI", f"{s['roi']:+.1%}" if s["bets"] else "—")
    c4.metric("Open", s["open"])

    led = ledger.sort_values(["season", "week", "game_id"]).copy()
    settled = led[led["result"].isin(["win", "loss", "push"])]
    if not settled.empty:
        settled = settled.assign(
            n=range(1, len(settled) + 1),
            cum=settled["profit"].fillna(0).cumsum())
        line = (
            alt.Chart(settled).mark_line(point=True).encode(
                x=alt.X("n:Q", title="bet # (chronological)"),
                y=alt.Y("cum:Q", title="Cumulative units won/lost"),
                tooltip=[alt.Tooltip("cum:Q", title="Units", format="+.1f")],
            ).properties(height=240, title="Running profit (settled bets)"))
        st.altair_chart(line, width="stretch")
        st.caption("Each point is one **settled** bet; the line is total units "
                   "won/lost so far (flat 10u at -110 → a win ≈ +9.1u, a loss "
                   "-10u). The axis counts bets in order, **not** weeks — several "
                   "bets post per week, so one week can add several points.")

    rows = []
    for _, r in led.iterrows():
        if r["result"] == "win":
            res = f"✓ +{float(r['profit']):.1f}u"
        elif r["result"] == "loss":
            res = f"✗ {float(r['profit']):.1f}u"
        elif r["result"] == "push":
            res = "push"
        else:
            res = "open"
        rows.append({
            "Week": int(r["week"]),
            "": teams_mod.logo(r["side"]),
            "Side": r["side"],
            "Matchup": f"{r['away_team']} @ {r['home_team']}",
            "Line": f"{float(r['spread_line']):+g}",
            "Implied": f"{float(r['implied_spread']):+g}"
                       if pd.notna(r["implied_spread"]) else "—",
            "Gap": f"{float(r['gap']):+.1f}" if pd.notna(r["gap"]) else "—",
            "Result": res,
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True,
                 column_config=logo_cfg(""))
    st.caption("**Line** = market spread (home-relative). **Implied** = the "
               "model's own spread from its win prob. **Gap** = implied − line; "
               "|gap| ≥ 2 is what triggers a bet, on the model's side.")


def render_blog(posts: list[dict]) -> None:
    st.header("📝 Blog")
    st.caption("Notes from Jim on the app, the season, and the stats. "
               "New posts appear at the top.")
    if not posts:
        st.info("No posts yet. Jim can publish one from the local dashboard.")
        return
    for post in posts:
        title = post.get("title") or "(untitled)"
        date = post.get("date", "")
        author = post.get("author", "")
        byline = " · ".join(x for x in (date, author) if x)
        with st.container(border=True):
            st.markdown(f"### {title}")
            if byline:
                st.caption(byline)
            st.markdown(post.get("body", ""))


def render_guide() -> None:
    """Render the friend-facing user guide (GUIDE.md at the repo root)."""
    try:
        st.markdown((Path(__file__).parent / "GUIDE.md").read_text())
    except Exception:
        st.info("Guide not available.")


def render_open_ai_picks(meta: dict) -> None:
    """The AI expert's picks for the OPEN (ungraded) week, shown pre-game.

    Reads the committed pick sheet for the preview week and shows only rows that
    carry a rationale — i.e. the AI expert. Human picks (no rationale) stay
    hidden until the week is graded, so the pool isn't spoiled.
    """
    season, week = meta.get("preview_season"), meta.get("preview_week")
    if season is None or week is None:
        return
    try:
        path = picks_mod.week_path(int(season), int(week))
        if not path.exists():
            return
        df = pd.read_csv(path, dtype={"game_id": str})
    except Exception:
        return
    if "rationale" not in df.columns:
        return
    ai = df[df["rationale"].notna()
            & df["rationale"].astype(str).str.strip().ne("")]
    if ai.empty:
        return
    st.subheader(f"🤖 AI expert — Week {int(week)} picks (pre-game)")
    show = pd.DataFrame({
        "Expert": ai["player"].values,
        **matchup_frame(ai["away_team"], ai["home_team"]),
        "  ": team_logos(ai["pick"]), "Pick": ai["pick"].values,
        "Conf": ai["confidence"].values, "Why": ai["rationale"].values,
    })
    st.dataframe(show, width="stretch", hide_index=True,
                 column_config=logo_cfg("", " ", "  "))
    st.caption("The AI's reasoning, shared **before kickoff**. The human experts' "
               "picks stay hidden until the week is graded.")


# Sentinel for "leave this game unpicked" in the Make-picks form. Writing an
# empty pick means the grader skips the game (it isn't scored) — so you can lock
# just tonight's game and genuinely leave the rest open.
NO_PICK = "— no pick yet —"
_ET = ZoneInfo("America/New_York")


def _user_tz() -> ZoneInfo:
    """The viewer's browser timezone (via st.context), falling back to ET."""
    try:
        name = getattr(st.context, "timezone", None)
        if name:
            return ZoneInfo(name)
    except Exception:  # noqa: BLE001 — unknown tz name / no context
        pass
    return _ET


def _kickoff_label(gameday, gametime, tz: ZoneInfo) -> str:
    """'Sun Sep 14, 12:00 PM CDT' in ``tz`` — or just the date if no kickoff time."""
    ko = _kickoff(gameday, gametime)
    if ko is None:
        d = pd.to_datetime(gameday, errors="coerce")
        return d.strftime("%a %b %d") if pd.notna(d) else "—"
    local = ko.astimezone(tz)
    hour = local.strftime("%I").lstrip("0") or "12"   # 12h, no leading zero
    return local.strftime(f"%a %b %d, {hour}:%M %p %Z")


def _kickoff(gameday, gametime) -> dt.datetime | None:
    """Kickoff as a timezone-aware datetime (nflverse gameday/gametime are ET).

    Returns None when either piece is missing/unparseable, in which case the
    caller leaves the game unlocked (better to allow a pick than to wrongly lock).
    """
    if gameday is None or (isinstance(gameday, float) and pd.isna(gameday)):
        return None
    try:
        d = pd.to_datetime(str(gameday), errors="coerce")
        if pd.isna(d):
            return None
        t = str(gametime) if gametime is not None else ""
        if ":" not in t:            # no kickoff time → treat as unknown (unlocked)
            return None
        hh, mm = t.split(":")[:2]
        return dt.datetime(d.year, d.month, d.day, int(hh), int(mm), tzinfo=_ET)
    except (ValueError, TypeError):
        return None


def _has_started(gameday, gametime, now: dt.datetime | None = None) -> bool:
    """True once a game's kickoff has passed. Unknown kickoff → not started."""
    ko = _kickoff(gameday, gametime)
    if ko is None:
        return False
    now = now or dt.datetime.now(tz=_ET)
    return now >= ko


def _player_name() -> str | None:
    """Map the signed-in user's email to a pick'em expert name via [players]."""
    email = getattr(st.user, "email", None)
    if not email:
        return None
    try:
        mapping = dict(st.secrets.get("players", {}))
    except Exception:
        mapping = {}
    return mapping.get(email)


def _github_store() -> "submit_mod.GitHubStore | None":
    try:
        gh = st.secrets.get("github", {})
        token, repo = gh.get("token"), gh.get("repo")
    except Exception:
        return None
    if not token or not repo:
        return None
    return submit_mod.GitHubStore(token=token, repo=repo,
                                  branch=gh.get("branch", "main"))


def render_make_picks(preview: pd.DataFrame, meta: dict) -> None:
    season = meta.get("preview_season")
    week = meta.get("preview_week")
    if preview is None or season is None or week is None:
        st.info("No open slate to pick yet — the weekly preview hasn't been "
                "published. Picks open once that week's preview is exported.")
        return

    # Off-season: the published slate is last season's finale (a seeded sample),
    # so don't show a stale, unsubmittable week. Compare the previewed season to
    # the current NFL season (Sep-Dec = this year, Jan-Feb = last year, else the
    # upcoming year). The preview flips to the new season automatically once the
    # Week 1 slate is exported (~5 days before kickoff).
    _now = dt.datetime.now()
    _cur_season = (_now.year if _now.month >= 9
                   else _now.year - 1 if _now.month <= 2 else _now.year)
    if int(season) < _cur_season:
        st.info(f"🏈 **Picks open when the {_cur_season} season kicks off** — the "
                f"Week 1 slate posts around **early September {_cur_season}**, and "
                "this tab will switch to it automatically. What you see elsewhere "
                "is last season's finale, kept as a sample until then.")
        return

    if not _auth_configured() or not getattr(st.user, "is_logged_in", False):
        st.info("Sign-in must be enabled to submit picks (we attribute each pick "
                "to the signed-in expert). The leaderboard still works read-only.")
        return

    store = _github_store()
    if store is None:
        st.info("Pick submission isn't enabled yet. Add a `[github]` token to the "
                "app's secrets to turn it on; until then, picks are entered via "
                "the CSV sheets in the repo.")
        return

    player = _player_name()
    if player is None:
        st.warning(f"{getattr(st.user, 'email', 'This account')} isn't mapped to an "
                   "expert. Add it under `[players]` in the app secrets.")
        return

    st.subheader(f"Your picks — {season} Week {int(week)}")
    st.caption(f"Signed in as **{player}**. Pick a winner per game and set your "
               "confidence (50 = coin-flip, 100 = lock). You can submit as often "
               "as you like — resubmitting updates your open games and never "
               "touches a game that's already kicked off. Leave a game on "
               "**“no pick yet”** to decide later.")

    sched_cols = [c for c in ("away_team", "home_team", "gameday", "gametime")
                  if c in preview.columns]
    games = preview[sched_cols].reset_index(drop=True)

    # Prefill from this expert's already-committed picks, if any.
    prior: dict[str, dict] = {}
    try:
        path = f"predictions/picks/{season}-wk{int(week):02d}.csv"
        current, _ = store.get_file(path)
        if current:
            import io
            cur = pd.read_csv(io.StringIO(current), dtype={"game_id": str})
            cur = cur[cur["player"].astype(str).str.strip() == player]
            for _, r in cur.iterrows():
                prior[str(r["game_id"])] = {
                    "pick": str(r["pick"]) if pd.notna(r["pick"]) else "",
                    "confidence": r["confidence"]}
    except Exception as e:  # noqa: BLE001 — prefill is best-effort
        st.caption(f"(Couldn't load existing picks: {e})")

    now = dt.datetime.now(tz=_ET)
    started = {}
    for _, g in games.iterrows():
        gid = submit_mod.game_id(season, int(week), g["away_team"], g["home_team"])
        started[gid] = _has_started(g.get("gameday"), g.get("gametime"), now)
    n_locked = sum(started.values())
    if n_locked:
        st.caption(f"🔒 {n_locked} game(s) have kicked off and are locked — you "
                   "can still set the rest. Pick a winner, or leave a game on "
                   "**“no pick yet”** and come back before it starts.")

    with st.form("make_picks"):
        form_choices: dict[str, dict] = {}
        for _, g in games.iterrows():
            away, home = g["away_team"], g["home_team"]
            gid = submit_mod.game_id(season, int(week), away, home)
            pre = prior.get(gid, {})
            prior_pick = pre.get("pick") if pre.get("pick") in (away, home) else NO_PICK
            opts = [NO_PICK, away, home]
            try:
                conf_default = int(float(pre.get("confidence")))
            except (TypeError, ValueError):
                conf_default = 50

            c1, c2 = st.columns([2, 1])
            if started[gid]:
                shown = prior_pick if prior_pick != NO_PICK else "no pick"
                c1.markdown(f"🔒 **{away} @ {home}** — locked · *{shown}*")
                c2.caption("kicked off")
                continue  # locked: prior pick is preserved verbatim on submit

            pick = c1.radio(f"{away} @ {home}", opts, index=opts.index(prior_pick),
                            horizontal=True, key=f"pick_{gid}")
            conf = c2.slider("confidence", 50, 100, conf_default,
                             key=f"conf_{gid}", label_visibility="collapsed",
                             disabled=(pick == NO_PICK))
            form_choices[gid] = {"pick": pick, "confidence": conf}
        submitted = st.form_submit_button("Submit my picks", type="primary")

    if submitted:
        # Assemble the full slate: open games from the form (NO_PICK → blank so
        # the grader skips them), locked games preserved from prior so a started
        # game can't be changed or wiped by this submit.
        selections: dict[str, dict] = {}
        for _, g in games.iterrows():
            gid = submit_mod.game_id(season, int(week), g["away_team"], g["home_team"])
            if started[gid]:
                pre = prior.get(gid, {})
                selections[gid] = {"pick": pre.get("pick", ""),
                                   "confidence": pre.get("confidence", "")}
                continue
            ch = form_choices.get(gid, {})
            if ch.get("pick") in (None, NO_PICK):
                selections[gid] = {"pick": "", "confidence": ""}
            else:
                selections[gid] = {"pick": ch["pick"], "confidence": ch["confidence"]}
        made = sum(1 for s in selections.values() if s["pick"])
        try:
            submit_mod.submit_picks(store, int(season), int(week), games,
                                    player, selections)
            st.success(f"Saved for {player}, Week {int(week)}: {made} pick(s) in, "
                       f"{len(selections) - made} left open. They'll score in "
                       "Tuesday's grade run — come back for the open ones before "
                       "they kick off.")
        except Exception as e:  # noqa: BLE001
            st.error(f"Couldn't save picks: {e}")


# ── Page ──────────────────────────────────────────────────────────────────────
_require_login()

st.title("🏈 NFL model — pick'em & tracker")

art = cloud.load_artifacts()
graded, scored, preview, meta = (
    art["graded"], art["scored"], art["preview"], art["meta"])
schedule = art["schedule"]
sim = art["sim"]
sim_history = art["sim_history"]
sim_market = art["sim_market"]
unit_elo_df = art["unit_elo"]
paper_ledger = paper_mod.load_ledger()
blog_posts = art["blog"]

if graded is None and preview is None and schedule is None and sim is None:
    st.warning("No data published yet. The local weekly runs export results here "
               "(`predictions/cloud/`) and push them; this app renders whatever's "
               "been published.")
    st.stop()

# Freshness line. Use the NEWEST season across artifacts (a stale seeded grade
# snapshot from a prior season shouldn't set the label), and only show a stamp
# that belongs to that current season.
_seasons = [meta.get(k) for k in
            ("preview_season", "schedule_season", "sim_season", "grade_season")
            if meta.get(k)]
season = max(_seasons) if _seasons else ""
stamps = []
if meta.get("grade_generated_at") and meta.get("grade_season") == season:
    stamps.append(f"grade through Wk {meta.get('grade_through_week', '?')} "
                  f"({meta['grade_generated_at'][:10]})")
if meta.get("preview_generated_at") and meta.get("preview_season") == season:
    stamps.append(f"preview Wk {meta.get('preview_week', '?')} "
                  f"({meta['preview_generated_at'][:10]})")
if season:
    st.caption(f"**{season} season** · last updated: " + " · ".join(stamps)
               if stamps else f"**{season} season**")

tabs, names = [], []
names.append("📝 Blog")  # landing tab (Streamlit opens the first tab)
if preview is not None:
    names.append("Weekly preview")
if preview is not None:
    names.append("Make picks")
if graded is not None:
    names.append("Season tracker")
if schedule is not None:
    names.append("🗓️ Schedule")
if sim is not None:
    names.append("🏆 Playoff odds")
if unit_elo_df is not None:
    names.append("⚔️ Unit Elo")
if scored is not None or graded is not None:
    names.append("Pick'em leaderboard")
names.append("📈 Paper play")  # always shown; empty-state until the first play
names.append("📖 Guide")
made = st.tabs(names)
tab_by_name = dict(zip(names, made))

if "🗓️ Schedule" in tab_by_name:
    with tab_by_name["🗓️ Schedule"]:
        render_schedule(schedule, meta.get("schedule_season") or season)

if "🏆 Playoff odds" in tab_by_name:
    with tab_by_name["🏆 Playoff odds"]:
        render_playoff_odds(sim, sim_history, meta, meta.get("sim_season") or season,
                            sim_market=sim_market)

if "⚔️ Unit Elo" in tab_by_name:
    with tab_by_name["⚔️ Unit Elo"]:
        render_unit_elo(unit_elo_df, matchups=preview)

if "Pick'em leaderboard" in tab_by_name:
    with tab_by_name["Pick'em leaderboard"]:
        if graded is None:
            st.info("Leaderboard needs a graded week to score against.")
        else:
            render_leaderboard(scored, graded)

if "Make picks" in tab_by_name:
    with tab_by_name["Make picks"]:
        render_make_picks(preview, meta)

if "Season tracker" in tab_by_name:
    with tab_by_name["Season tracker"]:
        render_tracker(graded)

if "Weekly preview" in tab_by_name:
    with tab_by_name["Weekly preview"]:
        render_preview(preview)
        render_open_ai_picks(meta)

if "📈 Paper play" in tab_by_name:
    with tab_by_name["📈 Paper play"]:
        render_paper(paper_ledger)

if "📝 Blog" in tab_by_name:
    with tab_by_name["📝 Blog"]:
        render_blog(blog_posts)

if "📖 Guide" in tab_by_name:
    with tab_by_name["📖 Guide"]:
        render_guide()
