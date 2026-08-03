---
status: proposed
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-28
---

# ADR-0025: Hedge model champion/challenger governance

- Status: proposed
- Date: 2026-07-28
- Related: ADR-0004, ADR-0007, ADR-0019, ADR-0024

## Context

KB Comme must recommend a hedge ratio without delegating arithmetic or model
selection to an LLM. The existing calculation uses a zero-drift rolling
volatility estimate, an adverse normal quantile and the minimum ratio that
protects a profit floor. More responsive or fat-tail-aware models may improve
the decision, but replacing the operational method from one backtest would
make results irreproducible and difficult to govern.

Historical validation currently has 2,600 committed ECOS USD/KRW spot
observations. It does not contain company-applicable historical forward quotes.
Using spot as if it were an executable forward quote understates basis, spread,
credit, tenor and transaction-cost effects.

## Decision

1. Keep `rolling_normal_profit_floor` as the explicit champion.
2. Register Historical Simulation, EWMA Normal, GARCH Filtered Historical
   Simulation and Historical CVaR as challengers.
3. Implement the minimum-variance covariance/variance ratio, but mark it
   `data_blocked` until aligned spot and applicable forward histories exist.
4. Keep model metadata, source references, parameters, status, promotion gates
   and fallback policy in `knowledge/hedge_model_registry.json`.
5. Evaluate all models using walk-forward origins whose input history ends at
   the origin. Future observations may only be used as realized targets.
6. Measure tail calibration, profit-floor breaches, expected and maximum
   shortfall, quantile loss, hedge ratio, turnover and estimated cost, including
   named stress periods.
7. A challenger can be promoted only when it passes every declared gate on the
   same origins with observed forward quotes and receives knowledge-domain,
   platform-runtime and domain-expert approval.
8. Never fall back to a challenger automatically. Champion failure returns
   insufficient information instead of silently changing the method.
9. The LLM may explain a versioned model result but may not calculate a hedge
   ratio, invent a quote, select a model or override a promotion gate.
10. Record each model's scenario-centering policy explicitly. A model whose
    scenarios carry empirical directional drift cannot be promoted while the
    product promises zero-drift, non-directional risk scenarios.

## Model interpretation

- Rolling Normal and EWMA Normal use zero drift and normal quantiles. They are
  transparent baselines, not claims that FX returns are normally distributed.
- Historical Simulation replays observed overlapping horizon returns, so its
  empirical sample drift can move the scenario median away from spot.
- GARCH-FHS estimates conditional variance with deterministic Gaussian QMLE
  grid search and applies empirical standardized residuals. Those residuals
  are not forcibly recentered, and the model is not a Student-t
  maximum-likelihood implementation.
- Historical CVaR minimizes empirical profit-floor shortfall over a bounded
  ratio grid using the same empirically centered historical scenarios. It is
  an internal economic objective, not regulatory capital Expected Shortfall.
- Minimum variance follows the covariance of spot and forward returns divided
  by forward-return variance, bounded to the product's permitted ratio range.

## Consequences

The current production behavior does not change. Challenger results become
comparable, reproducible and auditable, while promotion remains blocked by
missing forward history. Acquiring tenor-, side-, company- and timestamp-aware
forward quotes is a separate prerequisite; it must not be approximated from
spot data.

## Verification

- executable and governed registries contain the same operational model IDs;
- exactly one explicit champion exists;
- no-lookahead tests prove origin dates precede target dates;
- malformed, unaligned or zero-variance paired histories fail closed;
- the committed ECOS snapshot produces at least 100 origins for every model;
- spot-proxy validation always blocks promotion;
- empirically centered scenario models remain blocked even when numerical
  gates and observed-quote requirements pass;
- observed-quote fixtures can pass the numerical gates;
- `scripts/check_hedge_models.py` reproduces the benchmark.
