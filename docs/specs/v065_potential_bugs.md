# Release 0.6.5 Hardening Bug Register & Audit

**Release Target:** V0.6.5  
**Scope:** Hardening, multi-league consistency, edge-case coverage, and quality gates for EuroLeague Fantasy Manager.  
**Execution Date:** 2026-09-29  
**Status:** All items dispositioned (`FIXED` or `ACCEPTED RISK`) with automated regression test coverage.

---

## 1. Summary of Dispositions

| Bug ID | Workstream | Area | Severity | Status | Test Coverage |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **BUG-CLI-001** | W1 | CLI | P1 | **FIXED** | `test_w1_cli_league_isolation_and_header` |
| **BUG-CLI-002** | W1 | CLI | P1 | **FIXED** | `test_w1_resolve_command_league_precedence`, `test_w1_cli_league_isolation_and_header` |
| **BUG-CLI-003** | W1 | CLI | P1 | **FIXED** | `test_w2_cli_invalid_league_exit_code_2` |
| **BUG-CLI-004** | W1 | CLI | P2 | **FIXED** | `test_w1_cli_league_isolation_and_header` |
| **BUG-ING-001** | W2 | Ingestion | P1 | **FIXED** | `test_w2_eurocup_ingestion_and_schema_v3` |
| **BUG-ING-002** | W2 | Ingestion | P1 | **FIXED** | `test_w2_eurocup_ingestion_and_schema_v3` |
| **BUG-ING-003** | W2 | Storage | P1 | **FIXED** | `test_w2_eurocup_ingestion_and_schema_v3`, `test_schema_migration_idempotent` |
| **BUG-ING-004** | W2 | Ingestion | P2 | **FIXED** | `test_w2_eurocup_ingestion_and_schema_v3` |
| **BUG-LG-004** | W3 | Import | P1 | **FIXED** | `test_w3_squad_import_league_isolation_and_mismatch` |
| **BUG-EDGE-001** | W4 | Engine | P1 | **FIXED** | `test_w4_edge_001_postponed_fixtures` |
| **BUG-EDGE-002** | W4 | Engine | P1 | **FIXED** | `test_w4_edge_002_departed_player_handling` |
| **BUG-EDGE-003** | W4 | Engine | P2 | **FIXED** | `test_w4_edge_003_replaced_head_coach` |
| **BUG-EDGE-004** | W4 | Engine | P1 | **FIXED** | `test_w4_edge_004_bank_boundaries` |
| **BUG-RULE-002** | W4 | Rules | P1 | **FIXED** | `test_w4_rule_002_played_starter_and_captaincy` |
| **BUG-EDGE-005** | W4 | Engine | P2 | **FIXED** | `test_w4_edge_005_three_turn_rounds` |
| **BUG-EDGE-006** | W4 | Engine | P2 | **FIXED** | `test_w4_edge_006_round_rollover_uses_team_round` |
| **BUG-SEC-002** | W5 | Web / Security | P1 | **FIXED** | `test_w5_static_app_js_escaping_guard` |
| **BUG-API-001** | W5 | API | P1 | **FIXED** | `test_w5_api_invalid_league_returns_400` |
| **BUG-API-002** | W5 | API | P1 | **FIXED** | `test_w5_api_player_detail_league_scoping` |
| **BUG-PROV-001** | W6 | Provenance | P2 | **FIXED** | `test_w6_version_single_sourcing` |
| **BUG-PROV-002** | W6 | Provenance | P2 | **FIXED** | `test_w6_dossier_content_hash_invariance_and_sensitivity` |
| **BUG-PROV-003** | W6 | Provenance | P2 | **FIXED** | `test_w6_dossier_content_hash_invariance_and_sensitivity` |
| **BUG-LLM-001** | W6 | Providers | P2 | **FIXED** | `test_w6_provider_discovery_and_heuristic_metadata` |
| **BUG-LLM-002** | W6 | Providers | P2 | **ACCEPTED RISK** | `test_w6_provider_discovery_and_heuristic_metadata` |
| **BUG-QA-001** | W7 | CI / QA | P2 | **FIXED** | `.github/workflows/ci.yml` |

