# EuroLeague Fantasy Manager roadmap

> **Living document.** This is the source of truth for delivery status, engineering priorities, release criteria, known risks, and long-term direction. Human contributors and AI agents must read it before material work and update it when priorities or milestone status changes.
>
> **Current planning baseline:** V0.1, V0.2, V0.2.5, and V0.3 (`0.3.0`) are completed (2026-09-23). **V0.4** (Lineup & Transfer Optimizer on Validated Projections) is the single next milestone.
>
> See [`docs/architecture.md`](architecture.md), [`docs/v02/v02.md`](v02/v02.md), [`docs/v02/items_left_for_v02.md`](v02/items_left_for_v02.md), [`docs/v025/v025.md`](v025/v025.md), [`docs/v025/v025_cleanup.md`](v025/v025_cleanup.md), and [`docs/v03/v03.md`](v03/v03.md) for architectural and implementation details.


---

## 0. Executive roadmap

The project is evolving from a deterministic EuroLeague Fantasy calculation engine into a complete **EuroLeague (and future EuroCup) Fantasy Challenge decision-support and experimentation platform**.

The system is built to answer:

- What should I do this Round before Turn 1 lock?
- What are the best legal `1..4` trade alternatives?
- How should I partition my 11-unit squad across Turn 1 and Turn 2?
- Which Turn 1 scores should be subbed out?
- Which unplayed Turn 2 players create valuable optionality?
- Which players are undervalued relative to expected fantasy production?
- How can capital gains expand the future budget?
- How should the team be managed around Unlimited Trade Windows?
- How does ownership affect risk strategy?
- How did each recommendation perform against reality?

The core design principle remains:

```text
Official Fantasy + EuroLeague data
            ↓
Point-in-time local snapshots
            ↓
Deterministic rules / state
            ↓
Quantitative projections
            ↓
Valuation
            ↓
Optimizers
            ↓
Decision log
            ↓
Actual outcome
            ↓
Evaluation / backtesting
            ↓
Model improvement
```

The major roadmap change is deliberate:

> **Evaluation moves ahead of sophisticated prediction and optimization.**

We do not want to build an increasingly complex model without first proving whether the current baseline works.

---

# Delivery phases

## V0.1 — Trustworthy data and rules foundation

**Status: completed on 2026-09-22.**

### Scope

- Live EuroLeague Fantasy ingestion.
- Official EuroLeague metadata.
- Raw timestamped JSON archive.
- Local SQLite snapshots.
- 11-unit squad representation.
- Budget and club constraints.
- Five legal court formations.
- Captain, Sixth Man and Bench weights.
- Trade validation.
- Unlimited Trade Window support.
- Private squad configuration.
- Hermetic tests.

### Outcome

The project has a deterministic source of truth for fantasy state and rules.

---

## V0.2 — Decision-support basics

**Status: completed on 2026-09-22.**

### Scope

- Current squad financial/capital-gain dossier.
- Multi-round fixture ticker.
- Team Strength Index.
- Win probability.
- Position-aware FDR.
- Baseline xPDK.
- Head Coach expected score.
- Turn-aware lineup optimizer.
- Captain/Sixth-Man/Bench optimization.
- Turn 1 -> Turn 2 option-value heuristic.
- 1..4 trade candidate generator.

### Important model status

V0.2 xPDK is a **heuristic baseline**, not a validated predictive model.

The current uncertainty/sigma used for option-value calculations is also a heuristic.

The purpose of V0.2 is to establish a useful deterministic + quantitative decision layer that can become the benchmark for later models.

### Merge criteria

See:

```text
docs/v02/items_left_for_v02.md
```

---

## V0.2.5 — Historical Evaluation Foundation

**Status: completed on 2026-09-22 (`0.2.5`).**

### Objective

Build the historical laboratory needed to determine—rigorously, point-in-time safely, and reproducibly—whether projections and lineup decisions actually work.

### Scope

- Normalized multi-season historical dataset (`E2022`–`E2025`) in SQLite (`eval_players`, `eval_teams`, `eval_rounds`, `eval_games`, `eval_team_games`, `eval_player_games`, `eval_historical_snapshots`, `eval_predictions`).
- Authoritative EuroLeague PIR (`reconstruct_pir`), Dunkest player fantasy points (`reconstruct_player_fantasy_points` with `+10%` win bonus and `0.0` for `DNP`/`out`), and separate Head Coach margin scoring (`reconstruct_coach_fantasy_points`).
- Strict point-in-time feature generation (`game_date < decision_cutoff`) with explicit cold-start fallback hierarchy (`current_season -> previous_season -> career_history -> position_team_prior`).
- Baselines (`season_mean`, `last3`, `last5`, `last10`, `ewma`, and historical point-in-time reproduction of `xpdk_v02`).
- Walk-forward evaluation separating **All Listed Players** from **Active Players Only** (`minutes > 0`) and Court Players (`G, F, C`) from Head Coaches (`HC`).
- Explicit historical pricing provenance tracking (`official_snapshot`, `archived_fantasy`, `reconstructed`, `proxy`, `missing`) and coverage reporting.
- Simplified 11-unit fantasy lineup decision/regret simulation (`avg_lineup_regret`, `avg_captain_regret`, `avg_sixth_man_regret`, `avg_bench_regret`, `avg_formation_regret`).
- Hermetic anti-leakage, target reconstruction, duplicate detection, and walk-forward backtest tests.

