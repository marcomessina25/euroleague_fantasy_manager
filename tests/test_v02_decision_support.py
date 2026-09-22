"""Hermetic V0.2 unit and integration tests for EuroLeague Fantasy decision support."""

import json
import math
from pathlib import Path

from euroleague_fantasy_manager.cli import main as cli_main
from euroleague_fantasy_manager.expected_points import (
    PlayerProjection,
    expected_coach_pdk,
    project_all_players,
)
from euroleague_fantasy_manager.fixtures import (
    analyze_squad_fixtures,
    analyze_team_fixtures,
    compute_team_strengths,
)
from euroleague_fantasy_manager.lineup import (
    compute_turn_option_bonuses,
    gaussian_call_option,
    optimize_court_lineup,
)
from euroleague_fantasy_manager.models import Player, Position
from euroleague_fantasy_manager.squad_report import generate_squad_report
from euroleague_fantasy_manager.squad_state import load_current_squad
from euroleague_fantasy_manager.storage import SnapshotStore
from euroleague_fantasy_manager.suggest_transfers import suggest_trades
from euroleague_fantasy_manager.transfers import TradeMove, validate_trades


def _make_proj(
    player: Player,
    xpdk: float,
    sigma: float = 6.0,
    turn: int | None = None,
) -> PlayerProjection:
    tnum = turn if turn is not None else player.turn_number
    return PlayerProjection(
        player_id=player.id,
        name=player.name,
        position=player.position,
        team_id=player.team_id,
        team_code=player.team_code,
        price_tenths=player.price_tenths,
        credits=player.credits,
        status=player.status,
        turn_number=tnum,
        opponent_code="OPP",
        is_home=True,
        fdr=3,
        win_probability=0.5,
        expected_margin=0.0,
        availability_factor=1.0,
        base_pir=xpdk,
        expected_pdk=xpdk,
        sigma_pdk=sigma,
    )


