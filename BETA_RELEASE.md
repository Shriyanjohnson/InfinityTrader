# Beta release candidate: 1.0.0-beta.1

The code is prepared for a controlled public beta. A public launch additionally requires the operator's actual hosting account/domain, support contact, commercial data entitlement, and successful online checks. Passing fixture tests or building the container does not establish those facts.

## Release configuration

1. Provision a single persistent Linux host with Docker Compose, at least 2 CPUs and 2 GB RAM, and outbound HTTPS. Do not use ephemeral-only hosting or multiple independent SQLite replicas.
2. Point the real beta domain at that host. Allow public ports 80/443; keep 8501 private. Copy `.env.example` to `.env` and set `PUBLIC_HOST`, `INFINITY_PUBLIC_URL`, and `INFINITY_SUPPORT_EMAIL`.
3. Obtain a Twelve Data plan explicitly allowing the intended public display/storage/redistribution and request volume. Put its key securely in `TWELVEDATA_API_KEY`; set `INFINITY_MARKET_PROVIDER=twelvedata`, `INFINITY_LIVE_DATA_ENABLED=1`, and `INFINITY_DATA_LICENSE_ACK=1` only after confirming rights. Yahoo remains a development-only integration.
4. Adopt the app's beta terms/privacy notice, a monitored support/refund process, and 30-day backup retention; then set `INFINITY_OPERATOR_TERMS_ACK=1`. Configure infrastructure logs consistently with the privacy notice. No advertising or email delivery service is installed.
5. Keep `INFINITY_FREE_BETA=1` and `INFINITY_CHECKOUT_ENABLED=0` for the first test cohort. All signed-in testers get the beta background features; nobody is charged. Optional paid testing requires `FREE_BETA=0`, `CHECKOUT_ENABLED=1`, and successful chain/rate checks. The paid plan remains $5/30 days; paid mode gates Live research and background checks on the server-side entitlement.
6. Run `docker compose up --build -d`. Startup validates public configuration, persistent storage, and a real provider request; when charging is enabled it also validates a chain lookup and BTC/USD quote. Caddy obtains TLS for the configured domain. Follow `docker compose logs` until the app is healthy.
7. Verify from outside the host that HTTPS works, no direct application port is exposed, registration/recovery work, and two distinct users cannot see each other's watchlists/forecasts/alerts. Monitor `worker-status.json` and service logs; the supervisor terminates if a required process dies so Docker can restart it.

## Tester acceptance flow

- Guest: open Demo, switch charts, and download simulated analysis. A guest selecting Live must be asked to sign in.
- Account: register with consent and a unique password, save the recovery code, sign out/in, then recover once with that code. The old code and old sessions must stop working.
- Privacy: use two test accounts, create different watchlists/rules/forecasts, and verify isolation. Export one account; it must contain no other account's records or auth hashes.
- Live: request a supported US equity, verify provider badge/date, indicators, baseline metrics, and CSV. Data errors must stay inside a safe message without exposing keys or credentials.
- Alerts: create a condition/crossing rule, verify one match per rule/session, pause/resume, remove while retaining history, and export. Leave the browser closed for a worker cycle and return to the private inbox. Today's candle, stale data, and missing previous sessions cannot generate matches.
- Forecasts: save one snapshot, verify repeat saves do not rewrite it, then review its scheduled next-session outcome after that session becomes available. Apply filters and confirm metrics/table/export agree.
- Feedback/privacy: submit feedback, confirm the operator can review it, export research data, and test account deletion with password confirmation.
- Payments, only when explicitly enabled: request an account-bound invoice with a fresh server quote, verify the exact address/satoshis/window, observe payment while the browser is closed, and require three confirmations before access. Test reuse, wrong amount/address, stale payment, expiry, and renewal. No real payment has been verified merely by the automated fixtures. Review small-value testing and refunds with the wallet owner; this release never sends funds.

## Operations and rollback

Back up the persistent volume to separate protected storage using `manage.py backup`; schedule it daily on the host and expire snapshots older than 30 days. Test restore into an isolated directory with `PRAGMA integrity_check` before admitting testers. To restore, stop all services, replace the data volume contents from a verified snapshot preserving ownership/permissions, revoke restored sessions with `DELETE FROM sessions` in the restored accounts database, and restart. Never restore test fixtures over real account data.

Keep a copy of the previous image and a pre-upgrade database snapshot. Roll back the image and matching database snapshot together while services are stopped. Do not delete persistent volumes with `docker compose down -v`. Schema setup is additive; old shared prototype research databases stay at the root and are not exposed to beta users. Only the operator should review and copy any legacy research into a known owner's private directory, without overwriting existing account files.

The beta does not provide intraday alerts, email/push delivery, verified email recovery, multi-region scaling, automatic refunds, unique Bitcoin invoice addresses, broker trading, options analysis, or guaranteed predictive returns. Use the displayed capabilities and known limits in tester communications.
