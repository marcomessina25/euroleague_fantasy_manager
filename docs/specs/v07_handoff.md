# V0.7 Handoff — Remaining Work

> **Superseded.** This handoff document is a historical record. All tasks were delivered in commit `f7f4dec`
> on branch `v07` and refined during PR review remediation. See [`v07.md`](v07.md) and [`v07_review.md`](v07_review.md)
> for current specifications and findings.

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
| `f7f4dec` | **W6** Sequential replay & forward trade replay | Point-in-time reconstruction, past-round forward trade replay with 4-trade cap, sequential decision simulator, model comparison ledgers, telescoping regret attribution, CLI round-aware entry. |

Test modules added: `tests/test_v07_trade_capacity.py`, `tests/test_v07_player_universe.py`,
`tests/test_v07_llm_providers.py`, `tests/test_v07_past_rounds.py`, `tests/test_v07_sequential_replay.py`.

---

## 3. Delivered scope summary

### 3.1 W6 — Sequential historical replay & multi-season backtesting (Delivered in `f7f4dec`)

Delivered and audited:
1. **F1 Synthetic multi-season fixtures** — deterministic multi-season fixtures for EuroLeague and EuroCup
   across 2022-23 … 2025-26 in `evaluation/dataset.py` and `storage.py`. (Real historical box score ingestion
   is scheduled for V0.8).
2. **F2 Point-in-time state reconstruction** — `reconstruct_point_in_time_state` rebuilds valuation, bank,
   availability, and price changes at round boundaries from `team_transfers` and checkpoints.
3. **F3 Sequential decision simulation** — `SequentialDecisionSimulator` in `optimization/sequential_replay.py`
   simulates transfers, lineups, captaincy, sixth man, and T1→T2 turn substitutions across seasons.
4. **F4 Model-version comparison ledgers** — `ModelComparisonLedger` compares multiple models, human play,
   and hindsight oracle.
5. **F5 & F7 Historical regret attribution** — decomposed via a telescoping chain (Captain, Sixth Man, Bench,
   Turn Substitution, Transfer, Formation) with exact residual (`residual ≡ 0.0`).

### 3.2 Past-round TRADE entry with forward replay (Delivered in `f7f4dec`)

Implemented with full forward propagation:
- Past-round trades execute via `execute_transfers` and propagate forward through later rounds and checkpoints
  using `replay_transfers_forward`.
- Live round start checkpoint is preserved and updated (`overwrite=True`), never deleted; `revert-round-start`
  remains functional.
- The 4-trade cap is strictly enforced per round via point-in-time reconstruction.

### 3.3 CLI round-aware entry (Delivered in `f7f4dec`)

Delivered in `cli.py`:
- `elf team set-lineup --round N --starters … --captain … --sixth-man … --bench … --coach …`
- `elf team trade --round N --out … --in …`

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
