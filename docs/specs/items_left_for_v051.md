# V0.5.1 Pre-Merge Checklist: Live Score Presentation, Quantitative Decomposed Predictions & High-Speed Transfer Optimizer

> **Status:** Branch `v051` pending review. This document tracks all blocking issues, validation tasks, and acceptance criteria before merge to `main`.

> **Target:** All items must be resolved or explicitly deferred (with ticket linkage) before PR approval.

---

## Overview

V0.5.1 introduces:
- **Live Score Separation**: Clean decoupling of `has_played` / `actual_fp` from expected points
- **Decomposed Prediction Model**: Replaces naive `price / 10` prior with quantitative `P(play) × E[min] × E[FP/min]`
- **High-Speed Transfer Optimizer**: 2-stage screening + bounded MILP for 1–5 transfer recommendations in <1.5s
- **Intra-Round Substitution Optimizer**: Legal bench-to-court swaps across matchday turns (T1 → T2 → T3)
- **Round-Start Checkpoint Rollback**: Save and restore squad state to round baseline

Three features ship new **quantitative models**. Before merge, each must be validated against V0.5.0 baseline to prevent regression.

---

## 🔴 BLOCKING ISSUES (Must Resolve Before Merge)

### 1. Prediction Model Calibration Validation

**Problem:** V0.5.1 replaces the V0.5.0 expected points baseline (`exp_fp = avg_fantasy_pts or price/10`) with a decomposed model:
```
E[FP] = P(play) × E[min] × E[FP/min] × location_multiplier
```

This is a **quantitative core change** that could regress (or improve) model accuracy. No validation data exists yet.

**Acceptance Criteria:**
- Historical backtest on 2025-26 season (or available historical data)
- Compare V0.5.0 vs V0.5.1 prediction accuracy across:
  - **xP MAE** (expected vs realized points per player)
  - **xM MAE** (expected vs realized minutes)
  - **Spearman rank correlation** (prediction ranking consistency)
  - **Calibration curve** (confidence intervals)
- **Pass criterion:** `MAE(V0.5.1) <= MAE(V0.5.0) + 0.05 FP` (allow tiny regression if CI calibration improves)
- **Deliverable:** `src/euroleague_fantasy_manager/evaluation/backtest_v051_predictions.py`

**Implementation Steps:**
1. Create test: `test_v051_prediction_calibration_vs_v050()` in `tests/test_v05_multi_team_and_gui.py`
   ```python
   def test_v051_prediction_calibration_vs_v050():
       """Compare V0.5.0 and V0.5.1 prediction accuracy on historical season."""
       season = "2025-26"  # or earliest available
       rounds = list(range(1, 39))  # Full season
       
       # Load historical snapshots
       # Reconstruct V0.5.0 predictions using frozen model
       # Reconstruct V0.5.1 predictions using decomposed model
       # Compute metrics for both
       # Assert V0.5.1 does not regress significantly
       mae_v050 = compute_mae(v050_predictions, actual_points)
       mae_v051 = compute_mae(v051_predictions, actual_points)
       assert mae_v051 <= mae_v050 + 0.05, f"Regression: {mae_v051} > {mae_v050 + 0.05}"
   ```
2. Run backtest against 2025-26 season historical data
3. Document findings in `docs/v051_prediction_validation.md`:
   - Metrics tables (MAE, RMSE, rank correlation by position)
   - Calibration plots
   - Ablation: impact of each decomposed component

**Owner:** Assign to @marcomessina25  
**Estimated Effort:** 2–4 hours  
**Blocking:** Yes. Cannot merge without evidence that new baseline does not regress xP accuracy.

---

### 2. Schema Migration Safety & Rollback Strategy

**Problem:** Database migration adds `has_played` column to `players` table. Current implementation uses bare `try/except`:
```python
try:
    conn.execute("ALTER TABLE players ADD COLUMN has_played INTEGER NOT NULL DEFAULT 0")
except Exception:
    pass  # Silent failure—bad in production!
```

This is unsafe:
- **Silent failures** mask schema inconsistencies
- **No version tracking** to prevent re-running migrations
- **No rollback path** if migration partially succeeds
- Production dbs could end up corrupted

**Acceptance Criteria:**
- Schema version tracking in `snapshots` or metadata table
- Explicit migration gate: only run if version < target
- Pre-check: verify `has_played` column does not already exist before attempting ALTER
- Detailed logging: before/after column count, affected row counts
- Test: verify migration is idempotent (can run multiple times safely)
- Deliverable: `src/euroleague_fantasy_manager/storage.py` refactored with safe migrations