### Empirical findings (`E2025` Rounds 1–12 benchmark)

Different evaluation metrics favor different baselines in the `E2025` R1–12 benchmark (`N=288` all court-player observations, `N=282` active court-player observations):
- **`xpdk_v02`**: strongest rank ordering (`Spearman = 0.678` all / `0.691` active, `Value Spearman = 0.231`), while exhibiting a negative level bias (`Bias = -1.97` all / `-2.08` active) due to conservative quotation scaling relative to the `1.10x` win bonus.
- **`season_mean` / `ewma`**: strongest point-error accuracy (`season_mean MAE = 3.75`, `ewma MAE = 3.87`) and highest simulated single-round reference-squad score (`199.13` / `198.62`).
- **`last5`**: tied strongest `Top-10 Recall = 0.74`.

These findings directly motivate V0.3's decomposed architecture and point-in-time calibration.

### Detailed plan & cleanup

See [`docs/v025/v025.md`](v025/v025.md) and [`docs/v025/v025_cleanup.md`](v025/v025_cleanup.md).

---

## V0.3 — Validated Predictive Projection Layer

**Status: completed on 2026-09-23 (`0.3.0`).**

### Objective

Build the first **validated, point-in-time predictive projection system** for EuroLeague Fantasy, built on top of the V0.2.5 historical evaluation laboratory.

### Core architectural rule & pipeline

> **Do not make one model learn availability, playing time, and performance as one undifferentiated target.**

```text
historical/current information
        ↓
P(play)                      [Phase B: Availability model]
        ↓
E(minutes | play)            [Phase C: Conditional minutes model]
        ↓
E(FP/min | play)             [Phase D: Conditional production-per-minute model]
        ↓
E(fantasy points)            [Phase E: Coherent composition: P(play) × E(min|play) × E(FP/min|play)]
        ↓
calibration + uncertainty    [Phases F & G: Out-of-sample level calibration + residual intervals]
        ↓
player valuation             [Phase I: Expected FP / price & value above replacement]
        ↓
V0.4 optimizer               [Downstream decision layer]
```

### Delivered V0.3 components

1. **Explicit Component Decomposition (`src/euroleague_fantasy_manager/prediction/`)**:
   - Availability: `availability_logistic_v03`, status lookup, historical and rolling rates, Brier score, and binary log-loss evaluation.
   - Minutes: `minutes_ewma_v03` with empirical Bayes shrinkage to starter/bench role priors and rest/congestion adjustments.
   - Production: `production_ridge_v03` component rate proxy conditioned on playing time, plus dedicated Head Coach model (`predict_expected_coach_conditional_fp`).
   - Fantasy points composition: $\mathbb{E}[\text{FP}] = P(\text{play}) \times \mathbb{E}[\text{minutes} \mid \text{play}] \times \mathbb{E}[\text{FP/min} \mid \text{play}]$.
2. **Out-of-Sample Calibration (Zero Test Leakage)**:
   - `fit_out_of_sample_calibrator`: Fits linear/intercept adjustments strictly on accumulated historical rounds $r' < r$ with empirical Bayes prior shrinkage $(n < 20 \to \text{intercept}=0.0, \text{slope}=1.0)$, completely eliminating the V0.2 xPDK level bias without test leakage.
3. **Uncertainty & Risk Bounds**:
   - Out-of-sample residual error analysis providing `lower_bound`, `upper_bound`, `prediction_spread`, and $\sigma$ segmented by position and availability state.
4. **Player Valuation (`src/euroleague_fantasy_manager/valuation/`)**:
   - Exposes `expected_fp_per_credit`, positional `points_above_replacement` (PAR), and `risk_adjusted_value` ($\mathbb{E}[\text{FP}] - \lambda \cdot \text{spread}$).
5. **Evaluation Laboratory Hardening & Paired Comparisons**:
   - Multi-season walk-forward backtest (`E2022`–`E2025`), automated paired model comparisons ($\Delta\text{MAE} \pm 95\%\text{ CI}$, $\Delta\text{RMSE}$, $\Delta\text{Spearman}$, $\Delta\text{Lineup Score}$, $\Delta\text{Captain Regret}$), and CSV report generation (`paired_comparisons.csv`).
6. **Persistence & Provenance**:
   - SQLite tables `prediction_runs`, `player_predictions`, and `model_metrics` for complete auditability.
   - Model registry tracking model IDs, versions, target families, and hyperparameters.
7. **CLI Integration**:
   - `elf predict --season ... --round ... --model ... [--position ...] [--top ...] [--json]`
   - `elf evaluate --seasons ... --compare-models ... --calibration ...`

### Important boundary

> **V0.2.5 tells us whether our predictions are good. V0.3 builds better predictions. V0.4 decides what to do with them.**

See [`docs/v03/v03.md`](v03/v03.md) for the complete V0.3 specification and verified benchmark results.


