"""Forecast journal within the existing research workspace."""
import os
from pathlib import Path
import sqlite3

import pandas as pd
import streamlit as st

from analytics import supervised_data
from forecast_journal import (filter_forecasts, performance, performance_trend,
                              read_forecasts, record_forecast, settle_forecasts)


def render_forecast_journal(symbol, mode, data, result):
    st.write("**Track forecasts as new sessions arrive**")
    st.caption("Save a snapshot now, then refresh Live analysis after a later completed session to check its outcome. This records research scores and places no trades.")
    if mode == "Demo":
        st.info("Switch to Live to save forecasts. Simulated results are kept out of the journal.")
        return
    if str(data.index.tz) != "America/New_York":
        st.info("The journal currently supports US daily histories with New York exchange timestamps. Analysis and CSV downloads remain available for other markets.")
        return
    directory = Path(os.environ.get("INFINITY_DATA_DIR", Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "infinitytrader"))
    database = directory / "forecast_journal.sqlite3"
    st.caption("This journal is shared across this app instance. It is not a private account history. Performance covers US stocks and ETFs with a regular 9:30 a.m. New York open.")
    try:
        if st.button("Save this forecast", key="save_forecast"):
            _, labels = supervised_data(data)
            created = record_forecast(database, symbol, data, result, float(labels.mean()))
            if created:
                st.success("Forecast saved. Its original score will be preserved.")
            else:
                st.info("A forecast for this symbol and source session is already saved; the first snapshot is preserved.")
        settle_forecasts(database, symbol, data)
        records = read_forecasts(database, symbol)
    except (OSError, sqlite3.Error, ValueError):
        st.warning("The forecast journal is unavailable. Analysis still works; check that the app data directory is writable.")
        return
    if records.empty:
        st.info("No saved forecasts for this symbol yet.")
        return
    version_col, window_col = st.columns(2)
    revision = version_col.selectbox("Model version", ["All versions"] + sorted(records.model_revision.unique()), key=f"journal_version_{symbol}")
    window = window_col.selectbox("Performance window", ["All history", "Last 30 days", "Last 90 days"], key=f"journal_window_{symbol}")
    days = {"Last 30 days": 30, "Last 90 days": 90}.get(window)
    since = pd.Timestamp.now(tz="America/New_York").normalize() - pd.Timedelta(days=days) if days else None
    records = filter_forecasts(records, None if revision == "All versions" else revision, since)
    st.caption("Filters apply to metrics, chart, table, and CSV. Model versions identify the prediction code; the selected model family may vary between forecasts.")
    if records.empty:
        st.info("No saved forecasts match these filters.")
        return
    stats = performance(records)
    if stats:
        cols = st.columns(3)
        cols[0].metric("Scored forecasts", str(stats["count"]))
        cols[1].metric("Recorded direction accuracy", f"{stats['accuracy']:.1%}")
        cols[2].metric("Recorded Brier loss", f"{stats['brier']:.3f}")
        st.caption(f"Same-snapshot historical-frequency baseline: {stats['baseline_accuracy']:.1%} accuracy, {stats['baseline_brier']:.3f} Brier loss. Lower loss is better. Small samples do not establish a trading edge.")
        st.caption(f"95% Wilson accuracy interval: {stats['accuracy_low']:.1%}–{stats['accuracy_high']:.1%}, assuming independent outcomes. Accuracy uses a 50% score cutoff; flat closes count as non-rising. Serial dependence and selectively saved forecasts limit this estimate.")
        if stats["count"] >= 2:
            with st.expander("Recorded accuracy over time"):
                st.line_chart(performance_trend(records), width="stretch")
                st.caption("Cumulative direction accuracy on eligible saved forecasts, compared with their original historical-frequency baselines.")
    pending = int(records.outcome.isna().sum())
    late = int((records.eligible.eq(0) & records.session_match).sum())
    mismatched = int((records.outcome.notna() & ~records.session_match).sum())
    if mismatched:
        st.warning(f"{mismatched} saved outcomes do not match the next exchange session and are excluded from performance. Their original snapshots are preserved.")
    st.caption(f"{pending} awaiting a later completed session · {late} late snapshots excluded. Only snapshots recorded before the next scheduled US exchange session opens count. Missing target prices leave a forecast pending. Refreshing analysis checks this symbol's outcomes; there is no background scheduler.")
    display = records[["source_session", "recorded_at", "model_name", "upward_score", "target_session", "actual_return"]].copy()
    display["recorded_at"] = pd.to_datetime(display.recorded_at, utc=True).dt.strftime("%Y-%m-%d %H:%M:%S")
    display["target_session"] = display.target_session.fillna("Pending")
    display["actual_return"] = pd.to_numeric(display.actual_return, errors="coerce")
    display["Status"] = ["Pending" if pd.isna(outcome) else "Session mismatch · excluded" if not matched else "Scored" if eligible == 1 else "Late · excluded"
                         for outcome, eligible, matched in zip(records.outcome, records.eligible, records.session_match)]
    display = display.rename(columns={"source_session": "Source session", "recorded_at": "Recorded at (UTC)",
        "model_name": "Model", "upward_score": "Upward score", "target_session": "Outcome session", "actual_return": "Next-session return"})
    st.dataframe(display, hide_index=True, width="stretch", column_config={
        "Upward score": st.column_config.NumberColumn(format="percent"),
        "Next-session return": st.column_config.NumberColumn(format="percent")})
    st.download_button("↓ Download forecast journal CSV", records.to_csv(index=False).encode(),
        file_name=f"{symbol}_forecast_journal.csv", mime="text/csv")
    st.caption("Resolved outcomes use source and next-session prices from the same adjusted history, then stay fixed. Provider revisions may change later comparisons. CSV includes model revision and input fingerprint for each snapshot.")
