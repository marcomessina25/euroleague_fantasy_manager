# V0.4 — Items Left Before Merge

> Final merge-readiness checklist for V0.4 (Fantasy Decision & Optimization Layer).
> Core architectural principle: **V0.3 predicts. V0.4 decides.**

---

## 1. Phase A — Constraint Engine & Projection Contract

- [x] Define clean `PlayerProjectionContract` in `src/euroleague_fantasy_manager/optimization/constraints.py`.
- [x] Decouple optimizer input from predictive model implementation details.
- [x] Support conversions from V0.3 `DecomposedProjection`, V0.2 `PlayerProjection`, and V0.2.5 `PredictionRecord`.
- [x] Formalize all Classic Mode fantasy constraints:
  - [x] 11-unit squad (4 Guards, 4 Forwards, 2 Centers, 1 Head Coach).
  - [x] Legal Starting 5 formations: `(2,2,1)`, `(1,2,2)`, `(2,1,2)`, `(1,3,1)`, `(3,1,1)`.
  - [x] Captain in starters (`2.0x`).
  - [x] Sixth Man on bench (`1.0x`).
  - [x] Bench units (`0.5x`).
  - [x] Head Coach (`1.0x`).
  - [x] Club quota limit (max players per EuroLeague club).
  - [x] Budget constraint with 0% sell-on fee.
  - [x] Trade limits (`1..4` trades or unlimited windows).

---

## 2. Phase B, C, D — Pure Deterministic Fixed-Squad Lineup Optimizer

- [x] Build `FixedSquadLineupOptimizer` in `src/euroleague_fantasy_manager/optimization/lineup.py`.
- [x] Jointly optimize formation, starting five, captain, sixth man, bench, and head coach.
- [x] Represent formations as constraints and evaluate all 5 legal formations.
- [x] Support tie-breaking deterministically (by projected score, price, player ID).
- [x] Provide meaningful alternative lineup options.
- [x] Verify against brute-force exhaustive enumeration on small and standard squads.

---

## 3. Phase E — Lineup CLI Integration

- [x] Implement `elf optimize lineup` (with aliases or subparsers).
- [x] Support options: `--season`, `--round`, `--squad`, `--model`, `--risk-mode`, `--json`.
- [x] Format rich human-readable lineup table with starters, captain (`2.0x`), sixth man (`1.0x`), bench (`0.5x`), coach (`1.0x`), and projected totals.

---

## 4. Phase F & G — Transfer Optimization & Candidate Generation

- [x] Implement `TransferOptimizer` in `src/euroleague_fantasy_manager/optimization/transfers.py`.
- [x] Single-round transfer optimization (`1..4` trades and unlimited).
- [x] Account for 0% sell-on tax capital gains and bank budget.
- [x] Evaluate net transfer value: $\text{Optimal Score}(\text{Squad}_{\text{new}}) - \text{Optimal Score}(\text{Squad}_{\text{old}}) - \text{Transfer Cost}$.
- [x] Implement candidate generator & pruning in `src/euroleague_fantasy_manager/optimization/candidates.py`.
- [x] Provide an exhaustive mode for small candidate pools to guarantee global optimality.
- [x] Expose `elf optimize transfers` in CLI.

---

## 5. Phase H — Multi-Round Short-Horizon Planning

- [x] Implement `MultiRoundOptimizer` in `src/euroleague_fantasy_manager/optimization/multi_round.py`.
- [x] Support planning horizons $N \in \{2, 3, 4\}$.
- [x] Maximize cumulative discounted expected fantasy points: $\sum_{t=0}^{N-1} \gamma^t \cdot \mathbb{E}[\text{score}_{r+t}]$.
- [x] Maintain deterministic state transitions between rounds.
- [x] Expose `elf optimize multi-round` in CLI.

---

## 6. Phase I, J, K — Risk-Aware Objectives, Replacement Value & Real Option Value

- [x] Formalize scoring objectives in `src/euroleague_fantasy_manager/optimization/objective.py`:
  - [x] `expected`: $\mathbb{E}[\text{score}]$
  - [x] `conservative`: $\mathbb{E}[\text{score}] - \lambda \cdot \sigma$
  - [x] `aggressive`: $\mathbb{E}[\text{score}] + \lambda \cdot \sigma$
- [x] Calculate Points Above Replacement (PAR) and positional replacement baselines.
- [x] Formalize Turn 1 $\to$ Turn 2 substitution rights as real call options using V0.3 uncertainty $\sigma$.

---

## 7. Phase L — Historical Decision Backtesting & Oracle Regret

- [x] Implement `HistoricalDecisionBacktester` in `src/euroleague_fantasy_manager/optimization/backtest.py`.
- [x] Compute decision regret metrics vs hindsight oracle:
  - [x] Lineup regret
  - [x] Captain regret
  - [x] Sixth man regret
  - [x] Bench regret
  - [x] Formation regret
  - [x] Transfer regret
- [x] Strict zero-leakage guarantee: pre-round cutoff only.
- [x] Integrate into `elf optimize backtest` CLI command.

---

## 8. Verification & Test Suite

- [x] Write exhaustive unit and integration tests in `tests/test_v04_optimization.py`.
- [x] Confirm optimizer matches brute-force exhaustive enumeration on 100% of test cases.
- [x] Confirm all existing tests pass (V0.1, V0.2, V0.2.5, V0.3).
- [x] Check reproducible, deterministic behavior across runs.