**Implementation Steps:**
1. Add schema versioning:
   ```python
   CREATE TABLE IF NOT EXISTS schema_version (
       id INTEGER PRIMARY KEY,
       version INTEGER NOT NULL,
       applied_at TEXT NOT NULL,
       description TEXT
   );
   
   def _get_schema_version(self) -> int:
       row = self.conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
       return row[0] if row else 0
   
   def _set_schema_version(self, version: int, description: str):
       self.conn.execute("INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
                         (version, datetime.now(timezone.utc).isoformat(), description))
   ```

2. Create migration functions:
   ```python
   def _migrate_to_v2_add_has_played_column(self):
       """Safely add has_played column if it doesn't exist."""
       info = self.conn.execute("PRAGMA table_info(players)").fetchall()
       if any(col[1] == "has_played" for col in info):
           logger.info("Column 'has_played' already exists; skipping migration.")
           return
       
       logger.info("Migrating schema to v2: adding 'has_played' column...")
       self.conn.execute("ALTER TABLE players ADD COLUMN has_played INTEGER NOT NULL DEFAULT 0")
       logger.info("Migration complete: 'has_played' column added.")
   ```

3. Apply migrations in `_initialize_schema()`:
   ```python
   def _initialize_schema(self):
       current_version = self._get_schema_version()
       if current_version < 1:
           # Create base schema
           self._create_base_tables()
           self._set_schema_version(1, "Initial schema: snapshots, players, fixtures, teams")
       
       if current_version < 2:
           self._migrate_to_v2_add_has_played_column()
           self._set_schema_version(2, "Added has_played column for live score tracking")
   ```

4. Add tests:
   ```python
   def test_schema_migration_idempotent(tmp_path):
       """Verify migration can be run multiple times without error."""
       db = tmp_path / "test.sqlite3"
       store1 = SnapshotStore(database_path=db)
       store1._initialize_schema()
       
       store2 = SnapshotStore(database_path=db)
       store2._initialize_schema()  # Should not error
       
       # Verify schema is consistent
       info = store2.conn.execute("PRAGMA table_info(players)").fetchall()
       assert any(col[1] == "has_played" for col in info)
   ```

**Owner:** Assign to @marcomessina25  
**Estimated Effort:** 1–2 hours  
**Blocking:** Yes. Production safety requirement.

---

### 3. Intra-Round Optimizer: Captaincy Edge Case Guard

**Problem:** Captaincy logic in `IntraRoundSubstitutionOptimizer.optimize()` (lines ~200–210 in `intra_round.py`) allows switching captaincy from a player who has already played:

```python
candidate_caps: list[int] = []
if curr_cap_id in s_ids_set:
    candidate_caps.append(curr_cap_id)  # ← ISSUE: If curr_cap_id has played, this allows retaining them
for pid in s_ids:
    if not played_map[pid] and pid not in candidate_caps:
        candidate_caps.append(pid)
```

**Edge Case:** Current captain played T1 with score 8.0 FP (doubled = 16.0). Optimizer retains them as captain even though they cannot change their score. This violates the principle that captaincy switches should only occur to improve expected points.

**Acceptance Criteria:**
- Captaincy rule: If current captain has already played, **captaincy CANNOT switch** (preserve their doubled score). Only unplayed starters can become new captain.
- Add guard clause: raise `ValueError` if rule is violated
- Unit test: `test_intra_round_optimizer_captaincy_rules()`
- Deliverable: Updated `intra_round.py` with guard + passing test

**Implementation Steps:**
1. Add guard in `optimize()`:
   ```python
   def optimize(self, squad_units: Sequence[IntraRoundPlayerUnit], captain_id: int | None = None) -> IntraRoundSubstitutionResult:
       # ... existing code ...
       
       # GUARD: If current captain has played, they MUST remain captain
       if curr_cap_id and played_map.get(curr_cap_id, False):
           # Current captain already played—their score is locked.
           # Cannot switch captaincy to improve expected points.
           # Retain current captain in all candidate solutions.
           candidate_caps = [curr_cap_id]
       else:
           # Current captain hasn't played yet
           # Captaincy can stay or switch to another unplayed starter
           candidate_caps = []
           if curr_cap_id in s_ids_set and not played_map.get(curr_cap_id, False):
               candidate_caps.append(curr_cap_id)
           for pid in s_ids:
               if not played_map[pid] and pid not in candidate_caps:
                   candidate_caps.append(pid)
   ```

