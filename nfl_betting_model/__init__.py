"""Read-only helpers for the public NFL pick'em / dashboard app.

This is the *public* subset of the project: only the light modules the Streamlit
app needs to render pre-exported artifacts (no training, no nflreadpy). The full
model and pipeline live in the private repo, which generates the artifacts under
``predictions/`` that this app reads.
"""
