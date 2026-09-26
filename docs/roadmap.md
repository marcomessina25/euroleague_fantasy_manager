# EuroLeague Fantasy Manager — Roadmap

> **Current planning baseline:** 2026-09-26  
> **Current release:** V0.5.1 implemented; PR #7 pending merge  
> **Next release:** V0.6 — Strategic Intelligence, Manager Dossier & Multi-League Foundation

## 1. Vision

Build a deterministic, reproducible and auditable fantasy decision platform that helps a human manager make better-informed decisions without pretending to be an oracle or autonomous manager.

The system should eventually support multiple competitions through one shared engine:

```text
                    ┌─────────────────────┐
                    │   Common Engine     │
                    │ data / rules /      │
                    │ prediction / value /│
                    │ optimization / eval │
                    └──────────┬──────────┘
                               │
                 ┌─────────────┴─────────────┐
                 ▼                           ▼
        EuroLeague adapter            EuroCup adapter
                 │                           │
                 └─────────────┬─────────────┘
                               ▼
                       Team-specific state
                               │
                               ▼
                       Manager Dossier
                               │
                               ▼
                  deterministic analysis
                               │
                               ▼
                         optional LLM
                               │
                               ▼
                         human decision
```

### Core philosophy

> **Intelligence around the engine, not intelligence instead of the engine.**

The deterministic engine remains the source of truth for rules, legality, projections, optimization and recorded outcomes.

The AI layer interprets, explains and challenges those outputs.

---

# 2. Architectural Principles

## 2.1 Common engine, not competition forks

EuroLeague and EuroCup use the same:

- data interfaces
- storage architecture
- team model
- prediction contracts
- valuation contracts
- optimization contracts
- decision logging
- evaluation framework
- service layer
- CLI patterns
- workstation architecture

Competition-specific differences are represented by explicit adapters/rulesets.

## 2.2 League belongs to the team

Every managed team carries its league/competition metadata.

The application must not create separate application architectures for EuroLeague and EuroCup.

```text
Team
 ├── team_id
 ├── league
 ├── squad
 ├── bank
 ├── transfers
 ├── decisions
 └── state
```

The same team/service/storage primitives work across competitions.

## 2.3 Six-team workstation

The target capacity is up to **6 isolated teams per user**.

Teams may belong to different competitions.

There must be no cross-team state leakage.

## 2.4 Human-controlled AI

LLM output is advisory.

It cannot:

- execute transfers
- mutate persistent state silently
- override official rules
- replace deterministic optimization
- invent numerical facts

---

# 3. Levels of Truth

The system is organized into four levels:

### Level 1 — Fantasy truth
Official data + deterministic rules + point-in-time state.

### Level 2 — Statistical truth
Predictions, historical outcomes, calibration and uncertainty.

### Level 3 — Decision optimization
Legal lineup, captain, sixth, transfer and multi-round optimization.

### Level 4 — Strategic interpretation
Deterministic strategic analysis + optional LLM interpretation.

Higher levels must not silently override lower levels.

---

# 4. Completed Releases

## V0.1 — Trustworthy Data & Rules Foundation
**Status: Completed**

Established reliable data acquisition, deterministic fantasy rules, persistence and reproducible foundations.

## V0.2 — Deterministic Decision Support
**Status: Completed**

Introduced deterministic player valuation and xPDK-style decision support.

## V0.2.5 — Historical Evaluation Laboratory
**Status: Completed**

Built the historical evaluation dataset, baselines, point-in-time features, prediction provenance and benchmark framework.

## V0.3 — Validated Predictive Projection Layer
**Status: Completed**

Introduced decomposed prediction:

```text
E[FP] =
P(play)
× E(minutes | play)
× E[FP/min | play]
× context/location factors
```

Added calibration, uncertainty, cold starts, leakage tests and model provenance.

## V0.4 — Decision & Optimization Engine
**Status: Completed**

Added deterministic lineup, captain, sixth, bench, transfer and multi-round optimization with explicit correctness boundaries between exact and heuristic optimization.