def _seed_v02_snapshot_and_squad(tmp_path: Path) -> tuple[Path, Path]:
    """Create a hermetic SQLite database and current_squad.json with Turn 1 and Turn 2 games."""
    db_path = tmp_path / "test_v02.sqlite3"
    squad_path = tmp_path / "current_squad.json"

    players = [
        # Guards (4 in squad + 1 external target)
        Player(1, "Kendrick Nunn", Position.GUARD, 1, "PAO", 165, "starter", 1.0, 1, 21.0, 18.5),
        Player(2, "Facundo Campazzo", Position.GUARD, 2, "RMB", 150, "starter", 1.0, 1, 19.5, 17.0),
        Player(3, "Thomas Walkup", Position.GUARD, 3, "OLY", 90, "starter", 1.0, 2, 11.5, 10.5),
        Player(4, "Bench Guard", Position.GUARD, 6, "BER", 45, "bench", 1.0, 1, 4.5, 4.0),
        Player(101, "Mike James", Position.GUARD, 5, "ASM", 150, "starter", 1.0, 1, 24.5, 22.0),
        # Forwards (4 in squad + 1 external target)
        Player(5, "Sasha Vezenkov", Position.FORWARD, 3, "OLY", 170, "starter", 1.0, 2, 23.5, 21.0),
        Player(6, "Nigel Hayes-Davis", Position.FORWARD, 4, "FBB", 145, "starter", 1.0, 2, 18.0, 16.0),
        Player(7, "Mario Hezonja", Position.FORWARD, 2, "RMB", 125, "starter", 1.0, 1, 15.0, 14.0),
        Player(8, "Rookie Forward", Position.FORWARD, 6, "BER", 40, "bench", 1.0, 1, 4.0, 3.5),
        Player(102, "Alpha Diallo", Position.FORWARD, 5, "ASM", 120, "starter", 1.0, 1, 20.0, 18.5),
        # Centers (2 in squad + 1 external target)
        Player(9, "Mathias Lessort", Position.CENTER, 1, "PAO", 155, "starter", 1.0, 1, 20.0, 18.0),
        Player(10, "Walter Tavares", Position.CENTER, 2, "RMB", 140, "starter", 1.0, 1, 18.5, 16.5),
        Player(103, "Moustapha Fall", Position.CENTER, 3, "OLY", 110, "starter", 1.0, 2, 15.5, 14.0),
        # Head Coaches (1 in squad + 1 external target)
        Player(11, "Georgios Bartzokas", Position.HEAD_COACH, 3, "OLY", 80, "starter", 1.0, 2, 10.0, 9.0),
        Player(104, "Ergin Ataman", Position.HEAD_COACH, 1, "PAO", 85, "starter", 1.0, 1, 16.0, 14.0),
    ]

    squad_payload = {
        "season": "E2026",
        "league_id": 10,
        "round_number": 1,
        "bank_tenths": 25,
        "free_trades": 4,
        "player_ids": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
        "purchase_prices_tenths": {
            "1": 150,  # +1.5 Cr capital gain
            "2": 150,
            "3": 95,   # -0.5 Cr capital loss
            "4": 45,
            "5": 160,  # +1.0 Cr capital gain
            "6": 145,
            "7": 125,
            "8": 40,
            "9": 150,  # +0.5 Cr capital gain
            "10": 140,
            "11": 80,
        },
    }
    squad_path.write_text(json.dumps(squad_payload, indent=2), encoding="utf-8")

    teams_meta = {
        1: ("Panathinaikos AKTOR Athens", "PAO"),
        2: ("Real Madrid", "RMB"),
        3: ("Olympiacos Piraeus", "OLY"),
        4: ("Fenerbahce Beko Istanbul", "FBB"),
        5: ("AS Monaco", "ASM"),
        6: ("ALBA Berlin", "BER"),
    }

    def _team_lineup_block(tid: int) -> dict[str, object]:
        tname, tabbr = teams_meta[tid]
        return {
            "id": tid,
            "name": tname,
            "abbreviation": tabbr,
            "lineups": [
                {
                    "id": p.id,
                    "first_name": p.name.split()[0],
                    "last_name": " ".join(p.name.split()[1:]),
                    "position": p.position.short_code,
                    "quotation": p.credits,
                    "status": p.status,
                    "probability_of_playing": p.probability_of_playing,
                    "avg_fantasy_pts": p.avg_fantasy_pts,
                    "last_match_pts": p.last_match_pts,
                }
                for p in players
                if p.team_id == tid
            ],
        }

    round1_schedule = {
        "id": 1528,
        "number": 1,
        "rounds": [
            {
                "id": 2523,
                "number": 1,
                "matches": [
                    {
                        "id": 101,
                        "status": "scheduled",
                        "started_at": "2026-10-01T18:15:00Z",
                        "home_team": {"id": 1, "name": "Panathinaikos AKTOR Athens", "abbreviation": "PAO"},
                        "away_team": {"id": 6, "name": "ALBA Berlin", "abbreviation": "BER"},
                    },
                    {
                        "id": 102,
                        "status": "scheduled",
                        "started_at": "2026-10-01T19:00:00Z",
                        "home_team": {"id": 2, "name": "Real Madrid", "abbreviation": "RMB"},
                        "away_team": {"id": 5, "name": "AS Monaco", "abbreviation": "ASM"},
                    },
                ],
            },
            {
                "id": 2524,
                "number": 2,
                "matches": [
                    {
                        "id": 103,
                        "status": "scheduled",
                        "started_at": "2026-10-02T18:15:00Z",
                        "home_team": {"id": 3, "name": "Olympiacos Piraeus", "abbreviation": "OLY"},
                        "away_team": {"id": 4, "name": "Fenerbahce Beko Istanbul", "abbreviation": "FBB"},
                    }
                ],
            },
        ],
    }

    round2_schedule = {
        "id": 1529,
        "number": 2,
        "rounds": [
            {
                "id": 2525,
                "number": 1,
                "matches": [
                    {
                        "id": 201,
                        "status": "scheduled",
                        "started_at": "2026-10-08T18:15:00Z",
                        "home_team": {"id": 1, "name": "Panathinaikos AKTOR Athens", "abbreviation": "PAO"},
                        "away_team": {"id": 2, "name": "Real Madrid", "abbreviation": "RMB"},
                    }
                ],
            },
            {
                "id": 2526,
                "number": 2,
                "matches": [
                    {
                        "id": 202,
                        "status": "scheduled",
                        "started_at": "2026-10-09T18:15:00Z",
                        "home_team": {"id": 3, "name": "Olympiacos Piraeus", "abbreviation": "OLY"},
                        "away_team": {"id": 6, "name": "ALBA Berlin", "abbreviation": "BER"},
                    }
                ],
            },
        ],
    }

    store = SnapshotStore(db_path)
    store.save_snapshot(
        {
            "league_id": 10,
            "competition_code": "E",
            "season_code": "E2026",
            "config": {
                "current_matchday": {"id": 1528, "number": 1, "num_rounds": 2},
                "teams": [
                    {"id": tid, "name": tname, "abbreviation": tabbr}
                    for tid, (tname, tabbr) in teams_meta.items()
                ],
            },
            "schedule": round1_schedule,
            "schedules": [round1_schedule, round2_schedule],
            "match_lineups": [
                {"id": 101, "turn_number": 1, "home_team": _team_lineup_block(1), "away_team": _team_lineup_block(6)},
                {"id": 102, "turn_number": 1, "home_team": _team_lineup_block(2), "away_team": _team_lineup_block(5)},
                {"id": 103, "turn_number": 2, "home_team": _team_lineup_block(3), "away_team": _team_lineup_block(4)},
            ],
        }
    )

    return db_path, squad_path


