# Items left for V0.2

> **Status:** V0.2 implementation and pre-merge verification checklist are complete on branch `v02` (under PR #1).
>
> This document is the final pre-merge checklist. It intentionally contains only items that should be addressed before or as part of merging V0.2. Anything that is a design improvement rather than a release blocker belongs in V0.25/V0.3.

## 1. Merge-state and documentation cleanup

### 1.1 Roadmap status
- [x] Keep `V0.2` described as **implemented on `v02`, pending merge** until PR #1 is merged.
- [x] After merge, update `docs/roadmap.md` to `Status: completed on 2026-09-22`.
- [x] Ensure README/roadmap wording consistently distinguishes branch implementation status from released `main` status.

### 1.2 V0.2 implementation/design document
- [x] Ensure the final V0.2 implementation notes accurately describe the shipped behavior.
- [x] Document all intentionally heuristic quantities:
  - Team Strength Index
  - win probability
  - FDR multipliers
  - xPDK baseline coefficients
  - availability/depth-chart multiplier
  - uncertainty/sigma used by option-value calculations.
- [x] Explicitly state that V0.2 xPDK is a **decision-support baseline**, not a historically validated predictive model.
- [x] Explicitly state that the current sigma is a **heuristic uncertainty estimate**, not empirical player variance.

## 2. xPDK semantic clarification

The V0.2 model combines recent/per-game fantasy production with a market-price prior and then applies availability, FDR and win-probability adjustments.

This is acceptable for V0.2, but the model contract must be clear:

- [x] Name/document xPDK V0.2 as a heuristic baseline.
- [x] Explain that quotation/price is intentionally used as an input prior.
- [x] Do not describe the model as an ML model or as a validated forecast.
- [x] Avoid implying that the current coefficients have been statistically fitted.
- [x] Preserve the current implementation as a stable baseline so V0.25 can compare against it.

## 3. Turn Option Value tests

The current test suite verifies that the option-value mechanism produces a positive bonus, but this is not enough to establish numerical correctness.

Before merge:

- [x] Add at least one deterministic hand-calculated option-value test.
- [x] Add a test where the backup has a different position and the swap is illegal.
- [x] Add a test where a nominally attractive backup cannot be used because the resulting formation is illegal.
- [x] Add a test for captain-switch option value.
- [x] Add a zero-option-value case:
  - no eligible unplayed backup, or
  - backup score cannot improve the primary under the configured scenario.
- [x] Keep tests deterministic; do not depend on live API values.

## 4. Lineup optimizer validation

The exhaustive optimizer is appropriate for the current 10 court-player search space and should remain exhaustive for V0.2.

Before merge:

- [x] Add a test that each of the five legal formations can be selected when the roster makes it optimal.
- [x] Add a test that captain must be a starter.
- [x] Add a test that sixth man is not also a starter.
- [x] Add a test that all four bench players are distinct from starters/sixth man.
- [x] Add a test that the coach is not accidentally included in court-player formation constraints.
- [x] Add a test for a T1/T2 lineup where the best T1 choice is not simply the highest-xPDK five.

## 5. Trade recommender sanity checks

The two-stage candidate filtering approach is appropriate for V0.2.

Before merge:

- [x] Verify that all generated trade bundles are passed through the deterministic `validate_trades()` validator.
- [x] Verify Head Coach swaps count toward the 1..4 trade limit.
- [x] Verify `--unlimited` bypasses the normal trade-count limit without bypassing budget/roster/club rules.
- [x] Add a no-improvement case where the recommender returns no actionable trade.
- [x] Add a case where a superficially attractive individual transfer becomes illegal as part of a multi-player bundle.
- [x] Document that Pareto/marginal filtering is a performance optimization, not yet a formally proven exact search reduction for every future objective.

## 6. Live verification

- [x] Run the full `pytest` suite.
- [x] Run `elf squad`.
- [x] Run `elf fixtures --rounds 5`.
- [x] Run `elf fixtures --rounds 5 --squad-only`.
- [x] Run `elf lineup`.
- [x] Run `elf suggest-trades --trades 1`.
- [x] Run at least one multi-trade example (`--trades 2`) against the current snapshot.
- [x] Confirm that no private squad/configuration data is included in the PR.

## 7. Merge criteria

V0.2 is ready to merge when:

1. All automated tests pass.
2. The CLI commands above execute successfully against the current data snapshot.
3. The xPDK and sigma semantics are documented as heuristic baselines.
4. Turn option-value tests cover both positive and zero/illegal cases.
5. The deterministic validator remains the final authority for all actionable lineup/trade outputs.
6. Documentation correctly reflects that V0.2 is pending merge until PR #1 lands.

## Explicitly deferred to V0.25+

Do **not** block V0.2 on:

- historical backtesting;
- ML prediction;
- empirical uncertainty calibration;
- expected-minutes modeling;
- price-change prediction;
- exact multi-round optimization;
- exact exhaustive Turn-1 -> Turn-2 substitution optimization;
- ownership/risk modeling;
- GUI;
- LLM integration.

Those are subsequent milestones.
