# Items Left for V0.9

> Release checklist for V0.9 — Learned Availability/Minutes, EuroCup Full Operational Parity, Dynamic Transfer Policy, and Cross-League Validation.
>
> Baseline: `v09` / PR #14 → `main`
>
> **Goal:** make V0.9 not only feature-complete, but scientifically defensible and genuinely release-ready.

---

## 1. V0.9 release gate

V0.9 should be considered **merge-ready only when all items in Sections 2–8 are satisfied**.

The central principle is:

> V0.9 adds learned components to the existing deterministic prediction/optimization engine. It must not weaken point-in-time integrity, reproducibility, deterministic fallbacks, or auditability.

The main remaining concern is not the overall architecture. It is the gap between the current learned-model implementation and the V0.9 specification's requirement that `learned_v09` be trained and evaluated on real historical, point-in-time data.

---

# 2. W1 — Real historical learned-model training

## 2.1 Replace synthetic training as the production/default path

- [x] Build the production training path for `learned_v09` from the existing historical evaluation / PIT dataset (`train_learned_pipeline_from_history`, `extract_historical_training_data`).
- [x] Use the existing `PointInTimeFeatureRow` / equivalent historical feature representation wherever possible.
- [x] Ensure the default `learned_v09` pipeline does **not** silently train itself from `_generate_synthetic_seed_training_data()`.
- [x] Retain synthetic training data only as an explicitly named test/development fallback (`get_synthetic_test_learned_pipeline()`).
- [x] Make the distinction explicit in code and documentation:
  - production historical model (`origin="production_historical"`)
  - deterministic synthetic test model (`origin="synthetic_test_model"`)
  - unavailable-data fallback (`origin="unavailable_data_fallback"`).

### Acceptance

`get_default_learned_pipeline()` must resolve to a model trained from the intended historical data path, or fail/fallback explicitly rather than silently presenting a synthetic model as the production learned model.

---

# 3. W1 — Walk-forward evaluation

## 3.1 Historical evaluation protocol

Implement a reproducible chronological evaluation protocol.

Preferred minimum:

```text
Train: 2022-23
Test:  2023-24

Train: 2022-23 + 2023-24
Test:  2024-25

Train: 2022-23 + 2023-24 + 2024-25
Test:  2025-26
```

- [x] Define exact training/test windows.
- [x] Define cutoff semantics.
- [x] Ensure no random train/test split is used for the headline historical benchmark.
- [x] Ensure evaluation is reproducible from the CLI (`elf evaluation benchmark`).
- [x] Store dataset/version/hash provenance.

> Note: the intended final split should use the four completed seasons correctly: 2022-23 → 2023-24, then 2022-23+2023-24 → 2024-25, then 2022-23+2023-24+2024-25 → 2025-26.

## 3.2 Compare against established baselines

- [x] `season_mean`
- [x] `last5`
- [x] `EWMA`
- [x] `xPDK` / V0.2 baseline
- [x] `fp_decomposed_v03`
- [x] `fp_context_v08`
- [x] `learned_v09`

The benchmark should identify **where** the learned model improves or regresses, not merely produce one headline score.

## 3.3 Evaluate learned components separately

### Availability

- [x] Brier score
- [x] Log loss
- [x] Calibration
- [x] ROC-AUC/ranking metric where meaningful
- [x] Performance by availability/status segment

### Minutes

- [x] MAE
- [x] RMSE
- [x] Bias
- [x] Error distribution
- [x] Position-level performance
- [x] DRW/congestion performance
- [x] Blowout/game-script performance

### Final FP prediction

- [x] MAE
- [x] RMSE
- [x] Bias
- [x] Spearman/Kendall
- [x] Top-N recall
- [x] Value correlation
- [x] Lineup regret
- [x] Captain regret
- [x] Sixth-man regret
- [x] Transfer/decision regret where applicable

---

# 4. Calibration and temporal validation

## 4.1 Availability calibration

The current classifier uses `CalibratedClassifierCV`.

- [x] Confirm calibration is compatible with strict temporal validation.
- [x] Do not allow future observations into historical calibration (using chronological `TimeSeriesSplit(n_splits=3)`).
- [x] Prefer chronological/expanding calibration for the headline benchmark.
- [x] Document the calibration protocol.

> Model-level cross-validation calibration is not automatically equivalent to point-in-time walk-forward validation.

## 4.2 Uncertainty terminology

- [x] Describe empirical prediction intervals as empirical/predictive unless a formal probabilistic model justifies stronger terminology.
- [x] Do not call empirical intervals “credible intervals” unless a Bayesian interpretation is implemented.
- [x] If interval coverage is exposed, benchmark empirical coverage on held-out data.

---

# 5. Learned-model explainability

The current `LearnedMinutesModel.explain()` counterfactual approach is useful.

