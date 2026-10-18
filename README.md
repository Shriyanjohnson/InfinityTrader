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

Enter a symbol, choose Demo or Live, and press **Analyze stock**. Demo starts without credentials and labels simulated prices. Live loads up to five years of daily adjusted Yahoo history and never silently substitutes demo data. The current New York day's candle is excluded; daily prices are not real-time quotes. Switch chart ranges and styles, refresh cached prices, and download an analysis CSV.

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

The tests cover indicators, model evaluation, forecast snapshots and outcome eligibility, signups, dashboard interactions, and Bitcoin billing: purchase ownership, quoted amounts, recipient matching, purchase timing, prior transactions, chain confirmations, replay protection, concurrent checks, and 30-day expiry. Live-provider availability and browser rendering are checked separately.

## Forecast journal

Open the **Forecast journal** tab in Live mode and choose **Save this forecast**. The first snapshot for each symbol and source session is immutable: reruns, repeated saves, and model updates cannot rewrite its score. Snapshots include the server recording time, model family, prediction-code revision hash, input fingerprint, and historical-frequency baseline from the same known outcomes. New revision hashes cover the analytics and calendar code plus core dependency versions. The current dashboard layout, model selection, and Bitcoin billing behavior are preserved.

Refresh analysis after a later completed session to resolve that symbol's pending snapshots. Direction accuracy and Brier loss include only snapshots recorded strictly before the next scheduled exchange session opens. An offline NYSE calendar supplies holidays, exceptional closures, and opening times for supported US regular-session histories with New York exchange timestamps. Missing target quotes leave forecasts pending instead of scoring a multi-day move. Training labels use the same session check for New York histories. Late recordings remain visible and are excluded from metrics. Older settlements with a mismatched target date are flagged and excluded without rewriting original snapshots. Outcomes compare source and target prices from the same adjusted history to handle splits, then stay fixed; provider revisions remain a limitation.

Use **Model version** and **Performance window** to compare saved results. The same filters apply to metrics, the cumulative accuracy chart, table, and CSV export. Accuracy uses a 50% score cutoff, with flat closes classified as non-rising. A 95% Wilson interval shows sampling uncertainty, assuming independent outcomes; serial dependence and selective saving limit that estimate. Small samples do not establish a predictive edge or profitability. The cumulative accuracy chart appears after two eligible outcomes.

The journal is shared by this app instance, with no account isolation. It stores no trades, places no orders, and is separate from billing. Demo data is never saved. SQLite snapshots live at `INFINITY_DATA_DIR/forecast_journal.sqlite3`, or `XDG_DATA_HOME/infinitytrader/forecast_journal.sqlite3` (default `~/.local/share/infinitytrader`). Preserve this file across restarts and keep it out of Git. Recording requires writable persistent storage; storage failures leave analysis available. There is no background scheduler: outcomes update when the corresponding symbol's Live analysis reruns. The tab provides a CSV export of all snapshots for that symbol. Live price histories more than seven calendar days old are flagged on the dashboard.

## Daily in-app alerts

In **Live → Daily alerts**, create rules for adjusted daily close, RSI, relative volume, or ATR as a percentage of price. Choose an inclusive at-or-above/below threshold and either **Condition met** or **Threshold crossing**. A new rule checks the latest completed session immediately. Condition rules can match on each new session; crossing rules require the previous exchange session's value to be strictly on the other side. Missing previous data blocks a crossing. Quotes must match the most recent exchange session before today's New York date, consistent with the app's conservative daily-candle policy. Stale, current-day, unsupported-market, or invalid data cannot trigger events.

Each rule records at most one match per session, including concurrent refreshes; existing events are immutable even if prices are later revised. Pause/resume rules, remove them while retaining past matches, or export their event history to CSV. The workspace supports up to 20 rules per symbol and prevents duplicate configurations. Price thresholds use adjusted prices and should be reviewed after corporate actions. Rules and events are shared by this app instance and stored outside the repository in `INFINITY_DATA_DIR/alerts.sqlite3`, otherwise `XDG_DATA_HOME/infinitytrader/alerts.sqlite3` (default `~/.local/share/infinitytrader`). Preserve this database across restarts.

