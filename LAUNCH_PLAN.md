# From prototype to paid product

Start with individual investors who want a concise daily stock-research workspace. Sell workflow and convenience: saved watchlists, alerts, and research summaries. Do not market the model as guaranteed profitable predictions. Proposed discovery pricing is Explorer at $0 and Pro at $19/month; test demand with early-access signups before committing to it.

## Implemented

- Free research workspace, real daily price history, explicit demo mode, session watchlists, and exports.
- Chronological model validation, baseline comparisons, and indicator/model explanations.
- Pricing concept and a consent-based early-access signup stored locally.

## Before paid launch

1. Choose a commercial market-data plan and confirm display, storage, redistribution, and rate-limit rights. Replace the Yahoo development integration where required.
2. Add hosted authentication and a managed database. Store watchlists per user and test access isolation. Migrate early-access signups with consent records.
3. Integrate Stripe Checkout, verified webhook signatures, and a customer portal. Enforce Pro entitlements server-side from subscription state; a redirect alone must never unlock access. Handle cancellation, failed payments, duplicate events, and refunds.
4. Ship one useful Pro feature, such as persistent watchlists plus price alerts. Add alert scheduling/delivery, deduplication, unsubscribe controls, and verified recipient ownership.
5. Deploy with TLS, monitoring, backups, privacy/terms pages, and signup deletion support. Review financial-product claims and jurisdiction-specific obligations for the actual service.
6. Evaluate models on repeated chronological holdouts across tickers and regimes. For trading-return analysis include fees, slippage, corporate actions, and survivorship effects. Report poor results; never use demo scores as real performance claims.

## Validate demand

Interview prospective users about their research routine and measure signup-to-active-research conversion. Look for repeat use and willingness to pay for the planned workflow. Accounts, billing, alerts, and outgoing emails are not implemented in this prototype.
