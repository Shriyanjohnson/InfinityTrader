"""Market indicators and chronological model evaluation, independent of the UI."""

from dataclasses import dataclass
import hashlib

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score

FEATURES = ["Return", "RSI", "ATR_pct", "SMA20_gap", "SMA50_gap", "Volume_ratio"]
OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def normalize_history(history: pd.DataFrame) -> pd.DataFrame:
    if history is None or history.empty:
        raise ValueError("No price history returned. Check the symbol or try again later.")
    if not set(OHLCV).issubset(history.columns):
        raise ValueError("The data provider returned incomplete price history.")
    data = history[OHLCV].copy()
    data.index = pd.to_datetime(data.index)
    data = data[~data.index.duplicated(keep="last")].sort_index()
    data = data.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    valid = (data[["Open", "High", "Low", "Close"]] > 0).all(axis=1)
    valid &= (data["Volume"] >= 0) & (data["High"] >= data[["Open", "Close", "Low"]].max(axis=1))
    valid &= data["Low"] <= data[["Open", "Close"]].min(axis=1)
    data = data.loc[valid]
    if len(data) < 100:
        raise ValueError("At least 100 trading sessions are needed for a useful analysis.")
    return data


def add_indicators(history: pd.DataFrame) -> pd.DataFrame:
    data = normalize_history(history)
    close = data["Close"]
    change = close.diff()
    gain = change.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    data["RSI"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    data.loc[(loss == 0) & (gain > 0), "RSI"] = 100
    data.loc[(loss == 0) & (gain == 0), "RSI"] = 50
    previous = close.shift(1)
    true_range = pd.concat([data["High"] - data["Low"],
                            (data["High"] - previous).abs(),
                            (data["Low"] - previous).abs()], axis=1).max(axis=1)
    data["ATR"] = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    data["SMA_20"] = close.rolling(20).mean()
    data["SMA_50"] = close.rolling(50).mean()
    data["OBV"] = (np.sign(change).fillna(0) * data["Volume"]).cumsum()
    data["Return"] = close.pct_change()
    data["ATR_pct"] = data["ATR"] / close
    data["SMA20_gap"] = close / data["SMA_20"] - 1
    data["SMA50_gap"] = close / data["SMA_50"] - 1
    average_volume = data["Volume"].rolling(20).mean()
    data["Volume_ratio"] = data["Volume"] / average_volume.replace(0, np.nan)
    return data


def supervised_data(data: pd.DataFrame):
    """Keep features with known next-session outcomes; never label the final row."""
    future = data["Close"].shift(-1)
    target = (future > data["Close"]).astype(int)
    valid = data[FEATURES].notna().all(axis=1) & future.notna()
    valid &= np.isfinite(data[FEATURES]).all(axis=1)
    return data.loc[valid, FEATURES], target.loc[valid]


def chronological_split(features, labels):
    if len(features) < 40:
        raise ValueError("Not enough complete sessions to evaluate the model.")
    split = int(len(features) * .8)
    # Purge the boundary row: its label depends on the first validation close.
    return features.iloc[:split - 1], features.iloc[split:], labels.iloc[:split - 1], labels.iloc[split:]


@dataclass
class ModelResult:
    upward_score: float
    accuracy: float
    baseline: float
    validation_sessions: int
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    importance: pd.Series


def upward_score(model, features):
    classes = list(model.classes_)
    return float(model.predict_proba(features)[0, classes.index(1)]) if 1 in classes else 0.0


def analyze(data: pd.DataFrame) -> ModelResult:
    features, labels = supervised_data(data)
    train_x, test_x, train_y, test_y = chronological_split(features, labels)
    def new_model():
        return RandomForestClassifier(n_estimators=150, max_depth=5,
                                      min_samples_leaf=4, random_state=42, n_jobs=2)
    evaluator = new_model().fit(train_x, train_y)
    accuracy = accuracy_score(test_y, evaluator.predict(test_x))
    majority = int(train_y.mean() >= .5)
    baseline = accuracy_score(test_y, np.full(len(test_y), majority))
    # Only after evaluation, fit a separate forecast model on all known outcomes.
    forecast = new_model().fit(features, labels)
    latest = data[FEATURES].iloc[[-1]]
    if not np.isfinite(latest).all(axis=None):
        raise ValueError("The latest session has incomplete indicators.")
    return ModelResult(upward_score(forecast, latest), accuracy, baseline, len(test_y),
                       train_x.index[-1], test_x.index[0],
                       pd.Series(forecast.feature_importances_, index=FEATURES).sort_values(ascending=False))


def demo_history(symbol: str, sessions: int = 252) -> pd.DataFrame:
    """Reproducible synthetic OHLCV. Never use this as market data."""
    seed = int.from_bytes(hashlib.sha256(symbol.encode()).digest()[:4], "big")
    rng = np.random.default_rng(seed)
    close = (80 + seed % 260) * np.exp(np.cumsum(rng.normal(.0005, .015, sessions)))
    opened = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, .003, sessions))
    spread = rng.uniform(.002, .016, sessions)
    today = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
    index = pd.bdate_range(end=today - pd.offsets.BDay(1), periods=sessions)
    return pd.DataFrame({"Open": opened, "High": np.maximum(opened, close) * (1 + spread),
                         "Low": np.minimum(opened, close) * (1 - spread), "Close": close,
                         "Volume": rng.integers(4_000_000, 35_000_000, sessions)}, index=index)