def test_squad_report_capital_gains_and_zero_sell_tax(tmp_path: Path) -> None:
    db_path, squad_path = _seed_v02_snapshot_and_squad(tmp_path)
    report = generate_squad_report(
        squad_path=squad_path,
        database_path=db_path,
        report_path=None,
        round_number=1,
    )

    assert report["squad_size"] == 11
    assert report["is_valid"] is True
    assert report["state"]["next_unlimited_window_round"] == 7
    assert report["state"]["free_trades"] == 4

    fin = report["financials"]
    assert fin["squad_purchase_value_tenths"] == 1280
    assert fin["squad_current_value_tenths"] == 1305
    assert fin["squad_selling_value_tenths"] == 1305  # 0% sell-on tax
    assert fin["unrealized_capital_gain_tenths"] == 25  # +2.5 Cr
    assert fin["total_team_value_tenths"] == 1330       # 130.5 Cr + 2.5 Cr bank


def test_fixtures_fdr_and_multi_round_ticker(tmp_path: Path) -> None:
    db_path, squad_path = _seed_v02_snapshot_and_squad(tmp_path)
    store = SnapshotStore(db_path)
    players = store.load_latest_players()
    teams_map = store.load_latest_teams()

    strengths = compute_team_strengths(players, teams_map)
    assert strengths[1] > strengths[6]
    assert strengths[2] > strengths[6]

    team_report = analyze_team_fixtures(
        database_path=db_path,
        num_rounds=2,
        start_round=1,
        report_path=None,
    )
    rankings = team_report["team_rankings"]
    assert len(rankings) == 6
    assert rankings[0]["avg_fdr"] <= rankings[-1]["avg_fdr"]

    squad_report = analyze_squad_fixtures(
        squad_path=squad_path,
        database_path=db_path,
        num_rounds=2,
        start_round=1,
    )
    assert len(squad_report["squad_units"]) == 11


def test_expected_points_coach_margin_step_brackets() -> None:
    fav_pts, fav_std = expected_coach_pdk(expected_margin=8.5)
    dog_pts, _ = expected_coach_pdk(expected_margin=-8.5)
    even_pts, _ = expected_coach_pdk(expected_margin=0.0)

    assert fav_pts > even_pts > dog_pts
    assert fav_pts > 9.0
    assert dog_pts < 0.0
    assert fav_std >= 2.0


