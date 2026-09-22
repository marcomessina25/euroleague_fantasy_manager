"""Hermetic V0.2 unit and integration tests for EuroLeague Fantasy decision support."""

import json
from pathlib import Path

from euroleague_fantasy_manager.cli import main as cli_main
from euroleague_fantasy_manager.expected_points import (
    expected_coach_pdk,
    project_all_players,
)
from euroleague_fantasy_manager.fixtures import (
    analyze_squad_fixtures,
    analyze_team_fixtures,
    compute_team_strengths,
)
from euroleague_fantasy_manager.lineup import optimize_court_lineup
from euroleague_fantasy_manager.models import Player, Position
from euroleague_fantasy_manager.squad_report import generate_squad_report
from euroleague_fantasy_manager.storage import SnapshotStore
from euroleague_fantasy_manager.suggest_transfers import suggest_trades


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
    # Total purchase cost = 1280 tenths (128.0 Cr); current quotation = 1305 tenths (130.5 Cr)
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


def test_lineup_optimizer_turn_1_to_turn_2_real_option_value(tmp_path: Path) -> None:
    db_path, squad_path = _seed_v02_snapshot_and_squad(tmp_path)
    store = SnapshotStore(db_path)
    players_by_id = {p.id: p for p in store.load_latest_players()}
    squad_ids = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    squad_players = [players_by_id[pid] for pid in squad_ids]

    projections = project_all_players(database_path=db_path, round_number=1)
    rec = optimize_court_lineup(squad_players, projections, round_number=1)

    assert rec.is_valid is True
    assert len(rec.starter_ids) == 5
    assert len(rec.bench_ids) == 4
    assert rec.formation in ("2-2-1", "1-2-2", "2-1-2", "1-3-1", "3-1-1")

    # Because we have Turn 1 starters (PAO/RMB) AND Turn 2 backups/vice-captain (OLY/FBB),
    # the Turn 1 -> Turn 2 Real Option Value bonus MUST be strictly positive.
    assert (rec.captain_option_bonus_xpdk + rec.slot_option_bonus_xpdk) > 0.0
    assert rec.total_turn_adjusted_xpdk > rec.static_xpdk


def test_suggest_trades_one_and_two_moves_legality(tmp_path: Path) -> None:
    db_path, squad_path = _seed_v02_snapshot_and_squad(tmp_path)
    report = suggest_trades(
        squad_path=squad_path,
        database_path=db_path,
        num_trades=2,
        round_number=1,
        top_k=5,
        report_path=None,
    )

    assert report["suggestions_count"] > 0
    best = report["suggestions"][0]
    assert best["is_valid"] is True
    assert best["net_xpdk_gain"] > 0.0
    assert best["bank_after_tenths"] >= 0


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