2. Add test:
   ```python
   def test_intra_round_optimizer_captaincy_rules():
       """Verify captaincy rules: if captain played, cannot switch; if not played, can switch."""
       # Case 1: Current captain played T1
       squad_with_played_cap = [
           IntraRoundPlayerUnit(1, "CaptPlayed", "G", current_role="starter", is_captain=True, 
                                has_played=True, actual_fp=8.0, expected_fp=14.0),
           IntraRoundPlayerUnit(2, "G2", "G", current_role="starter", has_played=False, expected_fp=16.0),
           # ... rest of squad ...
       ]
       res = IntraRoundSubstitutionOptimizer().optimize(squad_with_played_cap, captain_id=1)
       assert res.captain_id == 1, "Played captain must be retained; cannot switch"
       
       # Case 2: Current captain NOT played; unplayed alternative is better
       squad_with_unplayed_cap = [
           IntraRoundPlayerUnit(1, "CaptUnplayed", "G", current_role="starter", is_captain=True, 
                                has_played=False, expected_fp=10.0),
           IntraRoundPlayerUnit(2, "G2", "G", current_role="starter", has_played=False, expected_fp=16.0),
           # ... rest of squad ...
       ]
       res = IntraRoundSubstitutionOptimizer().optimize(squad_with_unplayed_cap, captain_id=1)
       assert res.captain_id == 2, "Unplayed captain can switch if better alternative exists"
   ```

**Owner:** Assign to @marcomessina25  
**Estimated Effort:** 1 hour  
**Blocking:** Yes. Correctness requirement.

---

## 🟡 STRONGLY RECOMMENDED (Should Fix Before Merge)

### 4. Round Checkpoint Fail-Fast & Validation

**Problem:** `get_round_checkpoint()` has fallback logic that silently returns the closest prior round if exact match not found. This masks missing data:

```python
def get_round_checkpoint(self, team_id, round_number, season):
    row = conn.execute("SELECT * FROM team_round_checkpoints WHERE team_id=? AND round_number=? AND season=?", ...)
    if not row:
        row = conn.execute("SELECT * FROM team_round_checkpoints WHERE team_id=? AND season=? AND round_number <= ? ORDER BY round_number DESC LIMIT 1", ...)
    # ← Silently uses older checkpoint if exact round not found
```

This can cause confusion: user expects to revert to Round 5, but gets Round 3 data instead.

**Acceptance Criteria:**
- `get_round_checkpoint()` raises `ValueError` if exact checkpoint not found (fail loud)
- Add new method `get_latest_checkpoint_before_round()` for cases where fallback is intentional
- Update `revert_to_round_start()` to use exact-match only
- Add tests for both methods

**Implementation Steps:**
1. Refactor checkpoint retrieval:
   ```python
   def get_round_checkpoint(self, team_id: str, round_number: int, season: str) -> dict[str, Any]:
       """Get the exact round start checkpoint. Raises if not found."""
       row = conn.execute(
           "SELECT * FROM team_round_checkpoints WHERE team_id=? AND round_number=? AND season=?",
           (team_id, round_number, season)
       ).fetchone()
       if not row:
           raise ValueError(f"No checkpoint found for team '{team_id}' in Round {round_number}, season {season}.")
       return dict(row)
   
   def get_latest_checkpoint_before_round(self, team_id: str, round_number: int, season: str) -> dict[str, Any] | None:
       """Get the latest checkpoint at or before a round (may be older). Returns None if no checkpoint exists."""
       row = conn.execute(
           "SELECT * FROM team_round_checkpoints WHERE team_id=? AND season=? AND round_number <= ? ORDER BY round_number DESC LIMIT 1",
           (team_id, season, round_number)
       ).fetchone()
       return dict(row) if row else None
   ```

2. Update `revert_to_round_start()`:
   ```python
   def revert_to_round_start(self, team_id: str, season: str = "2026/27", round_number: int | None = None) -> Team:
       team = self.get_team(team_id)
       rnd = round_number or team.round_number
       checkpoint = self.get_round_checkpoint(team_id, rnd, season)  # Exact match; raises if not found
       # ... restore state ...
   ```