These alerts run only when that symbol's Live analysis reruns, including **Refresh data**; they show matching rules, record history, and show an in-app notice for new matches. There is no background polling, email, push delivery, order placement, account isolation, or historical backfill. Demo mode never creates or triggers saved alerts. Provider failures or storage errors do not create matches or block the research dashboard. Background monitoring and notification delivery remain planned Pro capabilities.

## Model

The model estimates whether the next session's close is higher using 18 historical return, momentum, volatility, volume, trend, and candle features. Live analysis requests up to five years of adjusted daily prices. Three chronological folds within the earliest 80% select historical frequency, regularized logistic regression, or random forest by Brier loss (lower is better). Scaling is fitted inside each training fold. The selected family stays fixed while the final 20% are evaluated across three successive blocks. Each block refits on earlier known outcomes, excluding one boundary session to prevent label leakage. A separate forecast model uses all known outcomes afterward. The dashboard reports accuracy and Brier loss against a baseline refitted on the same training windows; it can select historical frequency when learned models add no signal during selection.

RSI uses exponentially smoothed gains/losses; ATR includes overnight gaps. Indicators use historical data only. Live analysis conservatively excludes the current New York calendar day's candle, even after market close, and forecasts from the last completed prior session. Model scores are uncalibrated; three historical evaluation blocks are limited evidence and do not establish profitability after costs. This app does not analyze options chains, premiums, liquidity, or expiry calendars and does not generate arbitrary option strikes.

## Product status

Explorer is implemented. Pricing is $5 for 30 days, payable in Bitcoin at a server-obtained invoice-time exchange rate. The pricing page remains a launch preview; customer checkout is disabled. Public merchant settings, including the supplied mainnet receiving address, are in `billing_config.json`. No private keys belong in this project. Early-access signups require consent and are saved in SQLite under `INFINITY_DATA_DIR`, or `XDG_DATA_HOME/infinitytrader`. Emails are not sent. Keep user databases outside source control and support deletion requests.

## Bitcoin verification backend

`billing.py` implements invoice creation and blockchain verification. It must be called using a trusted authenticated account ID, a server-obtained BTC/USD rate, and a database outside the repository; it is not yet connected to customer checkout or dashboard access controls.

- Each invoice records the receiving address, exact satoshi amount for $5 (rounded up by at most one satoshi), server creation/expiry times, chain height, and existing unconfirmed transactions.
- The quote lasts 15 minutes. Existing confirmed or unconfirmed payments cannot be reused. Matching amounts on the static address are reserved so overlapping purchases cannot claim the same payment.
- Verification obtains transaction outputs, block status, canonical block hash, and chain height from the HTTPS blockchain API; a supplied transaction ID alone never grants access.
- The recipient and exact amount must match. A newly confirmed payment must postdate the purchase and be mined inside its quote window, or have been observed by the server in that window before confirming later. Block timestamps are approximate; this deliberately conservative policy can require manual review for legitimate clock/skew or replacement-transaction cases.
- Three confirmations are required. Access lasts 30 days from verification; early renewal adds 30 days to existing access. Atomic writes and a unique paid transaction ID prevent replay and duplicate extension from concurrent checks.
- Already-paid invoices return their original entitlement on retry. Three-confirmation settlement is treated as final by this prototype; ongoing reorganization monitoring/revocation is not implemented.

`BlockstreamClient` needs network access to `blockstream.info`. Blockchain API failures leave access locked. A static-address design limits concurrency and cannot independently prove the sender's identity. Before public launch, connect verified sign-in, obtain a reliable exchange-rate quote, provide payment observation/reconciliation and manual review, and migrate to unique per-purchase addresses or an invoice service for scale. An observed payment awaiting confirmation retains its amount reservation until resolved.

Before paid launch, connect authentication, the verifier, and dashboard entitlements; add a managed user database, monitoring, and privacy/terms pages. Select a market/news-data provider whose plan permits commercial display and redistribution. The Yahoo development integration does not establish those rights. See [LAUNCH_PLAN.md](LAUNCH_PLAN.md).
