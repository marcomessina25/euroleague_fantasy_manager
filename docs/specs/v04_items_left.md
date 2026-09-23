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

- [ ] Remove duplicate/outdated V0.4 status statements.
- [ ] Make README, roadmap and V0.4 documentation agree on release status.
- [ ] Clearly separate V0.4 from V0.45 scope.
- [ ] Ensure terminology is consistent:
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

- [ ] Verify the currently implemented club-player quota against the official/current fantasy rules.
- [ ] Resolve the discrepancy between the documented default quota and the current-season rules.
- [ ] Add a regression test for the verified rule.
- [ ] Document the rule source/version.

Do not leave a historical rule silently presented as the current rule.

---

# 4. Projection / optimizer boundary

V0.4 should consume projections rather than redesigning the prediction model.

- [ ] Ensure `PlayerProjectionContract` is clearly defined.
- [ ] Ensure optimizer inputs are independent of the V0.3 model implementation.
- [ ] Verify optimizer behavior with deterministic synthetic projections.
- [ ] Keep prediction generation and decision optimization separate.

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

- [ ] Preserve the exhaustive implementation.
- [ ] Verify all implemented constraints.
- [ ] Verify formation legality.
- [ ] Verify squad-size constraints.
- [ ] Verify club quota.
- [ ] Verify budget constraints.
- [ ] Verify captain/sixth/bench legality.
- [ ] Verify objective calculation.
- [ ] Verify deterministic tie-breaking.
- [ ] Retain brute-force comparison tests.

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

- [ ] Document the mathematical interpretation.
- [ ] Test monotonic behavior with increasing uncertainty.
- [ ] Test expected/conservative/aggressive modes.
- [ ] Ensure risk mode does not alter deterministic inputs unexpectedly.

Covariance modelling remains out of scope for V0.4.

---

# 8. Transfer optimizer

The transfer optimizer needs an explicit exactness boundary.

If the default implementation uses candidate pruning:

- [ ] Document that default optimization is candidate-pruned.
- [ ] Do not describe it as globally exhaustive.
- [ ] Document exhaustive mode.
- [ ] Verify exhaustive mode on small synthetic cases.
- [ ] Test that candidate pruning does not violate hard constraints.
- [ ] Test transfer counts 1..4 and unlimited mode.

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

- [ ] Clearly document that it is beam search.
- [ ] Do not describe it as globally optimal.
- [ ] Test deterministic ordering/tie-breaking.
- [ ] Test horizon 2–4.
- [ ] Test discounting.
- [ ] Test that legal state transitions are preserved.
- [ ] Verify that the returned path is the best path among the retained beam states.

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

- [ ] Use explicit terminology such as `actual_fantasy_points`.
- [ ] Do not ambiguously call realized values simply “actual score” if multiple score concepts exist.
- [ ] Keep projected score and realized fantasy score distinct.

Example:

```text
projected_fantasy_points
actual_fantasy_points
```

---

# 12. V0.4 tests

Before merge, verify at minimum:

### Core optimizer

- [ ] Exact optimizer vs exhaustive optimizer.
- [ ] Formation legality.
- [ ] Budget legality.
- [ ] Club quota.
- [ ] Squad-size constraints.
- [ ] Captain legality.
- [ ] Sixth-man legality.
- [ ] Bench legality.
- [ ] Deterministic tie-breaking.

### Captain option value

- [ ] Captain multiplier.
- [ ] Multiple eligible future captains.
- [ ] Ineligible players excluded.
- [ ] Zero option value.
- [ ] Positive option value.

### Risk

- [ ] Expected mode.
- [ ] Conservative mode.
- [ ] Aggressive mode.
- [ ] Uncertainty sensitivity.

### Transfers

- [ ] 1 transfer.
- [ ] 2 transfers.
- [ ] 3 transfers.
- [ ] 4 transfers.
- [ ] Unlimited.
- [ ] Candidate-pruned mode.
- [ ] Exhaustive mode.

### Multi-round

- [ ] Horizons 2–4.
- [ ] Beam width behavior.
- [ ] Deterministic output.
- [ ] Legal state transitions.
- [ ] Discounting.

### Backtesting

- [ ] Actual fantasy points.
- [ ] Static oracle.
- [ ] Regret calculation.
- [ ] Deterministic replay.

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

- [ ] Help text is accurate.
- [ ] Inputs are validated.
- [ ] Outputs identify the optimizer/model version.
- [ ] Results are deterministic.
- [ ] CLI documentation matches actual commands.

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

- [ ] Current club quota verified.
- [ ] All fantasy constraints tested.

### Optimizer

- [ ] Exact fixed-squad optimizer verified.
- [ ] Exhaustive correctness oracle retained.
- [ ] Captain option-value formula corrected.
- [ ] Captain option candidate set correct.
- [ ] Risk modes documented/tested.
- [ ] Transfer exact-vs-pruned distinction documented.
- [ ] Multi-round beam-search distinction documented.
- [ ] Gamma documented as strategic parameter.

### Backtester

- [ ] Static hindsight oracle scope documented.
- [ ] `actual_fantasy_points` terminology clarified.
- [ ] Backtest tests pass.

### CLI

- [ ] V0.4 commands work.
- [ ] Help/documentation matches implementation.
- [ ] Deterministic output verified.

### Reproducibility

- [ ] Optimizer runs are deterministic.
- [ ] Optimizer/projection provenance is available.
- [ ] Replay tests pass.

### Documentation

- [ ] README updated.
- [ ] Roadmap updated.
- [ ] V0.4/V0.45 boundary documented.
- [ ] No V0.45 functionality is incorrectly described as V0.4.

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
