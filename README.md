# InfinityTrader — 1.0.0-beta.1

A stock-research beta with the existing dashboard, daily direction models, private accounts, forecast journals, daily alerts, and purchase-linked Bitcoin access. This repository contains a release candidate; it is not evidence of a public deployment or a predictive trading edge.

## What testers can do

- Explore eight clearly simulated Demo stocks without an account.
- Create a username/password account, save a one-time recovery code, and sign in for private research. Argon2id hashes protect passwords and recovery codes; opaque sessions expire after 12 hours. A browser reload may require signing in again.
- Keep a persistent account watchlist of up to 20 symbols. Licensed Live analysis includes adjusted daily charts, indicators, model-family selection, chronological evaluation, baseline comparison, and CSV exports.
- Save immutable next-session forecast snapshots. Exchange-calendar checks prevent missing quotes from becoming multi-day labels or outcomes. Compare model versions, date windows, accuracy uncertainty, and cumulative performance.
- Create daily price, RSI, relative-volume, or ATR rules with condition/crossing triggers, pause/resume, deduplicated history, and CSV exports. The background worker checks private rules and resolves forecast outcomes while browsers are closed. Matches appear in the app; no email, push notification, intraday feed, brokerage connection, or order execution is provided.
- Send private beta feedback; export account research data or delete the account after password confirmation.
- When the operator enables real checkout, pay the configured **$5 for 30 days in Bitcoin**. Invoices belong to authenticated accounts. Address/amount, purchase timing, canonical blocks, three confirmations, and replay checks govern access. The independent reconciliation process observes matching address transactions while browsers are closed. The receiving address in `billing_config.json` is preserved; no private keys are stored.

Free beta access is **on by default** and real checkout is **off by default**. This does not change the configured paid price. Turn free beta off and checkout on only after online payment checks, support/refund policy, and payment monitoring are verified. Paid mode requires unexpired confirmed access for both Live research and background checks; Demo and account/privacy controls remain free. A static receiving address serializes identical invoice amounts and is unsuitable for high-throughput paid checkout; use unique invoice addresses for scale.

## Run locally

Use Python 3.12:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.lock
export INFINITY_DATA_DIR=/absolute/private/path/infinity-data
python service.py
```

The supervisor runs the web app, daily worker, and payment observer. Demo, account creation, recovery, feedback, export, and deletion work without provider keys. Live data stays disabled until configured. For editing UI code, run `streamlit run main.py` and `python -m worker` separately; the web command alone does not supply background monitoring.

Existing developer workflows can use `INFINITY_MODE=development` for Yahoo development data and legacy shared storage. **Never expose development mode publicly.** Existing root-level research databases are preserved and are not automatically assigned to new accounts. New beta account files are stored under `INFINITY_DATA_DIR/users/<opaque-account-id>/`.

## Public deployment

See [BETA_RELEASE.md](BETA_RELEASE.md). Copy `.env.example` to a private `.env`, supply your real domain/support contact, a Twelve Data API key and plan allowing public display, and explicitly adopt the data/terms acknowledgements. The app does not establish commercial data rights on your behalf. Optional NewsAPI headlines also require a suitable plan and `INFINITY_NEWS_LICENSE_ACK=1`.

```sh
python manage.py preflight --public --online
# On the deployment host, after configuring .env and DNS:
docker compose up --build -d
```

The Compose deployment uses a persistent volume and Caddy HTTPS; the application port is not published directly. Public container startup runs release preflight and refuses missing settings. Use one application replica on one persistent host for this SQLite beta. The initial cohort is capped at 200 accounts by default. Background cycles share provider fetches and rotate through at most 100 distinct symbols per cycle; the default cycle interval is 15 minutes. This is daily research, without an intraday latency guarantee. Size the provider plan for the cohort and monitor worker errors/backlog.

## Verify

```sh
python -m pip check
python -m unittest discover -s tests -v
python manage.py preflight --public --online
```

Tests cover model causality, calendar gaps, forecast scoring, account/session security, privacy boundaries, recovery, worker behavior, alert concurrency, backups, provider adapters, checkout ownership, blockchain matching, and access expiry. Controlled provider/chain fixtures do not prove live credentials, a real payment, or public availability. The CI workflow runs the same local suite.

## Data, privacy, and operations

`INFINITY_DATA_DIR` contains private account credentials/session hashes, per-account research databases, a payment ledger, worker status, and a persisted Streamlit cookie secret. Keep it outside Git and back it up. Defaults use `XDG_DATA_HOME/infinitytrader` (otherwise `~/.local/share/infinitytrader`). Operators must provide persistent storage, a monitored support contact, backups with a 30-day retention policy, and an account-deletion response process. Terms/privacy notices are available in **Beta guide & feedback** and must be reviewed by the operator before publication.

```sh
python manage.py backup /separate/private/backup-directory
python manage.py feedback
```

Backups use SQLite's consistent backup API and integrity checks. Account export includes only the authenticated account's research and feedback, never password/session hashes or other users' data. Deletion revokes sessions and removes research/feedback; pseudonymous payment records may be retained for reconciliation. Recovery codes are shown once and rotate after password recovery. No email reset service is provided.

## Model limits

Eighteen causal features feed historical frequency, standardized logistic regression, and random forest. Earlier chronological folds choose the family by Brier loss; three later blocks evaluate it with expanding refits and boundary purges. Latest forecasts are fitted afterward on known outcomes. New York data uses scheduled next-session labels. Live analysis excludes today's entire New York candle, including after close. Scores remain uncalibrated. Historical testing has not demonstrated an edge over the baseline; see [MODEL_EVALUATION.md](MODEL_EVALUATION.md). No options chains, option strikes, trading strategy execution, or profitability claims are included.
