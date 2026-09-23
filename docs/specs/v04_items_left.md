# V0.4 — Items Left Before Merge

> **Scope note:** This checklist has been updated after defining V0.45.
>
> V0.4 ends at the boundary:
>
> **prediction → deterministic optimization → recommendation**
>
> V0.45 owns:
>
> **recommendation → human decision → actual outcome → regret/drift/feedback**
>
> Do not pull V0.45 functionality back into V0.4.

---

# 1. V0.4 merge objective

V0.4 is complete when the deterministic decision and optimization layer is:

- correct;
- deterministic;
- tested;
- reproducible;
- explicit about exact vs approximate optimization;
- explicit about strategy assumptions vs official fantasy rules;
- usable through the CLI;
- suitable as the quantitative engine underneath V0.45 and eventually V0.5.

V0.4 does **not** need persistent real-world decision tracking.

---

# 2. Required V0.4 items

## 2.1 Documentation cleanup

- [x] Remove duplicate/outdated V0.4 status statements.
- [x] Make README, roadmap and V0.4 documentation agree on release status.
- [x] Clearly separate V0.4 from V0.45 scope.
- [x] Ensure terminology is consistent:
  - recommendation;
  - optimization;
  - oracle;
  - actual outcome;
  - decision regret.

### Required boundary

Document explicitly:

```text
V0.4:
    optimize a decision

V0.45:
    record the decision and evaluate it after reality happens
```

---

# 3. Fantasy-rule verification

## 3.1 Club quota

- [x] Verify the currently implemented club-player quota against the official/current fantasy rules.
- [x] Resolve the discrepancy between the documented default quota and the current-season rules.
- [x] Add a regression test for the verified rule.
- [x] Document the rule source/version.

Do not leave a historical rule silently presented as the current rule.

---

# 4. Projection / optimizer boundary

V0.4 should consume projections rather than redesigning the prediction model.

- [x] Ensure `PlayerProjectionContract` is clearly defined.
- [x] Ensure optimizer inputs are independent of the V0.3 model implementation.
- [x] Verify optimizer behavior with deterministic synthetic projections.
- [x] Keep prediction generation and decision optimization separate.

The intended architecture remains:

```text
V0.3 prediction
      ↓
PlayerProjectionContract
      ↓
V0.4 optimizer
```

V0.4 should not introduce another prediction model.

---

# 5. Exact fixed-squad optimizer

The exhaustive optimizer is an important correctness oracle.

- [x] Preserve the exhaustive implementation.
- [x] Verify all implemented constraints.
- [x] Verify formation legality.
- [x] Verify squad-size constraints.
- [x] Verify club quota.
- [x] Verify budget constraints.
- [x] Verify captain/sixth/bench legality.
- [x] Verify objective calculation.
- [x] Verify deterministic tie-breaking.
- [x] Retain brute-force comparison tests.

The optimized implementation must continue to agree with exhaustive enumeration for testable small state spaces.

Do **not** remove the exhaustive implementation simply because a faster optimizer exists.

---

# 6. Captain option-value model

This is the most important remaining technical correction.

## 6.1 Multiplier

The captain option value must correctly account for the captain multiplier.

If captain scoring is 2×, the expected incremental value from a future captain switch should reflect that multiplier.

Do not use:

```text
E[max(0, backup_score)]
```

as the complete captain option value if the underlying score is subsequently doubled.

The implementation and tests should explicitly establish the intended formula.

---

## 6.2 Candidate selection

The option-value calculation should not assume that only one preselected backup captain can become captain unless that is explicitly required by the actual fantasy rules.

Where the rules allow switching to any eligible unplayed player, the model should evaluate the best eligible future captain.

Add tests covering:

- current captain remains best;
- another eligible player becomes best;
- multiple eligible alternatives;
- zero/negative incremental option;
- captain multiplier;
- already-played/ineligible players.

---

# 7. Risk modes

Document the current risk implementation accurately.

If the objective is:

```text
E[score] ± λσ
```

describe this as a **risk-adjusted heuristic**, not as a complete portfolio variance model.

- [x] Document the mathematical interpretation.
- [x] Test monotonic behavior with increasing uncertainty.
- [x] Test expected/conservative/aggressive modes.
- [x] Ensure risk mode does not alter deterministic inputs unexpectedly.

Covariance modelling remains out of scope for V0.4.

---

# 8. Transfer optimizer

The transfer optimizer needs an explicit exactness boundary.