---

## 2. Detailed Bug Dispositions & Implementation Details

### BUG-CLI-001: CLI Commands Implicitly Read Newest Snapshot Regardless of League
- **Severity:** P1 (High)
- **Status:** `FIXED`
- **Root Cause:** Commands like `elf players`, `elf report`, `elf squad`, `elf lineup` loaded latest snapshot via `load_latest_players()` without filtering by `league_id`, causing a newer EuroCup snapshot to hijack EuroLeague queries.
- **Resolution:** Threaded `league_id` through all query functions in `SnapshotStore` and `cli.py`. Commands now query exclusively the snapshot belonging to the resolved competition.
- **Verification:** `tests/test_v065_hardening.py::test_w1_cli_league_isolation_and_header`

### BUG-CLI-002: `--league` Flag Missing from Most Subcommands
- **Severity:** P1 (High)
- **Status:** `FIXED`
- **Root Cause:** `--league` was only recognized on `update` and `report` subcommands.
- **Resolution:** Added a common `sub_league_parent` in `cli.py` across all relevant subparsers (`update`, `report`, `players`, `import-squad`, `validate-trades`, `squad`, `fixtures`, `lineup`, `suggest-trades`, `advise`). Added root parser fallback with §2.1 resolution precedence.
- **Verification:** `tests/test_v065_hardening.py::test_w1_resolve_command_league_precedence`

### BUG-CLI-003: Invalid League Strings Cause Silent Fallback or Tracebacks
- **Severity:** P1 (High)
- **Status:** `FIXED`
- **Root Cause:** Unknown league strings defaulted silently or threw unhandled tracebacks.
- **Resolution:** `League.from_str` raises strict `ValueError`. `cli.main()` catches `ValueError` on league resolution, prints readable `Error: ...` to `stderr`, and exits cleanly with code 2.
- **Verification:** `tests/test_v065_hardening.py::test_w2_cli_invalid_league_exit_code_2`

### BUG-CLI-004: Active League Invisible in CLI Operations
- **Severity:** P2 (Medium)
- **Status:** `FIXED`
- **Root Cause:** Operators could not see whether the CLI was executing against EuroLeague or EuroCup data.
- **Resolution:** Added diagnostic header emitted to `sys.stderr` on every league-scoped command: `League: {LEAGUE} ({source})` (e.g. `League: EUROLEAGUE (active team 'team_1')`).
- **Verification:** `tests/test_v065_hardening.py::test_w1_cli_league_isolation_and_header`

### BUG-ING-001: Competition Code Hardcoded to "E"
- **Severity:** P1 (High)
- **Status:** `FIXED`
- **Root Cause:** `api.py` and `storage.py` hard-coded competition code to `"E"`.
- **Resolution:** Resolved dynamically from `get_league_ruleset(league).competition_code` ("E" for EuroLeague, "U" for EuroCup).
- **Verification:** `tests/test_v065_hardening.py::test_w2_eurocup_ingestion_and_schema_v3`

### BUG-ING-002: Hard-Coded Club Counts
- **Severity:** P1 (High)
- **Status:** `FIXED`
- **Root Cause:** Hard-coded club count of 20 used rather than dynamically parsing config.
- **Resolution:** Derived club count dynamically from API `config.teams` length without hard-coded constants.
- **Verification:** `tests/test_v065_hardening.py::test_w2_eurocup_ingestion_and_schema_v3`

### BUG-ING-003: Missing SQLite Index on `snapshots.league_id`
- **Severity:** P1 (High)
- **Status:** `FIXED`
- **Root Cause:** Schema version 2 had no index on `snapshots(league_id)`.
- **Resolution:** Upgraded schema to version 3 in `storage.py`, adding `CREATE INDEX IF NOT EXISTS idx_snapshots_league_id ON snapshots(league_id)`.
- **Verification:** `tests/test_storage_and_cli.py::test_schema_migration_idempotent`, `tests/test_v065_hardening.py::test_w2_eurocup_ingestion_and_schema_v3`

