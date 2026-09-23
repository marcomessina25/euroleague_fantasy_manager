# V0.3 — Items Left Before Merge

> Final merge-readiness checklist for V0.3. Do not redesign the V0.3 architecture at this stage.

## 1. Documentation — required

- [x] Remove duplicate V0.3 status lines from `README.md`.
- [x] Keep one canonical status: V0.1, V0.2, V0.2.5 and V0.3 completed; V0.4 next.
- [x] Remove obsolete V0.3 planned/next-milestone section from `docs/roadmap.md`.
- [x] Keep one canonical V0.3 completed section.
- [x] Search for stale `V0.3 planned`, `V0.3 next`, `V0.25`, `0.25.0` and obsolete release wording.
- [x] Verify documentation links.

## 2. PR wording — required

- [x] Replace “completely cures the `-1.97` level bias” with “substantially reduces the negative level bias in the evaluated sample”.
- [x] State explicitly that the reported benchmark is E2025 R1–R4, if unchanged.
- [x] Do not generalize R1–R4 results to all seasons.
- [x] Replace “statistically significant error reduction” unless the statistical procedure fully justifies it with “observed error reduction in the evaluated sample”.
- [x] Replace “credible bounds” with “empirical prediction intervals” unless the implementation is genuinely Bayesian.
- [x] Replace “complete CLI integration” with precise wording if some V0.3 capabilities remain library-only.

## 3. Leakage — strongly recommended

- [x] Add future availability/status mutation test (`test_future_availability_roster_and_blowout_game_leakage`).
- [x] Add future roster/status mutation test where those fields are prediction inputs.
- [x] Verify that post-cutoff information cannot alter the prediction.
- [x] Verify that blowout handling uses only pre-game information.
- [x] Verify actual future game margin cannot enter the minutes model.

## 4. Calibration — strongly recommended

For round `r`:

```text
calibration data < r
prediction target = r
```

- [x] Verify calibration is strictly expanding-window (`test_expanding_window_calibration_invariants`).
- [x] Verify early-round behavior with insufficient history.
- [x] Verify calibration is deterministic.
- [x] Verify future observations cannot alter earlier calibration/predictions.

## 5. Uncertainty — recommended

- [x] Measure empirical coverage of the advertised 80% prediction interval (`test_uncertainty_empirical_coverage_and_width`).
- [x] Report coverage and interval width.
- [x] Check all players and active players separately.
- [x] Check positions where sample size permits.
- [x] Do not call intervals “credible intervals” unless a Bayesian posterior is actually used.

## 6. Mathematical invariants — recommended

Test:

```text
0 <= P(play) <= 1
E(minutes | play) >= 0
E(FP/min | play) is finite

E(FP)
=
P(play)
× E(minutes | play)
× E(FP/min | play)
```

Also verify:

- [x] HC projections remain separate.
- [x] zero/unavailable cases are deterministic.
- [x] NaN/inf values cannot enter final projections.

## 7. Regression verification — required

- [x] Run full test suite.
- [x] Confirm all V0.2.5 tests pass.
- [x] Confirm all V0.3 tests pass.
- [x] Re-run the PR benchmark.
- [x] Confirm reproducibility.
- [x] Confirm result changes are explainable by code/data/model changes.

## 8. Benchmark record

Record:

- [x] seasons/rounds (`E2025` R1–R4).
- [x] player observations (`N = 96` court players).
- [x] active-player count (`N = 94`).
- [x] model versions (`0.3.0`, `0.2.0`).
- [x] calibration method (`fit_out_of_sample_calibrator`, expanding window $r' < r$, empirical Bayes prior shrinkage).
- [x] uncertainty method (`estimate_prediction_uncertainty`, empirical residual intervals).
- [x] paired-comparison method (`compute_paired_model_comparison` with 95% bootstrap CIs).
- [x] dataset/version identifier where available (`historical-v0.2.5-001`).

Clearly distinguish prediction, availability, decision and valuation metrics.

## 9. Out of scope

Do not add:

- deep learning;
- reinforcement learning;
- transfer optimization;
- multi-round optimization;
- GUI;
- LLM strategy;
- automatic submission;
- live news scraping;
- full-season Monte Carlo optimization.

## 10. Merge criterion

Merge when documentation is consistent, claims are correctly scoped, major leakage paths are covered, calibration is confirmed as expanding-window, uncertainty terminology is correct, invariants are tested, the suite passes, and the benchmark is reproducible.

Then merge V0.3 and start V0.4.