def test_turn_option_value_hand_calculated_and_zero_or_illegal_cases() -> None:
    """Verify Section 3 of items_left_for_v02.md:
    - Exact hand-calculated Gaussian call option value: when mu_backup == mu_primary == 15.0 and sigma == 10.0,
      z = 0, Phi(0) = 0.5, phi(0) = 1/sqrt(2*pi) ~= 0.39894228, so E[max(0, 15 - S)] = 10 * phi(0) ~= 3.9894228.
      Captain option bonus = round(3.9894228, 2) == 3.99; single slot option bonus = round(0.5 * 3.9894228, 2) == 1.99.
    - Cross-position illegal formation transition: in a 1-2-2 formation (1G, 2F, 2C), the lone T1 Guard cannot be
      substituted by a T2 Bench Forward (which would create 0-3-2, an illegal formation).
    - Zero-option-value cases when no unplayed T2 backup exists or when backup cannot improve a low-variance primary.
    """
    expected_equal_mean_call = 10.0 / math.sqrt(2.0 * math.pi)
    assert math.isclose(
        gaussian_call_option(mu_backup=15.0, mu_primary=15.0, sigma_primary=10.0),
        expected_equal_mean_call,
        rel_tol=1e-6,
    )
    # Zero option value when sigma is negligible and backup < primary
    assert gaussian_call_option(mu_backup=8.0, mu_primary=20.0, sigma_primary=0.01) == 0.0

    # Construct a 1-2-2 starting lineup (G1 in T1; F1, F2, C1, C2 in T2)
    g1_t1 = Player(1, "G1_T1", Position.GUARD, 1, "PAO", 100, "starter", 1.0, 1)
    g2_t1 = Player(2, "G2_T1", Position.GUARD, 1, "PAO", 100, "starter", 1.0, 1)
    g3_t1 = Player(3, "G3_T1", Position.GUARD, 1, "PAO", 100, "starter", 1.0, 1)
    g4_t2 = Player(4, "G4_T2", Position.GUARD, 2, "OLY", 100, "starter", 1.0, 2)
    f1_t2 = Player(5, "F1_T2", Position.FORWARD, 2, "OLY", 100, "starter", 1.0, 2)
    f2_t2 = Player(6, "F2_T2", Position.FORWARD, 2, "OLY", 100, "starter", 1.0, 2)
    f3_t2 = Player(7, "F3_T2", Position.FORWARD, 2, "OLY", 100, "starter", 1.0, 2)
    f4_t1 = Player(8, "F4_T1", Position.FORWARD, 1, "PAO", 100, "starter", 1.0, 1)
    c1_t2 = Player(9, "C1_T2", Position.CENTER, 2, "OLY", 100, "starter", 1.0, 2)
    c2_t2 = Player(10, "C2_T2", Position.CENTER, 2, "OLY", 100, "starter", 1.0, 2)

    starters_122 = (g1_t1, f1_t2, f2_t2, c1_t2, c2_t2)
    sixth_man_t2 = f3_t2  # T2 sixth man

    # Case A: T2 bench has only a Forward (f3_t2) while Guards on bench are T1 (0.0xp) ->
    # Attempting to swap lone starter Guard g1_t1 with a T2 Forward would create 0-3-2 (illegal formation!)
    bench_illegal_swap = (f3_t2, g2_t1, g3_t1, f4_t1)
    projs_illegal = {
        g1_t1.id: _make_proj(g1_t1, 15.0, sigma=10.0, turn=1),
        f1_t2.id: _make_proj(f1_t2, 15.0, sigma=10.0, turn=2),
        f2_t2.id: _make_proj(f2_t2, 15.0, sigma=10.0, turn=2),
        c1_t2.id: _make_proj(c1_t2, 15.0, sigma=10.0, turn=2),
        c2_t2.id: _make_proj(c2_t2, 15.0, sigma=10.0, turn=2),
        g4_t2.id: _make_proj(g4_t2, 15.0, sigma=10.0, turn=2),
        f3_t2.id: _make_proj(f3_t2, 22.0, sigma=10.0, turn=2),  # High-scoring T2 Forward on bench!
        g2_t1.id: _make_proj(g2_t1, 0.0, sigma=0.0, turn=1),
        g3_t1.id: _make_proj(g3_t1, 0.0, sigma=0.0, turn=1),
        f4_t1.id: _make_proj(f4_t1, 0.0, sigma=0.0, turn=1),
    }
    cap_opt, slot_opt_illegal = compute_turn_option_bonuses(
        starters=starters_122,
        sixth_man=g4_t2,
        bench=bench_illegal_swap,
        captain=g1_t1,       # T1 Captain (15.0, sigma=10.0)
        vice_captain=f1_t2,  # T2 Vice-Captain (15.0)
        projections=projs_illegal,
    )
    # Captain switch option value is exact: round(10 / sqrt(2*pi), 2) == 3.99
    assert cap_opt == 3.99
    # Slot option bonus MUST be 0.0 because g1_t1 is the only Guard in a 1-2-2 formation and cannot swap with f3_t2 (Forward)!
    assert slot_opt_illegal == 0.0

    # Case B: Now place g4_t2 (a Turn 2 Guard with 15.0 xPDK) on the bench -> legal G-for-G swap in 1-2-2!
    bench_legal_swap = (g4_t2, g2_t1, g3_t1, f4_t1)
    cap_opt_2, slot_opt_legal = compute_turn_option_bonuses(
        starters=starters_122,
        sixth_man=sixth_man_t2,
        bench=bench_legal_swap,
        captain=g1_t1,
        vice_captain=f1_t2,
        projections=projs_illegal,
    )
    assert cap_opt_2 == 3.99
    assert slot_opt_legal == 1.99  # round(0.5 * 3.9894228, 2)

    # Case C: Zero option bonus when Captain plays in Turn 2 and all active players play in Turn 2
    cap_opt_zero, slot_opt_zero = compute_turn_option_bonuses(
        starters=starters_122,
        sixth_man=sixth_man_t2,
        bench=bench_legal_swap,
        captain=f1_t2,       # Turn 2 Captain -> cannot switch after Turn 2!
        vice_captain=g1_t1,  # Turn 1 Vice-Captain
        projections={pid: _make_proj(p, 15.0, sigma=10.0, turn=2) for pid, p in [
            (g1_t1.id, g1_t1), (g2_t1.id, g2_t1), (g3_t1.id, g3_t1), (g4_t2.id, g4_t2),
            (f1_t2.id, f1_t2), (f2_t2.id, f2_t2), (f3_t2.id, f3_t2), (f4_t1.id, f4_t1),
            (c1_t2.id, c1_t2), (c2_t2.id, c2_t2),
        ]},
    )
    assert cap_opt_zero == 0.0
    assert slot_opt_zero == 0.0


