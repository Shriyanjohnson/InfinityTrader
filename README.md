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

The 37 tests cover indicators, model evaluation, signups, dashboard interactions, and Bitcoin billing: purchase ownership, quoted amounts, recipient matching, purchase timing, prior transactions, chain confirmations, replay protection, concurrent checks, and 30-day expiry. Live-provider availability and browser rendering are checked separately.

## Model

The random forest predicts whether the next session's close is higher. Evaluation trains on the earliest 80% of known outcomes, excludes one boundary session whose label would reach into validation, and tests the final 20% in chronological order. A separate forecast model uses all known outcomes. The dashboard compares validation accuracy with a majority-class baseline.

RSI uses exponentially smoothed gains/losses; ATR includes overnight gaps. Indicators use historical data only. Model scores are uncalibrated and one holdout is limited evidence. This app does not analyze options chains, premiums, liquidity, or expiry calendars and does not generate arbitrary option strikes.

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