3. Add tests:
   ```python
   def test_checkpoint_exact_match_or_raise():
       """Verify get_round_checkpoint raises if exact checkpoint not found."""
       ts = TeamService(...)
       team = ts.create_team("test", "Test Team", season="2026/27", round_number=1)
       
       # Checkpoint exists for round 1
       checkpoint = ts.store.get_round_checkpoint(team.team_id, 1, "2026/27")
       assert checkpoint is not None
       
       # No checkpoint for round 2 → should raise
       with pytest.raises(ValueError):
           ts.store.get_round_checkpoint(team.team_id, 2, "2026/27")
   ```

**Owner:** Assign to @marcomessina25  
**Estimated Effort:** 45 minutes  
**Blocking:** No, but strongly recommended for UX clarity.

---

### 5. Transfer Multi-Option Ranking Validation

**Problem:** The 2-stage transfer optimizer ranks multiple recommendations using a proxy `net_delta` in Stage 1 (line ~340 in `transfers.py`):

```python
proxy_gain = in_exp_sum - out_exp_sum
screened_packages.append((proxy_gain, ...))
```

This proxy is used to filter top 25 packages, but there's no evidence that Stage 2 (full MILP) ranking matches proxy ranking. Second and third options could be sub-optimal.

**Acceptance Criteria:**
- Add test: verify top 3 recommendations (Stage 2 exact scores) are ranked correctly
- Specifically: `recommendations[0].net_transfer_value >= recommendations[1].net_transfer_value >= recommendations[2].net_transfer_value`
- Backtest on synthetic squad: construct scenario with 3 known-optimal trade options; verify ranking matches expected order
- Deliverable: `test_transfer_optimizer_multi_option_ranking()` in test suite

**Implementation Steps:**
1. Add test:
   ```python
   def test_transfer_optimizer_multi_option_ranking():
       """Verify Stage 2 exact ranking matches expected order of recommendations."""
       # Create squad: 5 guards, 4 forwards, 2 centers
       current_squad = [...]  # Known baseline
       
       # Market: 3 guards with expected scores 25/24/22, 2 forwards 26/25, 1 center 27
       market = [...]
       
       # Trade 1 guard: options are:
       # Option A: out guard (22 FP) → in guard (25 FP) = +3 net (BEST)
       # Option B: out guard (22 FP) → in guard (24 FP) = +2 net (MEDIUM)
       # Option C: out guard (22 FP) → in guard (23 FP) = +1 net (WORST)
       
       res = optimizer.optimize_transfers(current_squad, market, max_trades=1, top_n=3)
       
       # Verify ranking
       assert res.recommendations[0].trade_details == "out 22FP → in 25FP"
       assert res.recommendations[1].trade_details == "out 22FP → in 24FP"
       assert res.recommendations[2].trade_details == "out 22FP → in 23FP"
   ```

2. If ranking fails: debug proxy vs exact scoring discrepancy
3. Document findings in PR description

**Owner:** Assign to @marcomessina25  
**Estimated Effort:** 1.5 hours  
**Blocking:** No, but important for feature quality.

---

### 6. UI Score Breakdown Consistency & Tests

**Problem:** Dashboard displays split scores in two ways:
1. JSON payload: `realized_total_fp + unplayed_expected_fp`
2. JavaScript rendering: combines from multiple sources

If these disagree, users see confusing totals.

**Acceptance Criteria:**
- All code paths (API routes) must enforce: `realized_total_fp + unplayed_expected_fp == expected_total_fp`
- Add assertion in routes: `assert realized + unplayed == total or abs(diff) < 0.01`
- UI unit tests: verify score breakdown display for all 3 scenarios:
  - All unplayed (only expected shown)
  - All played (only actual shown)
  - Mixed (both shown, with breakdown)
- Deliverable: Test in test suite + updated UI rendering code

**Implementation Steps:**
1. Add server-side assertion in `routes_workstation.py` `get_dashboard()`:
   ```python
   # Compute and validate score breakdown
   tot_realized_fp = round(sum(...), 2)
   tot_unplayed_expected_fp = round(sum(...), 2)
   tot_projected_fp = tot_realized_fp + tot_unplayed_expected_fp
   
   # Assert consistency
   assert abs(tot_projected_fp - opt_lineup.objective_value) < 0.01, \
       f"Score breakdown mismatch: {tot_projected_fp} vs {opt_lineup.objective_value}"
   ```

2. Add JavaScript unit test (if using Jest or similar):
   ```javascript
   test("score breakdown consistency: realized + unplayed = total", () => {
       const dashboard = {
           realized_total_fp: 42.5,
           unplayed_expected_fp: 28.3,
           total_fp: 70.8
       };
       expect(dashboard.realized_total_fp + dashboard.unplayed_expected_fp)
           .toBeCloseTo(dashboard.total_fp, 2);
   });
   ```

