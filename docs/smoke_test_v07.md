# V0.7 Smoke Test Record

> **Date:** 2026-09-30 / 2026-10-01  
> **Branch:** `v07` (including PR review remediation)  
> **Environment:** Python 3.12, conda env `elf`, Windows 11

## §9.3 Manual Verification Checklist & Audit Trail

| # | Check | Requirement | Verification Method | Status | Evidence / Test Mapping |
|---|---|---|---|---|---|
| 1 | 4-Trade Suggestion Default | Suggester evaluates up to 4 trades by default (`rules.MAX_TRADES_PER_ROUND = 4`) | Automated test | **PASS** | `tests/test_v065_hardening.py::test_w1_four_trade_cap_...` and `tests/test_v07_sequential_replay.py::test_transfer_optimizer_k4_is_deterministic` |
| 2 | Cheapest Player Reachable | Manual transfer player browser does not truncate cheap players | Automated test | **PASS** | `tests/test_v07_player_universe.py` and `tests/test_v05_multi_team_and_gui.py::test_player_list_sort_and_pagination` |
| 3 | OpenRouter Key + Free Sub-Model Advice | Paste OpenRouter key in GUI, select free model (e.g., `meta-llama/llama-3-8b-instruct:free`), receive advice without setting env vars | Manual interactive run | **PASS** | Verified manually on 2026-09-30 against OpenRouter API. Automated unit tests verify header passing, key redaction on error, and localStorage key names (`tests/test_v07_llm_providers.py`). Live network is prohibited in CI per F6. |
| 4 | Past Round Recorded & Forward Propagation | Record lineup / trade for past round, verify round-start checkpoints preserved, `revert-round-start` functional | Automated test | **PASS** | `tests/test_v07_sequential_replay.py::test_past_round_trade_forward_replay_and_cap_enforcement` and `tests/test_v07_past_rounds.py` |

## Automated Gates Status

- **Unit & Integration Suite**: Full test suite passing in `elf` conda environment (`pytest -q`).
- **GUI Static Validation**: `node --check src/euroleague_fantasy_manager/web/static/js/app.js` exit 0.
- **Zero-Mutation Invariant**: Database byte hash identical before and after full replay runs (`test_f8_zero_mutation_invariant`).
- **Replay Determinism**: Bit-for-bit identical ledger outputs across identical simulation runs (`test_season_replay_is_deterministic`).
- **Telescoping Exact Regret**: Zero residual (`residual == 0.0`) across full 34-round season replay (`test_lengthened_season_replay_34_rounds`).
