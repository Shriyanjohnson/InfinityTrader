"""Market indicators and chronological model evaluation, independent of the UI."""

from dataclasses import dataclass
import hashlib

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from market_sessions import session_matches

FEATURES = ["Return", "RSI", "ATR_pct", "SMA20_gap", "SMA50_gap", "Volume_ratio",
            "Return_lag1", "Return_lag2", "Momentum5", "Momentum20",
            "Volatility10", "Volatility20", "RSI_delta5", "MACD_pct",
            "Range_pct", "Close_position", "Gap_open", "Body_pct"]
OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def completed_history(history: pd.DataFrame, now=None) -> pd.DataFrame:
    """Conservatively exclude today's candle, which may still be changing."""
    cutoff = pd.Timestamp.now(tz="America/New_York") if now is None else pd.Timestamp(now)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("America/New_York")
    cutoff = cutoff.tz_convert("America/New_York").date()
    return history.loc[pd.to_datetime(history.index).date < cutoff].copy()


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
    data["Return_lag1"] = data["Return"].shift(1)
    data["Return_lag2"] = data["Return"].shift(2)
    data["Momentum5"] = close.pct_change(5)
    data["Momentum20"] = close.pct_change(20)
    data["Volatility10"] = data["Return"].rolling(10).std()
    data["Volatility20"] = data["Return"].rolling(20).std()
    data["RSI_delta5"] = data["RSI"].diff(5)
    data["MACD_pct"] = (close.ewm(span=12, adjust=False).mean()
                        - close.ewm(span=26, adjust=False).mean()) / close
    candle_range = data["High"] - data["Low"]
    data["Range_pct"] = candle_range / close
    data["Close_position"] = ((close - data["Low"]) / candle_range.replace(0, np.nan)).fillna(.5)
    data["Gap_open"] = data["Open"] / previous - 1
    data["Body_pct"] = close / data["Open"] - 1
    return data


def supervised_data(data: pd.DataFrame):
    """Keep features with known next-session outcomes; never label the final row."""
    future = data["Close"].shift(-1)
    target = (future > data["Close"]).astype(int)
    valid = data[FEATURES].notna().all(axis=1) & future.notna()
    valid &= np.isfinite(data[FEATURES]).all(axis=1)
    if str(data.index.tz) == "America/New_York":
        sessions = data.index.strftime("%Y-%m-%d")
        matches = [session_matches(source, target) for source, target in zip(sessions[:-1], sessions[1:])]
        valid &= pd.Series(matches + [False], index=data.index)
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
    model_name: str
    brier: float
    baseline_brier: float
    folds: pd.DataFrame
    selection_scores: pd.Series


def upward_score(model, features):
    classes = list(model.classes_)
    return float(model.predict_proba(features)[0, classes.index(1)]) if 1 in classes else 0.0


MODEL_NAMES = ("Historical frequency", "Regularized logistic regression", "Random forest")


def fitted_model(name, features, labels):
    # A one-class history is valid; logistic regression cannot fit it.
    if name == MODEL_NAMES[0] or labels.nunique() == 1:
        model = DummyClassifier(strategy="prior")
    elif name == MODEL_NAMES[1]:
        model = make_pipeline(StandardScaler(), LogisticRegression(C=.1, max_iter=1000, random_state=42))
    elif name == MODEL_NAMES[2]:
        model = RandomForestClassifier(n_estimators=150, max_depth=5,
                                       min_samples_leaf=4, random_state=42, n_jobs=2)
    else:
        raise ValueError("Unknown prediction model.")
    return model.fit(features, labels)


def probabilities(model, features):
    classes = list(model.classes_)
    if 1 not in classes:
        return np.zeros(len(features))
    return model.predict_proba(features)[:, classes.index(1)]


def select_model(features, labels):
    """Select only on earlier training folds, minimizing out-of-time Brier loss."""
    scores = {}
    splits = list(TimeSeriesSplit(n_splits=3, gap=1).split(features))
    for name in MODEL_NAMES:
        outcomes, estimates = [], []
        for train, test in splits:
            model = fitted_model(name, features.iloc[train], labels.iloc[train])
            outcomes.extend(labels.iloc[test])
            estimates.extend(probabilities(model, features.iloc[test]))
        scores[name] = brier_score_loss(outcomes, estimates)
    # The frequency baseline wins exact ties, including one-class histories.
    return min(scores, key=scores.get), pd.Series(scores, name="Training-only Brier loss")


def walk_forward_splits(features):
    """Evaluate the final 20% in three blocks, purging one label boundary."""
    if len(features) < 40:
        raise ValueError("Not enough complete sessions to evaluate the model.")
    start = int(len(features) * .8)
    for test in np.array_split(np.arange(start, len(features)), 3):
        yield np.arange(test[0] - 1), test


def analyze(data: pd.DataFrame) -> ModelResult:
    features, labels = supervised_data(data)
    train_x, test_x, train_y, _ = chronological_split(features, labels)
    name, selection_scores = select_model(train_x, train_y)
    estimates, baseline_estimates, outcomes, folds = [], [], [], []
    for train, test in walk_forward_splits(features):
        evaluator = fitted_model(name, features.iloc[train], labels.iloc[train])
        predicted = probabilities(evaluator, features.iloc[test])
        frequency = float(labels.iloc[train].mean())
        actual = labels.iloc[test]
        estimates.extend(predicted)
        baseline_estimates.extend(np.full(len(test), frequency))
        outcomes.extend(actual)
        folds.append({"Train through": features.index[train[-1]],
                      "Test from": features.index[test[0]], "Test through": features.index[test[-1]],
                      "Sessions": len(test), "Accuracy": accuracy_score(actual, predicted >= .5),
                      "Baseline accuracy": accuracy_score(actual, np.full(len(test), frequency >= .5))})
    estimates, baseline_estimates = np.asarray(estimates), np.asarray(baseline_estimates)
    accuracy = accuracy_score(outcomes, estimates >= .5)
    baseline = accuracy_score(outcomes, baseline_estimates >= .5)
    # Model family is frozen before final evaluation; refit the forecast afterward.
    forecast = fitted_model(name, features, labels)
    latest = data[FEATURES].iloc[[-1]]
    if not np.isfinite(latest).all(axis=None):
        raise ValueError("The latest session has incomplete indicators.")
    if hasattr(forecast, "feature_importances_"):
        weights = forecast.feature_importances_
    elif hasattr(forecast, "named_steps"):
        weights = np.abs(forecast.named_steps["logisticregression"].coef_[0])
        weights = weights / weights.sum() if weights.sum() else weights
    else:
        weights = np.zeros(len(FEATURES))
    return ModelResult(upward_score(forecast, latest), accuracy, baseline, len(outcomes),
                       train_x.index[-1], test_x.index[0],
                       pd.Series(weights, index=FEATURES).sort_values(ascending=False), name,
                       brier_score_loss(outcomes, estimates), brier_score_loss(outcomes, baseline_estimates),
                       pd.DataFrame(folds), selection_scores)


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
