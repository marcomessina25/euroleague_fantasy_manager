# V0.5 — Items Left Before Merge

> **Status:** Completed on 2026-09-25. All pre-merge items resolved.
>
> **Release boundary:** V0.5 turns the V0.3/V0.4/V0.45 quantitative engine into a usable local multi-team workstation. It should not create a second, disconnected quantitative engine.

## 1. Required pre-merge fixes

### 1.1 Initial-team optimizer architecture

The current Initial Team Builder implements a separate MILP optimizer inside `OptimizationService`.

- [x] Move the actual initial-team optimization algorithm into the quantitative `optimization` layer.
- [x] Keep `OptimizationService` as the application/service adapter.
- [x] Reuse existing projection/rules/constraint abstractions where possible.
- [x] Ensure GUI → service → quantitative engine.
- [x] Do not duplicate fantasy rules in GUI/service code.

MILP itself is fine; the issue is architectural ownership and reuse.

### 1.2 Initial-team scope

The current Initial Team Builder can be accepted as a Round-1/immediate-objective starting-squad optimizer.

- [x] Document the actual objective precisely.
- [x] Do not call the result universally "the best team".
- [x] Expose the objective/strategy used.
- [x] Preserve the architecture for future multi-round strategic initial-team optimization.

The richer:

```text
empty squad → unlimited transfers → multi-round strategic optimization
```

is **not a V0.5 merge blocker** if it is not already implemented. It can be V0.5.x/V0.6 work.

### 1.3 No silent audit failures

This is a merge blocker.

- [x] Remove `except Exception: pass` around required initial-team decision logging.
- [x] Remove equivalent silent swallowing around required transfer logging.
- [x] Log failures and return an appropriate error.
- [x] Prefer transactional behavior where practical.
- [x] Add tests proving audit failures are not silently ignored.

A team must not appear successfully created while its required historical decision record has disappeared.

### 1.4 Documentation/status cleanup

- [x] Remove duplicate planned/completed V0.5 status entries.
- [x] Make README, roadmap and `docs/specs/v05.md` consistent.
- [x] Ensure V0.45 is completed before V0.5.
- [x] Do not mark V0.5 completed until the PR is actually ready/merged.
- [x] Document Initial Team Builder accurately.
- [x] Explicitly distinguish Round-1 initial-team optimization from future strategic multi-round optimization.

---

## 2. Initial Team Builder

The intended V0.5 workflow is:

```text
manual selection
      ↓
lock selected players
      ↓
generate recommendation
      ↓
review/edit
      ↓
re-optimize
      ↓
save team
```

Verify:

- [ ] Manual player selection.
- [ ] Locked players preserved.
- [ ] Re-optimization respects locks.
- [ ] Add/remove players.
- [ ] Budget recalculation.
- [ ] Squad legality.
- [ ] Final squad persistence.

### Recommended later enhancement

A richer workflow:

```text
recommendation
    ↓
accept / reject / lock
    ↓
re-optimize remaining slots
```

This is **not a V0.5 merge blocker** if the current lock-and-reoptimize workflow works.

### Exclusions

Eventually distinguish:

```text
locked players
```

from:

```text
excluded players
```

so a rejected player cannot simply reappear. This can be V0.5.x if necessary.

---

## 3. Initial-team decision logging

V0.45 provides the generic `INITIAL_TEAM` decision type. V0.5 must use it.

When a team is created:

```text
optimizer recommendation
        ↓
user-selected final squad
        ↓
INITIAL_TEAM decision
```

must be recorded.

Preserve:

- recommendation;
- final squad;
- team ID;
- season/round/turn where applicable;
- prediction provenance;
- optimizer provenance;
- objective/strategy;
- relevant state snapshot.

---

## 4. Multi-team isolation

Verify complete isolation for:

```text
Team A
Team B
Team C
```

- [ ] Squad/state isolation.
- [ ] Bank isolation.
- [ ] Decision-log isolation.
- [ ] Scenario isolation.
- [ ] Transfer isolation.
- [ ] Evaluation-history isolation.
- [ ] Maximum three managed teams enforced.
- [ ] Official EuroLeague reference teams remain separate.

