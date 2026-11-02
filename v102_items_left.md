# v102 items left before shipping

This file captures the remaining issues identified during the v1.0.2 review. These are the items I would still resolve before treating the release as ready to merge.

## 1) Broken squad import path logic

File: `src/euroleague_fantasy_manager/import_squad.py`

Issue:
- The function resolves a concrete path into `resolved_players_path`, but the actual file read later still uses `players_path.read_text(...)`.
- `players_path` is not guaranteed to be defined after the path normalization branch.
- This creates a runtime failure in the normal import flow and breaks the CLI path for `elf import-squad`.

Impact:
- Squad import is effectively broken for any code path that relies on the sanitized/normalized `players_path` value.

Suggested fix:
- Replace `players_path.read_text(...)` with `resolved_players_path.read_text(...)`.
- Confirm the same pattern is applied consistently for `resolved_squad_path` and `resolved_db` elsewhere in the function.

## 2) CLI ambiguity in team command arguments

File: `src/euroleague_fantasy_manager/cli.py`

Issue:
- Team commands like `select` and `delete` accept a positional argument and a `--id` argument.
- The code path does not clearly enforce one source of truth.
- This leaves room for ambiguous/inconsistent behavior depending on argument ordering and caller expectations.

Impact:
- User-facing command ergonomics are fragile and can produce surprising results.
- It also reduces confidence in the CLI's validation and error semantics.

Suggested fix:
- Normalize the target team ID resolution into a single helper.
- Reject conflicting values if both positional and `--id` are supplied.
- Ensure one consistent error path and exit code for invalid or missing team IDs.

## 3) Ruleset source-of-truth is still inconsistent across call paths

Files:
- `src/euroleague_fantasy_manager/competition/ruleset.py`
- `src/euroleague_fantasy_manager/cli.py`
- related optimizer/service modules

Issue:
- The PR introduces official config resolution (`resolve_ruleset`), but the wider codebase still contains legacy defaulting and rule selection paths.
- That means the repository can still silently use stale constraints depending on which function path is called.

Impact:
- The release claim of authoritative, unified ruleset handling is not yet consistently true across the product.
- It creates risk of hidden behavior differences between CLI flows, GUI flows, and background services.

Suggested fix:
- Centralize all ruleset resolution behind a single entry point.
- Remove or deprecate lingering hardcoded rule defaults where they are no longer authoritative.
- Add tests covering the same scenario across CLI, service, and optimizer layers.

## 4) Review evidence should be stronger before release

Issue:
- The PR is large and contains a broad set of “hardening” claims, but the code-level evidence in the patch is not yet strong enough to show that the critical user flows are proven by red-to-green test coverage.

Impact:
- Hardening and correctness changes are more likely to hide regressions when the change scope is large and the validation story is partial.

Suggested fix:
- Add failing regression tests for the squad import bug, CLI command ambiguity, and any ruleset override mismatch.
- Require the relevant tests to pass after the fixes before merge.

## 5) Release gate recommendation

Before merging v1.0.2, I would insist on:
- fixing the broken `import_squad` path read,
- normalizing team command argument handling,
- reconciling ruleset resolution across entry points,
- and validating the critical flows with targeted automated tests.

Once those items are addressed, the PR will be in much stronger shape for release.
