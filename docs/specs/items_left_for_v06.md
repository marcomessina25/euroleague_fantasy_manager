# V0.6 — Items Left Before Release

> **Purpose:** Finalize V0.6 without expanding its scope.
>
> **Current state:** PR #8 implements the main V0.6 architecture: Manager Dossier, deterministic strategic analysis, grounded Copilot, multi-league foundation, six-team capacity, provenance, consistency checks and workstation integration.
>
> **Rule:** This document is the execution checklist for completing V0.6. Do not add new prediction models, optimizer algorithms, autonomous behavior or unrelated product features.

---

# 1. V0.6 Release Boundary

V0.6 is complete when the following architecture is reliable:

```text
common engine
      ↓
league adapter / ruleset
      ↓
team-specific state
      ↓
Manager Dossier
      ↓
deterministic strategic analysis
      ↓
optional LLM Copilot
      ↓
human decision
      ↓
decision log
```

The deterministic engine remains authoritative.

The LLM may explain, compare, challenge and interpret, but it must not:

- override deterministic rules;
- replace optimizer calculations;
- invent quantitative facts;
- execute transfers;
- mutate persistent team state without explicit human workflow.

EuroLeague and EuroCup must use the same engine/contracts. V0.6 establishes EuroCup architectural compatibility; complete EuroCup feature/rule parity remains a V0.9 objective.

---

# 2. PR #8 Merge Blockers

These are the small correctness/hardening items to resolve before merging the current V0.6 PR.

## 2.1 Strict league parsing

**Status:** ✅ Completed

Review `League.from_str()` and related parsing.

Required:

- valid EuroLeague values map to `EUROLEAGUE`;
- valid EuroCup values map to `EUROCUP`;
- existing supported case/format variants remain supported;
- unknown non-empty league values must fail explicitly;
- malformed league values must fail explicitly;
- an unknown league must never silently become EuroLeague.

Add regression tests for:

- valid EuroLeague;
- valid EuroCup;
- supported aliases/case variants;
- unknown league → error;
- malformed league → error.

Do not add support for additional competitions.

---

## 2.2 `elf advise` must be read-only

**Status:** ✅ Completed

Review the CLI `elf advise` path.

The analysis command must not silently create a persistent `"default_team"` or otherwise mutate team state.

Required behavior:

- resolve an existing team;
- if no valid team exists, return a clear actionable error;
- do not create a persistent team as a side effect;
- do not modify squad, bank, transfers, decisions, checkpoints, scenarios or other persistent team state.

If a separate team-creation workflow already exists, point the user toward it.

Add a regression test proving that `elf advise` with no valid team does not create or modify persistent state.

---

## 2.3 Strong zero-mutation invariant

**Status:** ✅ Completed

Add an integration-level test for the central V0.6 safety property:

> Dossier generation and strategic/Copilot analysis may inspect team state but cannot mutate persistent fantasy state.

Test sequence:

```text
state_before
    ↓
Manager Dossier
    ↓
deterministic strategic analysis
    ↓
mock/heuristic Copilot
    ↓
state_after
```

Assert that the complete relevant persistent state is identical.

Cover, as applicable:

- team metadata;
- league;
- squad;
- bank;
- transfers;
- decisions;
- checkpoints;
- scenarios;
- provenance/audit records;
- any other persistent team state.

The test must not depend on an external LLM vendor.

Run it with at least:

- deterministic/heuristic provider;
- mocked LLM provider.

---

# 3. Multi-League Foundation

## 3.1 Shared engine / adapter boundary

**Status:** ✅ Verified

Confirm that the architecture is:

```text
Shared engine contracts
        │
        ├── EuroLeague ruleset
        └── EuroCup ruleset
```

and not separate EuroLeague/EuroCup application implementations.

Verify that the following remain shared:

- API/service contracts;
- storage;
- team model;
- prediction contracts;
- valuation contracts;
- optimization contracts;
- decision logging;
- evaluation;
- CLI;
- workstation.