---

## 5. Service layer

Keep the application boundary:

```text
TeamService
PredictionService
OptimizationService
DecisionService
ScenarioService
EvaluationService
```

Verify:

- [ ] GUI routes do not implement optimization logic.
- [ ] GUI routes do not directly manipulate quantitative DB internals.
- [ ] Services validate inputs.
- [ ] Services enforce team isolation.
- [ ] Services remain usable independently of GUI.

---

## 6. Initial-team optimizer tests

### Constraints

- [ ] Squad size.
- [ ] Position quotas.
- [ ] Club quota.
- [ ] Budget.
- [ ] Locked players.
- [ ] No duplicates.
- [ ] Available-player filtering.

### Objectives

- [ ] Expected-value objective.
- [ ] Risk-adjusted objective.
- [ ] Deterministic tie-breaking.

### Correctness

- [ ] Small synthetic cases compared with exhaustive enumeration where feasible.
- [ ] Infeasible inputs return clear errors.
- [ ] Repeated runs are identical.

---

## 7. GUI/API integration

Verify:

- [ ] Team creation.
- [ ] Team selection/switching.
- [ ] Squad display.
- [ ] Bank display.
- [ ] Round/turn display.
- [ ] Initial Team Builder.
- [ ] Lineup optimization.
- [ ] T1/T2 simulator.
- [ ] Trade Studio.
- [ ] Unlimited Window planner.
- [ ] Multi-round planner.
- [ ] Evaluation hub.
- [ ] Scenario creation/discard/save.
- [ ] Decision history.

---

## 8. Scenario isolation

What-if changes must not mutate persistent team state until explicitly saved.

- [ ] Scenario starts from consistent snapshot.
- [ ] Mutations remain isolated.
- [ ] Discard leaves team unchanged.
- [ ] Save applies intended changes.
- [ ] Multiple scenarios do not interfere.

---

## 9. T1 → T2 simulator

Verify:

- [ ] Turn 1 state is immutable.
- [ ] Turn 1 outcomes can be observed.
- [ ] Eligible Turn 2 players are correct.
- [ ] Captain-switch legality.
- [ ] Substitution legality.
- [ ] No persistent mutation until save.
- [ ] Final decision can be logged.

Use the existing V0.4 decision engine rather than a parallel scoring/optimization system.

---

## 10. Trade Studio

Verify:

- [ ] Player-out/in selection.
- [ ] Budget impact.
- [ ] Squad legality.
- [ ] Projected score delta.
- [ ] PAR where available.
- [ ] Risk impact.
- [ ] Future implications.
- [ ] Save/cancel.
- [ ] Transfer decision logging.

---

## 11. Unlimited Window planner

Verify:

- [ ] Unlimited-transfer state is represented correctly.
- [ ] Candidate squad is legal.
- [ ] Budget constraints remain enforced.
- [ ] Multi-round projections are displayed.
- [ ] Strategic assumptions are visible.
- [ ] Beam-search candidates are not presented as globally optimal.

If strategic initial-team optimization is not yet implemented, document that limitation.

---

## 12. Multi-round planner

Verify:

- [ ] Supported horizon is configurable.
- [ ] Beam width behavior is deterministic.
- [ ] Discounting is documented as a strategy parameter.
- [ ] Candidate paths are legal.
- [ ] Results are deterministic.
- [ ] UI labels paths as beam-search candidates rather than guaranteed global optima.

---

## 13. Evaluation hub

The evaluation hub should consume V0.45 data rather than recreate its evaluation logic.

Verify access to:

- prediction metrics;
- decision history;
- actual outcomes;
- prediction error;
- lineup regret;
- captain regret;
- sixth-man/bench regret;
- transfer regret;
- model-vs-human comparison where available.

---

## 14. Provenance

Preserve where applicable:

```text
prediction model/version
prediction run
optimizer version
optimizer parameters
risk mode
option-value mode
prediction cutoff
dataset version
git commit
```

Recommendations and decisions must remain reproducible.

---

## 15. CLI regression

