"""Hermetic unit tests for EuroLeague Fantasy Classic Mode rules, formations, and trade validation."""

import pytest

from euroleague_fantasy_manager.models import Player, Position
from euroleague_fantasy_manager.rules import (
    LEGAL_COURT_FORMATIONS,
    validate_court_lineup,
    validate_squad,
)
from euroleague_fantasy_manager.squad_state import CurrentSquadState
from euroleague_fantasy_manager.transfers import (
    TradeMove,
    parse_trade_specs,
    selling_price_tenths,
    validate_trades,
)


def make_sample_pool() -> dict[int, Player]:
    """Build a test pool of Guards, Forwards, Centers, and Head Coaches."""
    pool = [
        # Guards (G)
        Player(id=101, name="Mike James", position=Position.GUARD, team_id=1, team_code="EFS", price_tenths=110),
        Player(id=102, name="TJ Shorts", position=Position.GUARD, team_id=2, team_code="VBC", price_tenths=95),
        Player(id=103, name="Sylvain Francisco", position=Position.GUARD, team_id=3, team_code="PAO", price_tenths=85),
        Player(id=104, name="Facundo Campazzo", position=Position.GUARD, team_id=4, team_code="RMB", price_tenths=80),
        Player(id=105, name="Shane Larkin", position=Position.GUARD, team_id=1, team_code="EFS", price_tenths=100),
        Player(id=106, name="Nadir Hifi", position=Position.GUARD, team_id=5, team_code="PBB", price_tenths=75),
        # Forwards (F)
        Player(id=201, name="Sasha Vezenkov", position=Position.FORWARD, team_id=6, team_code="OLY", price_tenths=120),
        Player(id=202, name="Chima Moneke", position=Position.FORWARD, team_id=7, team_code="CZV", price_tenths=95),
        Player(id=203, name="Tornike Shengelia", position=Position.FORWARD, team_id=8, team_code="DUB", price_tenths=90),
        Player(id=204, name="Alberto Abalde", position=Position.FORWARD, team_id=4, team_code="RMB", price_tenths=65),
        Player(id=205, name="Jaylen Hoard", position=Position.FORWARD, team_id=9, team_code="MTA", price_tenths=85),
        # Centers (C)
        Player(id=301, name="Nikola Milutinov", position=Position.CENTER, team_id=6, team_code="OLY", price_tenths=100),
        Player(id=302, name="Vincent Poirier", position=Position.CENTER, team_id=1, team_code="EFS", price_tenths=85),
        Player(id=303, name="Jonas Valanciunas", position=Position.CENTER, team_id=10, team_code="ZAL", price_tenths=95),
        # Head Coaches (HC)
        Player(id=401, name="Georgios Bartzokas", position=Position.HEAD_COACH, team_id=6, team_code="OLY", price_tenths=75),
        Player(id=402, name="Ergin Ataman", position=Position.HEAD_COACH, team_id=3, team_code="PAO", price_tenths=80),
    ]
    return {p.id: p for p in pool}


def make_valid_squad(pool: dict[int, Player]) -> list[Player]:
    ids = [101, 102, 103, 104, 201, 202, 203, 204, 301, 302, 401]
    return [pool[i] for i in ids]


def test_validate_squad_legal_11_units() -> None:
    pool = make_sample_pool()
    squad = make_valid_squad(pool)
    result = validate_squad(squad)
    assert result.is_valid, f"Expected valid squad, got errors: {result.errors}"


def test_validate_squad_rejects_budget_and_position_violations() -> None:
    pool = make_sample_pool()
    squad = make_valid_squad(pool)
    # Exceed budget (100.0 Cr = 1000 tenths; squad costs 1000 tenths, test against 950 tenths)
    over_budget = validate_squad(squad, budget_tenths=950)
    assert not over_budget.is_valid
    assert any("exceeding" in err for err in over_budget.errors)

    # Replace Head Coach (401) with a 5th Guard (105)
    bad_positions = [p for p in squad if p.id != 401] + [pool[105]]
    pos_res = validate_squad(bad_positions, budget_tenths=1200)
    assert not pos_res.is_valid
    assert any("guards" in err for err in pos_res.errors)
    assert any("head coaches" in err for err in pos_res.errors)


