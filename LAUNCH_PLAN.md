# From prototype to paid product

Start with active traders who want useful price and volatility alerts for their watchlists. Sell monitoring and convenience: custom thresholds, reliable delivery, alert history, and controls that reduce notification noise. The current daily research workspace is a prototype for exploring demand; it is not an intraday alert service. Do not market the model as guaranteed profitable predictions. Proposed discovery pricing is Explorer at $0 and Pro at $19 for 30 days, paid in Bitcoin; test demand and data/delivery costs before committing to it.

## Bitcoin payment configuration

- Payment network: Bitcoin mainnet.
- User-supplied receiving address: `18mJqcLYWSjJHHTw5RznAToPHW8cPqRizz`.
- Receiving URI: `bitcoin:18mJqcLYWSjJHHTw5RznAToPHW8cPqRizz`.
- The address passed Base58Check validation. This verifies the address format, not control of the wallet.
- Configuration is saved in `billing_config.json`; checkout is planned and inactive. The current app has no active payment link or QR code.

## Implemented

- Free research workspace, real daily price history, explicit demo mode, session watchlists, and exports.
- Chronological model validation, baseline comparisons, and indicator/model explanations.
- Pricing concept and a consent-based early-access signup stored locally.

## Before paid launch

1. Choose a commercial market-data plan and confirm display, storage, redistribution, and rate-limit rights. For active-trader alerts, confirm intraday coverage, quote latency, exchange entitlements, and total per-user costs. Replace the daily Yahoo development integration where required.
2. Add hosted authentication and a managed database. Store watchlists per user and test access isolation. Migrate early-access signups with consent records.
3. Integrate a Bitcoin invoice service, such as BTCPay Server, using the merchant's configured wallet. Quote a precise BTC amount for each $19/30-day purchase using an expiring exchange-rate quote. Bind each invoice to an authenticated user; handle underpayment, overpayment, expired invoices, network fees, and refund requests. Verify invoice authenticity, confirmed payment status, and duplicate events server-side before granting access. Never unlock access from a redirect or a user-submitted transaction ID alone. Use prepaid 30-day access with customer-initiated renewal; a Bitcoin address does not enable automatic recurring debits. A static receiving address alone cannot reliably attribute payments to customers; the invoice service and merchant setup are required before enabling checkout. Private wallet keys must remain outside the application.
4. Ship custom price-threshold alerts with persistent watchlists first. Define crossing behavior, session-hours handling, quote freshness, cooldowns, and one-shot/repeating rules. Add scheduling/delivery, retries, deduplication, unsubscribe controls, and verified recipient ownership. Test stale quotes, overnight gaps, and duplicate events before adding volatility alerts.
5. Deploy with TLS, monitoring, backups, privacy/terms pages, and signup deletion support. Review financial-product claims and jurisdiction-specific obligations for the actual service.
6. Evaluate models on repeated chronological holdouts across tickers and regimes. For trading-return analysis include fees, slippage, corporate actions, and survivorship effects. Report poor results; never use demo scores as real performance claims.

## Validate demand

Interview active traders about which thresholds they monitor, required notification speed, preferred delivery channels, and current tools. Measure repeat watchlist use and willingness to pay for the specific alert workflow. Accounts, billing, alerts, and outgoing emails are not implemented in this prototype.