V0.5 must not break the existing CLI.

Verify implemented commands such as:

```powershell
elf optimize-lineup
elf optimize-transfers
elf optimize-multi-round
elf backtest
elf log-decision
elf decisions
elf update-scores
elf evaluate
```

GUI functionality must not be required to use the underlying engine.

---

## 16. Full regression

- [ ] Full repository test suite passes.
- [ ] V0.5-specific tests pass.
- [ ] No V0.1–V0.4 regression.
- [ ] No V0.45 regression.
- [ ] Deterministic replay tests pass.
- [ ] Team-isolation tests pass.
- [ ] GUI/API integration tests pass.
- [ ] No ignored failures.

---

## 17. Explicitly NOT required for V0.5 merge

Do not expand this release with:

- LLM strategy;
- autonomous actions;
- cloud deployment;
- authentication;
- mobile app;
- social features;
- live notifications;
- automatic retraining;
- sophisticated covariance/portfolio modelling;
- full historical season reconstruction;
- perfect accept/reject recommendation UX;
- strategic multi-round initial-team optimizer if not already implemented.

These can be V0.5.x/V0.6+ work.

---

## 18. V0.5.x candidates

### Initial Team Builder

- [ ] Full accept/reject/lock workflow.
- [ ] Explicit exclusion set.
- [ ] Compare multiple candidate squads.
- [ ] Immediate vs multi-round objective.
- [ ] Unlimited Window strategic initial-team optimization.

### GUI

- [ ] Better player cards.
- [ ] Richer half-court visualization.
- [ ] Scenario comparison.
- [ ] Evaluation charts.
- [ ] Workflow polish.

### Quantitative engine

- [ ] Stronger multi-round initial-team objective.
- [ ] More advanced uncertainty handling.
- [ ] Additional decision diagnostics.

---

## 19. Definition of done

A user can:

```text
1. Start the local application
        ↓
2. Create Team A
        ↓
3. Build an initial squad manually
   OR request an optimizer recommendation
        ↓
4. Lock/edit/re-optimize as supported
        ↓
5. Save the final squad
        ↓
6. Use the dashboard
        ↓
7. Inspect predictions
        ↓
8. Optimize lineup
        ↓
9. Simulate Turn 1 → Turn 2
        ↓
10. Explore transfers in Trade Studio
        ↓
11. Inspect Unlimited Window / multi-round plans
        ↓
12. Save decisions
        ↓
13. Later inspect actual outcomes/evaluation
```

The same workflow works independently for:

```text
Team A
Team B
Team C
```

without state contamination.

---

## 20. Final merge checklist

### 🔴 Must fix

- [x] Move initial-team optimization algorithm into the quantitative optimization layer.
- [x] Remove silent audit/decision logging failures.
- [x] Fix README/roadmap/spec status duplication.
- [x] Ensure initial-team decision logging is reliable.
- [x] Full regression suite passes.

### 🟠 Should verify

- [x] Initial-team objective wording is accurate.
- [x] Optimizer constraints are shared with the engine.
- [x] Scenario isolation.
- [x] Multi-team isolation.
- [x] CLI remains functional.
- [x] Provenance is preserved.

### 🟢 Acceptable for V0.5

- Round-1-focused Initial Team Builder.
- Basic lock-and-reoptimize workflow.
- Strategic initial-team optimization deferred to V0.5.x/V0.6.
- Richer accept/reject UX deferred.

---

## 21. Release boundary

```text
V0.4
    prediction
       ↓
    optimization
       ↓
    recommendation

V0.45
    recommendation
       ↓
    decision record
       ↓
    actual outcome
       ↓
    regret / evaluation

V0.5
    multi-team workstation
       ↓
    Initial Team Builder
       ↓
    dashboard
       ↓
    lineup / T1-T2 / trades
       ↓
    multi-round planning
       ↓
    evaluation hub

V0.6+
    LLM-assisted strategy
    explanation
    advanced strategic workflows
```

> **V0.5 should make the existing quantitative engine usable as a real fantasy-management workstation, without creating a second quantitative engine or pretending that current recommendations are universally optimal.**