### BUG-ING-004: Hardcoded Season Code Fallback
- **Severity:** P2 (Medium)
- **Status:** `FIXED`
- **Root Cause:** Ingestion hard-coded `"E2026"` fallbacks.
- **Resolution:** Dynamic fallback resolution based on competition ruleset.
- **Verification:** `tests/test_v065_hardening.py::test_w2_eurocup_ingestion_and_schema_v3`

### BUG-LG-004: `import-squad` Does Not Scope by League
- **Severity:** P1 (High)
- **Status:** `FIXED`
- **Root Cause:** `import_squad_from_file` matched names against all snapshots without league filtering, allowing EuroLeague players to be imported into EuroCup teams.
- **Resolution:** `import_squad_from_file` takes `league`/`league_id`, searches only that competition's snapshot, records `league_id` in `current_squad.json`, and rejects league mismatches.
- **Verification:** `tests/test_v065_hardening.py::test_w3_squad_import_league_isolation_and_mismatch`

### BUG-EDGE-001: Postponed / Cancelled Mid-Round Fixtures
- **Severity:** P1 (High)
- **Status:** `FIXED`
- **Root Cause:** Postponed fixtures were projected as normal scheduled fixtures.
- **Resolution:** Detected fixture status in `("postponed", "cancelled", "canceled", "suspended")`. When true, `expected_pdk = 0.0`, `sigma_pdk = 0.0`, `availability_factor = 0.0`, and status is set to `"postponed"`.
- **Verification:** `tests/test_v065_hardening.py::test_w4_edge_001_postponed_fixtures`

### BUG-EDGE-002: Squad Player Left Competition / Missing from Snapshot
- **Severity:** P1 (High)
- **Status:** `FIXED`
- **Root Cause:** Inconsistent handling across services: `squad_report` raised `ValueError`, `suggest_trades` silently dropped to a 10-man squad, `lineup` crashed, and optimizer synthesized arbitrary 10 FP.
- **Resolution:** Harmonized policy: departed squad units are retained, projected at 0.0 FP, and flagged as `"unavailable - sell candidate"`. `OptimizationService._resolve_squad_contracts` assigns 0.0 FP when market data exists.
- **Verification:** `tests/test_v065_hardening.py::test_w4_edge_002_departed_player_handling`

### BUG-EDGE-003: Head Coach Replaced Mid-Season
- **Severity:** P2 (Medium)
- **Status:** `FIXED`
- **Root Cause:** Coach changes mid-season removed old coach ID and introduced new coach ID.
- **Resolution:** Covered under BUG-EDGE-002 policy. Old coach projects 0.0 FP and is readily replaced by the optimizer for the active club coach.
- **Verification:** `tests/test_v065_hardening.py::test_w4_edge_003_replaced_head_coach`

### BUG-EDGE-004: Bank Boundary Legality (0.0 Cr vs -0.1 Cr)
- **Severity:** P1 (High)
- **Status:** `FIXED`
- **Root Cause:** Ambiguity around exact 0.0 Cr remaining balance legality.
- **Resolution:** Confirmed and verified across `validate_trades`, `TransferOptimizer`, and API routes: exact `bank_tenths == 0` (0.0 Cr) is 100% legal; `bank_tenths < 0` (-0.1 Cr) is rejected.
- **Verification:** `tests/test_v065_hardening.py::test_w4_edge_004_bank_boundaries`

### BUG-RULE-002: Played Starter Moved to Bench / Mid-Round Captaincy Hand-Off
- **Severity:** P1 (High)
- **Status:** `FIXED`
- **Official EuroLeague Fantasy Rule Verified (2026-09-29):**
  1. Starters who played on Turn 1 CAN be moved to the bench between turns to bank 0.5x points and promote an unplayed Turn 2 player to starter.
  2. Bench players who already played are locked on the bench and can NEVER enter the court.
  3. A captain who has played may surrender the armband, but it may only be passed to an eligible starter who has NOT played yet.
- **Verification:** `tests/test_v065_hardening.py::test_w4_rule_002_played_starter_and_captaincy`, `tests/test_v05_multi_team_and_gui.py::test_intra_round_optimizer_captaincy_rules`

