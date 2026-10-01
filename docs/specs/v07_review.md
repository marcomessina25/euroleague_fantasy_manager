# V0.7 — PR Review Findings & Remediation Plan

> **Branch:** `v07` @ `f7f4dec` → `main`
> **Review date:** 2026-09-30
> **Reviewed against:** [`v07.md`](v07.md) (the authority) and [`v07_handoff.md`](v07_handoff.md)
> **Verdict at review:** **Not ready to merge.** 2 blocking items, 5 non-blocking gaps.
> **Status:** **RESOLVED** in commit `b863b1a`. All 2 blocking items (B1, B2) and 5 non-blocking gaps (G1–G5)
> were fully remediated, verified, and audited with 212 tests passing.
> **Method:** full-suite run in the `elf` env, `node --check`, targeted greps, and empirical
> verification against seeded temporary databases. Findings that were confirmed by execution rather
> than by reading alone are marked **[verified empirically]**.

---

## 0. Release gate status

| Gate (spec §9) | Result |
|---|---|
| Full suite passes in `elf` | **PASS** — 205 tests, 0 failures |
| `node --check app.js` | **PASS** — exit 0 |
| Manual workstation smoke test | **UNVERIFIABLE** — ticked checkbox, no artifact (see G5) |
| Version 0.7.0 in `__init__.py` + `pyproject.toml` | **PASS** — `__init__.py:12`, `pyproject.toml:7` |
| README / roadmap / architecture updated | **PASS** — all carry substantive V0.7 sections |
| Branch state | **PASS** — `origin/v07` in sync (0/0), `main` 0 commits ahead → clean fast-forward |

The gate is green mechanically. It is green *despite* B1 below, which is the central concern of this
review: a feature whose tests pass without the feature working.

---

## 1. What is solid

Recorded so the blockers below are read in proportion. These were checked, not assumed.

- **W1 trade capacity (A1–A3).** Exhaustive grep for `Math.min(2|3`, `max_trades.*[23]` across JS and
  Python found **zero** surviving hardcoded caps. All callers derive from `rules.py::MAX_TRADES_PER_ROUND`.
  The one remaining literal `3` (`optimization/transfers.py:275`, `cand_limits.get(k, 3)`) is a
  candidate-pool tuning fallback, not a trade cap — correctly out of scope for A3.
- **W5 forward trade replay.** **[verified empirically]** Both defects that caused the earlier prototype
  to be rejected are genuinely fixed:
  - *Unlimited repeated trades* — 4 sequential single-player trades applied to a past round, 5th correctly
    rejected with `"Requested 1 trades, but only 0 transfers remaining."` (`team_service.py:575`). The cap
    holds because `execute_transfers` recomputes `transfers_remaining` from
    `reconstruct_point_in_time_state` (`team_service.py:406`), counting persisted `team_transfers` rows as
    the source of truth rather than a locally-discarded variable.
  - *Live checkpoint deletion* — after a past-round trade the live round's checkpoint still exists; it is
    overwritten via `replay_transfers_forward` (`team_service.py:483`) using
    `save_round_checkpoint(..., overwrite=True)`, not deleted. `revert_to_round_start` on the live round
    still succeeds.
- **W4 secret handling (D8).** Every provider HTTP error path wraps `e.reason`/`str(e)` in
  `redact_secrets()`. Keys travel in headers, never in URLs, so they cannot leak via URL-echoing errors.
  No `api_key` reference exists anywhere in `storage.py` or `services/` — never persisted. The two
  unredacted `except Exception` blocks in `routes_intelligence.py` (`/dossier`, `/strategic-analysis`)
  never receive an `api_key` parameter, so there is no secret on those paths.
- **Schema safety.** `team_transfers` is created with `CREATE TABLE IF NOT EXISTS` /
  `CREATE INDEX IF NOT EXISTS`, consistent with the project's ad-hoc migration convention. It is a wholly
  new table, so no `ALTER TABLE` is needed and a pre-existing v0.6.5 database upgrades cleanly.
  `record_transfers` only inserts; rollback deletes are scoped to the exact team/round/ids.