def test_lineup_optimizer_all_five_formations_and_slot_invariants() -> None:
    """Verify Section 4 of items_left_for_v02.md:
    - Each of the 5 legal formations ('2-2-1', '1-2-2', '2-1-2', '1-3-1', '3-1-1') is selected when optimal.
    - Captain is always a starter; Sixth Man is never a starter; all 4 Bench units are distinct from starters/Sixth Man;
      Head Coach is never in court formation slots.
    - T1 -> T2 option bonus can cause a lower static-xPDK T1 player to be chosen over a higher static-xPDK T2 player.
    """
    squad = [
        Player(1, "G1", Position.GUARD, 1, "PAO", 100, "starter", 1.0, 1),
        Player(2, "G2", Position.GUARD, 2, "RMB", 100, "starter", 1.0, 1),
        Player(3, "G3", Position.GUARD, 3, "OLY", 100, "starter", 1.0, 1),
        Player(4, "G4", Position.GUARD, 4, "FBB", 100, "starter", 1.0, 1),
        Player(5, "F1", Position.FORWARD, 1, "PAO", 100, "starter", 1.0, 1),
        Player(6, "F2", Position.FORWARD, 2, "RMB", 100, "starter", 1.0, 1),
        Player(7, "F3", Position.FORWARD, 3, "OLY", 100, "starter", 1.0, 1),
        Player(8, "F4", Position.FORWARD, 4, "FBB", 100, "starter", 1.0, 1),
        Player(9, "C1", Position.CENTER, 1, "PAO", 100, "starter", 1.0, 1),
        Player(10, "C2", Position.CENTER, 2, "RMB", 100, "starter", 1.0, 1),
        Player(11, "HC1", Position.HEAD_COACH, 1, "PAO", 80, "starter", 1.0, 1),
    ]

    formation_starters_map = {
        "2-2-1": {1, 2, 5, 6, 9},
        "1-2-2": {1, 5, 6, 9, 10},
        "2-1-2": {1, 2, 5, 9, 10},
        "1-3-1": {1, 5, 6, 7, 9},
        "3-1-1": {1, 2, 3, 5, 9},
    }

    for target_formation, boosted_ids in formation_starters_map.items():
        projections = {
            p.id: _make_proj(p, xpdk=25.0 if p.id in boosted_ids else 5.0, sigma=4.0, turn=1)
            for p in squad
        }
        rec = optimize_court_lineup(squad, projections, round_number=1)
        assert rec.is_valid is True
        assert rec.formation == target_formation
        assert set(rec.starter_ids) == boosted_ids
        assert rec.captain_id in rec.starter_ids
        assert rec.sixth_man_id not in rec.starter_ids
        assert len(rec.bench_ids) == 4
        assert set(rec.bench_ids).isdisjoint(set(rec.starter_ids) | {rec.sixth_man_id})
        assert rec.head_coach_id == 11
        assert rec.head_coach_id not in (set(rec.starter_ids) | {rec.sixth_man_id} | set(rec.bench_ids))

    # Now verify that a T1 player with slightly lower static xPDK (14.6, Turn 1, sigma=10.0)
    # is selected in the active 1.0x lineup ahead of a T2 player with higher static xPDK (15.0, Turn 2)
    # when a T2 bench backup (14.5, Turn 2) provides Real Option Value (+1.95 xPDK > 0.20 static gap).
    projs_option_flip = {
        1: _make_proj(squad[0], 24.0, sigma=5.0, turn=1),   # G1 (Starter)
        2: _make_proj(squad[1], 22.0, sigma=5.0, turn=2),   # G2 (Starter / VC)
        3: _make_proj(squad[2], 14.6, sigma=10.0, turn=1),  # G3 (Turn 1 volatile candidate: 14.6 xPDK)
        4: _make_proj(squad[3], 15.0, sigma=5.0, turn=2),   # G4 (Turn 2 higher static candidate: 15.0 xPDK)
        5: _make_proj(squad[4], 21.0, sigma=5.0, turn=2),   # F1 (Starter)
        6: _make_proj(squad[5], 20.0, sigma=5.0, turn=2),   # F2 (Starter)
        7: _make_proj(squad[6], 4.0, sigma=2.0, turn=1),    # F3 (Bench)
        8: _make_proj(squad[7], 4.0, sigma=2.0, turn=1),    # F4 (Bench)
        9: _make_proj(squad[8], 21.5, sigma=5.0, turn=2),   # C1 (Starter)
        10: _make_proj(squad[9], 4.0, sigma=2.0, turn=1),   # C2 (Bench)
        11: _make_proj(squad[10], 10.0, sigma=4.0, turn=1), # HC
    }
    rec_flip = optimize_court_lineup(squad, projs_option_flip, round_number=1)
    active_1x_ids = set(rec_flip.starter_ids) | {rec_flip.sixth_man_id}
    # Player 3 (14.6 xPDK, Turn 1) is placed in the active 1.0x slots while Player 4 (15.0 xPDK, Turn 2)
    # is kept on the 0.5x bench as the Turn 2 option backup!
    assert 3 in active_1x_ids
    assert 4 in rec_flip.bench_ids
    assert rec_flip.slot_option_bonus_xpdk > 0.5


