# EuroLeague Fantasy Manager roadmap

> **Living document.** This is the source of truth for delivery status, engineering priorities, release criteria, known risks, and long-term direction. Human contributors and AI agents must read it before material work and update it when priorities or milestone status changes.
>
> **Current planning baseline:** V0.1 and V0.2 are completed on `main` (2026-09-22); V0.25 is implemented on branch `v025` and pending merge. V0.3 is the next planned milestone.
>
> See [`docs/architecture.md`](architecture.md), [`docs/v02/v02.md`](v02/v02.md), [`docs/v02/items_left_for_v02.md`](v02/items_left_for_v02.md), [`docs/v025/v025.md`](v025/v025.md), and [`docs/v03/v03.md`](v03/v03.md) for architectural and implementation details.

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

## V0.25 — Historical Evaluation Foundation

**Status: implemented on `v025`; pending merge.**

### Objective

Build the machinery needed to determine whether our projections actually work.

### Scope

- Historical player-game dataset.
- Historical team/game dataset.
- Point-in-time feature generation.
- Historical fantasy-score reconstruction.
- Season-average baseline.
- Last-3/5/10 baselines.
- EWMA baseline.
- Historical reproduction of V0.2 xPDK.
- Walk-forward evaluation.
- MAE/RMSE.
- Bias.
- Spearman/ranking metrics.
- Top-K metrics.
- Historical lineup simulation.
- Captain/Sixth-Man/Bench decision metrics.
- Data/model provenance.
- Leakage tests.
- Evaluation reports.

### Key question

```text
Does V0.2 xPDK actually beat
simple historical baselines?
```

If not, V0.3 must address the identified weakness rather than simply adding model complexity.

### Detailed plan

See:

```text
docs/v025.md
```

---

## V0.3 — Validated Predictive Projection Layer

**Status: planned.**

### Objective

Move from heuristic xPDK to statistically grounded projections.

### Architecture

```text
availability
     ↓
expected minutes
     ↓
component production
     ↓
game context
     ↓
expected PIR / fantasy points
     ↓
empirical uncertainty
```

### Scope

- Expected availability.
- Expected minutes.
- Component production rates.
- Player role/rotation features.
- Team/opponent context.
- Schedule/rest/congestion features.
- Statistical prediction models.
- Empirical uncertainty estimates.
- Model registry/versioning.
- Model-agnostic prediction objects.
- V0.2 vs V0.3 walk-forward comparison.
- Deterministic conversion of component projections into fantasy points.
- Separate Head Coach model.

### Important separation

V0.3 must distinguish:

```text
performance prediction
        ≠
fantasy valuation
        ≠
lineup/trade optimization
```

### Capital gain

A first dedicated capital-gain model may be introduced only after establishing a clean price-change target and baseline.

### Detailed architecture

See:

```text
docs/v03.md
```

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

Once V0.25/V0.3 have established reliable point-in-time prediction and evaluation:

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
1. Merge V0.2 cleanly
        ↓
2. Build V0.25 evaluation foundation
        ↓
3. Measure V0.2 against simple baselines
        ↓
4. Build V0.3 only where evaluation shows value
        ↓
5. Optimize using validated projections
        ↓
6. Build exact live Turn decisions
        ↓
7. Add decision/outcome backtesting
        ↓
8. Add GUI / LLM
```

This ordering is intentional.

The objective is not maximum feature count.

The objective is a system whose recommendations can eventually be **measured, reproduced, explained, and improved**.