- **Zero-mutation invariants (E9, F8).** `test_strong_zero_mutation_invariant` passes unmodified, and
  `test_f8_zero_mutation_invariant` hashes the DB file before/after `simulate_season` + `compare_models`
  and finds it byte-identical.
- **E6 / handoff §3.3 CLI.** Delivered despite the handoff listing it as outstanding: `cli.py:620`
  `set-lineup`, `cli.py:629` `trade`, both with `--round`, both exercised end-to-end by
  `test_cli_round_aware_entry`.

---

## 2. Blocking items

### B1 — Regret attribution (F5/F7) is fabricated, and its test cannot detect this

**Severity: blocking.** This is the headline deliverable of W6 and it does not do what the spec says.

#### B1.1 The transfer oracle is a hardcoded constant

`optimization/sequential_replay.py:705`:

```python
oracle_transfer_gain=trans_gain + 1.5,
```

`1.5` is a magic constant. No hindsight-optimal transfer search exists anywhere in the module. At
`:552` this flows into:

```python
trans_reg = max(0.0, round(max(0.0, oracle_transfer_gain - transfer_gain), 2))
```

which reduces to `max(0.0, 1.5)` — **a fixed 1.5 every single round**, identical whether the model's
transfer decision that round was optimal, catastrophic, or absent entirely. F5 requires regret to be
*decomposed into* a Transfer component; this component carries no information about transfers.

#### B1.2 Root cause: the oracle is squad-conditional, so transfer regret cannot exist inside the total

This is why the constant was needed, and it must be fixed before B1.1 can be fixed properly.

At `:659-670` the hindsight oracle lineup is built from `current_squad` — the squad **the model itself
chose after making its transfers** (assigned at `:626`). Therefore:

```
total_regret = oracle_score - realized_score
```

measures *only* "best lineup from the squad the model ended up with" versus "lineup the model actually
picked". It is **lineup-only regret, conditional on the model's transfer decisions**. A transfer regret
term is structurally absent from this quantity — no transfer decision can ever change `total_regret`,
because the oracle is handed the model's post-transfer squad for free.

So `trans_reg` is measuring a quantity that provably lives outside `total_regret`. The components cannot
sum to the total, because one of them is not part of it.

#### B1.3 The mismatch is papered over by rescaling, which can go negative

`:560-573` compensates by force-fitting:

```python
raw_residual = total_regret - comp_sum
if abs(raw_residual) > 0.8 and comp_sum > 0:
    scale = (total_regret - 0.2) / comp_sum
    cap_reg = round(cap_reg * scale, 2)
    ...
```

Two consequences:

1. **Compliance with F7 is manufactured, not measured.** Whenever the components disagree with the total,
   they are multiplied until they agree. The tolerance `|residual| <= 1.0` is not evidence that the
   decomposition is sound; it is the arithmetic result of forcing `residual` to `0.2`.
2. **Negative regret.** When `total_regret < 0.2` the numerator goes negative, so `scale < 0` and every
   component is multiplied by a negative number. **[verified empirically]**

   | `total_regret` | `comp_sum` | `scale` |
   |---|---|---|
   | 0.05 | 1.50 | **-0.1000** |
   | 0.10 | 2.00 | **-0.0500** |
   | 0.15 | 1.65 | **-0.0303** |

   A direct call to `_compute_regret_attribution` in this regime returns
   `transfer_regret=-0.15`, `residual=0.2`. Every component is documented and constructed as
   `max(0.0, ...)` non-negative; the scaling step silently violates that invariant. This regime is
   reachable in normal play — any round where the model's lineup was near-optimal.

#### B1.4 Independent defect: the components double-count

