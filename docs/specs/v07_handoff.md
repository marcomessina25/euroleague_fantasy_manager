# V0.7 Handoff — Remaining Work

> **For:** the next AI agent (or human) continuing V0.7.
> **Branch:** `v07` (pushed to `origin/v07`, branched from `main` after PR #11 merged V0.6.5).
> **State at handoff:** 2026-09-30. **197 tests pass**, `node --check` clean.
> **Spec:** [`v07.md`](v07.md) is the authority. This file only tracks what is left.

---

## 1. Environment (read first — this trips people up)

- **Use the `elf` conda environment.** It is Python 3.12 with all dependencies installed:
  `C:\Users\mom\.conda\envs\elf\python.exe`
- The machine's *global* Python is **3.14**, which `pyproject.toml` excludes (`>=3.11,<3.14`).
  Do not use it, and do not create a `.venv`.
- Run the suite:
  ```powershell
  cd c:\Projects\euroleague_fantasy_manager
  & "C:\Users\mom\.conda\envs\elf\python.exe" -m pytest -q
  ```
- Validate the GUI script (CI does this and will fail the build):
  ```powershell
  node --check src/euroleague_fantasy_manager/web/static/js/app.js
  ```
- **PowerShell has no heredoc** and does not support `&&` / `||`. Chain with `;`.
  For commit messages, write the message to a file and use `git commit -F <file>`.
- CI (`.github/workflows/ci.yml`) runs `pytest` + `node --check` on push/PR to `main` and `v0*`.

---

## 2. What is already DONE on `v07`

| Commit | Workstream | Summary |
|---|---|---|
| `139bd46` | **W1** Full trade capacity | Engine already did `k=1..4`; the GUI hardcoded `Math.min(2,…)` and the API/service defaulted to 1. All callers now derive from `rules.py::MAX_TRADES_PER_ROUND = 4`. |
| `139bd46` | **W2** Suggester performance | Validated by measurement, no tuning needed. On the 200-player reference market `k=4` costs **0.699s** vs `0.539s` at `k=1`. Perf test extended to `(1,2,3,4)`. |
| `8c29a42` | **W3** Player universe | `/api/workstation/players` sorted by value then sliced, making cheap players unreachable. Added `offset` + `sort` + `X-Total-Count`; GUI paginates at 100 with a sort selector. |
| `1127f26` | **W4** LLM provider parity | Server-driven model catalog, GUI API-key input (localStorage, never server-side), sub-model selector with `*` paid marker, `auto` mode, and `intelligence/security.py::redact_secrets`. |
| `1127f26` | **W5** Past-round lineups | `round_number` on the lineup write path, `team_transfers` event table (append-only), `GET /api/teams/{id}/rounds`, round selector on the Lineup tab. |

Test modules added: `tests/test_v07_trade_capacity.py`, `tests/test_v07_player_universe.py`,
`tests/test_v07_llm_providers.py`, `tests/test_v07_past_rounds.py`.

---

## 3. What is LEFT

### 3.1 W6 — Sequential historical replay & multi-season backtesting  ← the big one

This is the roadmap's original V0.7 scope ([`../roadmap.md`](../roadmap.md) §7) and is **not started**.
Deliverables, from the spec:

1. **F1 Multi-season historical datasets** — ingest historical round snapshots for EuroLeague **and** EuroCup
   across 2022-23 … 2025-26. Look at the existing ingestion in `api.py` / `storage.py` (schema v3,
   league-partitioned) and the dataset tooling in `evaluation/dataset.py`.
2. **F2 Point-in-time state reconstruction** — rebuild squad valuation, bank, availability and price changes at
   every historical round boundary. `multi_team/store.py` already stores squads per round
   (`PRIMARY KEY (team_id, round_number, player_id)`) and round-start checkpoints
   (`team_round_checkpoints`), plus the new `team_transfers` event log.
3. **F3 Sequential decision simulation** — lineup, captaincy, sixth man, T1→T2 turn substitution and transfers
   across whole seasons. Reuse `optimization/backtest.py` and `evaluation/backtest.py` rather than starting fresh.
4. **F4 Model-version comparison ledgers** — compare decision versions against actual human decisions and a
   hindsight oracle.
5. **F5 Historical regret attribution** — decompose season regret into Captain / Sixth Man / Bench / Turn
   Substitution / Transfer regret.

Acceptance: a full season replays **deterministically with no network access in tests**; regret components sum
to total measured regret within a documented tolerance; replay is strictly read-only w.r.t. live team state.

### 3.2 Past-round TRADE entry (deliberately deferred into W6)

**Do not re-attempt this as a standalone feature — it was prototyped and rejected in review.**

Why: unlike a lineup edit (which rewrites only role flags), a past-round trade changes the bank *and* the trade
budget of that round **and every round after it**. Per-round financial state exists only as round-**start**
checkpoints, so editing round *n* requires recomputing *n+1…* — which is precisely F2 above.

The rejected prototype failed two ways, both verified by the reviewer against a seeded DB:
- it computed `new_bank_tenths` / `rem_trades` and then **discarded them**, so the same round accepted
  unlimited repeated trades (8 trades applied to a 4-trade round);
- invalidating "downstream" checkpoints also deleted the **live round's** checkpoint, permanently breaking
  `POST /api/teams/{id}/revert-round-start`.

Current behaviour: `POST /api/teams/{team_id}/transfers` accepts `round_number` but returns **HTTP 400** for any
value other than the live round, with an explanatory message. Pinned by
`tests/test_v07_past_rounds.py::test_trades_for_a_past_round_are_rejected_not_silently_misapplied`.

**When implementing in W6:** apply the trade to round *n*, then write the resulting bank/budget as the
round-start checkpoint of *n+1*, and replay forward through the recorded `team_transfers` events to rebuild
every later round. Keep `revert-round-start` working throughout.

### 3.3 CLI round-aware entry (spec E6)

The CLI has **no lineup/trade write command at all** today — only optimizer *advice*
(`elf optimize-lineup`, `elf suggest-trades`) and team CRUD (`elf team create|show|select|delete`).
So this is new surface, not a flag:

- `elf team set-lineup --round N --starters … --captain … --sixth-man … --bench … --coach …`
- `elf team trade --round N --out … --in …` (blocked on §3.2)

Both should go through `TeamService` so the GUI and CLI share validation. Note `cli.py` already threads
`--round` through `log-decision`, `update-scores` and `advise`; follow that pattern.

### 3.4 Release tasks (W7)

- [x] Bump version to `0.7.0` in **both** `src/euroleague_fantasy_manager/__init__.py` and `pyproject.toml`.
      `tests/test_v065_hardening.py::test_w6_version_single_sourcing` enforces they agree.
- [x] Update `README.md`, `docs/roadmap.md` (mark V0.7 complete, promote V0.8 to "next") and
      `docs/architecture.md`.
- [x] Manual workstation smoke test (spec §9.3): a 4-trade suggestion; the cheapest player reachable in manual
      transfers; an OpenRouter key + free sub-model producing advice; a past round selected and its lineup
      re-read; past-round trade forward propagation verified.
- [ ] Open the PR from `v07` → `main`. Follow the format of PR #11 (summary, delivered capabilities, behaviour
      changes for reviewers, test breakdown).