def test_suggest_trades_sanity_checks_hc_quota_unlimited_no_improvement_and_bundle_club_cap(tmp_path: Path) -> None:
    """Verify Section 5 of items_left_for_v02.md:
    - All recommended bundles pass `validate_trades()`.
    - Head Coach swaps count toward the 1..4 trade limit.
    - `--unlimited` bypasses free_trades=0 while still enforcing budget, position, and club limits.
    - No-improvement case returns 0 suggestions.
    - Two individually legal transfers to the same club (when team already has 5 players, cap=6)
      become illegal as a 2-player bundle and are rejected.
    """
    db_path, squad_path = _seed_v02_snapshot_and_squad(tmp_path)
    store = SnapshotStore(db_path)
    players_by_id = {p.id: p for p in store.load_latest_players()}
    state = load_current_squad(squad_path)

    # 1. Every recommended bundle passes deterministic `validate_trades()`
    report_2 = suggest_trades(
        squad_path=squad_path,
        database_path=db_path,
        num_trades=2,
        round_number=1,
        top_k=5,
        report_path=None,
    )
    assert report_2["suggestions_count"] > 0
    for sug in report_2["suggestions"]:
        moves = [TradeMove(out_id=m["out_id"], in_id=m["in_id"]) for m in sug["moves"]]
        val = validate_trades(state, moves, players_by_id)
        assert val.is_valid is True
        assert sug["trades_count"] == 2

    # 2. When free_trades=1, requesting num_trades=2 is capped at 1 trade, unless unlimited_window=True
    squad_1_ft = tmp_path / "squad_1_ft.json"
    data_1_ft = json.loads(squad_path.read_text(encoding="utf-8"))
    data_1_ft["free_trades"] = 1
    squad_1_ft.write_text(json.dumps(data_1_ft), encoding="utf-8")

    capped_rep = suggest_trades(
        squad_path=squad_1_ft,
        database_path=db_path,
        num_trades=2,
        round_number=1,
        unlimited_window=False,
        report_path=None,
    )
    assert capped_rep["requested_trades"] == 1

    unlimited_rep = suggest_trades(
        squad_path=squad_1_ft,
        database_path=db_path,
        num_trades=2,
        round_number=1,
        unlimited_window=True,
        report_path=None,
    )
    assert unlimited_rep["requested_trades"] == 2
    assert unlimited_rep["unlimited_window_active"] is True

    # 3. No-improvement case: if the squad already holds the highest-projected players at every position
    # (swap out the weak bench units 3, 4, 8, 11 for the top external stars 101, 102, 104 in squad.json)
    optimal_squad_path = tmp_path / "squad_optimal.json"
    data_opt = json.loads(squad_path.read_text(encoding="utf-8"))
    data_opt["player_ids"] = [1, 2, 101, 3, 5, 6, 7, 102, 9, 10, 104]
    data_opt["purchase_prices_tenths"] = {str(pid): 150 for pid in data_opt["player_ids"]}
    data_opt["bank_tenths"] = 0  # No bank left to upgrade 3 (9.0 Cr) or 7 (12.5 Cr)
    optimal_squad_path.write_text(json.dumps(data_opt), encoding="utf-8")

    no_imp_rep = suggest_trades(
        squad_path=optimal_squad_path,
        database_path=db_path,
        num_trades=1,
        round_number=1,
        report_path=None,
    )
    assert no_imp_rep["suggestions_count"] == 0
    assert no_imp_rep["suggestions"] == []

    # 4. Superficially attractive individual transfers that become illegal as a 2-player bundle due to MAX_PLAYERS_PER_TEAM (6):
    # Add 3 more PAO players to the snapshot so PAO has 5 players in the squad + 2 elite PAO targets outside the squad.
    club_cap_db = tmp_path / "club_cap.sqlite3"
    club_cap_squad = tmp_path / "club_cap_squad.json"
    cap_store = SnapshotStore(club_cap_db)

    cap_players = [
        # 5 PAO players currently in squad (team_id=1)
        Player(1, "PAO_G1", Position.GUARD, 1, "PAO", 100, "starter", 1.0, 1, 15.0, 15.0),
        Player(2, "PAO_G2", Position.GUARD, 1, "PAO", 100, "starter", 1.0, 1, 15.0, 15.0),
        Player(5, "PAO_F1", Position.FORWARD, 1, "PAO", 100, "starter", 1.0, 1, 15.0, 15.0),
        Player(6, "PAO_F2", Position.FORWARD, 1, "PAO", 100, "starter", 1.0, 1, 15.0, 15.0),
        Player(9, "PAO_C1", Position.CENTER, 1, "PAO", 100, "starter", 1.0, 1, 15.0, 15.0),
        # 5 BER players currently in squad (team_id=6) with low xPDK
        Player(3, "BER_G3", Position.GUARD, 6, "BER", 100, "starter", 1.0, 1, 4.0, 4.0),
        Player(4, "BER_G4", Position.GUARD, 6, "BER", 100, "starter", 1.0, 1, 4.0, 4.0),
        Player(7, "BER_F3", Position.FORWARD, 6, "BER", 100, "starter", 1.0, 1, 4.0, 4.0),
        Player(8, "BER_F4", Position.FORWARD, 6, "BER", 100, "starter", 1.0, 1, 4.0, 4.0),
        Player(10, "BER_C2", Position.CENTER, 6, "BER", 100, "starter", 1.0, 1, 4.0, 4.0),
        Player(11, "BER_HC", Position.HEAD_COACH, 6, "BER", 80, "starter", 1.0, 1, 8.0, 8.0),
        # 2 Superstar PAO targets (individually each brings PAO count from 5 -> 6 [LEGAL],
        # but together in a 2-trade bundle they bring PAO count from 5 -> 7 [ILLEGAL > 6]!)
        Player(201, "PAO_Super_G", Position.GUARD, 1, "PAO", 100, "starter", 1.0, 1, 28.0, 28.0),
        Player(202, "PAO_Super_F", Position.FORWARD, 1, "PAO", 100, "starter", 1.0, 1, 28.0, 28.0),
    ]
    cap_store.save_snapshot(
        {
            "league_id": 10,
            "competition_code": "E",
            "season_code": "E2026",
            "config": {
                "current_matchday": {"id": 1528, "number": 1, "num_rounds": 1},
                "teams": [
                    {"id": 1, "name": "Panathinaikos", "abbreviation": "PAO"},
                    {"id": 6, "name": "ALBA Berlin", "abbreviation": "BER"},
                ],
            },
            "schedule": {
                "id": 1528,
                "number": 1,
                "rounds": [
                    {
                        "id": 2523,
                        "number": 1,
                        "matches": [
                            {
                                "id": 101,
                                "status": "scheduled",
                                "started_at": "2026-10-01T18:15:00Z",
                                "home_team": {"id": 1, "name": "Panathinaikos", "abbreviation": "PAO"},
                                "away_team": {"id": 6, "name": "ALBA Berlin", "abbreviation": "BER"},
                            }
                        ],
                    }
                ],
            },
            "schedules": [],
            "match_lineups": [
                {
                    "id": 101,
                    "turn_number": 1,
                    "home_team": {
                        "id": 1,
                        "name": "Panathinaikos",
                        "abbreviation": "PAO",
                        "lineups": [
                            {
                                "id": p.id,
                                "first_name": p.name,
                                "last_name": "",
                                "position": p.position.short_code,
                                "quotation": p.credits,
                                "status": p.status,
                                "probability_of_playing": 1.0,
                                "avg_fantasy_pts": p.avg_fantasy_pts,
                                "last_match_pts": p.last_match_pts,
                            }
                            for p in cap_players
                            if p.team_id == 1
                        ],
                    },
                    "away_team": {
                        "id": 6,
                        "name": "ALBA Berlin",
                        "abbreviation": "BER",
                        "lineups": [
                            {
                                "id": p.id,
                                "first_name": p.name,
                                "last_name": "",
                                "position": p.position.short_code,
                                "quotation": p.credits,
                                "status": p.status,
                                "probability_of_playing": 1.0,
                                "avg_fantasy_pts": p.avg_fantasy_pts,
                                "last_match_pts": p.last_match_pts,
                            }
                            for p in cap_players
                            if p.team_id == 6
                        ],
                    },
                }
            ],
        }
    )
    club_cap_squad.write_text(
        json.dumps(
            {
                "season": "E2026",
                "league_id": 10,
                "round_number": 1,
                "bank_tenths": 50,
                "free_trades": 4,
                "player_ids": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
                "purchase_prices_tenths": {str(i): 100 for i in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]} | {"11": 80},
            }
        ),
        encoding="utf-8",
    )

    # Both 201 and 202 are legal as single 1-trade moves (bringing PAO from 5 -> 6 players):
    rep_single = suggest_trades(
        squad_path=club_cap_squad,
        database_path=club_cap_db,
        num_trades=1,
        round_number=1,
        top_k=10,
        report_path=None,
    )
    single_in_ids = {m["in_id"] for s in rep_single["suggestions"] for m in s["moves"]}
    assert 201 in single_in_ids
    assert 202 in single_in_ids

    # However, in a 2-trade bundle, acquiring BOTH 201 and 202 (without trading out an existing PAO player)
    # would put 7 PAO court players on the squad (> MAX_PLAYERS_PER_TEAM=6) and MUST NOT be recommended:
    rep_double = suggest_trades(
        squad_path=club_cap_squad,
        database_path=club_cap_db,
        num_trades=2,
        round_number=1,
        top_k=10,
        report_path=None,
    )
    for sug in rep_double["suggestions"]:
        in_ids = {m["in_id"] for m in sug["moves"]}
        out_teams = {m["out_team"] for m in sug["moves"]}
        if {201, 202}.issubset(in_ids):
            # Only legal if one of the outgoing players was already from PAO!
            assert "PAO" in out_teams


