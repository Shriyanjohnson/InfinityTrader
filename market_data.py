"""Daily provider adapter. Public live access requires an operator's data-rights acknowledgement."""
import os
import re

import pandas as pd
import requests
import yfinance as yf

from analytics import completed_history
from settings import development, live_enabled


def get_history(symbol):
    if not re.fullmatch(r"[A-Z^][A-Z0-9.^-]{0,11}", symbol):
        raise ValueError("Invalid symbol.")
    if not live_enabled():
        raise ValueError("Public live data is not enabled by the operator.")
    if not development():
        import accounts
        accounts.budget("provider-total", 100)
    provider = os.environ.get("INFINITY_MARKET_PROVIDER", "yahoo" if development() else "twelvedata")
    if provider == "yahoo" and development():
        history = yf.Ticker(symbol).history(period="5y", auto_adjust=True, raise_errors=True, timeout=12)
    elif provider == "twelvedata":
        key = os.environ.get("TWELVEDATA_API_KEY")
        if not key:
            raise ValueError("The live-data provider is not configured.")
        try:
            response = requests.get("https://api.twelvedata.com/time_series", params={
                "symbol": symbol, "interval": "1day", "outputsize": 1250, "order": "ASC", "adjust": "all"},
                headers={"Authorization": f"apikey {key}"}, timeout=15)
            response.raise_for_status()
            body = response.json()
            rows = body.get("values")
            if body.get("status") == "error" or not isinstance(rows, list):
                raise ValueError
            if body.get("meta", {}).get("exchange_timezone") != "America/New_York":
                raise ValueError
            history = pd.DataFrame(rows).rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
            history.index = pd.to_datetime(history.pop("datetime")).dt.tz_localize("America/New_York")
        except (requests.RequestException, ValueError, KeyError, TypeError):
            raise ValueError("Daily prices are unavailable. Try again later.") from None
    else:
        raise ValueError("Configure the supported licensed provider for public live data.")
    if history.empty:
        raise ValueError("No history returned for this symbol.")
    return completed_history(history)