### BUG-EDGE-005: Three-Turn Rounds (T1 -> T2 -> T3)
- **Severity:** P2 (Medium)
- **Status:** `FIXED`
- **Root Cause:** Turn optimization handling 3 turns.
- **Resolution:** Verified `IntraRoundSubstitutionOptimizer` correctly accommodates units across turns 1, 2, and 3.
- **Verification:** `tests/test_v065_hardening.py::test_w4_edge_005_three_turn_rounds`

### BUG-EDGE-006: Round Rollover Mid-Round
- **Severity:** P2 (Medium)
- **Status:** `FIXED`
- **Root Cause:** Potential projection mismatch if snapshot round increments while managed team is still mid-round.
- **Resolution:** Dossier generation and services consistently use `team.round_number`.
- **Verification:** `tests/test_v065_hardening.py::test_w4_edge_006_round_rollover_uses_team_round`

### BUG-SEC-002: DOM Interpolation of Untrusted Strings in `app.js`
- **Severity:** P1 (High)
- **Status:** `FIXED`
- **Root Cause:** Dynamic template literals in `app.js` rendered unescaped player names, modal fields, and LLM advice text directly into `innerHTML`.
- **Resolution:** Implemented `escapeHtml(str)` helper in `app.js` and wrapped all interpolated dynamic values across cards, tables, chips, and modals.
- **Verification:** `tests/test_v065_hardening.py::test_w5_static_app_js_escaping_guard`, `node --check src/euroleague_fantasy_manager/web/static/js/app.js`

### BUG-API-001: Invalid `league` Query Parameter Returned HTTP 500
- **Severity:** P1 (High)
- **Status:** `FIXED`
- **Root Cause:** Passing `?league=nba` to `/players`, `/players/{id}`, `/update-data`, or `/initial-team/suggest` raised unhandled `ValueError` inside handlers, causing Starlette 500.
- **Resolution:** Added `parse_league()` FastAPI dependency in `deps.py` returning HTTP 400. Added query parameter validation across all endpoints.
- **Verification:** `tests/test_v065_hardening.py::test_w5_api_invalid_league_returns_400`

### BUG-API-002: `/players/{id}` Snapshot Lookup Unscoped
- **Severity:** P1 (High)
- **Status:** `FIXED`
- **Root Cause:** `SELECT * FROM players WHERE id = ? ORDER BY snapshot_id DESC LIMIT 1` ignored league, returning rows from the wrong competition.
- **Resolution:** Scoped query with `JOIN snapshots s ON s.id = p.snapshot_id WHERE p.id = ? AND s.league_id = ?`.
- **Verification:** `tests/test_v065_hardening.py::test_w5_api_player_detail_league_scoping`

### BUG-PROV-001: Version Mismatch (`__version__` vs `pyproject.toml`)
- **Severity:** P2 (Medium)
- **Status:** `FIXED`
- **Root Cause:** `__version__` in `__init__.py` was out of sync with `pyproject.toml`.
- **Resolution:** Single-sourced via `importlib.metadata` with release fallback bumped to `0.6.5`.
- **Verification:** `tests/test_v065_hardening.py::test_w6_version_single_sourcing`

### BUG-PROV-002: Dossier `content_hash` Inadequately Coarse
- **Severity:** P2 (Medium)
- **Status:** `FIXED`
- **Root Cause:** `content_hash` only hashed `team_id:round:total:len(transfers)`.
- **Resolution:** Updated `content_hash` to SHA-256 of the canonical sorted JSON serialization of quantitative outputs (lineups, units, valuations, transfers, intra-round options, league, round, ruleset), excluding timestamps and UUIDs.
- **Verification:** `tests/test_v065_hardening.py::test_w6_dossier_content_hash_invariance_and_sensitivity`

### BUG-PROV-003: Hardcoded Provenance Engine Identifiers
- **Severity:** P2 (Medium)
- **Status:** `FIXED`
- **Root Cause:** Provenance strings were hard-coded to `"decomposed_v051"` and `"bounded_milp_v051"`.
- **Resolution:** Dynamically populated with active engine names (`"fp_decomposed_v03"`, `f"bounded_milp_{team.settings.risk_mode}"`).
- **Verification:** `tests/test_v065_hardening.py::test_w6_dossier_content_hash_invariance_and_sensitivity`

