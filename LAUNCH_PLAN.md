# Current beta launch plan

The active release candidate is **1.0.0-beta.1**. Follow [BETA_RELEASE.md](BETA_RELEASE.md) for concrete deployment, acceptance testing, backups, and rollback.

Implemented: the existing research dashboard and models; private username/password accounts with recovery codes and expiring sessions; persistent watchlists; private forecast journals; condition/crossing alert rules and an in-app event inbox; a background daily worker; server-quoted, account-bound Bitcoin checkout; automatic address observation/confirmation reconciliation; feedback; data export/deletion; public-startup preflight; pinned dependencies; CI; a non-root Docker image; and a Caddy HTTPS/persistent-volume deployment.

The paid configuration is unchanged: Bitcoin mainnet, address `18mJqcLYWSjJHHTw5RznAToPHW8cPqRizz`, $5 for 30 days, a 15-minute invoice window, and 3 canonical-chain confirmations. Free beta access defaults on and real charging defaults off until online payment readiness is verified. The static address serializes identical invoice amounts; unique invoice addresses are a future scaling requirement. No private keys or automatic wallet debits are introduced.

External launch requirements remain: an actual host/domain with HTTPS and persistent storage, a support/privacy/refund contact, a public-use market-data contract and key, operator review of terms/privacy/retention, real online provider/payment checks, and external-browser acceptance on the deployed domain. Deployment credentials and data rights cannot be fabricated by the application. Do not call this publicly deployed until those checks complete.

Future paid-service expansion: verified email or hosted identity, email/push delivery with recipient ownership and unsubscribe controls, an entitled intraday feed, per-user notification cooldowns, managed database migration, unique Bitcoin invoice addresses, ongoing reorganization monitoring, and independently evaluated predictive/trading-return performance.