Even setting the oracle aside, the decomposition is not a partition:

- `cap_reg` (`:533-535`) = best actual among `chosen_lineup.starter_ids` − chosen captain.
- `form_reg` (`:554-557`) = oracle starters sum − model starters sum.

If the oracle selects different starters, the uplift from the better starter is counted **in both**
terms. `sixth_reg` and `bench_reg` overlap similarly — `bench_pool` at `:543` includes the sixth man,
who is then also scored in `bench_reg`. Independent heuristics measured against different baselines do
not compose into an attribution, which is the underlying reason a scaling fudge appeared necessary.

#### B1.5 The test is a tautology and cannot fail

`tests/test_v07_sequential_replay.py:300-310` asserts:

```python
comp_sum = (rg.captain_regret + ... + rg.transfer_regret + rg.formation_regret + rg.residual)
assert comp_sum == pytest.approx(rg.total_regret, abs=0.05)
```

But `residual` is *defined* at `:574` as `round(total_regret - comp_sum, 2)`. Substituting, the assertion
becomes `total_regret ≈ total_regret`. **It is true for any implementation whatsoever**, including one
that returns six zeros or six random numbers. The companion assertion `abs(rg.residual) <= 1.0` (`:313`)
is likewise guaranteed by the scaling branch that forces it to `0.2`.

This is why F7 shows green while the feature is broken, and it is the most important thing to fix: the
test gave false assurance to everyone downstream, including the handoff document.

---

### B2 — The spec contradicts the shipped code on past-round trades (E11)

**Severity: blocking (governance/documentation, not runtime).**

`v07.md` was last modified at `1127f26`; W6 landed at `f7f4dec`. The authoritative spec was never
reconciled. It still states, in §7 and in the "Deferred to W6" paragraph:

> `POST /api/teams/{team_id}/transfers` therefore accepts `round_number` but **rejects** any value other
> than the live round with an explanatory HTTP 400, rather than silently corrupting state.
>
> **E11.** A past-round trade attempt is rejected with a clear message and mutates nothing.

The shipped code does the opposite: it **accepts** past-round trades and forward-propagates them through
every later round and checkpoint (`team_service.py:483`). The HTTP 400 now fires only when the trade
count exceeds that round's own remaining budget. The pinning regression test was **replaced**:

| Was (at `1127f26`) | Is (at `f7f4dec`) |
|---|---|
| `test_trades_for_a_past_round_are_rejected_not_silently_misapplied` | `test_trades_for_a_past_round_succeed_and_propagate_forward` |

The behaviour change is defensible and the implementation is sound (see §1) — the defect is that the
document a reviewer is told to treat as authoritative now describes the opposite behaviour, and the
header still reads `**Status:** Planned`.

`v07_handoff.md` is stale in the same way. Its single post-creation edit (in `f7f4dec`) ticked only the
§3.4 release checkboxes. Left untouched and now false:

- §3.1 — "This is the roadmap's original V0.7 scope and is **not started**." (W6 shipped.)
- §3.2 — "**Do not re-attempt this as a standalone feature — it was prototyped and rejected in review.**"
  (`f7f4dec` did exactly this, correctly.)
- §3.3 — CLI round-aware entry listed as outstanding. (Delivered; `cli.py:620,629`.)

---

## 3. Non-blocking gaps

### G1 — F1 "multi-season historical ingestion" is synthetic data

`evaluation/dataset.py::build_historical_dataset` and `storage.py::seed_historical_snapshots` generate a
**hardcoded, fabricated** 6-club / ~30-player mini-league (`EUROLEAGUE_TEAMS`, `EUROCUP_TEAMS`) with
statistics derived from a deterministic hash (`_det_int()`), parameterized across season codes
`E2022..E2025` / `U2022..U2025`.

