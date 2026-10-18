"""Immutable research snapshots and outcomes; no trades or payment state."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import math
from pathlib import Path
import re
import sqlite3

import pandas as pd

from market_sessions import next_session_info, session_matches

MODEL_REVISION = hashlib.sha256(b"\n".join(
    [Path(__file__).with_name(name).read_bytes() for name in ("analytics.py", "market_sessions.py")]
    + [f"{name}=={version(name)}".encode() for name in ("scikit-learn", "exchange-calendars", "pandas", "numpy")]
)).hexdigest()[:12]
COLUMNS = ["id", "symbol", "source_session", "recorded_at", "source_close", "upward_score",
           "baseline_score", "model_name", "model_revision", "data_fingerprint", "target_session",
           "actual_return", "outcome", "eligible", "session_match"]


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
    if next_session_info(session.isoformat()) is None:
        raise ValueError("The source date is not a US exchange session.")
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
    """Resolve only the scheduled next exchange session; exclude late snapshots."""
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
            expected = next_session_info(source)
            if expected is None:
                continue
            target, next_open = expected
            target_position = positions.get(target)
            if target_position is None:
                continue
            if target >= today:
                continue
            before, after = float(closes.iloc[position]), float(closes.iloc[target_position])
            if not all(math.isfinite(value) and value > 0 for value in (before, after)):
                continue
            eligible = int(pd.Timestamp(recorded_at) < next_open)
            change = after / before - 1
            connection.execute("""UPDATE forecasts SET target_session=?, actual_return=?, outcome=?, eligible=?
                WHERE id=? AND outcome IS NULL""", (target, change, int(after > before), eligible, identifier))


def read_forecasts(database, symbol):
    if not Path(database).exists():
        return pd.DataFrame(columns=COLUMNS)
    with closing(sqlite3.connect(database, timeout=10)) as connection:
        records = pd.read_sql_query("SELECT * FROM forecasts WHERE symbol=? ORDER BY source_session DESC, id DESC",
                                    connection, params=(symbol,))
    # Audit older settlements without rewriting their saved scores or outcomes.
    records["session_match"] = [session_matches(source, target)
                                for source, target in zip(records.source_session, records.target_session)]
    return records


def filter_forecasts(records, revision=None, since=None):
    selected = records
    if revision is not None:
        selected = selected.loc[selected.model_revision.eq(revision)]
    if since is not None:
        selected = selected.loc[selected.source_session >= pd.Timestamp(since).date().isoformat()]
    return selected.copy()


def scored_forecasts(records):
    return records.loc[records.eligible.eq(1) & records.outcome.notna() & records.session_match.eq(True)]


def performance(records):
    """Only resolved snapshots recorded before the next session open count."""
    scored = scored_forecasts(records)
    if scored.empty:
        return None
    actual = scored.outcome.astype(float)
    count = len(scored)
    accuracy = float(((scored.upward_score >= .5) == actual).mean())
    z = 1.959963984540054
    denominator = 1 + z * z / count
    center = (accuracy + z * z / (2 * count)) / denominator
    margin = z * math.sqrt(accuracy * (1 - accuracy) / count + z * z / (4 * count * count)) / denominator
    return {"count": count, "accuracy": accuracy,
            "accuracy_low": max(0., center - margin), "accuracy_high": min(1., center + margin),
            "baseline_accuracy": float(((scored.baseline_score >= .5) == actual).mean()),
            "brier": float(((scored.upward_score - actual) ** 2).mean()),
            "baseline_brier": float(((scored.baseline_score - actual) ** 2).mean())}


def performance_trend(records):
    scored = scored_forecasts(records).sort_values(["target_session", "id"])
    if scored.empty:
        return pd.DataFrame(columns=["Forecast accuracy", "Baseline accuracy"])
    actual = scored.outcome.astype(float)
    return pd.DataFrame({"Forecast accuracy": ((scored.upward_score >= .5) == actual).expanding().mean().to_numpy(),
                         "Baseline accuracy": ((scored.baseline_score >= .5) == actual).expanding().mean().to_numpy()},
                        index=pd.Index(scored.target_session, name="Outcome session"))
