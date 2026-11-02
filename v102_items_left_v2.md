# Review Findings for PR #17 (V1.0.2)

## Summary

I would not approve this PR as-is. The pull request is broad in scope and includes several high-risk, correctness-related issues that still need to be resolved before merge.

## Key Findings

### 1) Broken squad import flow / path resolution issue

In the import workflow, the code resolves a path into `resolved_players_path`, but the actual file read still uses the original `players_path` variable. This creates a broken runtime flow for the normal import process and undermines the path-resolution hardening work claimed in the release summary.

This is a correctness issue and should block the merge.

### 2) Ambiguous command behavior for team selection and deletion

The CLI team commands now accept multiple ways to identify a team, including positional values and `--id`-style inputs, without a single explicit resolution path. This can create inconsistent behavior depending on how the command is invoked.

This creates user-facing risk and command ambiguity, especially in a release focused on correctness and state hardening.

### 3) Ruleset source-of-truth remains inconsistent

The PR claims to centralize authoritative configuration and rules ingestion, but the effective ruleset still appears inconsistent across app paths. Some optimization and service paths still depend on legacy/default behavior rather than the new authoritative rules. This means the product can use different club quotas, limits, or trade logic depending on execution path.

This is a substantial correctness bug in a release specifically framed as a ruleset hardening update.

### 4) Prediction routing still not fully honest / point-in-time safe

The release notes mention “honest point-in-time prediction routing,” but the code still includes fallback logic that does not consistently enforce a strict, time-correct, point-in-time contract across all prediction entry points.

This is a model correctness and trust issue and should be treated as a release blocker.

### 5) Team-state and replay logic is still too fragile for a hardening release

The changes in the multi-team store and associated round-state code are broad and central to state integrity. The persistence, checkpointing, revert logic, and trade-replay flow are tightly coupled. A single mistake here can rewrite user state or make historical replay impossible.

Because this release explicitly claims state hardening and ACID-style safety, the resulting implementation needs stronger invariants and broader regression coverage before merge.

### 6) Security hardening is not sufficiently convincing for a security-focused release

The PR description claims strong local web security measures, but the code still shows incomplete evidence of comprehensive validation, safe mutation handling, and defense-in-depth checks. For a release that markets security work, this needs stronger enforcement and test evidence.

## Overall Assessment

Overall risk: high.

This PR is too broad for a single release and still contains several concrete correctness and safety issues. The most important weaknesses are in:

- import path handling
- command ambiguity
- ruleset consistency
- prediction integrity
- state management/replay
- security hardening coverage

## Recommendation

Request changes before merge.

The PR should not be approved until the above issues are fixed and validated with tests covering the changed behavior.