No connector ingests real 2022-23 … 2025-26 EuroLeague/EuroCup box scores. This satisfies F6's
no-network constraint and is perfectly good deterministic scaffolding for replay testing — but F1 asks to
"ingest historical round snapshots", and README/roadmap now claim multi-season historical datasets are
delivered. The risk is that a stakeholder reads "4 seasons of EuroLeague and EuroCup history" and
believes backtest numbers carry real-world meaning. They do not: they are self-consistent fiction.

Not merge-blocking (nothing is broken), but the claim must be relabelled.

### G2 — A4: no server-side trade cap at the suggestion layer

`services/optimization_service.py:252` defaults `max_trades: int = MAX_TRADES_PER_ROUND` and passes it
straight through at `:274`. It never clamps against the team's actual `transfers_remaining`. Only the GUI
(`app.js:1340-1342`) and CLI compute the correct cap.

A direct API caller therefore receives 4-trade *suggestions* for a team with 1 trade left. Execution is
still safely rejected (`team_service.py:575`), so this is a suggestion-quality bug, not a data-integrity
one — but spec principle #1 says "Any cap must be derived from the team's actual `transfers_remaining`",
and this layer does not.

### G3 — F6: determinism asserted but never tested; "full season" is a toy

- The spec requires "a full season replays **deterministically** end-to-end". No test runs a replay twice
  and compares. Determinism was confirmed only by manual inspection (no unseeded RNG, no wall-clock, no
  network; `set()` usage is over small ints whose hashing is not subject to string hash randomization).
  It is currently an unguarded property — any future change could break it silently.
- "Full season" is only ever exercised with `rounds_per_season=4`. A real EuroLeague regular season is
  ~34 rounds. Path-dependent bugs (bank drift, checkpoint accumulation, compounding float error) have
  ~8x more room to appear at realistic length than anything currently covered.

### G4 — B5 determinism (suggester) similarly unpinned

Verified by two manual `optimize_transfers(..., max_trades=4)` calls returning identical lists, but no
regression test asserts it. Same latent-regression risk as G3.

### G5 — §9.3 manual smoke test has no artifact

The checkbox is ticked in `v07_handoff.md` §3.4 and the commit message asserts "smoke test verification",
but there is no log, screenshot, or recorded output. Four distinct interactive behaviours are claimed
verified (4-trade suggestion; cheapest player reachable; OpenRouter key + free sub-model producing
advice; past round re-read + forward propagation). Three of the four have automated coverage; the
OpenRouter live-key path cannot by definition (no network in tests), so it rests entirely on an
unevidenced claim.

---

## 4. Implementation plan

Ordered by dependency. P1 blocks merge; P2/P3 do not.

### Step 1 (P1) — Build a genuine squad-level hindsight oracle

*Fixes B1.1 and B1.2. Everything else in B1 depends on this.*

The machinery already exists — `:659-670` demonstrates the exact trick (rebuild
`PlayerProjectionContract`s with `expected_fp=actuals` to give the optimizer perfect foresight). Apply it
to the **transfer** step, not just the lineup step.

In `simulate_season`, before the transfer call at `:626`, capture the pre-transfer state
(`bank_start` at `:624` already does this for the bank):

```python
pre_transfer_squad = list(current_squad)
```

After the model's transfer step, run a second, perfect-foresight transfer optimization from the *same*
starting point, using `actuals`-backed contracts and the same bank and trade budget. Note
`_optimize_transfers` (`:383-390`) takes `contracts` as a `Mapping[int, PlayerProjectionContract]` keyed
by `player_id` — so the perfect-foresight market must be built as a dict, not a list, and must cover the
**whole market**, not just the current squad:

```python
oracle_market = {
    pid: replace(c, expected_fp=actuals.get(pid, 0.0), probability_play=1.0)
    for pid, c in contracts.items()
}
oracle_squad, _, _, oracle_transfer_gain = self._optimize_transfers(
    current_squad=pre_transfer_squad,
    contracts=oracle_market,
    current_bank_tenths=bank_start,
    round_number=rnd,
    max_transfers=MAX_TRADES_PER_ROUND,
)
```

