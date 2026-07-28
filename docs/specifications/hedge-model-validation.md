---
status: proposed
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-28
---

# Hedge model validation specification

## Purpose and boundary

This pipeline compares deterministic hedge-ratio models before any result is
sent to an LLM. It does not create an executable quote, place a trade or
promote a model automatically. Every live decision still requires a usable
`HedgeMeasure` with an actual contract rate.

## Common request

Each model receives:

- ordered positive FX observations available at the decision time;
- a selected, currently usable hedge measure and contract rate;
- signed net exposure, baseline profit and profit floor;
- horizon, confidence level, estimation window and ratio-grid step.

Malformed inputs or insufficient history raise a model error. The registry does
not substitute another model.

## Implemented models

| ID | Method | Decision objective | State |
|---|---|---|---|
| `rolling_normal_profit_floor` | rolling standard deviation, square-root-of-time normal scenarios | smallest ratio meeting the adverse profit floor | champion |
| `historical_profit_floor` | overlapping realized horizon returns | smallest ratio meeting the adverse profit floor | challenger |
| `ewma_profit_floor` | RiskMetrics-style EWMA variance, default decay 0.94 | smallest ratio meeting the adverse profit floor | challenger |
| `garch_fhs_profit_floor` | GARCH(1,1) variance plus empirical standardized innovations | smallest ratio meeting the adverse profit floor | challenger |
| `historical_cvar` | empirical horizon-return scenarios | minimum tail shortfall, then minimum ratio | challenger |
| `minimum_variance_forward` | covariance of spot and forward returns divided by forward variance | minimum variance ratio | data blocked |

The machine-readable source of truth is
[`knowledge/hedge_model_registry.json`](../../knowledge/hedge_model_registry.json).

Each model also declares `scenario_centering`. Rolling Normal and EWMA use
`zero`; Historical Simulation and Historical CVaR use `empirical`; GARCH-FHS
uses `empirical_standardized_residuals`; Minimum Variance is
`not_applicable`. Empirically centered models may be evaluated as challengers,
but they cannot be promoted while the product contract remains
non-directional.

## Walk-forward protocol

For origin index `t` and horizon `h`:

1. construct the model request only from observations through `t`;
2. obtain the forward contract rate that was observable at `t`;
3. calculate and freeze the decision;
4. use observation `t + h` only to score the frozen decision;
5. advance by the configured step and repeat.

The default reproducibility check uses a spot proxy only because the repository
does not yet contain historical forward quotes. The result is useful for
forecast diagnostics but is ineligible for promotion.

## Metrics

- adverse-quantile breach rate and absolute calibration error;
- profit-floor breach rate;
- mean, tail-average and maximum monetary shortfall;
- mean quantile loss;
- mean hedge ratio and ratio turnover;
- estimated hedge cost;
- the same breach and shortfall metrics for named stress periods.

Champion and challenger must be evaluated on the same origins. A challenger
must have no failures, adequate sample size, acceptable calibration, material
shortfall and quantile-loss improvement, no floor-breach deterioration, and
bounded cost and turnover increases.

## Promotion gates

Defaults are versioned in the registry:

- at least 100 origins and zero model failures;
- calibration error no greater than 0.03;
- expected-shortfall improvement at least 2%;
- quantile-loss improvement at least 1%;
- no increase in profit-floor breach rate;
- estimated-cost increase at most 10%;
- ratio-turnover increase at most 0.05;
- observed historical forward quotes;
- scenario centering allowed by the non-directional product policy;
- approval by knowledge-domain, platform-runtime and a domain expert.

Failure of any gate blocks promotion. There is no weighted score that can hide
one failed safety gate.

## Data still required

An honest economic comparison needs timestamped forward quotes aligned to the
spot observation and decision origin, with currency pair, side, tenor or value
date, provider, company applicability, rate, spread or fee, notional bounds and
validity interval. It also needs realized settlement rates and, where
available, actual trade cost and execution outcome.

Until that dataset exists:

- minimum-variance estimation remains non-operational;
- spot-proxy results cannot support promotion;
- no synthetic forward curve may be labelled as observed execution data.

## Reproduction

From the repository root:

```powershell
$env:PYTHONPATH = "src"
python scripts/check_hedge_models.py
```

The check loads the committed ECOS USD/KRW snapshot, compares all operational
models over no-lookahead origins, reports promotion blockers and fails if the
executable and governed registries drift.

## Persistent validation and promotion workflow

The benchmark can be written and registered in the hash-bound governance ledger:

```powershell
$env:PYTHONPATH = "src"
python scripts/check_hedge_models.py `
  --output data/governance/latest_hedge_validation.json `
  --store data/governance/hedge_models.db
```

`validation_runs.content_hash` is calculated over canonical JSON. Identical
reports resolve to the same run. A promotion request is rejected before approval
collection when any numerical gate fails or `quote_basis` is not
`observed_forward_quote`.

For an eligible observed-quote report, the controlled sequence is:

```powershell
python scripts/manage_hedge_model_promotion.py request `
  --run-id MODEL-RUN-... --challenger ewma_profit_floor
python scripts/manage_hedge_model_promotion.py approve `
  --request-id MODEL-PROMOTION-... --role knowledge_domain --reviewer REVIEWER
python scripts/manage_hedge_model_promotion.py approve `
  --request-id MODEL-PROMOTION-... --role platform_runtime --reviewer REVIEWER
python scripts/manage_hedge_model_promotion.py approve `
  --request-id MODEL-PROMOTION-... --role domain_expert --reviewer REVIEWER `
  --organization ORGANIZATION
python scripts/manage_hedge_model_promotion.py promote `
  --request-id MODEL-PROMOTION-...
```

Every approval stores the exact validation hash. Domain-expert approval also
requires an organization. `promote` refuses incomplete approvals and only swaps
an active challenger with the current champion; it never selects a model by
score or falls back automatically.

The committed latest spot-proxy report is intentionally ineligible. Persistence
of a blocked result proves the workflow and preserves diagnostics; it does not
weaken the observed-forward-quote gate.
