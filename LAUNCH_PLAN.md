# From prototype to paid product

Start with active traders who want useful price and volatility alerts for their watchlists. Sell monitoring and convenience: custom thresholds, reliable delivery, alert history, and controls that reduce notification noise. The current daily research workspace is a prototype for exploring demand; it is not an intraday alert service. Do not market the model as guaranteed profitable predictions. The selected paid-access price is $5 for 30 days, paid in Bitcoin; validate that data and delivery costs fit this price.

## Bitcoin payment configuration

- Payment network: Bitcoin mainnet.
- User-supplied receiving address: `18mJqcLYWSjJHHTw5RznAToPHW8cPqRizz`.
- Receiving URI: `bitcoin:18mJqcLYWSjJHHTw5RznAToPHW8cPqRizz`.
- The address passed Base58Check validation. This verifies the address format, not control of the wallet.
- Configuration is saved in `billing_config.json`: $5 for 30 days, a 15-minute quote window, and 3 required confirmations. Checkout remains inactive, with no customer payment link or QR code.

## Implemented

- Free research workspace, real daily price history, explicit demo mode, session watchlists, and exports.
- Chronological model validation, baseline comparisons, and indicator/model explanations.
- Pricing concept and a consent-based early-access signup stored locally.
- Bitcoin verification backend: account-bound invoices, purchase-window matching, recipient/amount validation, canonical-chain confirmation checks, transaction replay protection, and 30-day entitlements. Tests exercise the backend with controlled blockchain responses; this is not proof of live payment verification.

## Before paid launch

1. Choose a commercial market-data plan and confirm display, storage, redistribution, and rate-limit rights. For active-trader alerts, confirm intraday coverage, quote latency, exchange entitlements, and total per-user costs. Replace the daily Yahoo development integration where required.
2. Add hosted authentication and a managed database. Store watchlists per user and test access isolation. Migrate early-access signups with consent records.
3. Connect verified accounts and dashboard access controls to `billing.py`, using a trusted server-side exchange rate for each $5/30-day quote and a private persistent billing database. Enable the `blockstream.info` network requirement and test live chain lookups before enabling customer checkout. Run a reconciliation worker so on-time broadcasts are observed even if the user closes the browser. Resolve expired, replaced, underpaid/overpaid, or indefinitely unconfirmed payments through manual review; add refund handling. The prototype serializes equal amounts on the static address and cannot prove the sender's identity from timestamps. For scalable concurrent checkout, use unique invoice addresses via a Bitcoin invoice service such as BTCPay Server. Never unlock access from a redirect or a submitted transaction ID alone. Access renews through customer-initiated payments; no automatic wallet debits. Keep private keys outside the application.
4. Ship custom price-threshold alerts with persistent watchlists first. Define crossing behavior, session-hours handling, quote freshness, cooldowns, and one-shot/repeating rules. Add scheduling/delivery, retries, deduplication, unsubscribe controls, and verified recipient ownership. Test stale quotes, overnight gaps, and duplicate events before adding volatility alerts.
5. Deploy with TLS, monitoring, backups, privacy/terms pages, and signup deletion support. Review financial-product claims and jurisdiction-specific obligations for the actual service.
6. Evaluate models on repeated chronological holdouts across tickers and regimes. For trading-return analysis include fees, slippage, corporate actions, and survivorship effects. Report poor results; never use demo scores as real performance claims.

## Validate demand

Interview active traders about which thresholds they monitor, required notification speed, preferred delivery channels, and current tools. Measure repeat watchlist use and willingness to pay for the alert workflow. Account sign-in, customer checkout, dashboard access enforcement, alerts, and outgoing emails are not connected or implemented in this prototype. The billing verifier is implemented and tested separately.