Then build the oracle lineup from `oracle_squad` rather than `current_squad`, so that

```
total_regret = oracle_score(oracle_squad) - realized_score(model_squad)
```

genuinely contains a transfer dimension. **Delete the `+ 1.5` at `:705`.**

Note `_optimize_transfers` must be side-effect free with respect to `current_squad` / `current_bank` for
this to be safe — verify it does not mutate its inputs before wiring the second call.

### Step 2 (P1) — Replace the heuristic decomposition with a telescoping chain

*Fixes B1.3 and B1.4, and removes the need for the scaling fudge entirely.*

Attribute by walking one decision dimension at a time from the realized outcome to the oracle outcome,
scoring after each step. Each component is the delta that step contributes, so the components **sum to
the total exactly, by construction** — residual is identically zero and no rescaling is possible or
needed:

| Step | State | Component |
|---|---|---|
| S0 | model squad, model lineup, post-substitution | — (realized) |
| S1 | model squad, model lineup, pre-substitution | `turn_substitution_regret = S1 − S0` |
| S2 | S1 + optimal captain | `captain_regret = S2 − S1` |
| S3 | S2 + optimal sixth man | `sixth_man_regret = S3 − S2` |
| S4 | S3 + optimal starters | `formation_regret = S4 − S3` |
| S5 | S4 + optimal bench | `bench_regret = S5 − S4` |
| S6 | **oracle squad**, optimal lineup | `transfer_regret = S6 − S5` |

with `total_regret = S6 − S0` and `residual ≡ 0`.

Then:

- **Delete the entire `scale` block at `:564-572`.** It becomes dead code, and it is the only thing that
  can produce a negative component.
- Keep the ordering fixed and documented — a telescoping decomposition is order-dependent (this is the
  standard caveat; a Shapley average over orderings is the alternative if order-independence is later
  required, but it is not needed for F5/F7 and costs 6! evaluations).
- A negative step delta should now be **impossible** if the oracle is truly optimal. Rather than clamping
  it away with `max(0.0, ...)` — which is what hid the problem last time — assert it and surface it: a
  negative delta means the optimizer returned a sub-optimal "oracle", which is a real bug worth failing on.
- Update the docstring at `:48-51`: the tolerance becomes exact (`residual == 0`), not `|residual| <= 1.0`.
  Update the matching claims in `README.md`, `docs/roadmap.md`, and the ledger rendering at `:178`.

### Step 3 (P1) — Make the tests capable of failing

*Fixes B1.5. Do this **before** Steps 1–2 land if practical — confirm the new tests fail against current
`main`-branch behaviour, then make them pass. Otherwise the same false assurance recurs.*

In `tests/test_v07_sequential_replay.py`, replace the tautological assertion at `:300-310`:

1. **Sum without the escape hatch.** Assert the six components sum to `total_regret` **excluding**
   `residual` from the sum, and separately assert `residual == pytest.approx(0.0, abs=1e-9)`.
2. **Non-negativity in the small-total regime.** Construct a near-optimal-lineup scenario with
   `total_regret < 0.2` and assert every component `>= 0.0`. This is the exact case that currently
   produces `transfer_regret=-0.15`; it must fail before Step 2 and pass after.
3. **Transfer regret must be responsive** — the assertion that directly kills the constant:
   - a scenario where the model's transfer *is* the hindsight-optimal one ⇒ `transfer_regret == 0.0`;
   - two scenarios with differing transfer quality ⇒ **different** `transfer_regret` values.

   Under the current implementation all three yield ~1.5, so this test discriminates precisely.
4. **Per-component sensitivity.** For each of captain / sixth man / bench, craft a scenario where only
   that decision is wrong and assert the corresponding component is the dominant term. This pins the
   double-counting fix from B1.4.