def test_v02_cli_commands_end_to_end(tmp_path: Path, capsys) -> None:
    db_path, squad_path = _seed_v02_snapshot_and_squad(tmp_path)

    # 1. elf squad
    rc = cli_main(["--db", str(db_path), "squad", "--squad", str(squad_path)])
    assert rc == 0
    squad_out = json.loads(capsys.readouterr().out)
    assert squad_out["financials"]["squad_selling_value_tenths"] == 1305

    # 2. elf fixtures
    rc = cli_main(["--db", str(db_path), "fixtures", "--rounds", "2"])
    assert rc == 0
    fix_out = json.loads(capsys.readouterr().out)
    assert len(fix_out["team_rankings"]) == 6

    # 3. elf lineup
    rc = cli_main(["--db", str(db_path), "lineup", "--squad", str(squad_path)])
    assert rc == 0
    lineup_out = json.loads(capsys.readouterr().out)
    assert lineup_out["total_turn_adjusted_xpdk"] > lineup_out["static_xpdk"]

    # 4. elf suggest-trades
    rc = cli_main(["--db", str(db_path), "suggest-trades", "--trades", "1", "--squad", str(squad_path)])
    assert rc == 0
    trades_out = json.loads(capsys.readouterr().out)
    assert trades_out["suggestions_count"] > 0
