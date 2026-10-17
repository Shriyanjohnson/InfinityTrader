"""Forecast journal within the existing research workspace."""
import os
from pathlib import Path
import sqlite3

import pandas as pd
import streamlit as st

from analytics import supervised_data
from forecast_journal import performance, read_forecasts, record_forecast, settle_forecasts


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
    stats = performance(records)
    if stats:
        cols = st.columns(3)
        cols[0].metric("Scored forecasts", str(stats["count"]))
        cols[1].metric("Recorded direction accuracy", f"{stats['accuracy']:.1%}")
        cols[2].metric("Recorded Brier loss", f"{stats['brier']:.3f}")
        st.caption(f"Same-snapshot historical-frequency baseline: {stats['baseline_accuracy']:.1%} accuracy, {stats['baseline_brier']:.3f} Brier loss. Lower loss is better. Small samples do not establish a trading edge.")
    pending = int(records.outcome.isna().sum())
    late = int(records.eligible.eq(0).sum())
    st.caption(f"{pending} awaiting a later completed session · {late} late snapshots excluded. Only snapshots recorded before the next observed session's 9:30 a.m. New York open count. Refreshing analysis checks this symbol's outcomes; there is no background scheduler.")
    display = records[["source_session", "recorded_at", "model_name", "upward_score", "target_session", "actual_return"]].copy()
    display["recorded_at"] = pd.to_datetime(display.recorded_at, utc=True).dt.strftime("%Y-%m-%d %H:%M:%S")
    display["target_session"] = display.target_session.fillna("Pending")
    display["actual_return"] = pd.to_numeric(display.actual_return, errors="coerce")
    display["Status"] = ["Pending" if pd.isna(outcome) else "Scored" if eligible == 1 else "Late · excluded"
                         for outcome, eligible in zip(records.outcome, records.eligible)]
    display = display.rename(columns={"source_session": "Source session", "recorded_at": "Recorded at (UTC)",
        "model_name": "Model", "upward_score": "Upward score", "target_session": "Outcome session", "actual_return": "Next-session return"})
    st.dataframe(display, hide_index=True, width="stretch", column_config={
        "Upward score": st.column_config.NumberColumn(format="percent"),
        "Next-session return": st.column_config.NumberColumn(format="percent")})
    st.download_button("↓ Download forecast journal CSV", records.to_csv(index=False).encode(),
        file_name=f"{symbol}_forecast_journal.csv", mime="text/csv")
    st.caption("Resolved outcomes use source and next-session prices from the same adjusted history, then stay fixed. Provider revisions may change later comparisons. CSV includes model revision and input fingerprint for each snapshot.")