---

## V0.35 / V0.4 — Optimization on validated projections

**Status: planned.**

### Objective

Use the validated projection layer to improve fantasy decisions.

### Scope

- Exact/more efficient trade optimization.
- Multi-player trade bundles.
- Unlimited Trade Window solver.
- Multi-round rolling planner.
- Future fixture horizon.
- Capital-gain-aware planning.
- Risk-aware objectives.
- Portfolio-style roster evaluation.

### Important design rule

Do not introduce Branch-and-Bound simply because the roadmap says so.

First measure the actual search space.

The current single-round 10-player lineup problem is small enough for exhaustive enumeration. More advanced solvers should be introduced where multi-round or multi-trade combinatorics justify them.

---

## V0.4 — Exact Intra-Turn Decision Engine

**Status: planned.**

### Scope

- Exact Turn 1 -> Turn 2 substitution optimizer.
- Legal formation transitions.
- Captain switches.
- Sixth-Man transitions.
- Bench ordering.
- Realized T1 score handling.
- T2/T3 unplayed player handling.
- Decision logging.
- Post-round outcome logging.
- Turn-sub regret.

### Target interface

```bash
elf turn-subs
```

The engine should enumerate legal decisions rather than relying on a greedy pairwise heuristic.

---

## V0.45 — Closed-loop Evaluation and Strategy

**Status: planned.**

### Scope

- `elf log-decision`
- `elf decisions`
- `elf update-scores`
- `elf evaluate`
- Prediction error tracking.
- Captain regret.
- Sixth-Man/Bench regret.
- Turn-sub regret.
- Lineup regret.
- Trade regret.
- Model drift monitoring.

This phase turns the manager into a real experimentation platform.

---

## V0.5 — Multi-team management and local Web GUI

**Status: planned.**

### Scope

- Up to 3 isolated Classic Mode teams.
- Team-scoped configuration.
- Team-scoped decision logs.
- Interactive local dashboard.
- Basketball half-court view.
- T1/T2/T3 state.
- Turn substitution simulator.
- Trade Studio.
- Unlimited Window planner.
- Multi-round planner.
- Evaluation hub.

The GUI remains downstream of the quantitative engine.

---

## V0.6+ — Strategic/LLM layer

**Status: future horizon.**

### Scope

- Analytical manager briefing.
- Live matchday/turn tracker.
- Optional LLM strategy critique.
- Structured manager dossier.
- Explanation of optimizer choices.
- Assumption/uncertainty analysis.
- Alternative scenario analysis.

The LLM remains:

```text
analyst / challenger / explainer
```

and never becomes:

```text
rules engine / source of truth / optimizer
```

---

## V0.7+ — Historical decision backtesting

**Status: future horizon.**

Once V0.2.5/V0.3 have established reliable point-in-time prediction and evaluation:

- multi-season historical decision simulation;
- sequential decision A/B backtesting;
- historical transfer simulation;
- historical Turn 1 -> Turn 2 simulation;
- model-version comparison;
- human-vs-model decision comparison.

Potential historical seasons:

```text
2022/23
2023/24
2024/25
2025/26
2026/27
```

subject to data availability and point-in-time reconstruction quality.

---

## V0.8+ — Advanced context models

**Status: future horizon.**

Potential features:

- double-week congestion;
- turnaround/rest models;
- with/without-teammate effects;
- injury replacement effects;
- role/rotation changes;
- ownership dynamics;
- price elasticity;
- advanced uncertainty distributions.

Only features that demonstrate out-of-sample value should graduate into production.

---

## V0.9+ — EuroCup inheritance

**Status: future horizon.**

Activate the existing parameterized architecture for:

```text
league_id = 11
competition_code = "U"
```

The objective is to reuse:

```text
API clients
storage
rules abstraction
prediction architecture
evaluation
optimizer
CLI
```

rather than creating a separate EuroCup codebase.

---

# Release philosophy

## The project has four levels of truth

### 1. Fantasy truth

```text
API snapshots + deterministic rules
```

### 2. Statistical truth

```text
historical outcomes + point-in-time evaluation
```

### 3. Decision optimization

```text
legal optimizer using validated projections
```

### 4. Strategic interpretation

```text
human + optional LLM
```

Never allow level 4 to override levels 1–3 silently.

---

# Current priority order

```text
1. V0.1 & V0.2 deterministic foundation & baseline [Completed]
        ↓
2. V0.2.5 historical evaluation foundation (`0.2.5`) [Completed]
        ↓
3. V0.3 validated predictive projection layer (`0.3.0`) [Completed]
   (P(play) × E(minutes|play) × E(FP/min|play) + calibration + uncertainty + valuation)
        ↓
4. V0.4 Lineup & Transfer Optimizer on Validated Projections [Next Milestone]
        ↓
5. V0.45 exact live Turn 1 -> Turn 2 decisions & closed-loop backtesting
        ↓
6. V0.5+ GUI / LLM strategic layer
```

This ordering is intentional.

The objective is not maximum feature count.

The objective is a system whose recommendations can eventually be **measured, reproduced, explained, and improved**.