## V0.45 — Closed-Loop Decision Logging
**Status: Completed**

Connected recommendations to human decisions and actual outcomes through decision records, snapshots, provenance and regret/evaluation hooks.

## V0.5 — Multi-Team Workstation
**Status: Completed**

Introduced the local workstation, service layer, multi-team management, initial-team workflow, T1/T2 simulation, Trade Studio, multi-round planning and evaluation hub.

## V0.5.1 — Stabilization & Production Readiness
**Status: Implemented; pending PR #7 merge**

Focus:

- live score presentation
- decomposed prediction cleanup
- high-speed transfer optimization
- multi-option transfer ranking
- generalized T1/T2/T3 substitutions
- checkpoint rollback
- decision audit
- prediction validation
- schema hardening
- performance benchmarking

V0.5.1 is a stabilization boundary. Feature creep should stop here.

---

# 5. V0.6 — Strategic Intelligence, Manager Dossier & Multi-League Foundation

**Status: Next major release**

V0.6 establishes the architecture that connects the deterministic engine to human strategic reasoning.

## Core deliverables

1. Deterministic Manager Dossier
2. Deterministic strategic checklist
3. League-aware team model
4. Shared engine + league adapter architecture
5. Six-team workstation capacity
6. Optional LLM Copilot
7. Provider abstraction
8. Provenance
9. Failure isolation
10. Numerical/rule consistency checks

### Manager Dossier

The dossier is the structured boundary between the deterministic engine and strategic interpretation.

It contains:

- team state
- league metadata
- projections
- uncertainty
- valuations
- optimizer recommendations
- transfer alternatives
- intra-round alternatives
- multi-round candidates
- schedule/context
- provenance

### AI philosophy

V0.6 is not "add an LLM and hope it improves performance."

It is:

```text
deterministic dossier
       ↓
deterministic analysis
       ↓
optional AI interpretation
       ↓
human decision
```

### EuroCup

EuroCup is **architecturally supported in V0.6**, but complete feature parity remains a later milestone.

The shared engine and contracts must not require a EuroLeague-only implementation.

---

# 6. V0.7 — Sequential Historical Decision Replay

**Status: Planned**

Move from evaluating individual predictions to reconstructing the decision process over time.

Focus:

- historical decision drill-down
- point-in-time state reconstruction
- sequential lineup decisions
- sequential transfer decisions
- T1/T2/T3 historical replay
- multi-round decision replay
- model-version comparison
- human-vs-model decision comparison
- historical regret attribution

V0.7 answers:

> "Given only what the manager could have known at that moment, what decision did the system recommend, what did the manager choose, and what happened?"

This should precede major new predictive complexity.

---

# 7. V0.8 — Advanced Prediction & Context

**Status: Planned**

Improve prediction only where V0.7 evidence identifies meaningful decision errors or systematic blind spots.

Potential areas:

- participation modeling
- expected minutes
- role/state changes
- schedule congestion
- rest
- teammate effects
- injury replacement effects
- rotation patterns
- ownership/context features
- price elasticity
- uncertainty improvements

V0.8 is evidence-driven.

It should not become a collection of predictive features added because they appear interesting.

---

# 8. V0.9 — Competition Parity, Cross-League Validation & Advanced Strategy

**Status: Planned**

V0.9 is **not the point at which EuroCup is introduced**.

The architecture already supports EuroCup from V0.6.

V0.9 completes and validates competition support.

Focus:

- EuroCup feature parity
- competition-specific rules validation
- cross-league dataset validation
- shared-engine deduplication
- cross-league regression suite
- competition-specific adapter hardening
- strategy behavior across competitions
- advanced strategic workflows where justified by V0.7/V0.8 evidence

Acceptance criterion:

> EuroLeague and EuroCup use the same core engine and contracts while correctly applying their respective competition rules and data semantics.

---

# 9. V1.0 — Mature Multi-League Fantasy Decision Platform

**Status: Long-term target**

V1.0 is a maturity milestone, not a feature-count milestone.

The system should be:

