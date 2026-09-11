# 🏈 NFL Pick'em — public app

The public, read-only Streamlit app for our NFL pick'em pool and model dashboard.
Deployed on Streamlit Community Cloud (`streamlit_app.py`).

**This repo is intentionally thin.** It contains only what the deployed site needs:
the Streamlit app, a handful of light helper modules, and the pre-computed result
artifacts under `predictions/`. It does **no** model training and never fetches
data — it just renders artifacts.

The full model, training pipeline, and analysis live in a separate **private**
repo. That repo's weekly jobs generate the CSVs/JSON under `predictions/cloud/`
and push them here; this app reads them.

## What's here
- `streamlit_app.py` — the app (tabs: Blog, Weekly preview, Make picks, Season
  tracker, Schedule, Playoff odds, Pick'em, Paper play, Guide).
- `nfl_betting_model/` — light helpers only: `cloud` (artifact IO), `picks`,
  `paper` / `paper_spread` (paper-trade trackers), `submit` (pick submission via
  the GitHub Contents API), `sb_futures`, `teams`, `betting`.
- `predictions/cloud/` — exported artifacts the app renders (grades, preview,
  schedule, playoff odds, paper ledgers, blog posts).
- `predictions/picks/` — the weekly pick sheets + `players.txt`.
- `requirements.txt` — the light dependency set (no nflreadpy/polars/etc.).

## Run locally
```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deployment notes
- Streamlit Cloud resolves dependencies from `requirements.txt` (there is
  deliberately no `pyproject.toml` / `uv.lock` here, which would otherwise pull
  the heavy pipeline stack).
- Optional sign-in (Descope OIDC) and in-app pick submission activate only when
  the matching `[auth]` / `[github]` / `[players]` secrets are set in the
  Streamlit Cloud app settings (see `.streamlit/secrets.toml.example`).
