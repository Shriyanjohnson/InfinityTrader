# InfinityTrader

A Streamlit market-research prototype for active traders, with a dark dashboard, stock watchlist, price/volume charts, technical indicators, next-session model signals, and an early-access pricing page. The planned Pro product focuses on custom price and volatility alerts; alert scheduling and delivery are not implemented yet.

## Run

Use Python 3.11 or newer:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run main.py
```

Enter a symbol, choose Demo or Live, and press **Analyze stock**. Demo starts without credentials and labels simulated prices. Live loads one year of daily adjusted Yahoo history and never silently substitutes demo data. Daily prices can include an unfinished session and are not real-time quotes. Switch chart ranges and styles, refresh cached prices, and download an analysis CSV.

The sidebar watchlist lasts for the browser session. News is optional: configure `NEWSAPI_KEY` through secure environment settings, then request headlines in Live mode. News sentiment is independent of the price model. Never commit secrets or `.env` files.

## Cloud workspace

```sh
cd /workspace/InfinityTrader
export XDG_CACHE_HOME=/workspace/.cache/InfinityTrader
export XDG_DATA_HOME=/workspace/.local/share/InfinityTrader
/workspace/.venvs/InfinityTrader/bin/python -m streamlit run main.py --server.headless true --server.address 127.0.0.1 --server.port 8501
```

## Validate

```sh
python -m unittest discover -s tests -v
```

Tests cover indicator edge cases, chronological evaluation boundaries, unknown future labels, single-class forecasts, signups, dashboard interactions, and graceful provider failure. Live-provider availability and browser rendering are checked separately.

## Model

The random forest predicts whether the next session's close is higher. Evaluation trains on the earliest 80% of known outcomes, excludes one boundary session whose label would reach into validation, and tests the final 20% in chronological order. A separate forecast model uses all known outcomes. The dashboard compares validation accuracy with a majority-class baseline.

RSI uses exponentially smoothed gains/losses; ATR includes overnight gaps. Indicators use historical data only. Model scores are uncalibrated and one holdout is limited evidence. This app does not analyze options chains, premiums, liquidity, or expiry calendars and does not generate arbitrary option strikes.

## Product status

Explorer is implemented. The pricing page proposes $19 for 30 days of Pro access, payable in Bitcoin at an invoice-time exchange rate. Pro features and checkout are planned; the app does not request transfers or verify payments yet. Public merchant settings, including the user-supplied mainnet receiving address, are stored in `billing_config.json`. No private keys belong in this project. Early-access signups require consent and are saved in SQLite under `INFINITY_DATA_DIR`, or `XDG_DATA_HOME/infinitytrader`. Emails are not sent. The database is outside source control; protect it, preserve it across deploys, and support deletion requests.

Before paid launch, implement authentication, a managed user database, verified billing and subscription entitlements, monitoring, and privacy/terms pages. Select a market/news-data provider whose plan permits commercial display and redistribution. The Yahoo development integration does not establish those rights. See [LAUNCH_PLAN.md](LAUNCH_PLAN.md).
