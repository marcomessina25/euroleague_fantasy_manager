# V1.0.2 Repository Analysis — Critical Review of `main` @ `d0fa34f` (v1.0.1)

**Branch:** `v102` (from `origin/main` after PR #16) · **Date:** 31 Oct 2026 · **Scope:** entire repository (≈33k lines of source/docs/frontend + 13k lines of tests)

## How this was produced

- Seven independent read-only reviews, one per subsystem: data layer, CLI and certification, optimization, prediction and evaluation, services/state/audit, web and intelligence, tests/CI/docs. Every finding was backed by reading the code, and most by a minimal reproduction against throwaway databases in `%TEMP%`.
- I personally re-checked the most severe findings: PRED-1, WEB-2, WEB-3, DATA-2/RULE-1, and the `squad_report` crash.
- A static scan with `ruff` (installed to a temp folder, not into the `elf` env) added the undefined-name and swallowed-exception data.
- No tracked file, `data/euroleague.sqlite3` or `config/` file was modified. One reviewer's experiment regenerated the git-ignored `reports/evaluation/e2025_*` files through the default reports path. That is itself bug TEST-2.
- Severities: **Critical** = wrong decisions or corrupted state in normal use. **High** = wrong results or a security hole on a realistic path. **Medium** = wrong in edge cases, or misleading. **Low** = hygiene.
- Confidence is the reviewer's 1–10 score. Findings marked *suspected* were not reproduced.

---

## 1. Executive summary

The engineering scaffolding is strong:
- Parameterized SQL everywhere.
- A lineup optimizer that matches a brute-force oracle in expected mode.
- Deterministic sorting.
- Strict PIT cutoffs in the evaluation feature builder.
- Good API test coverage.

**But the product's core promise is not met in live use, and several V1.0 guarantees are claims rather than facts:**

1. **Live recommendations do not come from the evaluated models.**
   - Every live projection for the real season is a hard-coded price/average heuristic built from the *latest* snapshot. It ignores the selected model and the requested round (PRED-1).
   - The data that heuristic relies on (`avg_fantasy_pts`, popularity) is never populated by ingestion (DATA-4).
   - Everything downstream depends on these numbers: lineups, trades, the dossier, and copilot advice.
2. **The club-quota rule is contradictory across the codebase, and the EuroLeague value is probably wrong** (RULE-1).
   - The official API config in your own snapshots says EuroLeague Classic allows **6** players from one club. The code, specs and tests assert **3** for EuroLeague in some paths and 6 in others.
   - Either way, the app currently accepts squads in one place that it rejects in another.
3. **Past-round editing can silently corrupt the live squad** (STATE-1…5).
   - A trade's replay through later rounds gives bought players the position and club of the sold player.
   - It skips trades that no longer apply but still charges them to the bank.
   - The undo path moves the team's current round backwards.
4. **The local server can be driven by any website** (WEB-1). On top of that, script injection through player names already breaks trading for a real player, `Amath M'baye` (WEB-2).
5. **The "immutable audit" and "16-gate certification" don't hold up.**
   - Audit records are written with `INSERT OR REPLACE` (AUD-1). Score updates fail for any round with trades (AUD-2). Logged transfers are dropped by the CLI (CLI-4).
   - Certification gates are `assert`s that pass under `python -O` (CERT-1). Several gates check almost nothing (CERT-7, COV-1). Gate 5 cannot detect a learned model that has fallen back to v08.
6. **The test suite depends on test order and on your real files** (TEST-1/2). CI doesn't run on pushes to `v10`/`v101`/`v102` (CI-1).

**Verdict:** v1.0.1 is a capable research prototype with a solid optimizer core. It is not yet a trustworthy live decision tool. v1.0.2 should be a correctness and hardening release (section 5), not a feature release.

### Finding counts

| Subsystem | Critical | High | Medium | Low | Total |
|---|---|---|---|---|---|
| Rules (cross-cutting) | 1 | – | – | – | 1 |
| Prediction & evaluation | 1 | 4 | 9 | 2 | 16 |
| Services, state & audit | 2 | 7 | 7 | 2 | 18 |
| Optimization | – | 4 | 8 | 3 | 15 |
| Web & intelligence | – | 4 | 8 | 7 | 19 |
| CLI & certification | – | 9 | 9 | 4 | 22 |
| Data layer & core domain | – | 5 | 8 | 5 | 18 |
| Tests, CI, docs, packaging | – | 4 | 11 | 5 | 20 |
| **Total** | **4** | **37** | **60** | **28** | **129** |

Findings rated "Medium-High" by a reviewer (OPT-4, OPT-6, WEB-4) are counted as Medium. DATA-2 is the evidence for RULE-1 and is counted once, under data.

---

## 2. Decision needed before any fix: the club quota (RULE-1)

| Source | EuroLeague max per club |
|---|---|
| Official API `config.game_modes_configs[game_mode_id=1]` (Classic, 11 units, 1 coach) in every archived snapshot (`data/raw/snapshot_2026-10-27T14-12-03Z.json` etc.) | **`max_num_same_team_players: 6`** (`default_starting_num_same_team_players: 6`) |
| Published 2026-27 rules summary (web search; official article rate-limited) | **6** |
| `competition/ruleset.py:123`, `TeamService`, `OptimizationService._resolve_constraints`, transfer screening, v10 tests, README, `v101.md` | **3** |
| `rules.py:21` `MAX_PLAYERS_PER_TEAM`, `OptimizationConstraints()` default, root CLI paths (`validate-trades`, `suggest-trades`, `optimize transfers/multi-round`, `squad`), initial-team suggestion, sequential replay, v02/v04 tests, `architecture.md` | **6** |

- The 3 entered the codebase in v0.9 (`items_left_for_v09.md:230`) without a cited source.
- **Recommendation:** treat the official API config as the source of truth.
  - Read `max_num_same_team_players`, the player/coach counts and `captain_multiplier` from `game_modes_configs` at ingestion.
  - Store them per snapshot, and build `CompetitionRuleset` from them, with hard-coded values only as a fallback that warns on mismatch.
  - Open question: whether the API's limit counts the head coach. The code currently excludes the coach.
- **How this changes other findings:**
  - If 6 is correct, OPT-1, CLI-1/2, DATA-1, WEB-10 and TEST-6 flip. The paths enforcing 3 (`TeamService`, transfer screening, the GUI's server-side checks) are the wrong ones, and they over-restrict users and the optimizer.
  - Either way, one rule must be applied in one place.

---

## 3. Critical and High findings

### 3.1 Predictions feeding live decisions

| ID | Sev | Location | Finding | Conf |
|---|---|---|---|---|
| PRED-1 | **Critical** | `services/prediction_service.py:162-268` | For any season not in the eval dataset (the real E2026), `_build_contracts` falls back to `exp_min*fp_per_min*loc_mult` blended with `avg_fantasy_pts`, from `load_latest_players`/`load_latest_fixtures`. `model_name` is never used, and the snapshot is always the newest. Reproduced on a copy of the production DB: all five models returned identical projections, and round-2 projections used round-8 prices for 306 players. *(Verified by me at lines 120-180.)* | 10 |
| PRED-2 | High | `prediction/learned_models.py:569`, `:360-382` | learned_v09 trains on every season in `DATABASE_PATH`, including the backtest's test rounds. Measured on E2025: minutes MAE 1.573 in-sample vs 2.290 out-of-sample, about 31% inflated. `max_season`/`max_round` are broken and unused. Head coaches are in the training rows (144/720). It also ignores the backtest's `database_path`. | 9 |
| PRED-3 | High | `prediction_service.py:129`, `cli.py:968-970`, `backtest._ensure_dataset_present` | `elf predict --season 2026` silently builds a *synthetic* E2026 dataset into the production DB. After that, live projections serve fictional players: 30 instead of 361. | 9 |
| PRED-4 | High | `evaluation/features.py:85-141` | Team strength comes from `eval_players` with no season or league filter. EuroLeague and EuroCup are normalized together, using current rosters (not PIT). Adding E2025 data changed all 30 U2025 predictions. | 9 |
| PRED-5 | High | `evaluation/reproducibility.py:50-91, 108` | The dataset hash covers row counts plus the first 500 rows of 2 columns. Changing labels, prices, statuses and cutoffs left the hash unchanged. The V1.0 reproducibility contract is unenforceable. | 10 |
| DATA-4 | High | `storage.py:291-297`, `api.py:47-56` | `avg_fantasy_pts`, `popularity` and `total_plus` are never populated: 0 non-zero rows in snapshots 5–8. `fetch_player_profile` is never called. PRED-1's heuristic therefore runs on a price-only prior. | 9 |
| DATA-6 | Medium | `ingestion/historical_feeds.py:740` | `and` should be `or`: live and scheduled games are ingested as final results (repro: `games_saved: 2` for "playing" and "scheduled"). | 9 |

### 3.2 Game-rule legality

| ID | Sev | Location | Finding | Conf |
|---|---|---|---|---|
| RULE-1 | **Critical** | see section 2 | The club quota is contradictory across code paths, and the EuroLeague value probably disagrees with the official config. | 8 |
| OPT-1 | High | `services/optimization_service.py:372, 410, 432` | Initial-team suggestions use the generic quota, so 6 players from one club are reported `is_valid: True` for EuroLeague under the current ruleset. | 10 |
| CLI-1 / CLI-2 / DATA-1 | High | `cli.py:859, 1082, 1113, 1854`; `rules.py:21, 99-101`; `suggest_transfers.py:192` | `validate-trades`, `optimize transfers/multi-round`, `suggest-trades` and `squad` use the generic quota. Repro: 4 of the top 20 recommended transfers break the EuroLeague ruleset. | 10 |
| OPT-2 | High | `optimization/transfers.py:303, 380, 383`; `constraints.py:393` | Unlimited-trade rounds never exceed 4 trades. `from_ruleset` doesn't set `unlimited_transfers`, so 5-trade packages all fail validation and the result is **0 recommendations**. The GUI sends `max_trades=4` when unlimited is on (`app.js:1525`). | 10 |
| OPT-3 | High | `optimization/transfers.py:317, 332` | Candidates are cut to the top 15/8/5/4 by expected FP *before* the budget and club checks. Repro: the default search returns `[]`, while exhaustive search finds a +27.5 trade. | 9 |
| OPT-9 | High | `optimization/sequential_replay.py:387` | The replay's starting squad is the top 4/4/2/1 by expected FP, ignoring budget and club quota. Repro: 275.0 Cr with 10 players from one club. Replay and certification scores built on it are inflated. | 10 |
| STATE-7 | Medium | `services/team_service.py:693, 653, 796` | A client-supplied `unlimited=True` bypasses the 4-trade limit in any round. Replay ignores unlimited rounds. | 8 |

### 3.3 Team state integrity

| ID | Sev | Location | Finding | Conf |
|---|---|---|---|---|
| STATE-1 | **Critical** | `web/api/routes_teams.py:373`, `team_service.py:216` | When the audit write fails after a past-round trade, the undo calls `set_squad(...)` with the default `advance_team_round=True`. The team's current round goes backwards (3→1) and later rounds keep the bought player. | 9 |
| STATE-2 | **Critical** | `team_service.py:539-550` | Reconstructing a round with no stored squad falls back to an earlier checkpoint and ignores that round's trades. `sync_team_to_live_round` creates exactly these gaps (1→4). Repro: a backfill un-sold player 100 and dropped 150 from the live squad. | 9 |
| STATE-3 | High | `team_service.py:634-651` | Re-applying trades through later rounds copies `position`/`team_code` from the *sold* unit onto the bought player. Repro: `(250,'G','A'), (150,'F','E')`. This corrupts lineups and makes the club quota meaningless. | 9 |
| STATE-4 | High | `team_service.py:634, 548` | A later trade that no longer applies is skipped in the squad but still counted in the bank, and still uses up a trade slot. | 9 |
| STATE-5 | High | `team_service.py:776-793` | The trade write is not atomic: `record_transfers` commits before `save_squad`. Buying a player already in the squad leaves an orphan trade row and drops `transfers_remaining` to 3. | 10 |
| STATE-6 | High | `team_service.py:443-445`, `:216` | The bank lives in two places that disagree (team row vs checkpoint plus trades). Re-importing a config writes the checkpoint with the old bank and can move the team's round backwards. | 9 |
| ISO-1 | High | `multi_team/store.py:119-126` | The 6-team cap and the single active team are not atomic. 8 concurrent creates exceeded 6 teams in 30 of 30 trials, and produced two or more active teams in 15 of 15. | 10 |
| CLI-3 | High | `cli.py:1450-1451` | `team import-squad` saves the round and bank before validating the squad (introduced in v1.0.1). An invalid squad leaves the team at the new round with the new bank. | 10 |
| WEB-3 | High | `web/api/routes_workstation.py:489` | Intra-round "apply" calls `update_lineup` without `round_number`, so applying while viewing a past round rewrites the **live** lineup and logs it to the live round. *(Verified by me.)* | 9 |
| DATA-9 | Medium | `team_service.py:565, 862` vs `storage.py:606` | `get_snapshot_by_round(season=..., league=...)` raises `TypeError`, which is swallowed. Unknown players then become a 10.0 Cr guard with no club (VAL-1), which bypasses the club quota. | 9 |

### 3.4 Security (local web server)

| ID | Sev | Location | Finding | Conf |
|---|---|---|---|---|
| WEB-1 | High | `web/app.py:27-55`; `routes_teams.py:255, 399`; `routes_workstation.py:204, 1060` | No Host allow-list, no Origin check, and body-less POSTs. Cross-site form posts reverted rounds, changed the active team and triggered data updates. DNS rebinding reaches the whole API, including `copilot/advise` with server-environment keys. `GET /dashboard` writes lineup flags, so a plain `<img>` tag can trigger it. | 9 |
| WEB-2 | High | `web/static/js/app.js:1367, 1699` | `onclick="...'${escapeHtml(name).replace(/'/g,"\\'")}'..."`: `escapeHtml` already turned `'` into `&#039;`, which the browser decodes back before running the handler. Real player **Amath M'baye cannot be traded** (SyntaxError), and a crafted name runs script. Copilot API keys sit in `localStorage`. *(Verified by me.)* | 9 |
| INTEL-1 | High | `intelligence/consistency.py:126, 163, 167` | The grounding check never fails: invented numbers ("87.3 FP", "bank 33.3"), invented players ("Buy Nikola Jokic") and "captain scores 3x" all return `is_consistent=True`, and the GUI shows "✓ Grounded in Dossier". | 10 |

### 3.5 Audit trail and certification

| ID | Sev | Location | Finding | Conf |
|---|---|---|---|---|
| AUD-1 | High | `tracking/store.py:143, 239, 391` | Snapshots, decisions and outcomes use `INSERT OR REPLACE`. Re-logging an ID rewrote the captain, override flag and notes, and set the snapshot bank to 999. | 10 |
| AUD-2 | High | `tracking/outcomes.py:59`, `services/evaluation_service.py:35-41` | Score updates raise for any round with a trade or turn-sub decision (they have no lineup), after a partial write. Trade-regret code is unreachable. | 10 |
| CLI-4 | High | `cli.py:597, 605-606, 1163-1219` | `log-decision` defines `--recommend`, `--transfers-out` and `--transfers-in` but never reads them. Transfers the user thinks were recorded are silently dropped. | 10 |
| CLI-5 | High | `cli.py:1269-1287` | `update-scores` with no actual scores records every score as 0.0 with status `final`. | 10 |
| CERT-1 | High | `certification.py:154-505` | Gates are `assert` statements. Under `python -O`, patched-to-wrong rulesets and a training gate with no data all PASS. | 10 |
| CERT-2/3/4 | High | `certification.py:184-189, 121, 73`; `cli.py:777, 1713` | Gate 4 trains on the production DB. The `db_path` argument is ignored, and `main()` migrates the default DB first. `fastapi.testclient` needs `httpx` (dev-only), so `certify-v1` crashes on a normal install. | 9 |
| COV-1 | High | `certification.py` | Certification has no test. Gates 2, 3 and 15 check almost nothing (64-character hash, same DB hashed twice, no baseline). Gate 5 passed with learned_v09 MAE = fp_context_v08 MAE, so it can't detect the fallback. | 9 |

### 3.6 Test suite and CI

| ID | Sev | Location | Finding | Conf |
|---|---|---|---|---|
| TEST-1 | High | `learned_models.py:557-586`; `tests/test_v09_learned_models.py`, `test_v10_learned_productionization.py`, `test_v10_golden_end_to_end.py` | These pass only because `test_v04` CLI tests (alphabetically earlier) create `data/euroleague.sqlite3` first. In a fresh checkout the file alone has 3 failures. On your machine the "production" model trains on your real DB. | 10 |
| TEST-2 | High | `tests/test_v04_optimization.py:546-827`, `test_v025_evaluation.py:254`, `test_v03_prediction.py:419` | Tests call `main([...])` without `--db` and `evaluate` without a reports dir. They read your real DB and squad and write `reports/evaluation/*`. If E2025 were missing, they would write synthetic data into your real DB. | 10 |
| CI-1 | High | `.github/workflows/ci.yml:4-7` | Branch pattern `v0*` doesn't match `v10`/`v101`/`v102`, so pushes there run no CI (confirmed in the Actions history). | 10 |
| WEB-4 | Medium-High | `app.js:178, 337`; `routes_workstation.py:204` | The viewed round persists across team switches, and the dashboard returns 500 for a round the new team doesn't have. The UI silently keeps the previous team's court, whose buttons send that team's player IDs. | 9 |

---

## 4. Medium and Low findings (condensed)

### Prediction & evaluation
- **PRED-6 (M)** `rotation_context.py:360, 364`: foul trouble uses fouls *drawn* and the player's own rate as the opponent rate, so aggressive scorers are penalized.
- **PRED-7 (M)** `injury_surge.py:335`: the surge drops calibration (calibrated 27.05 became 26.05 after +5.43 min). No 40-minute cap, no sigma update, and never evaluated.
- **PRED-8 (M)** `metrics.py:236, 270`: `UnboundLocalError` when there are no coach rows.
- **PRED-9 (M)** `error_attribution.py:192`: the code reads key `lineup_decisions`, but the backtest returns `lineup_simulation`. All lineup scores are 0, and the 0.35 aleatoric split is invented.
- **PRED-10 (M)** `backtest_v051_predictions.py:111, 156`: uses the same game's starter flag and filters on `minutes > 0` (target leakage).
- **PRED-11 (M)** `uncertainty.py:65`: sigma drops from 5.19 to 2.81 as p_play crosses 0.25, favoring high-DNP-risk players.
- **PRED-12 (M)** court-player calibration applied to head coaches.
- **PRED-13 (M)** `prediction_service.py:82-158`: swallowed exceptions return partial or empty sets, and expected FP changes mid-round.
- **PRED-14 (M)** confidence intervals assume i.i.d. player-rounds.
- **PRED-15 (L)** run provenance lacks league, dataset hash and git sha, and NaN matches 12.0 in the reproducibility check.
- **PRED-16 (L)** performance: a new `PredictionService` per request, so the cache is useless, and training takes 47 s lazily inside a request.

### Services, state & audit
- **STATE-8 (M)** hard-coded season `"2026/27"` in revert, trade and store revert, and `transfers_remaining=4` on revert.
- **VAL-1 (M)** unknown players silently become a guard with no club. `"C" in pos_str` treats any position containing "C" as a center.
- **VAL-2 (L/M)** unrecognized positions count as guards. `create_team` only checks the club quota. `update_team_squad` never validates.
- **AUD-3 (M)** trade and turn-sub decisions have no snapshot link, and EuroCup trades are logged as euroleague.
- **AUD-4 (M)** test player IDs (301, 701, …) and `pid % 10 + 1` are hard-coded in production regret logic.
- **AUD-5 (M, suspected)** turn-sub gain formula `in − 1.5·out`.
- **AUD-6 (L)** `decision_service.get_audit_events` calls a method that doesn't exist. `UnboundLocalError` on an empty initial-team log. Zero scores are marked final.
- **CONC-1 (M, suspected)** no WAL mode, 5 s vs 30 s lock timeouts, `update_team` lost-update races, and connections that are never closed.

### Optimization
- **OPT-4 (M-H)** packages are ranked by gross gain, and 25 slots are shared across trade sizes. With a trade penalty, the best-net 1-trade package (37.0) is screened out in favor of 4-trade packages (31.26).
- **OPT-5 (M)** in conservative and aggressive modes the sixth man and captain are picked by expected rather than risk-adjusted FP. 21 of 150 fuzzed squads were non-optimal (worst gap 4.65).
- **OPT-6 (M-H)** the multi-round planner ignores remaining trades and unlimited windows.
- **OPT-7 (M)** stale projections carry forward to rounds where the player has none.
- **OPT-8 (M)** `horizon` is unbounded: projections are fetched for every requested round, but the plan is clamped to 4 (300 rounds took 24.5 s).
- **OPT-10 (M)** replay uses the generic quota and never unlimited windows.
- **OPT-11 (M)** regret clamping means `total_regret ≠ oracle − realized`.
- **OPT-12 (M)** exhaustive transfer mode has no budget (>2 min with 42 players) and is reachable from the API.
- **OPT-13 (L-M)** the full-rebuild MILP ignores captain and bench multipliers but reports `is_exhaustive=True`.
- **OPT-14 (L-M, suspected)** `unlimited` is never checked against the round.
- **OPT-15 (L)** intra-round formation defaults to "2-2-1", and replay swallows exceptions.

### Web & intelligence
- **WEB-5 (M)** ownership uses the latest snapshot of *any* league (`hasattr(league, "league_id")` is always False).
- **WEB-6 (M)** `PATCH /api/teams/{id}` accepts a negative bank, a negative round, 999 transfers and an empty name.
- **WEB-7 (M)** the DB path is a process-wide global in `deps.py`, so a second app redirects the first.
- **WEB-8 (M)** frontend races: copilot advice is rendered for the wrong team, and stale dossier, analysis and player-pool responses can overwrite newer ones.
- **WEB-9 (L-M)** unbounded `horizon`, negative `gamma`, negative `window`.
- **WEB-10 (L)**:
  - Team builder hard-codes a club cap of 6.
  - Unencodable team IDs.
  - No CSP or X-Frame-Options.
  - Hard-coded provenance `production_ridge_v03`, and a header badge saying `v0.9.0`.
  - Dead sub-modal code.
  - Manual `/lineup` edits are not audited.
- **INTEL-2 (M)** a provider returning `content: null` causes a 500 instead of the fallback.
- **INTEL-3 (M)** the past-round dossier uses the live squad.
- **INTEL-4 (M)** the dossier formation comes from the optimizer, not the actual lineup.
- **INTEL-5 (L-M)** price is passed off as expected FP for unprojected players.
- **INTEL-6 (L)** the dossier hash omits season, bank and transfers, and any season string is accepted.
- **INTEL-7 (L)** unknown provider or persona is silently replaced.
- **INTEL-8 (L)**:
  - `auto` sends the dossier to the first remote provider with an environment key, without per-request consent.
  - Prompt injection via the team name.
  - No retries.
  - *suspected:* retired model names.
- **INTEL-9 (L)** one Advise click builds 3 dossiers.

### CLI & certification
- **CERT-5 (M)** gate 16 uses CWD-relative paths.
- **CERT-6 (M)** the offline gate only patches `socket.connect`, and only around one call.
- **CERT-7 (M)** near-empty gates and empty failure messages.
- **CERT-8 (L)** the gate 13 message says `/schedule` but the code calls `/players`.
- **CLI-6 (M)** `team create --league` overrides the global `--league`.
- **CLI-7 (M)** a missing squad file silently falls back to the 11 most expensive players (164.4 Cr).
- **CLI-8 (M)** global `--league` is ignored by `predict`, `optimize*`, `backtest`, `log-decision`, `advise` and `evaluate`.
- **CLI-9 (M)** every command, including read-only ones, creates or migrates the DB.
- **CLI-10 (M)** `update` writes raw archives to the repo's `data/raw` even with `--db` elsewhere.
- **CLI-11 (M)** `evaluate-decisions --json --csv` prints a status line first, so the output isn't valid JSON.
- **CLI-12 (L)** a bare `elf optimize` crashes.
- **CLI-13 (L)** `team list` prints ✓ and crashes on cp1252 when piped.
- **CLI-14 (L)** no-op flags (`--json` on legacy commands, `--risk-mode` on transfers, `--alpha`), `team delete` on an unknown ID exits 0, errors go to stdout.

### Data layer & core domain
- **DATA-2 (H)** = RULE-1 evidence.
- **DATA-3 (H)** raw archive file names have only second resolution and no league, so two leagues saved in the same second overwrite each other.
- **DATA-5 (M)** the season code turns into E2027 after 1 January.
- **DATA-7 (M)** fallback player IDs use the salted `hash()`, so they differ per process, and parsing non-numeric IDs aborts the season.
- **DATA-8 (M)** `list_snapshots` hides some snapshots and duplicates others.
- **DATA-10 (M)** a departed unit is modelled as a Guard, so no replacement is suggested for a departed Center or Forward.
- **DATA-11 (M)** root `lineup`/`suggest_transfers` ignore `has_played` mid-round.
- **DATA-12 (M)** no retries, and swallowed fetch failures leave fake blank rounds.
- **DATA-13 (L/M)** the current-round fallback never runs (`round_number` defaults to 1).
- **DATA-14 (L)** a second, conflicting head-coach formula in `competition/eurocup.py:107` (dead code).
- **DATA-15 (L, suspected)** EuroLeague unlimited windows are applied to EuroCup.
- **DATA-16 (L)** a partial `import-squad` overwrites a valid squad file.
- **DATA-17 (L)** a CWD-relative default store path.
- **SQR-1 (H)** `squad_report.py:64`: `Position` is not imported, so the report raises `NameError` exactly in the departed-player path written to handle it (BUG-EDGE-002, untested). *(Found by ruff; verified by me.)*

### Tests, CI, docs, packaging
- **TEST-3 (M)** a test asserts on your real DB when it exists.
- **TEST-4 (M)** wall-clock budgets of 3 s with about 35% headroom (docstrings still say 1.5 s).
- **TEST-5 (M)** checks that can't fail: `__version__ in (11 versions)`, `"escapeHtml(" in content`, a "counterfactual bounds" test that checks no bounds.
- **TEST-6 (M)** tests assert both 3 and 6 for the EuroLeague quota.
- **TEST-7 (L-M)** CWD-dependent seeding and paths, and `node` is not skipped when missing.
- **TEST-8 (L)** global state in `deps.py` and the learned singleton.
- **TEST-9 (L)** duplicated test bodies and helpers, and `test_v05` is imported twice under different module names.
- **COV-2 (M)** untested: `gui`, `team select`/`delete`, `ingestion fetch-history`, `certify-v1`, the `elf update` success path, the `api.py` fetchers, and `POST /evaluation/update-scores`.
- **CI-2 (M)** CI tests only Python 3.11, while the README, `.python-version` and your env use 3.12; 3.13 is allowed but never tested.
- **LINT-1 (M)** no linter or type check in CI. Ruff counts: 218 unused imports, 74 blind `except`s (15 `try/except/pass`), 46 `raise` without `from`, 21 unused variables, 3 undefined names.
- **PKG-1 (M, suspected)** `PROJECT_ROOT = parents[2]` points inside site-packages after a non-editable install.
- **PKG-2 (L)** numpy and scipy are imported but not declared, and there is no lock file.
- **DOC-1 (M)** `ELF_LEAGUE` is documented but doesn't exist.
- **DOC-2 (M)** the README `log-decision --sub-out/--sub-in/--new-cap` example is rejected by argparse.
- **DOC-3 (M)** `architecture.md` says the quota is ≤6 and claims "zero external runtime dependencies".
- **DOC-4 (L)** "committed SQLite reference fixtures" don't exist, and gate descriptions are overstated.

---

## 5. What is solid

- All SQL is parameterized. Snapshot writes are a single transaction. Schema migrations are versioned and idempotent, and `_latest_snapshot_row` never mixes leagues.
- In expected mode, the lineup optimizer matched the brute-force oracle in 300 of 300 fuzzed squads. Formation, captain, sixth man, coach and turn option-value maths are correct. Results are deterministic.
- `validate_transfers_constraints`, the initial-team MILP constraints and the transfer screening's club check are mutually consistent.
- The evaluation feature builder enforces `game_date < cutoff` with a runtime guard, and calibrators are fitted only on earlier rounds.
- Team-store queries are always scoped by `team_id` (and season), with cascading deletes. Backfilling a past round's lineup is strictly validated.
- Static files have no path traversal. LLM keys travel in headers, `redact_secrets` covers error paths, and LLM output is rendered with `textContent`.
- API endpoints are almost fully referenced by tests. Provider tests clear environment keys and mock the network. The wheel ships templates, static files and the `elf` entry point.

---

## 6. Recommended v1.0.2 plan

Ordered by risk to live decisions. Each workstream needs failing tests first, consistent with how v1.0.1 was hardened.

| # | Workstream | Findings | Notes |
|---|---|---|---|
| W1 | **One authoritative ruleset from the official config** | RULE-1, DATA-1/2, OPT-1, CLI-1/2, OPT-9/10, TEST-6, WEB-10, DOC-3 | Decide 3 vs 6, then route every validator and optimizer through `CompetitionRuleset` and delete `MAX_PLAYERS_PER_TEAM` and the generic `OptimizationConstraints()` defaults. |
| W2 | **Honest live projections** | PRED-1, PRED-3, DATA-4, PRED-13, PRED-16 | Point-in-time snapshot by round, the model actually used, ingestion of real averages, never auto-generate synthetic data into the production DB, and one `PredictionService` per app. |
| W3 | **Team state transactions & replay** | STATE-1…6, ISO-1, CLI-3, WEB-3, DATA-9, VAL-1/2, STATE-8 | Single-transaction trade/replay/audit. Store the incoming player's position and club on trades. Write skipped rounds on roll-forward. One bank source of truth. `BEGIN IMMEDIATE` for team creation. |
| W4 | **Local server security** | WEB-1, WEB-2, WEB-6, WEB-9, OPT-8, OPT-12 | TrustedHost and Origin checks, JSON-only mutations, no writes on GET, `addEventListener` instead of inline handlers, Pydantic bounds. |
| W5 | **Transfer search correctness** | OPT-2, OPT-3, OPT-4, OPT-6, STATE-7, OPT-14 | Make unlimited windows actually work, filter candidates by affordability and club headroom before truncating, rank by net value with a quota per trade size. |
| W6 | **Audit integrity** | AUD-1…6, CLI-4, CLI-5, INTEL-1 | Insert-only decisions, versioned outcomes, scoring for trade rounds, a grounding check that can fail. |
| W7 | **Truthful certification & evaluation** | CERT-1…8, COV-1, PRED-2, PRED-4, PRED-5, PRED-9 | No `assert`. Everything in `cert_db`. Point-in-time learned training. Full-content dataset hash. A test that runs `certify-v1`. |
| W8 | **Hermetic tests & CI** | TEST-1…5, TEST-7, CI-1, CI-2, LINT-1, PKG-1/2 | Autouse fixture redirecting `PROJECT_ROOT`/`DATABASE_PATH` to `tmp_path`. CI on `v*` across 3.11–3.13. Ruff in CI (start with F821/F841/S110/BLE001). |
| W9 | **Docs & small fixes** | SQR-1, DOC-1/2/4, CLI-6…14, DATA-3, 5, 7, 8, 10…17, remaining Medium/Low | Mostly mechanical; batch them. |

W1 needs your decision (section 2). W2 and W3 have the largest blast radius and should land before any new feature work.