If the default implementation uses candidate pruning:

- [x] Document that default optimization is candidate-pruned.
- [x] Do not describe it as globally exhaustive.
- [x] Document exhaustive mode.
- [x] Verify exhaustive mode on small synthetic cases.
- [x] Test that candidate pruning does not violate hard constraints.
- [x] Test transfer counts 1..4 and unlimited mode.

Important distinction:

```text
candidate-pruned:
    fast heuristic search

exhaustive:
    exact within the defined search space
```

If `transfer_penalty_cost` is configurable, document it as a **strategy parameter**, not an official fantasy-game rule unless it genuinely corresponds to one.

---

# 9. Multi-round optimizer

The multi-round optimizer is a beam-search strategy.

- [x] Clearly document that it is beam search.
- [x] Do not describe it as globally optimal.
- [x] Test deterministic ordering/tie-breaking.
- [x] Test horizon 2–4.
- [x] Test discounting.
- [x] Test that legal state transitions are preserved.
- [x] Verify that the returned path is the best path among the retained beam states.

Document:

```text
gamma = 0.95
```

as a **strategic modelling assumption**, not a fantasy rule.

A neutral alternative remains possible:

```text
gamma = 1.0
```

but does not need to be the V0.4 default.

---

# 10. Historical backtester / oracle

Clarify exactly what the V0.4 oracle represents.

The current oracle should be documented as:

> A static single-round hindsight oracle using realized outcomes to determine the best legal decision for that round.

It is **not** yet:

- a full turn-by-turn reconstruction;
- a complete historical manager simulator;
- a longitudinal human decision evaluator.

Those belong to V0.45.

---

# 11. Actual-score terminology

Where the backtester evaluates realized fantasy performance:

- [x] Use explicit terminology such as `actual_fantasy_points`.
- [x] Do not ambiguously call realized values simply “actual score” if multiple score concepts exist.
- [x] Keep projected score and realized fantasy score distinct.

Example:

```text
projected_fantasy_points
actual_fantasy_points
```

---

# 12. V0.4 tests

Before merge, verify at minimum:

### Core optimizer

- [x] Exact optimizer vs exhaustive optimizer.
- [x] Formation legality.
- [x] Budget legality.
- [x] Club quota.
- [x] Squad-size constraints.
- [x] Captain legality.
- [x] Sixth-man legality.
- [x] Bench legality.
- [x] Deterministic tie-breaking.

### Captain option value

- [x] Captain multiplier.
- [x] Multiple eligible future captains.
- [x] Ineligible players excluded.
- [x] Zero option value.
- [x] Positive option value.

### Risk

- [x] Expected mode.
- [x] Conservative mode.
- [x] Aggressive mode.
- [x] Uncertainty sensitivity.

### Transfers

- [x] 1 transfer.
- [x] 2 transfers.
- [x] 3 transfers.
- [x] 4 transfers.
- [x] Unlimited.
- [x] Candidate-pruned mode.
- [x] Exhaustive mode.

### Multi-round

- [x] Horizons 2–4.
- [x] Beam width behavior.
- [x] Deterministic output.
- [x] Legal state transitions.
- [x] Discounting.

### Backtesting

- [x] Actual fantasy points.
- [x] Static oracle.
- [x] Regret calculation.
- [x] Deterministic replay.

---

# 13. CLI consistency

Verify that the V0.4 CLI exposes the optimizer capabilities cleanly.

Expected capabilities:

```powershell
elf optimize-lineup
elf optimize-transfers
elf optimize-multi-round
elf backtest
```

- [x] Help text is accurate.
- [x] Inputs are validated.
- [x] Outputs identify the optimizer/model version.
- [x] Results are deterministic.
- [x] CLI documentation matches actual commands.

V0.45 commands such as:

```powershell
elf log-decision
elf decisions
elf update-scores
```

do **not** need to be implemented as part of V0.4.

They belong to V0.45.

---

# 14. Reproducibility

A V0.4 optimization result should be reproducible from:

```text
input state
+
projection set
+
optimizer version
+
optimizer parameters
```

Where useful, record or expose:

```text
git commit
optimizer version
parameter signature
risk mode
option-value mode
```

This provenance is required so V0.45 can later attach a real decision to the exact recommendation that produced it.

Do not implement the full V0.45 decision-history system here.

---

# 15. Explicitly moved to V0.45

The following are **not V0.4 merge blockers anymore**.