- deterministic where it needs to be deterministic
- reproducible
- auditable
- explainable
- testable
- modular
- observable
- usable by a technically competent human

## V1.0 architecture

```text
Official data
     ↓
Point-in-time snapshots
     ↓
League-aware deterministic rules
     ↓
Prediction layer
     ↓
Valuation
     ↓
Optimization
     ↓
Decision log
     ↓
Actual outcome
     ↓
Evaluation / backtesting
     ↓
Manager Dossier
     ↓
Strategic analysis
     ↓
Optional LLM
     ↓
Human decision
```

## V1.0 competition scope

- EuroLeague
- EuroCup
- shared engine
- explicit league adapters
- no competition-specific application forks

## V1.0 team scope

- up to 6 isolated teams per user
- mixed competitions allowed
- independent state and decision histories
- shared engine primitives

## V1.0 prediction scope

- point-in-time prediction
- calibrated availability/minutes/production components
- uncertainty
- cold-start handling
- leakage protection
- model provenance
- reproducible evaluation

## V1.0 decision scope

- initial team
- lineup
- captain
- sixth
- bench
- transfers
- unlimited windows
- T1/T2/T3 intra-round decisions
- multi-round planning
- documented risk assumptions

## V1.0 closed-loop scope

The system must distinguish:

```text
prediction
recommendation
human decision
actual outcome
```

and quantify the relevant differences.

## V1.0 AI scope

LLM is optional.

It may:

- explain
- challenge
- compare
- summarize
- interpret uncertainty
- identify changes

It may not:

- become the source of truth
- silently change deterministic results
- mutate team state
- execute management actions autonomously

---

# 10. What V1.0 Explicitly Does Not Mean

V1.0 does not require:

- autonomous management
- automatic transfers
- cloud SaaS
- mobile application
- perfect prediction
- perfect historical reconstruction
- universal strategy
- LLM-controlled decisions
- guaranteed fantasy performance improvement
- an oracle that always knows the optimal future

The target is a trustworthy decision-support system, not an autonomous fantasy manager.

---

# 11. Documentation Structure

Recommended long-term structure:

```text
docs/
├── roadmap.md
├── architecture.md
├── rules.md
├── data_model.md
├── prediction.md
├── optimization.md
├── evaluation.md
├── gui.md
├── strategy.md
│
├── specs/
│   ├── v01.md
│   ├── v02.md
│   ├── v025.md
│   ├── v03.md
│   ├── v04.md
│   ├── v045.md
│   ├── v05.md
│   ├── v051.md
│   ├── v06.md
│   ├── v07.md
│   ├── v08.md
│   ├── v09.md
│   └── v10.md
│
└── research/
```

The roadmap should remain the high-level contract. Version specifications contain implementation-level detail.

---

# 12. Release Sequence

```text
V0.1   Data / Rules
  ↓
V0.2   Decision Support
  ↓
V0.2.5 Historical Evaluation
  ↓
V0.3   Prediction
  ↓
V0.4   Optimization
  ↓
V0.45  Closed Loop
  ↓
V0.5   Workstation
  ↓
V0.5.1 Stabilization
  ↓
V0.6   Dossier + Intelligence + Multi-League Foundation
  ↓
V0.7   Sequential Replay
  ↓
V0.8   Prediction / Context
  ↓
V0.9   EuroCup Parity + Cross-League Validation
  ↓
V1.0   Mature Multi-League Platform
```

This sequence intentionally separates:

- predicting
- deciding
- measuring
- using
- interpreting
- replaying
- improving
- generalizing
- maturing

---

# 13. Final Architectural Test

Before V1.0, a technically competent human should be able to answer:

> What did the system know?

> What did the deterministic engine predict?

> What did the optimizer recommend?

> What alternatives existed?

> What did the strategic layer assume?

> What did the human decide?

> What actually happened?

> Which parts are rules, statistics, optimization, or interpretation?

> Can the result be reproduced from the recorded inputs and configuration?

If those questions can be answered reliably, the platform has reached its intended maturity bar.