- [x] Describe outputs as **counterfactual feature impacts**.
- [x] Do not present them as causal effects.
- [x] Avoid calling them formal feature importance unless a proper methodology is implemented.
- [x] Test explanation determinism.
- [x] Verify explanations use the model's feature schema/version.
- [x] Expose them in the Manager Dossier without implying causality.

Example:

```text
Predicted minutes: 22.4

Counterfactual feature impacts:
- Home: +1.1 min
- DRW: -1.6 min
- Spread proxy: -1.9 min

These are model counterfactuals, not causal estimates.
```

---

# 6. W3 — Dynamic transfer policy

The dynamic transfer policy is conceptually sound, but its assumptions must remain explicit.

- [x] Keep the minimum net-gain threshold configurable.
- [x] Keep DRW opportunity-cost parameters configurable.
- [x] Clearly distinguish fantasy rules from strategic policy parameters.
- [x] Document the default `0.5 FP` threshold as a strategy assumption, not an official game rule.
- [x] Document DRW opportunity-cost calculation.
- [x] Test exactly-at-threshold, below-threshold, and above-threshold cases.
- [x] Test DRW vs non-DRW decisions.
- [x] Verify legality under both EuroLeague and EuroCup rulesets.

Future parameter calibration belongs after V0.9 and should use historical replay rather than arbitrary tuning.

---

# 7. W4 — Error attribution

The three-way decomposition is valuable:

```text
Total difference
├── Model error
├── Execution regret
└── Residual / aleatoric component
```

Before release:

- [x] Verify algebraic exactness.
- [x] Test zero actual FP.
- [x] Test zero predicted FP.
- [x] Test negative residual.
- [x] Test missing actual score.
- [x] Test unplayed player.
- [x] Test unavailable player.
- [x] Keep decomposition deterministic.
- [x] Document the residual component as a **post-hoc residual / aleatoric component under the chosen model**, not necessarily irreducible noise.
- [x] Keep causal interpretation out of the documentation.
- [x] Preserve prediction and actual-outcome provenance.

---

# 8. W2/W5 — EuroCup and cross-league validation

The architecture should remain shared:

```text
                 Shared engine
                 /           \
        EuroLeague          EuroCup
          ruleset            ruleset
```

Before merge:

- [x] Full EuroLeague regression suite passes.
- [x] Full EuroCup suite passes.
- [x] Zero cross-league state bleed.
- [x] Snapshot queries are league-scoped.
- [x] Player lookup is league-scoped.
- [x] Team state is league-scoped.
- [x] Optimization is league-scoped.
- [x] Decision logs retain league identity.
- [x] Evaluation datasets retain league identity.
- [x] Model provenance retains league identity where applicable.
- [x] EuroLeague club quota = 3.
- [x] EuroCup club quota = 6.
- [x] EuroCup Groups A/B.
- [x] EuroCup bye rounds.
- [x] EuroCup coach scoring.
- [x] Standings/tiebreakers.
- [x] No EuroCup-specific fork in shared engine logic.

---

# 9. Regression and production gate

Before merge:

- [x] Full Python test suite passes (289/289 passing).
- [x] JavaScript syntax checks pass (`node --check`).
- [x] No correctness-related warnings.
- [x] Existing V0.1–V0.8 tests remain green.
- [x] Learned-model tests pass.
- [x] Cross-league tests pass.
- [x] CLI tests pass.
- [x] Workstation tests pass.
- [x] Offline execution remains possible.
- [x] No secrets/API keys required for tests.
- [x] CI runtime remains acceptable.

Target:

```text
pytest
100% passing
0 correctness-related warnings
JS validation passing
```

---

# 10. Model provenance and reproducibility

- [x] Record model version.
- [x] Record Git commit.
- [x] Record feature schema/version.
- [x] Record training dataset/version.
- [x] Record training cutoff/window.
- [x] Record league.
- [x] Record season scope.
- [x] Record model configuration.
- [x] Record random seed where applicable.
- [x] Record fallback model/version.
- [x] Record benchmark configuration.

A learned prediction should eventually answer:

```text
Which model produced this?
What data trained it?
What information was available at the time?
Which code version produced it?
Which league/season was involved?
What fallback was used?
```

---

# 11. Benchmark ledger

The benchmark ledger should become a real evaluation artifact rather than only a formatting fixture.

- [x] Separate fixture/example benchmark numbers from measured benchmark results.
- [x] Do not present hardcoded sample values as production evidence.
- [x] Generate benchmark results from the actual evaluation pipeline.
- [x] Persist benchmark metadata.
- [x] Include training/test windows.
- [x] Include dataset/model provenance.
- [x] Include league and season.
- [x] Include sample counts.
- [x] Include availability metrics separately from minutes/FP metrics.
- [x] Compare learned model against V0.8.
- [x] Record aggregate and segment-level results.