Only competition-specific rules/data semantics should live in league adapters/rulesets.

---

## 3.2 Ruleset semantics

**Status:** ✅ Verified

If EuroLeague and EuroCup currently have identical values for some rules, that is acceptable for V0.6.

Do not invent differences merely to make the classes different.

What matters is that:

- the ruleset contract is explicit;
- the active team's league selects the ruleset dynamically;
- competition-specific rules can diverge later without architectural duplication;
- the selected ruleset is persisted/reproducible.

Add or improve tests where necessary.

---

## 3.3 League persistence

**Status:** ✅ Verified

Confirm that:

- team league metadata survives persistence round-trip;
- old databases migrate safely;
- EuroLeague and EuroCup teams can coexist;
- services consistently retrieve the correct league;
- no component assumes EuroLeague when team metadata says EuroCup.

---

# 4. Six-Team Support

## 4.1 Six-team capacity

**Status:** ✅ Verified

Confirm maximum capacity is six managed teams.

Test:

```text
Team 1
Team 2
Team 3
Team 4
Team 5
Team 6
```

and verify that creation, persistence, selection and deletion/management remain isolated.

---

## 4.2 Mixed-league isolation

**Status:** ✅ Verified

Test a realistic mixed setup such as:

```text
Team A → EuroLeague
Team B → EuroLeague
Team C → EuroCup
Team D → EuroLeague
Team E → EuroCup
Team F → EuroCup
```

Verify:

- team state remains isolated;
- league metadata remains correct;
- selecting one team cannot alter another;
- dossier generation uses the selected team's league;
- ruleset selection follows the selected team's league.

---

# 5. Manager Dossier

## 5.1 Dossier completeness

**Status:** ✅ Verified

Confirm the dossier exposes the quantitative information required by V0.6:

- team state;
- league;
- squad;
- bank;
- round/turn;
- projections;
- expected minutes;
- play probability;
- FP/min;
- uncertainty where available;
- valuations;
- PAR/value metrics;
- lineup recommendation;
- captain;
- sixth;
- bench;
- transfer packages;
- intra-round alternatives;
- multi-round candidates where available;
- relevant schedule/context;
- optimizer configuration;
- prediction provenance.

Do not add new prediction functionality just to populate a field.

---

## 5.2 Determinism

**Status:** ✅ Verified

For identical:

- team state;
- data snapshot;
- model version;
- configuration;
- ruleset;

dossier generation must produce equivalent deterministic output.

Verify that timestamps or other intentionally dynamic metadata do not accidentally contaminate the quantitative content hash.

---

## 5.3 Provenance

**Status:** ✅ Verified

Confirm that quantitative facts can be traced back to:

- source/run;
- model version;
- cutoff;
- optimizer configuration;
- league/ruleset;
- dossier version.

Never store secrets/API keys.

---

# 6. Deterministic Strategic Analysis

## 6.1 Assumption Breakdown

**Status:** ✅ Verified

Confirm that the system identifies high-impact assumptions using deterministic inputs.

At minimum consider:

- participation;
- minutes;
- efficiency;
- captaincy;
- schedule/context;
- bank/liquidity where relevant.

The output must explain the quantitative basis rather than inventing assumptions.

---

## 6.2 Sensitivity Analysis

**Status:** ✅ Verified

Confirm one-way perturbation behavior is:

- deterministic;
- reproducible;
- clearly labeled as a scenario/shock;
- separate from the base prediction;
- not silently modifying persistent state.

---

## 6.3 Devil's Advocate Checklist

**Status:** ✅ Verified

Confirm deterministic checks for:

- legality;
- forecast plausibility;
- alternative completeness;
- downside/regret;
- context/change.

The checklist must remain fully usable with LLM functionality disabled.

---

# 7. Grounded Copilot

## 7.1 Provider abstraction

**Status:** ✅ Verified