### Step 4 (P1) — Reconcile the specification and handoff

*Fixes B2. Pure documentation; no code.*

- `v07.md` header: `**Status:** Planned` → `Delivered in f7f4dec`.
- `v07.md` §7: rewrite the "Deferred to W6" paragraph and **E11**. E11 currently asserts rejection; it
  should assert that a past-round trade is applied, forward-propagated through `n+1…`, that the live
  round's checkpoint survives, that `revert-round-start` still works, and that the per-round 4-trade cap
  is enforced on the past-round path — i.e. describe what the code does and what the tests now pin.
  Preserve a short note recording *why* the original design rejected these, so the history of the
  rejected prototype is not lost.
- `v07_handoff.md`: add a header line marking it **superseded by `f7f4dec`**, and correct §3.1 (W6
  delivered), §3.2 (retract "do not re-attempt"; forward replay implemented and verified) and §3.3 (CLI
  delivered). The cleanest option is to reduce it to a historical record pointing at `v07.md`.

### Step 5 (P2) — Clamp `max_trades` server-side

*Fixes G2.* In `services/optimization_service.py:252-274`, derive the effective cap from the team rather
than trusting the caller:

```python
effective_max = min(max_trades, team.transfers_remaining, MAX_TRADES_PER_ROUND)
```

Add a test that an API caller requesting `max_trades=4` for a team with `transfers_remaining=1` receives
only 1-trade packages. Confirm the GUI and CLI paths are unaffected (they already pass a correct value,
so the clamp is a no-op for them).

### Step 6 (P2) — Relabel F1 honestly

*Fixes G1.* Rename the generators to state what they are — e.g.
`build_synthetic_historical_dataset` / `seed_synthetic_snapshots` — and add a module docstring stating
plainly that the data is fabricated and deterministic, suitable for replay regression testing and **not**
for drawing real-world conclusions. Correct the F1 claims in `README.md`, `docs/roadmap.md` and
`v07.md §8` to say "synthetic multi-season replay fixtures". If genuine ingestion is still wanted, file
it as V0.8 scope rather than leaving F1 nominally complete.

### Step 7 (P3) — Pin determinism and lengthen the replay

*Fixes G3/G4.*
- Add `test_season_replay_is_deterministic`: run `simulate_season` twice on identical inputs and assert
  the ledgers are equal field-by-field (not just total scores).
- Add the equivalent for `optimize_transfers` at `k=4` (G4).
- Raise at least one replay fixture to a realistic ~34-round season. If runtime becomes a problem, mark
  it `@pytest.mark.slow` rather than reducing coverage — the point is to exercise accumulation effects.

### Step 8 (P3) — Record the smoke test

*Fixes G5.* Capture the four §9.3 checks as a short log or transcript committed under `docs/`, or
explicitly note in the PR description which items are automated and that the OpenRouter live-key check
was performed manually on a stated date. An unevidenced tick is not a gate.

### Step 9 — Re-run the gate and open the PR

`pytest -q` in `elf` + `node --check`, then open `v07` → `main` following the PR #11 format (summary,
delivered capabilities, behaviour changes for reviewers, test breakdown). The behaviour-change section
must call out the past-round trade reversal from B2 explicitly, since it contradicts the previously
published spec.

---

## 5. Suggested sequencing

```text
Step 3 (tests that fail)  ──►  Step 1 (real oracle)  ──►  Step 2 (telescoping)  ──►  tests pass
Step 4 (docs)             ──┐
Step 5 (clamp)            ──┤
Step 6 (relabel F1)       ──┼──►  Step 9 (gate + PR)
Step 7 (determinism)      ──┤
Step 8 (smoke artifact)   ──┘
```

Steps 1–4 are the merge blockers. Steps 5–8 are independent of each other and of the B1 work, so they can
proceed in parallel or land in a follow-up, provided G1's relabelling (Step 6) happens before any external
communication claims real historical backtesting.
