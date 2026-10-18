"""Persistent daily research alerts; evaluated on demand, with no external delivery."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import re
import sqlite3
import uuid

import pandas as pd

from market_sessions import next_session_info, session_matches

METRICS = {"Close": "Daily close ($)", "RSI": "RSI (0–100)",
           "Volume_ratio": "Relative volume (×)", "ATR_pct": "ATR as % of price"}
EVENT_COLUMNS = ["id", "rule_id", "symbol", "source_session", "detected_at", "metric",
                 "comparison", "threshold", "observed_value", "previous_value", "trigger_style"]


def _now(now=None):
    stamp = pd.Timestamp(datetime.now(timezone.utc) if now is None else now)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def latest_completed_session(now=None):
    """Match the app's conservative policy: exclude today's entire daily candle."""
    day = _now(now).tz_convert("America/New_York").date() - timedelta(days=1)
    for _ in range(31):
        if next_session_info(day.isoformat()) is not None:
            return day.isoformat()
        day -= timedelta(days=1)
    raise ValueError("No recent exchange session is available.")


def save_rule(database, symbol, metric, comparison, threshold, trigger_style="condition", now=None):
    if not re.fullmatch(r"[A-Z^][A-Z0-9.^-]{0,11}", symbol) or metric not in METRICS:
        raise ValueError("Choose a supported symbol and alert metric.")
    if comparison not in ("above", "below") or trigger_style not in ("condition", "crossing"):
        raise ValueError("Choose a valid alert condition.")
    threshold = float(threshold)
    if not math.isfinite(threshold) or threshold < 0 or (metric == "Close" and threshold == 0):
        raise ValueError("Enter a finite, valid threshold.")
    if metric == "RSI" and threshold > 100:
        raise ValueError("RSI thresholds must be between 0 and 100.")
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=10)) as connection, connection:
        database.chmod(0o600)
        connection.execute("""CREATE TABLE IF NOT EXISTS alert_rules (
            id TEXT PRIMARY KEY, symbol TEXT NOT NULL, metric TEXT NOT NULL,
            comparison TEXT NOT NULL, threshold REAL NOT NULL, trigger_style TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
            UNIQUE(symbol, metric, comparison, threshold, trigger_style))""")
        connection.execute("""CREATE TABLE IF NOT EXISTS alert_events (
            id INTEGER PRIMARY KEY, rule_id TEXT NOT NULL, symbol TEXT NOT NULL,
            source_session TEXT NOT NULL, detected_at TEXT NOT NULL, metric TEXT NOT NULL,
            comparison TEXT NOT NULL, threshold REAL NOT NULL, observed_value REAL NOT NULL,
            previous_value REAL, trigger_style TEXT NOT NULL, UNIQUE(rule_id, source_session))""")
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute("""SELECT id FROM alert_rules WHERE symbol=? AND metric=?
            AND comparison=? AND threshold=? AND trigger_style=?""", (symbol, metric, comparison, threshold, trigger_style)).fetchone()
        if existing:
            return existing[0], False
        if connection.execute("SELECT count(*) FROM alert_rules WHERE symbol=?", (symbol,)).fetchone()[0] >= 20:
            raise ValueError("Keep at most 20 rules per symbol. Remove a rule before adding another.")
        distinct = connection.execute("SELECT DISTINCT symbol FROM alert_rules").fetchall()
        if symbol not in {row[0] for row in distinct} and len(distinct) >= 20:
            raise ValueError("Keep alert rules for at most 20 symbols per workspace.")
        identifier = uuid.uuid4().hex
        connection.execute("INSERT INTO alert_rules VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                           (identifier, symbol, metric, comparison, threshold, trigger_style, _now(now).isoformat()))
        return identifier, True


def read_rules(database, symbol):
    if not Path(database).exists():
        return []
    with closing(sqlite3.connect(database, timeout=10)) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT * FROM alert_rules WHERE symbol=? ORDER BY created_at, id", (symbol,))]


def set_enabled(database, identifier, enabled):
    with closing(sqlite3.connect(database, timeout=10)) as connection, connection:
        connection.execute("UPDATE alert_rules SET enabled=? WHERE id=?", (int(bool(enabled)), identifier))


def remove_rule(database, identifier):
    """Remove the rule while retaining immutable past matches."""
    with closing(sqlite3.connect(database, timeout=10)) as connection, connection:
        connection.execute("DELETE FROM alert_rules WHERE id=?", (identifier,))


def evaluate_rule(rule, data, now=None):
    result = {"status": "Paused", "value": None, "previous": None}
    if not rule["enabled"]:
        return result
    if data.empty or str(data.index.tz) != "America/New_York":
        return {**result, "status": "Unsupported or missing daily history"}
    session = data.index[-1].date().isoformat()
    if session != latest_completed_session(now):
        return {**result, "status": "Waiting for the latest completed session"}
    metric = rule["metric"]
    if metric not in data.columns:
        return {**result, "status": "Indicator unavailable"}
    value = float(data[metric].iloc[-1])
    if not math.isfinite(value) or value < 0 or (metric == "Close" and value == 0) or (metric == "RSI" and value > 100):
        return {**result, "status": "Indicator unavailable"}
    result["value"] = value
    matched = value >= rule["threshold"] if rule["comparison"] == "above" else value <= rule["threshold"]
    if rule["trigger_style"] == "crossing":
        if len(data) < 2 or not session_matches(data.index[-2].date().isoformat(), session):
            return {**result, "status": "Previous session unavailable"}
        previous = float(data[metric].iloc[-2])
        if not math.isfinite(previous) or previous < 0 or (metric == "Close" and previous == 0) or (metric == "RSI" and previous > 100):
            return {**result, "status": "Previous indicator unavailable"}
        result["previous"] = previous
        crossed = previous < rule["threshold"] if rule["comparison"] == "above" else previous > rule["threshold"]
        matched = matched and crossed
    return {**result, "status": "Matched" if matched else "Waiting"}


def check_alerts(database, symbol, data, now=None):
    if not Path(database).exists():
        return [], 0
    stamp = _now(now)
    results, created = [], 0
    with closing(sqlite3.connect(database, timeout=10)) as connection, connection:
        # Serialize checks with pauses/removals, and deduplicate concurrent reruns.
        connection.execute("BEGIN IMMEDIATE")
        connection.row_factory = sqlite3.Row
        rules = connection.execute("SELECT * FROM alert_rules WHERE symbol=? ORDER BY created_at, id", (symbol,)).fetchall()
        for rule in rules:
            checked = evaluate_rule(rule, data, stamp)
            results.append({**dict(rule), **checked})
            if checked["status"] != "Matched":
                continue
            cursor = connection.execute("""INSERT INTO alert_events
                (rule_id, symbol, source_session, detected_at, metric, comparison, threshold,
                 observed_value, previous_value, trigger_style) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(rule_id, source_session) DO NOTHING""",
                (rule["id"], symbol, data.index[-1].date().isoformat(), stamp.isoformat(), rule["metric"],
                 rule["comparison"], rule["threshold"], checked["value"], checked["previous"], rule["trigger_style"]))
            created += cursor.rowcount
    return results, created


def read_events(database, symbol):
    if not Path(database).exists():
        return pd.DataFrame(columns=EVENT_COLUMNS)
    with closing(sqlite3.connect(database, timeout=10)) as connection:
        return pd.read_sql_query("SELECT * FROM alert_events WHERE symbol=? ORDER BY source_session DESC, id DESC", connection, params=(symbol,))
