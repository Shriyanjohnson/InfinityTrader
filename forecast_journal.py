"""Immutable research snapshots and outcomes; no trades or payment state."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import re
import sqlite3

import pandas as pd

MODEL_REVISION = hashlib.sha256(Path(__file__).with_name("analytics.py").read_bytes()).hexdigest()[:12]
COLUMNS = ["id", "symbol", "source_session", "recorded_at", "source_close", "upward_score",
           "baseline_score", "model_name", "model_revision", "data_fingerprint", "target_session",
           "actual_return", "outcome", "eligible"]


def _now(now=None):
    stamp = pd.Timestamp(datetime.now(timezone.utc) if now is None else now)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def record_forecast(database, symbol, data, result, baseline_score, now=None):
    """Keep the first snapshot for a symbol/session, including its original scores."""
    if not re.fullmatch(r"[A-Z^][A-Z0-9.^-]{0,11}", symbol):
        raise ValueError("Invalid forecast symbol.")
    if str(data.index.tz) != "America/New_York":
        raise ValueError("The journal requires New York exchange daily timestamps.")
    stamp = _now(now)
    session = data.index[-1].date()
    if session >= stamp.tz_convert("America/New_York").date():
        raise ValueError("Only prior completed sessions can be recorded.")
    score, baseline, close = float(result.upward_score), float(baseline_score), float(data.Close.iloc[-1])
    if not all(math.isfinite(value) for value in (score, baseline, close)) or close <= 0:
        raise ValueError("The forecast contains invalid values.")
    if not 0 <= score <= 1 or not 0 <= baseline <= 1:
        raise ValueError("Forecast scores must be between zero and one.")
    fingerprint = hashlib.sha256(data[["Open", "High", "Low", "Close", "Volume"]].to_csv().encode()).hexdigest()
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=10)) as connection:
        database.chmod(0o600)
        with connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS forecasts (
                id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, source_session TEXT NOT NULL,
                recorded_at TEXT NOT NULL, source_close REAL NOT NULL, upward_score REAL NOT NULL,
                baseline_score REAL NOT NULL, model_name TEXT NOT NULL, model_revision TEXT NOT NULL,
                data_fingerprint TEXT NOT NULL, target_session TEXT, actual_return REAL,
                outcome INTEGER, eligible INTEGER, UNIQUE(symbol, source_session))""")
            cursor = connection.execute("""INSERT INTO forecasts
                (symbol, source_session, recorded_at, source_close, upward_score, baseline_score,
                 model_name, model_revision, data_fingerprint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, source_session) DO NOTHING""",
                (symbol, session.isoformat(), stamp.isoformat(), close, score, baseline,
                 result.model_name, MODEL_REVISION, fingerprint))
            return cursor.rowcount == 1


def settle_forecasts(database, symbol, data, now=None):
    """Resolve with the first later observed completed session; exclude late snapshots."""
    if not Path(database).exists():
        return
    if str(data.index.tz) != "America/New_York":
        raise ValueError("The journal requires New York exchange daily timestamps.")
    closes = data.Close.copy().sort_index()
    sessions = [index.date().isoformat() for index in closes.index]
    if len(set(sessions)) != len(sessions):
        raise ValueError("Duplicate daily sessions cannot settle a forecast.")
    positions = {session: position for position, session in enumerate(sessions)}
    today = _now(now).tz_convert("America/New_York").date().isoformat()
    with closing(sqlite3.connect(database, timeout=10)) as connection, connection:
        pending = connection.execute("SELECT id, source_session, recorded_at FROM forecasts WHERE symbol=? AND outcome IS NULL", (symbol,)).fetchall()
        for identifier, source, recorded_at in pending:
            position = positions.get(source)
            if position is None or position + 1 >= len(sessions):
                continue
            target = sessions[position + 1]
            if target >= today:
                continue
            before, after = float(closes.iloc[position]), float(closes.iloc[position + 1])
            if not all(math.isfinite(value) and value > 0 for value in (before, after)):
                continue
            # The actual next observed session handles weekends and holidays without
            # inventing a trading calendar. Limit scoring to US regular-session opens.
            next_open = pd.Timestamp(f"{target} 09:30", tz="America/New_York")
            eligible = int(pd.Timestamp(recorded_at) < next_open)
            change = after / before - 1
            connection.execute("""UPDATE forecasts SET target_session=?, actual_return=?, outcome=?, eligible=?
                WHERE id=? AND outcome IS NULL""", (target, change, int(after > before), eligible, identifier))


def read_forecasts(database, symbol):
    if not Path(database).exists():
        return pd.DataFrame(columns=COLUMNS)
    with closing(sqlite3.connect(database, timeout=10)) as connection:
        return pd.read_sql_query("SELECT * FROM forecasts WHERE symbol=? ORDER BY source_session DESC, id DESC",
                                 connection, params=(symbol,))


def performance(records):
    """Only resolved snapshots recorded before the next session open count."""
    scored = records.loc[records.eligible.eq(1) & records.outcome.notna()]
    if scored.empty:
        return None
    actual = scored.outcome.astype(float)
    return {"count": len(scored), "accuracy": float(((scored.upward_score >= .5) == actual).mean()),
            "baseline_accuracy": float(((scored.baseline_score >= .5) == actual).mean()),
            "brier": float(((scored.upward_score - actual) ** 2).mean()),
            "baseline_brier": float(((scored.baseline_score - actual) ** 2).mean())}