@pytest.mark.parametrize(
    "starters",
    [
        (101, 102, 201, 202, 301),  # 2-2-1
        (101, 201, 202, 301, 302),  # 1-2-2
        (101, 102, 201, 301, 302),  # 2-1-2
        (101, 201, 202, 203, 301),  # 1-3-1
        (101, 102, 103, 201, 301),  # 3-1-1
    ],
)
def test_validate_court_lineup_all_five_legal_formations(starters: tuple[int, ...]) -> None:
    assert len(LEGAL_COURT_FORMATIONS) == 5
    pool = make_sample_pool()
    squad = make_valid_squad(pool)
    non_starter_players = [p.id for p in squad if p.id not in starters and p.position != Position.HEAD_COACH]
    result = validate_court_lineup(
        squad=squad,
        starters=starters,
        captain_id=starters[0],
        sixth_man_id=non_starter_players[0],
        head_coach_id=401,
    )
    assert result.is_valid, f"Formation failed: {result.errors}"


def test_validate_court_lineup_rejects_illegal_formation_and_coach_on_court() -> None:
    pool = make_sample_pool()
    squad = make_valid_squad(pool)
    # 3-2-0 (zero Centers) is illegal
    illegal = validate_court_lineup(
        squad=squad,
        starters=(101, 102, 103, 201, 202),
        captain_id=101,
        sixth_man_id=301,
        head_coach_id=401,
    )
    assert not illegal.is_valid
    assert any("Illegal starting formation 3-2-0" in err for err in illegal.errors)

    # Head coach in starting 5 is illegal
    coach_on_court = validate_court_lineup(
        squad=squad,
        starters=(101, 102, 201, 301, 401),
        captain_id=101,
        sixth_man_id=202,
        head_coach_id=401,
    )
    assert not coach_on_court.is_valid
    assert any("Head Coach" in err for err in coach_on_court.errors)


def test_trades_realize_100_percent_capital_gains_and_enforce_4_trade_limit() -> None:
    pool = make_sample_pool()
    squad = make_valid_squad(pool)
    squad_ids = tuple(p.id for p in squad)

    # Suppose Sasha Vezenkov (201) was purchased at 10.0 Cr (100 tenths) and is now worth 12.0 Cr (120 tenths).
    # In EuroLeague Fantasy (0% sell-on tax), selling him yields the full 12.0 Cr (120 tenths)!
    assert selling_price_tenths(pool[201], purchase_price_tenths=100) == 120

    state = CurrentSquadState(
        player_ids=squad_ids,
        purchase_prices_tenths={pid: 80 for pid in squad_ids},
        bank_tenths=0,
        free_trades=4,
        unlimited_windows_remaining=(7, 14, 19, 24, 29, 35),
        season="2026/27",
        round_number=2,
    )

    # Trade 1 Guard + 1 Head Coach (Mike James 11.0Cr -> Shane Larkin 10.0Cr; Bartzokas 7.5Cr -> Ataman 8.0Cr)
    moves = parse_trade_specs(["Mike James:Shane Larkin", "Bartzokas:Ataman"], pool, by_name=True)
    report = validate_trades(state, moves, pool)
    assert report.is_valid, f"Expected valid trades: {report.errors}"
    assert report.trades_count == 2
    assert report.free_trades_after == 2
    assert report.bank_after_tenths == 5  # +1.0Cr from Guard swap - 0.5Cr from Coach swap = +0.5Cr (5 tenths)

    # 5 trades in Round 2 (non-unlimited round) must be rejected
    five_moves = [
        TradeMove(101, 105),
        TradeMove(102, 106),
        TradeMove(202, 205),
        TradeMove(302, 303),
        TradeMove(401, 402),
    ]
    over_limit_report = validate_trades(state, five_moves, pool, unlimited_window=False)
    assert not over_limit_report.is_valid
    assert any("exceeding the 4-trade limit" in err for err in over_limit_report.errors)

    # Same 5 trades in Unlimited Trade Window (e.g., Round 7 after R6, or with unlimited_window=True) is valid
    unlimited_report = validate_trades(state, five_moves, pool, unlimited_window=True)
    assert unlimited_report.is_valid, f"Expected valid unlimited window trades: {unlimited_report.errors}"
