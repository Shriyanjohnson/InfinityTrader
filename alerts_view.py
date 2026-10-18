"""Daily in-app alert controls within the existing workspace."""
import os
from pathlib import Path
import sqlite3

import pandas as pd
import streamlit as st
from settings import workspace_directory
from exports import csv_bytes

from alerts import METRICS, check_alerts, read_events, remove_rule, save_rule, set_enabled


def _threshold_label(metric, value):
    return f"{value * 100:.2f}%" if metric == "ATR_pct" else f"{value:,.4g}"


def render_alerts(symbol, mode, data):
    st.write("**Daily price & indicator alerts**")
    st.caption("Rules check the latest completed daily session on analysis reruns. A configured beta/Pro worker also checks while you are away; matches appear in this inbox. New rules check the latest completed session immediately. There is no intraday monitoring, email, or push delivery.")
    if mode == "Demo":
        st.info("Switch to Live to create daily alerts. Simulated prices never trigger saved rules.")
        return
    if str(data.index.tz) != "America/New_York":
        st.info("Daily alerts currently support US histories with New York exchange timestamps.")
        return
    directory = workspace_directory()
    database = directory / "alerts.sqlite3"
    st.caption("Signed-in beta accounts have private rules and history. Stale or unfinished sessions cannot trigger alerts. Thresholds use split/dividend-adjusted prices; review fixed price thresholds after corporate actions.")
    metric = st.selectbox("Alert metric", list(METRICS), format_func=METRICS.get, key=f"alert_metric_{symbol}")
    defaults = {"Close": (0.0001, 1_000_000_000., max(.0001, round(float(data.Close.iloc[-1]), 4)), .01),
                "RSI": (0., 100., 70., 1.), "Volume_ratio": (0., 1_000_000., 1.5, .1), "ATR_pct": (0., 10_000., 3., .1)}
    low, high, initial, step = defaults[metric]
    with st.form(f"alert_form_{symbol}_{metric}"):
        first, second = st.columns(2)
        comparison = first.selectbox("Alert condition", ["At or above", "At or below"])
        threshold = second.number_input("Alert threshold", min_value=low, max_value=high, value=initial, step=step, format="%.4f")
        style = st.selectbox("Trigger style", ["Condition met", "Threshold crossing"])
        st.caption("Condition met can match each new daily session. Threshold crossing requires the previous exchange session to be on the other side. Each rule records at most one match per session.")
        submitted = st.form_submit_button("Create daily alert")
    try:
        if submitted:
            try:
                _, created = save_rule(database, symbol, metric, "above" if comparison == "At or above" else "below",
                                       float(threshold) / 100 if metric == "ATR_pct" else float(threshold),
                                       "condition" if style == "Condition met" else "crossing")
                if created:
                    st.success("Daily alert saved.")
                else:
                    st.info("That rule already exists. Its current pause state is preserved.")
            except ValueError as error:
                st.error(str(error))
        rules, new_matches = check_alerts(database, symbol, data)
        if new_matches:
            st.toast(f"{symbol}: {new_matches} daily alert match(es) recorded.")
        if rules:
            st.caption(f"Checked {data.index[-1]:%b %d, %Y} daily data. Rules persist across restarts. Removing a rule preserves its past matches.")
        for rule in rules:
            text, pause, remove = st.columns([6, 1.5, 1.5])
            direction = "≥" if rule["comparison"] == "above" else "≤"
            text.write(f"**{METRICS[rule['metric']]} {direction} {_threshold_label(rule['metric'], rule['threshold'])}** · {rule['trigger_style']}")
            observed = f" · latest {_threshold_label(rule['metric'], rule['value'])}" if rule["value"] is not None else ""
            text.caption(f"{rule['status']}{observed}")
            if pause.button("Pause" if rule["enabled"] else "Resume", key=f"pause_alert_{rule['id']}"):
                set_enabled(database, rule["id"], not rule["enabled"])
                st.rerun()
            if remove.button("Remove", key=f"remove_alert_{rule['id']}"):
                remove_rule(database, rule["id"])
                st.rerun()
        if not rules:
            st.info("No daily alert rules for this symbol yet.")
        events = read_events(database, symbol)
    except (OSError, sqlite3.Error, ValueError):
        st.warning("Daily alerts are unavailable. Analysis still works; check the app data directory or refresh the data.")
        return
    if events.empty:
        return
    st.write("**Recent alert matches**")
    display = events[["source_session", "detected_at", "metric", "comparison", "threshold", "observed_value", "trigger_style"]].head(100).copy()
    display["detected_at"] = pd.to_datetime(display.detected_at, utc=True).dt.strftime("%Y-%m-%d %H:%M:%S")
    for column in ("threshold", "observed_value"):
        display[column] = [_threshold_label(metric, value) for metric, value in zip(display.metric, display[column])]
    display["metric"] = display.metric.map(METRICS)
    display = display.rename(columns={"source_session": "Data session", "detected_at": "Checked at (UTC)", "metric": "Metric",
        "comparison": "Condition", "threshold": "Threshold", "observed_value": "Observed", "trigger_style": "Trigger style"})
    st.dataframe(display, hide_index=True, width="stretch")
    st.caption(f"Showing up to 100 of {len(events)} recorded matches. These report daily conditions, not executed trades.")
    st.download_button("↓ Download alert history CSV", csv_bytes(events),
                       file_name=f"{symbol}_alert_history.csv", mime="text/csv")