---

## 4. Constraints that must not be broken

1. **Zero-mutation invariant.** `tests/test_v06_strategic_intelligence.py::test_strong_zero_mutation_invariant`
   snapshots every SQLite table, runs dossier + strategic analysis + copilot advice, and asserts the database is
   byte-for-byte unchanged. Advisory and replay paths must never write. Only explicit write endpoints mutate.
2. **No network in tests.** The heuristic provider is the offline fallback; historical replay must run from
   stored snapshots.
3. **Secrets never persist.** API keys live only in browser `localStorage` and the request body. There is no
   settings table and there should not be one. Every new error path that could embed a key must go through
   `intelligence.security.redact_secrets`.
4. **No migration framework.** Schema changes follow the existing ad-hoc `PRAGMA table_info` + `ALTER TABLE`
   guard pattern (`multi_team/store.py:90-96`).
5. **Truncation is a display concern, never an existence concern** (W3). A list endpoint may paginate, but must
   never make a legal choice unreachable; report the total and offer an offset.
6. **The engine may use its full legal action space** (W1). Any trade cap must derive from the team's actual
   `transfers_remaining`, never a hardcoded number outside `rules.py`.

---

## 5. Suggested order of work

1. **F1 + F2** first — dataset ingestion and point-in-time reconstruction are the foundation; everything else
   depends on them.
2. **§3.2 past-round trades** immediately after F2, since F2 is exactly the missing machinery and the API
   rejection is already in place to flip.
3. **F3 → F4 → F5** in order; each consumes the previous.
4. **§3.3 CLI** once the service-layer semantics are settled.
5. **§3.4 release tasks** last.

Commit and push per workstream, as was done for W1–W5.
