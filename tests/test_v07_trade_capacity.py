"""V0.7 W1 — Full trade capacity (4 trades per round).

The EuroLeague ruleset grants 4 trades per round (`rules.py::MAX_TRADES_PER_ROUND`).
Prior to V0.7 the engine supported k=1..4 but every caller above it understated the
cap: the GUI hardcoded 2, and the API/service defaults were 1. These tests pin the
full legal action space end to end so it cannot silently regress again.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from euroleague_fantasy_manager.optimization.multi_round import MultiRoundOptimizer
from euroleague_fantasy_manager.rules import MAX_TRADES_PER_ROUND
from euroleague_fantasy_manager.services.optimization_service import OptimizationService
from euroleague_fantasy_manager.web.api.routes_workstation import OptimizeTransfersRequest

APP_JS = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "euroleague_fantasy_manager"
    / "web"
    / "static"
    / "js"
    / "app.js"
)


def test_ruleset_grants_four_trades_per_round():
    assert MAX_TRADES_PER_ROUND == 4


def test_api_request_model_defaults_to_full_capacity():
    """The web API must not understate the legal trade budget."""
    assert OptimizeTransfersRequest(team_id="t1").max_trades == MAX_TRADES_PER_ROUND


def test_optimization_service_defaults_to_full_capacity():
    sig = inspect.signature(OptimizationService.optimize_transfers)
    assert sig.parameters["max_trades"].default == MAX_TRADES_PER_ROUND


def test_multi_round_optimizer_defaults_to_full_capacity():
    sig = inspect.signature(MultiRoundOptimizer.__init__)
    assert sig.parameters["max_trades_per_round"].default == MAX_TRADES_PER_ROUND
    assert MultiRoundOptimizer().max_trades_per_round == MAX_TRADES_PER_ROUND


def test_gui_declares_and_uses_the_full_trade_cap():
    """The GUI previously sent `Math.min(2, ...)`, silently halving the action space."""
    source = APP_JS.read_text(encoding="utf-8")

    assert re.search(r"const\s+MAX_TRADES_PER_ROUND\s*=\s*4\s*;", source), (
        "app.js must declare MAX_TRADES_PER_ROUND = 4 mirroring rules.py"
    )

    # The transfer-suggestion payload must derive its cap from the constant,
    # never from a hardcoded 2.
    payload = re.search(r"max_trades:\s*(.+?),\n", source, re.DOTALL)
    assert payload is not None, "could not locate max_trades in the suggest-transfers payload"
    assert "MAX_TRADES_PER_ROUND" in payload.group(1)
    assert not re.search(r"Math\.min\(\s*2\s*,", source), (
        "app.js must not hardcode a 2-trade cap"
    )


def test_dossier_uses_full_capacity_not_three():
    """`dossier.py` previously capped suggestions at 3 trades."""
    dossier_src = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "euroleague_fantasy_manager"
        / "intelligence"
        / "dossier.py"
    ).read_text(encoding="utf-8")
    assert "min(team.transfers_remaining, MAX_TRADES_PER_ROUND)" in dossier_src
    assert "min(team.transfers_remaining, 3)" not in dossier_src


def test_engine_returns_packages_across_the_full_action_space():
    """The engine must actually produce 1-, 2-, 3- and 4-trade packages."""
    from euroleague_fantasy_manager.models import Position
    from euroleague_fantasy_manager.optimization.transfers import TransferOptimizer

    from test_v05_multi_team_and_gui import make_standard_squad, make_test_player

    squad = make_standard_squad()
    market = [
        make_test_player(
            1000 + i,
            [Position.GUARD, Position.FORWARD, Position.CENTER][i % 3],
            expected_fp=5.0 + (i % 25),
            price_tenths=40 + (i % 150),
        )
        for i in range(120)
    ]

    opt = TransferOptimizer()
    for k in (1, 2, 3, 4):
        res = opt.optimize_transfers(
            current_squad=squad, market=market, bank_tenths=100, max_trades=k
        )
        assert res.recommendations, f"no recommendation returned for max_trades={k}"
        assert max(r.trade_count for r in res.recommendations) == k, (
            f"engine did not explore the full budget at max_trades={k}"
        )
        assert all(r.trade_count <= k for r in res.recommendations)


def test_engine_respects_a_smaller_remaining_budget():
    """A team with fewer remaining trades must still be limited to that number."""
    from euroleague_fantasy_manager.models import Position
    from euroleague_fantasy_manager.optimization.transfers import TransferOptimizer

    from test_v05_multi_team_and_gui import make_standard_squad, make_test_player

    squad = make_standard_squad()
    market = [
        make_test_player(
            2000 + i,
            [Position.GUARD, Position.FORWARD, Position.CENTER][i % 3],
            expected_fp=5.0 + (i % 25),
            price_tenths=40 + (i % 150),
        )
        for i in range(120)
    ]

    res = TransferOptimizer().optimize_transfers(
        current_squad=squad, market=market, bank_tenths=100, max_trades=2
    )
    assert all(r.trade_count <= 2 for r in res.recommendations)