**Owner:** Assign to @marcomessina25  
**Estimated Effort:** 1 hour  
**Blocking:** No, but improves reliability.

---

## 🟢 GOOD TO HAVE (Nice-to-Haves; Can Defer if Needed)

### 7. Performance Benchmarking

**Description:** Verify transfer optimizer consistently runs <1.5s (per spec).

**Test:**
```python
def test_transfer_optimizer_performance_budget():
    """Verify optimizer meets <1.5s budget for 1–5 trades and unlimited mode."""
    import time
    squad = make_standard_squad()  # 11 players
    market = [make_test_player(...) for _ in range(80)]  # 80 market options
    
    for k in [1, 2, 3, 4, 5]:
        t0 = time.perf_counter()
        res = optimizer.optimize_transfers(squad, market, max_trades=k)
        duration = time.perf_counter() - t0
        assert duration < 1.5, f"Trade count {k}: {duration:.2f}s > 1.5s budget"
    
    # Unlimited mode
    t0 = time.perf_counter()
    res = optimizer.optimize_transfers(squad, market, unlimited=True)
    duration = time.perf_counter() - t0
    assert duration < 1.5, f"Unlimited mode: {duration:.2f}s > 1.5s budget"
```

**Owner:** Optional (can run post-merge)  
**Blocking:** No.

---

## 📋 Merge Readiness Checklist

- [ ] **BLOCKING #1:** Prediction model validation backtest (`test_v051_prediction_calibration_vs_v050`) passes. MAE regression within tolerance.
- [ ] **BLOCKING #2:** Schema migration refactored with versioning, idempotence test passes.
- [ ] **BLOCKING #3:** Intra-round captaincy guard implemented and tested. Edge case test passes.
- [ ] **RECOMMENDED #4:** Round checkpoint fail-fast implemented and tested.
- [ ] **RECOMMENDED #5:** Transfer multi-option ranking test passes.
- [ ] **RECOMMENDED #6:** UI score breakdown consistency asserted in routes + JS tests pass.
- [ ] All unit tests in `tests/test_v05_multi_team_and_gui.py` pass (including new V0.5.1 tests).
- [ ] Integration tests: `test_workstation_simulate_and_apply_intra_round_routes()` passes.
- [ ] No lint/format issues (`black`, `mypy`, `pylint` if configured).
- [ ] `docs/roadmap.md` updated to reflect V0.5.1 completion status.
- [ ] PR description links to this checklist and documents any deferred items.

---

## 🔗 Related Documentation

- [`docs/roadmap.md`](../roadmap.md) — Section 5.1: V0.5.1 scope
- [`docs/architecture.md`](../architecture.md) — Layer responsibilities
- `pyproject.toml` — Version bumped to 0.5.1

---

## Approval Workflow

1. **Author** (@marcomessina25): Complete all BLOCKING items + most RECOMMENDED items. Update this file with status.
2. **Reviewer**: Verify checklist completion. Request changes if any BLOCKING item incomplete.
3. **Author**: Resolve review feedback. Mark items as DONE ✓.
4. **Merge:** Once all BLOCKING + RECOMMENDED are ✓, PR is approved and merged.

Any GOOD TO HAVE items may be deferred to a follow-up PR (V0.5.2 or later) with explicit ticket linkage.

---

## Status Tracking

| Item | Status | Owner | Est. Effort | Notes |
|------|--------|-------|-------------|-------|
| #1 Prediction Validation | 🔴 Not Started | @marcomessina25 | 2–4h | Backtest required |
| #2 Schema Migration | 🔴 Not Started | @marcomessina25 | 1–2h | Production safety |
| #3 Captaincy Guard | 🔴 Not Started | @marcomessina25 | 1h | Correctness |
| #4 Checkpoint Fail-Fast | 🟡 Deferred | @marcomessina25 | 45m | UX improvement |
| #5 Transfer Ranking | 🟡 Deferred | @marcomessina25 | 1.5h | Quality check |
| #6 UI Breakdown Tests | 🟡 Deferred | @marcomessina25 | 1h | Reliability |
| #7 Performance Bench | 🟢 Deferred | — | 30m | Post-merge OK |

---

**Last Updated:** 2026-09-25  
**Next Review:** After each item status change
