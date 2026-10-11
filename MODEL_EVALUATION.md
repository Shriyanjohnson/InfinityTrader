# Model evaluation — October 11, 2026

This change expands causal inputs from 6 to 18, compares three fixed model families using earlier chronological folds, and evaluates the selected family across three later blocks. It improves evaluation and score reliability; it does not demonstrate a profitable prediction model.

The comparison uses Yahoo adjusted daily OHLCV for AAPL, MSFT, NVDA, and SPY: 1,255 sessions each, October 11, 2021 through October 9, 2026. The final 241 known next-session outcomes per symbol start October 23, 2025. Both versions use identical evaluation dates, training windows, and one-session boundary purges. The old six-feature random forest is refitted at each block for a fair comparison with the new evaluation protocol; these old-model numbers differ from the previous single-fit dashboard holdout.

| Symbol | Old forest accuracy | Selected model accuracy | Old forest Brier loss | Selected model Brier loss |
| --- | ---: | ---: | ---: | ---: |
| AAPL | 55.2% | 53.1% | 0.2495 | 0.2491 |
| MSFT | 45.6% | 49.4% | 0.2605 | 0.2510 |
| NVDA | 50.6% | 51.5% | 0.2541 | 0.2503 |
| SPY | 52.7% | 53.1% | 0.2545 | 0.2493 |

Brier loss measures squared probability error; lower is better. Historical frequency won training-only selection for all four symbols, so selected-model results equal the baseline. It improved Brier loss in all four comparisons and accuracy in three, with lower accuracy for AAPL. These results do not show that the expanded learned models outperform the baseline. The app explicitly identifies the selected family and reports when evaluation accuracy does not beat the baseline.

Selection uses three expanding chronological folds within the earliest 80%, with a one-row gap. Candidates are historical frequency, standardized logistic regression (C=0.1), and random forest (150 trees, depth 5, minimum leaf size 4). Standardization is fitted on each training fold. Candidate settings and features were fixed before this comparison; the final blocks do not select or tune the model family. Previously evaluated blocks may enter the next block's training set once their outcomes are known. The final forecast refits the selected family on all known outcomes after evaluation.

This is an exploratory historical comparison on four chosen symbols with overlapping market exposure, not an independent forward trial. Adjusted histories may be revised by the provider. Scores remain uncalibrated; there is no strategy execution, transaction-cost analysis, alert performance study, or evidence of profitable trades. Live analysis excludes the current New York day's candle conservatively to avoid scoring a changing session. More symbols, market regimes, and a prospective paper-trading study are needed before predictive value can support a paid product claim.

Validation: `python -m unittest discover -s tests -v` covers causal features, training-only model selection, boundary purges, complete evaluation coverage, one-class histories, candle filtering, dashboard behavior, and existing billing behavior. No payment logic or dashboard layout was changed.