Confirm provider implementations share a common interface.

Providers may include:

- Heuristic/offline;
- OpenAI;
- Claude;
- OpenRouter;
- Gemini;
- local provider.

Do not introduce provider orchestration/routing in V0.6.

---

## 7.2 Failure isolation

**Status:** ✅ Verified

Test:

- timeout;
- invalid credentials;
- unavailable provider;
- malformed provider response.

Expected behavior:

```text
provider failure
      ↓
deterministic fallback
      ↓
team state unchanged
```

No provider failure may corrupt persistent state.

---

## 7.3 Numerical grounding

**Status:** ✅ Verified

LLM numerical claims must be checkable against dossier facts.

Verify that:

- unknown player names are flagged;
- unsupported numbers are flagged;
- stated recommendations correspond to actual deterministic recommendations;
- alternatives exist in the dossier;
- unsupported fantasy mechanisms are flagged.

Do not attempt to make the LLM independently authoritative.

---

# 8. Human-Control Boundary

## 8.1 No autonomous mutation

**Status:** ✅ Verified

Confirm that Copilot cannot:

- execute transfers;
- change lineup;
- change captain;
- modify bank;
- create/delete teams;
- alter checkpoints;
- alter persistent decisions.

All state-changing workflows require explicit human action through the normal application path.

---

## 8.2 Read-only analysis

**Status:** ✅ Verified

Confirm that:

```text
dossier generation
strategic analysis
Copilot analysis
consistency verification
```

are all read-only with respect to fantasy state.

This is a core V0.6 invariant.

---

# 9. Workstation / GUI

## 9.1 Intelligence tab

**Status:** ✅ Verified

Confirm the GUI exposes:

- deterministic assumptions;
- sensitivity analysis;
- Devil's Advocate checklist;
- Copilot result;
- provider/tier metadata;
- consistency status;
- raw dossier/provenance inspection where appropriate.

---

## 9.2 Team selection

**Status:** ✅ Verified

Confirm the intelligence UI always operates on the currently selected team and therefore the correct:

- league;
- ruleset;
- squad;
- bank;
- round;
- decision history.

Test switching between EuroLeague and EuroCup teams.

---

# 10. CLI

## 10.1 `elf advise`

**Status:** ✅ Verified

Confirm:

- team selection works;
- league metadata is respected;
- provider selection works;
- persona selection works;
- tier selection works;
- JSON output works;
- output file handling works;
- no implicit team creation occurs.

---

## 10.2 `elf team create --league`

**Status:** ✅ Verified

Confirm:

- EuroLeague creation;
- EuroCup creation;
- invalid league rejection;
- persisted league metadata;
- maximum six-team limit.

---

# 11. Documentation

## 11.1 V0.6 specification

**Status:** ✅ Completed

Ensure `docs/specs/v06.md` clearly states:

- common engine;
- league adapter/ruleset architecture;
- six-team support;
- Manager Dossier;
- deterministic analysis;
- optional LLM;
- human control;
- provenance;
- failure isolation;
- V0.6 EuroCup architectural compatibility;
- V0.9 EuroCup parity boundary.

---

## 11.2 Roadmap

**Status:** ✅ Completed

Ensure `docs/roadmap.md` reflects:

```text
V0.5.1 → stabilization
V0.6   → dossier + intelligence + multi-league foundation
V0.7   → sequential replay
V0.8   → prediction/context
V0.9   → EuroCup parity + cross-league validation
V1.0   → mature multi-league platform
```

Do not describe V0.9 as the introduction of EuroCup.

---

## 11.3 V1.0 specification

**Status:** ✅ Completed

Ensure `docs/specs/v10.md` treats these as V1.0 maturity requirements:

- shared EuroLeague/EuroCup engine;
- explicit league adapters;
- six isolated teams;
- reproducibility;
- auditability;
- closed-loop evaluation;
- optional human-controlled AI;
- no autonomous management.

