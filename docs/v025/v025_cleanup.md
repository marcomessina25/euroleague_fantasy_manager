# V0.2.5 Cleanup

> **Purpose:** Small post-merge cleanup for the V0.2.5 historical evaluation release.
>
> **Naming decision:** This release is **V0.2.5**, not V0.25. Use `0.2.5` / `V0.2.5` consistently in user-facing documentation and release metadata. Existing `v025` branch/path names may remain as internal shorthand.

## 1. Version naming

- [x] Replace user-facing `V0.25` references with **V0.2.5**.
- [x] Replace user-facing `0.25.0` references with **0.2.5**.
- [x] Update `pyproject.toml` to `0.2.5`.
- [x] Update `src/euroleague_fantasy_manager/__init__.py` to `0.2.5`.
- [x] Update README badge and release wording.
- [x] Update roadmap and V0.2.5 documentation headings/references.
- [x] Keep internal `v025` names only where they are useful implementation identifiers.

## 2. README cleanup

The current PR introduced duplicate old/new lines.

- [x] Remove the old `0.2.0` badge.
- [x] Keep exactly one current version badge: `0.2.5`.
- [x] Remove duplicate roadmap-status bullets.
- [x] State clearly that V0.1, V0.2 and V0.2.5 are completed/released according to the actual merge state.
- [x] Make V0.3 the next milestone.
- [x] Rename the historical-evaluation section from V0.25 to V0.2.5.
- [x] Keep the existing CLI examples unless clarification is required.

## 3. Roadmap cleanup

- [x] Remove duplicate status lines introduced by the PR.
- [x] Replace `V0.25` with `V0.2.5`.
- [x] Remove obsolete “next milestone” wording once V0.2.5 is merged.
- [x] Make V0.3 the single next milestone.
- [x] Keep historical evaluation explicitly positioned as the foundation for V0.3.
- [x] Ensure all documentation links point to canonical paths.

## 4. V0.2 documentation paths

The V0.2 checklist is now:

`docs/v02/items_left_for_v02.md`

- [x] Remove every stale reference to `docs/items_left_for_v02.md`.
- [x] Search the repository for `docs/items_left_for_v02.md`.
- [x] Search for `V0.25`, `v0.25`, and `0.25.0`.
- [x] Search for `v025` and decide case-by-case whether each occurrence is an internal branch/path or a user-facing release reference.

## 5. V0.2.5 evaluation documentation

Do not change the evaluation methodology during this cleanup.

- [x] State clearly that the currently reported benchmark is **E2025 rounds 1–12**.
- [x] Do not present that benchmark as proof of global model superiority.
- [x] Explain that different metrics favor different baselines:
  - xPDK: strongest current rank-ordering/captain-regret result in the reported benchmark.
  - EWMA: strongest point-error / simulated-lineup result in the reported benchmark.
  - last5: strongest Top-10 recall in the reported benchmark.
- [x] Clearly distinguish **All Players** from **Active Players** metrics.
- [x] Include sample counts with aggregate metrics where practical.
- [x] Clarify that lineup regret is a simplified decision simulation, not a complete historical fantasy-season replay.

## 6. Historical pricing provenance

Historical fantasy pricing has weaker coverage than game statistics.

- [x] Document price coverage by season.
- [x] Identify price provenance where possible:
  - `official_snapshot`
  - `archived_fantasy`
  - `reconstructed`
  - `proxy`
  - `missing`
- [x] Avoid treating Value Spearman as equally reliable across observations with different price provenance.
- [x] If practical, expose price-coverage statistics in evaluation reports.

## 7. Tests and verification

- [x] Run the complete test suite.
- [x] Confirm the package reports `0.2.5`.
- [x] Run historical dataset inspection.
- [x] Re-run the E2025 R1–12 benchmark.
- [x] Confirm cleanup changes do not alter evaluation results except for expected metadata/reporting changes.
- [x] Check repository-wide documentation links.

## 8. Explicitly out of scope

Do **not** use this cleanup to:

- redesign xPDK;
- replace EWMA;
- introduce ML models;
- tune parameters against E2025 R1–12;
- change fantasy scoring reconstruction;
- redesign the database;
- build the V0.3 prediction architecture.

The goal is to make V0.2.5 clean, reproducible, correctly named, and scientifically well documented before V0.3.
