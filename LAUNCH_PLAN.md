# From prototype to paid product

Start with active traders who want useful price and volatility alerts for their watchlists. Sell monitoring and convenience: custom thresholds, reliable delivery, alert history, and controls that reduce notification noise. The current daily research workspace is a prototype for exploring demand; it is not an intraday alert service. Do not market the model as guaranteed profitable predictions. Proposed discovery pricing is Explorer at $0 and Pro at $19/month; test demand and data/delivery costs before committing to it.

## Implemented

- Free research workspace, real daily price history, explicit demo mode, session watchlists, and exports.
- Chronological model validation, baseline comparisons, and indicator/model explanations.
- Pricing concept and a consent-based early-access signup stored locally.

## Before paid launch

1. Choose a commercial market-data plan and confirm display, storage, redistribution, and rate-limit rights. For active-trader alerts, confirm intraday coverage, quote latency, exchange entitlements, and total per-user costs. Replace the daily Yahoo development integration where required.
2. Add hosted authentication and a managed database. Store watchlists per user and test access isolation. Migrate early-access signups with consent records.
3. Integrate Stripe Checkout, verified webhook signatures, and a customer portal. Enforce Pro entitlements server-side from subscription state; a redirect alone must never unlock access. Handle cancellation, failed payments, duplicate events, and refunds.
4. Ship custom price-threshold alerts with persistent watchlists first. Define crossing behavior, session-hours handling, quote freshness, cooldowns, and one-shot/repeating rules. Add scheduling/delivery, retries, deduplication, unsubscribe controls, and verified recipient ownership. Test stale quotes, overnight gaps, and duplicate events before adding volatility alerts.
5. Deploy with TLS, monitoring, backups, privacy/terms pages, and signup deletion support. Review financial-product claims and jurisdiction-specific obligations for the actual service.
6. Evaluate models on repeated chronological holdouts across tickers and regimes. For trading-return analysis include fees, slippage, corporate actions, and survivorship effects. Report poor results; never use demo scores as real performance claims.

## Validate demand

Interview active traders about which thresholds they monitor, required notification speed, preferred delivery channels, and current tools. Measure repeat watchlist use and willingness to pay for the specific alert workflow. Accounts, billing, alerts, and outgoing emails are not implemented in this prototype.