---

# 12. Test & Regression Gate

Before declaring V0.6 complete:

**Status:** ✅ Passed (114 passed, 0 failures, 0 regressions in 33.39s)

Run the complete repository test suite.

Required:

- all V0.6 tests pass;
- all V0.5.1 and earlier tests pass;
- no regression;
- no new unexpected warnings;
- no provider/network dependency for deterministic tests.

Record the exact command and result in the release/PR documentation.

Command executed:
```powershell
$env:PYTHONPATH="src"; C:\Users\mom\.conda\envs\elf\python.exe -m pytest tests/
```

Result:
```text
114 passed, 1 warning in 33.39s (0 failures, 0 regressions)
```

---

# 13. V0.6 Release Checklist

All must be checked before tagging/releasing V0.6:

- [x] strict league parsing
- [x] read-only `elf advise`
- [x] zero-mutation invariant test
- [x] six-team support verified
- [x] mixed EuroLeague/EuroCup isolation verified
- [x] league metadata persistence verified
- [x] shared engine / ruleset boundary verified
- [x] Manager Dossier complete
- [x] dossier deterministic
- [x] provenance complete
- [x] deterministic strategic analysis works offline
- [x] Copilot provider abstraction verified
- [x] provider failure isolation verified
- [x] numerical/rule grounding verified
- [x] human-control boundary verified
- [x] GUI intelligence workflow verified
- [x] CLI workflow verified
- [x] documentation synchronized
- [x] complete regression suite green

---

# 14. V0.6.5 Candidates

These are deliberately **not V0.6 blockers** unless they reveal a correctness issue.

Potential V0.6.5 work:

- UX polish of the Intelligence tab;
- improved dossier visualization;
- additional provider integrations;
- better Copilot prompt templates;
- richer deterministic sensitivity reports;
- improved latency/caching;
- more detailed provenance UI;
- additional consistency heuristics;
- performance improvements;
- usability improvements from real workstation usage.

V0.6.5 must remain a hardening/UX release, not a new prediction or optimization milestone.

---

# 15. Explicitly Out of Scope

Do not add the following to V0.6 merely because they are technically interesting:

- new prediction models;
- new optimizer algorithms;
- reinforcement learning;
- autonomous agents;
- automatic transfer execution;
- automatic provider routing;
- multi-agent LLM orchestration;
- full historical sequential replay;
- complete EuroCup feature parity;
- cloud SaaS;
- mobile application;
- social/competitive features;
- new fantasy competitions;
- replacing deterministic rules with LLM reasoning.

These belong to later releases or are explicitly non-goals.

---

# 16. Definition of Done

V0.6 is complete when a human can:

1. Manage up to six isolated teams.
2. Assign each team explicit EuroLeague/EuroCup metadata.
3. Run the same engine/contracts against either competition.
4. Generate a deterministic Manager Dossier.
5. Inspect deterministic strategic assumptions and sensitivities.
6. Run the complete workflow without an LLM.
7. Optionally invoke a grounded LLM Copilot.
8. Verify Copilot claims against deterministic evidence.
9. Recover safely from provider failure.
10. Confirm that analysis cannot mutate persistent fantasy state.
11. Make the final decision manually.
12. Log the decision with provenance.
13. Reproduce the relevant quantitative state from the recorded inputs/configuration.

The release should leave the project in this state:

```text
        ┌──────────────────────┐
        │   Common ELF Engine  │
        └──────────┬───────────┘
                   │
          ┌────────┴────────┐
          ▼                 ▼
     EuroLeague          EuroCup
      adapter             adapter
          │                 │
          └────────┬────────┘
                   ▼
              Team State
                   ▼
            Manager Dossier
                   ▼
       Deterministic Analysis
                   ▼
            Optional LLM
                   ▼
               Human
```

> **V0.6 is finished when intelligence is safely layered around the deterministic engine — not when the LLM becomes the engine.**