## Decision persistence

Moved to V0.45:

- [ ] `DecisionRecord`
- [ ] decision database/history
- [ ] persistent human decisions
- [ ] recommendation vs human decision storage
- [ ] decision notes/journal
- [ ] historical decision retrieval

## Actual outcomes

Moved to V0.45:

- [ ] `elf update-scores`
- [ ] attaching actual outcomes to decisions
- [ ] late outcome corrections
- [ ] outcome audit trail

## Closed-loop evaluation

Moved to V0.45:

- [ ] prediction error after real decisions;
- [ ] human decision regret;
- [ ] model recommendation regret;
- [ ] human-vs-model comparison;
- [ ] captain regret from actual decisions;
- [ ] sixth-man regret from actual decisions;
- [ ] bench regret from actual decisions;
- [ ] turn substitution regret;
- [ ] captain-switch regret;
- [ ] transfer regret.

## Longitudinal monitoring

Moved to V0.45:

- [ ] rolling prediction metrics;
- [ ] model drift;
- [ ] segment drift;
- [ ] decision-quality trends.

## T1 → T2 historical decision loop

Moved to V0.45:

```text
T1 actual
    ↓
manager decision
    ↓
T2 actual
    ↓
decision regret
```

V0.4 only needs to provide the underlying option-value/optimization machinery correctly.

---

# 16. Why this boundary matters

V0.4 should answer:

> **Given the current state and projections, what decision does the optimizer recommend?**

V0.45 should answer:

> **What did we actually decide, what happened, and how good was that decision?**

This avoids mixing:

```text
optimization correctness
```

with:

```text
real-world management performance
```

and makes both releases easier to test.

---

# 17. V0.5 dependency

V0.5 will consume the V0.45 interfaces.

Expected flow:

```text
V0.3
  ↓
predictions

V0.4
  ↓
optimization recommendation

V0.45
  ↓
decision + outcome + evaluation

V0.5
  ↓
GUI around the complete workflow
```

The GUI should not need to reimplement optimizer or evaluation logic.

---

# 18. Final V0.4 merge checklist

### Rules

- [x] Current club quota verified.
- [x] All fantasy constraints tested.

### Optimizer

- [x] Exact fixed-squad optimizer verified.
- [x] Exhaustive correctness oracle retained.
- [x] Captain option-value formula corrected.
- [x] Captain option candidate set correct.
- [x] Risk modes documented/tested.
- [x] Transfer exact-vs-pruned distinction documented.
- [x] Multi-round beam-search distinction documented.
- [x] Gamma documented as strategic parameter.

### Backtester

- [x] Static hindsight oracle scope documented.
- [x] `actual_fantasy_points` terminology clarified.
- [x] Backtest tests pass.

### CLI

- [x] V0.4 commands work.
- [x] Help/documentation matches implementation.
- [x] Deterministic output verified.

### Reproducibility

- [x] Optimizer runs are deterministic.
- [x] Optimizer/projection provenance is available.
- [x] Replay tests pass.

### Documentation

- [x] README updated.
- [x] Roadmap updated.
- [x] V0.4/V0.45 boundary documented.
- [x] No V0.45 functionality is incorrectly described as V0.4.

---

# 19. Merge criterion

V0.4 is ready to merge when:

```text
official rules
      +
correct optimizer
      +
correct option value
      +
explicit approximation boundaries
      +
deterministic tests
      +
reproducibility
      +
clean CLI
      +
accurate documentation
```

are all satisfied.

At that point:

```text
V0.4 = DONE
```

and the next development target is:

```text
V0.45 — Closed-Loop Evaluation & Live Decision State
```

---

# 20. Release boundary in one diagram

```text
                    V0.3
                 PREDICTION
                     │
                     ▼
            PlayerProjectionContract
                     │
                     ▼
                    V0.4
               OPTIMIZATION
                     │
                     ▼
              RECOMMENDATION
                     │
                     │
              ───────┼───────
                     │
                     ▼
                   V0.45
              DECISION LOG
                     │
                     ▼
              ACTUAL OUTCOME
                     │
                     ▼
             ERROR / REGRET
                     │
                     ▼
            MODEL / STRATEGY
              DIAGNOSTICS
                     │
                     ▼
                    V0.5
             MULTI-TEAM GUI
```

> **V0.4 should be a clean quantitative decision engine. V0.45 should be the feedback loop that measures what happens when that engine is actually used.**