### BUG-LLM-001: Provider Discovery Model Defaults Discrepancy
- **Severity:** P2 (Medium)
- **Status:** `FIXED`
- **Root Cause:** `list_available_providers()` reported different default models than the provider classes (e.g. Gemini `2.5-flash` vs `2.0-flash`, Heuristic naming).
- **Resolution:** Aligned all discovery entries with class defaults.
- **Verification:** `tests/test_v065_hardening.py::test_w6_provider_discovery_and_metadata`

### BUG-LLM-002: Deterministic Heuristic Provider Disregards Analysis Tier
- **Severity:** P2 (Medium)
- **Status:** **ACCEPTED RISK**
- **Rationale:** The deterministic heuristic provider operates 100% locally and offline without external LLM API calls. Generating distinct response text per tier without an LLM would require complex mock narrative generators that add no decision value over the deterministic math.
- **Mitigation:** The requested tier is recorded in `raw_metadata={"offline": True, "tier": request.tier}` for provenance, and docstrings explicitly document this behavior.
- **Verification:** `tests/test_v065_hardening.py::test_w6_provider_discovery_and_metadata`

### BUG-QA-001: No Automated CI Pipeline
- **Severity:** P2 (Medium)
- **Status:** `FIXED`
- **Root Cause:** No continuous integration workflow was present in the repository.
- **Resolution:** Added GitHub Actions workflow `.github/workflows/ci.yml` running `pytest` and `node --check` on `app.js` across pushes and PRs to `main` and `v0*`.
- **Verification:** Workflow validated locally with `node --check` and full pytest execution.

---

## 3. Workstation Manual GUI Smoke-Test Script

This manual smoke-test protocol validates the local workstation end-to-end:

### Pre-Requisites
1. Start the workstation server:
   ```powershell
   elf gui --port 8000
   ```
2. Open browser to `http://localhost:8000`.

### Smoke-Test Steps
1. **Create EuroLeague Team:**
   - Click "New Team" modal in workstation header.
   - Enter Name: `Test EuroLeague`, Competition: `EuroLeague`, Budget: `100.0 Cr`.
   - Click "Create Team". Confirm team appears in team selector dropdown with EuroLeague ruleset badge.
2. **Create EuroCup Team:**
   - Click "New Team" modal.
   - Enter Name: `Test EuroCup`, Competition: `EuroCup`, Budget: `100.0 Cr`.
   - Click "Create Team". Confirm team appears with EuroCup ruleset badge.
3. **Switch Teams:**
   - Toggle between `Test EuroLeague` and `Test EuroCup` in the header selector.
   - Verify court view, Trade Studio market pool, and settings update to reflect the respective competition.
4. **Update Data per League:**
   - With EuroLeague selected, click "Update Data". Confirm status toast indicates EuroLeague snapshot updated.
   - Switch to EuroCup, click "Update Data". Confirm EuroCup snapshot updated independently.
5. **Trade Studio Execution:**
   - Open Trade Studio tab.
   - Verify market pool shows players matching the active league only.
   - Stage a trade reducing bank to exactly `0.0 Cr`. Confirm trade validation passes.
   - Stage a trade requiring `-0.1 Cr`. Confirm validation fails with "Insufficient credits" error banner.
6. **Strategic Intelligence Tab (Copilot):**
   - Navigate to "Intelligence" tab.
   - Select Provider: `Deterministic Heuristic (Offline)`.
   - Test Tier `Fast`, click "Generate Strategic Advice". Confirm response renders.
   - Test Tier `Standard` and `Extended`. Confirm generation succeeds.
7. **XSS Payload Verification:**
   - In SQLite database, insert synthetic player with name `<img src=x onerror=alert(1)>`.
   - View player in Trade Studio market pool and Player Detail modal.
   - Confirm browser renders the string as literal text without triggering an alert or injecting HTML.