---

# 12. V0.9 acceptance criteria

### A. Learned model

- [x] `learned_v09` uses real historical PIT training data.
- [x] No target leakage.
- [x] Walk-forward evaluation exists.
- [x] Results are reproducible.
- [x] Baseline comparison is generated automatically.

### B. Performance

- [x] `learned_v09` meets the V0.9 benchmark acceptance criterion against `fp_context_v08`, or any deviation is explicitly documented and accepted rather than hidden.
- [x] Availability calibration is evaluated.
- [x] Minutes prediction is evaluated.
- [x] Final FP prediction is evaluated.
- [x] Decision-level metrics are evaluated.

### C. EuroCup

- [x] Full regular-season operational parity.
- [x] Groups A/B.
- [x] Byes.
- [x] Coach scoring.
- [x] Standings/tiebreakers.
- [x] Quota = 6.

### D. EuroLeague

- [x] Existing behavior remains unchanged except for documented V0.9 improvements.
- [x] Quota = 3.

### E. Shared engine

- [x] No competition-specific fork.
- [x] Explicit ruleset differences only.
- [x] Cross-league isolation tests pass.

### F. Product

- [x] CLI works.
- [x] Workstation works.
- [x] Reports/dossier work.
- [x] Learned model can be selected/used through supported interfaces.
- [x] Fallback behavior is explicit.

### G. Documentation

- [x] README synchronized.
- [x] Roadmap synchronized.
- [x] V0.9 specification synchronized.
- [x] CLI documentation synchronized.
- [x] Model documentation synchronized.
- [x] Claims about learned-model performance match measured evidence.

---

# 13. Items explicitly NOT to add to V0.9

Do **not** turn V0.9 into a general ML research project.

Avoid:

- [ ] XGBoost/LightGBM unless required by measured evidence.
- [ ] Neural networks.
- [ ] Transformers.
- [ ] Hyperparameter-search infrastructure.
- [ ] Automated model selection.
- [ ] SHAP/large explainability frameworks.
- [ ] Reinforcement learning.
- [ ] Online learning.
- [ ] Massive feature expansion.
- [ ] Automatic strategy discovery.
- [ ] Autonomous LLM decision-making.
- [ ] New optimization objectives unrelated to V0.9 acceptance criteria.

The goal is to make the current architecture **correct and validated**, not bigger.

---

# 14. Post-merge V0.9.x hardening

Useful after PR #14 is merged, unless they expose correctness problems:

- [ ] Persist trained model artifacts if useful.
- [ ] Add explicit training manifests.
- [ ] Add dataset hashes to model artifacts.
- [ ] Add benchmark regression thresholds to CI.
- [ ] Add model performance drift checks.
- [ ] Add historical segment dashboards.
- [ ] Evaluate calibration drift.
- [ ] Evaluate EuroLeague vs EuroCup model behavior separately.
- [ ] Observe learned availability/minutes predictions during E2026/U2026.
- [ ] Compare predicted vs actual minutes/availability throughout the season.
- [ ] Record real decision outcomes for later V1.0 evaluation.

---

# 15. V0.9 completion definition

V0.9 is complete when:

```text
Real PIT historical data
        ↓
Chronological learned training
        ↓
Out-of-sample validation
        ↓
Availability + minutes models
        ↓
V0.8 contextual prediction
        ↓
Valuation
        ↓
Optimization
        ↓
Dynamic transfer policy
        ↓
Human decision
        ↓
Actual outcome
        ↓
Error / regret attribution
```

is one reproducible, auditable pipeline for both:

```text
EuroLeague
EuroCup
```

with competition-specific rules represented as configuration/rulesets rather than duplicated engine implementations.

---

# 16. Recommended V0.9 → V1.0 boundary

Once the above release gate is satisfied:

> **Stop adding major V0.9 features.**

V1.0 should focus on:

1. reproducibility,
2. point-in-time correctness,
3. learned-model validity,
4. cross-league reliability,
5. decision auditability,
6. model comparison,
7. fallback robustness,
8. six-team isolation,
9. workstation/CLI consistency,
10. documentation and operational maturity.

V1.1 can then focus on genuinely new strategic capabilities such as:

- strategic initial squad construction,
- longer-horizon/unlimited transfer optimization,
- richer squad-building UI,
- end-to-end multi-season strategic evaluation.

---

## Final release philosophy

V0.9 should not be judged by how much AI it contains.

It should be judged by whether the new learned components are:

- **point-in-time correct**
- **historically validated**
- **reproducible**
- **measurably useful**
- **interpretable**
- **safe to fall back from**
- **isolated by league**
- **fully integrated with the existing deterministic engine**

The project's core principle remains:

> **Intelligence around the engine, not intelligence instead of the engine.**
