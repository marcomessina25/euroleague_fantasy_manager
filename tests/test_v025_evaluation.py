"""Hermetic V0.2.5 unit, point-in-time leakage, and walk-forward evaluation tests."""

import json
from pathlib import Path
import pytest

from euroleague_fantasy_manager import __version__
from euroleague_fantasy_manager.cli import main as cli_main
from euroleague_fantasy_manager.evaluation import (
    EvaluationDatasetStore,
    build_features,
    build_historical_dataset,
    build_round_feature_table,
    compute_point_and_ranking_metrics,
    inspect_historical_round,
    normalize_availability_status,
    predict_round_baselines,
    reconstruct_coach_fantasy_points,
    reconstruct_pir,
    reconstruct_player_fantasy_points,
    run_walk_forward_evaluation,
)


def test_multi_season_dataset_and_duplicate_detection(tmp_path: Path) -> None:
    """Verify Section 3 & 4: >= 3 historical seasons, stable IDs, and duplicate detection."""
    db_path = tmp_path / "eval_ds.sqlite3"
    summary = build_historical_dataset(
        database_path=db_path,
        seasons=("2022", "2023", "2024", "2025"),
        rounds_per_season=6,
    )
    assert summary.seasons == ("E2022", "E2023", "E2024", "E2025")
    assert summary.total_players == 24
    assert summary.total_coaches == 6
    assert summary.total_games == 4 * 6 * 3  # 4 seasons * 6 rounds * 3 games/round

    store = EvaluationDatasetStore(db_path)
    assert store.list_seasons() == ["E2022", "E2023", "E2024", "E2025"]

    # Verify duplicate detection raises ValueError on duplicate game_id or duplicate player_game
    with pytest.raises(ValueError, match="Duplicate game detected"):
        store.insert_game(
            {
                "season": "E2025",
                "round": 1,
                "game_id": 20250011,
                "game_date": "2025-10-03T16:00:00Z",
                "home_team_id": 1,
                "away_team_id": 6,
                "home_score": 85,
                "away_score": 75,
            },
            strict_duplicates=True,
        )

    with pytest.raises(ValueError, match="Duplicate player_game detected"):
        store.insert_player_game(
            {
                "season": "E2025",
                "round": 1,
                "game_id": 20250011,
                "game_date": "2025-10-03T16:00:00Z",
                "player_id": 1001,
                "position": "G",
                "team_id": 1,
                "opponent_team_id": 6,
                "minutes": 25.0,
                "pir": 18.0,
                "fantasy_points": 19.8,
            },
            strict_duplicates=True,
        )

    dup_counts = store.detect_duplicates(
        games=[{"season": "E2025", "game_id": 10}, {"season": "2025", "game_id": 10}],
        player_games=[
            {"season": "E2025", "game_id": 10, "player_id": 1001},
            {"season": "2025", "game_id": 10, "player_id": 1001},
        ],
    )
    assert dup_counts["duplicate_games"] == 1
    assert dup_counts["duplicate_player_games"] == 1


def test_target_reconstruction_and_availability_categories() -> None:
    """Verify Section 7 & 9: PIR, 10% win bonus, separate Head Coach brackets, and DNP/out statuses."""
    # PIR = (20 + 5 + 4 + 2 + 1 + 5) - ((14 - 8) + (6 - 5) + 2 + 3) = 37 - (6 + 1 + 2 + 3) = 25.0
    pir = reconstruct_pir(
        points=20,
        rebounds=5,
        assists=4,
        steals=2,
        blocks=1,
        turnovers=2,
        fouls=3,
        fouls_drawn=5,
        fg_attempted=14,
        fg_made=8,
        ft_attempted=6,
        ft_made=5,
    )
    assert pir == 25.0

    # Win bonus (1.10x) vs Loss (1.00x) vs DNP/out (0.0)
    assert reconstruct_player_fantasy_points(pir=25.0, team_won=True, player_status="available", minutes=28.0) == 27.5
    assert reconstruct_player_fantasy_points(pir=25.0, team_won=False, player_status="available", minutes=28.0) == 25.0
    assert reconstruct_player_fantasy_points(pir=25.0, team_won=True, player_status="DNP", minutes=0.0) == 0.0
    assert reconstruct_player_fantasy_points(pir=25.0, team_won=True, player_status="out", minutes=0.0) == 0.0

    # Separate Head Coach brackets (+25/+20/+10/-5/-10/-20)
    assert reconstruct_coach_fantasy_points(25) == 25.0
    assert reconstruct_coach_fantasy_points(15) == 20.0
    assert reconstruct_coach_fantasy_points(4) == 10.0
    assert reconstruct_coach_fantasy_points(-4) == -5.0
    assert reconstruct_coach_fantasy_points(-14) == -10.0
    assert reconstruct_coach_fantasy_points(-24) == -20.0

    # Availability normalization
    assert normalize_availability_status("starter", 25.0) == "available"
    assert normalize_availability_status("doubtful", 15.0) == "questionable"
    assert normalize_availability_status("injured", 0.0) == "out"
    assert normalize_availability_status("bench_dnp", 0.0) == "DNP"


def test_point_in_time_leakage_invariants_and_cold_start_hierarchy(tmp_path: Path) -> None:
    """Verify Section 11.2 & Section 15:
    - Cold-start fallback hierarchy (`position_team_prior`, `previous_season`, `current_season`).
    - Future-stat leakage test: injecting +999.0 fantasy points in Round R or Round R+1 does NOT alter Round R features/predictions.
    - Future-price leakage test: changing Round R+1 pre-round quotation to 999 does NOT alter Round R predictions.
    - Future-status leakage test: setting Round R+1 status to 'out' does NOT alter Round R predictions.
    - Round-boundary test: Round R's own completed game is strictly excluded at Round R's decision_cutoff.
    """
    db_path = tmp_path / "leakage.sqlite3"
    build_historical_dataset(
        database_path=db_path,
        seasons=("2022", "2023", "2024", "2025"),
        rounds_per_season=6,
    )
    store = EvaluationDatasetStore(db_path)

    # 1. Cold-start hierarchy verification
    cutoff_2022_r1 = store.get_round_decision_cutoff("E2022", 1)
    f_2022_r1 = build_features(1001, cutoff_2022_r1, database_path=db_path, season="E2022", round_number=1)
    assert f_2022_r1.cold_start_source == "position_team_prior"
    assert f_2022_r1.games_played == 0

    cutoff_2025_r1 = store.get_round_decision_cutoff("E2025", 1)
    f_2025_r1 = build_features(1001, cutoff_2025_r1, database_path=db_path, season="E2025", round_number=1)
    assert f_2025_r1.cold_start_source == "previous_season"
    assert f_2025_r1.games_played == 0

    cutoff_2025_r4 = store.get_round_decision_cutoff("E2025", 4)
    f_before = build_features(1001, cutoff_2025_r4, database_path=db_path, season="E2025", round_number=4)
    assert f_before.cold_start_source == "current_season"
    assert f_before.games_played <= 3  # Strictly Rounds 1..3 only!

    ft_before = build_round_feature_table("E2025", 4, database_path=db_path, decision_cutoff=cutoff_2025_r4)
    preds_before = predict_round_baselines(
        ft_before,
        actual_points_by_player={pid: 0.0 for pid in ft_before},
        models=("season_mean", "last5", "ewma", "xpdk_v02"),
    )

    # 2. Mutate Round 4 (at game time >= decision_cutoff) AND Round 5..6 with extreme stats (+999.0),
    # extreme future price (999 tenths = 99.9 Cr), and future status ('out'):
    with store._connect() as conn:
        conn.execute(
            """
            UPDATE eval_player_games
            SET pir = 999.0, fantasy_points = 999.0, points = 999
            WHERE season = 'E2025' AND round >= 4 AND player_id = 1001
            """
        )
        conn.execute(
            """
            UPDATE eval_player_games
            SET pre_round_quotation_tenths = 999, pre_round_status = 'out'
            WHERE season = 'E2025' AND round >= 5 AND player_id = 1001
            """
        )

    # Re-run feature generation and predictions at `cutoff_2025_r4`:
    f_after = build_features(1001, cutoff_2025_r4, database_path=db_path, season="E2025", round_number=4)
    assert f_after == f_before

    ft_after = build_round_feature_table("E2025", 4, database_path=db_path, decision_cutoff=cutoff_2025_r4)
    preds_after = predict_round_baselines(
        ft_after,
        actual_points_by_player={pid: 0.0 for pid in ft_after},
        models=("season_mean", "last5", "ewma", "xpdk_v02"),
    )
    for m_name in ("season_mean", "last5", "ewma", "xpdk_v02"):
        p_before = next(r.prediction for r in preds_before[m_name] if r.player_id == 1001)
        p_after = next(r.prediction for r in preds_after[m_name] if r.player_id == 1001)
        assert p_before == p_after


def test_walk_forward_evaluation_metrics_provenance_and_cli(tmp_path: Path, capsys) -> None:
    """Verify Section 12, 13, 14, 16 & 18: walk-forward evaluation, lineup regret, artifacts, and CLI."""
    db_path = tmp_path / "walk_forward.sqlite3"
    reports_dir = tmp_path / "reports" / "evaluation"

    # 1. CLI: elf evaluation build-dataset
    rc = cli_main(
        [
            "--db",
            str(db_path),
            "evaluation",
            "build-dataset",
            "--seasons",
            "2022",
            "2023",
            "2024",
            "2025",
            "--rounds-per-season",
            "6",
        ]
    )
    assert rc == 0
    build_out = json.loads(capsys.readouterr().out)
    assert build_out["seasons"] == ["E2022", "E2023", "E2024", "E2025"]

    # 2. CLI: elf evaluation inspect --season 2025 --round 4
    rc = cli_main(["--db", str(db_path), "evaluation", "inspect", "--season", "2025", "--round", "4"])
    assert rc == 0
    inspect_out = json.loads(capsys.readouterr().out)
    assert inspect_out["season"] == "E2025"
    assert inspect_out["round"] == 4
    assert inspect_out["player_count"] == 30

    # 3. Walk-forward evaluation & artifact generation
    eval_res = run_walk_forward_evaluation(
        season="2025",
        rounds="1:6",
        models=("season_mean", "last5", "ewma", "xpdk_v02"),
        database_path=db_path,
        reports_dir=reports_dir,
    )
    assert __version__ == "0.2.5"
    assert len(eval_res["models"]) == 4
    assert eval_res["models"][0]["active_player_samples"] > 0
    assert "E2025" in eval_res["price_coverage_by_season"]
    assert len(eval_res["lineup_simulation"]) == 4
    assert "MODEL" in eval_res["console_table"]
    assert "Fantasy lineup simulation" in eval_res["console_table"]

    # Verify Markdown and CSV reports were created
    assert Path(eval_res["artifacts"]["markdown_report"]).exists()
    assert Path(eval_res["artifacts"]["round_by_round_csv"]).exists()
    assert Path(eval_res["artifacts"]["player_predictions_csv"]).exists()

    # 4. CLI: elf evaluate --season 2025 --rounds 1:6 --models season_mean,last5,ewma,xpdk_v02
    rc = cli_main(
        [
            "--db",
            str(db_path),
            "evaluate",
            "--season",
            "2025",
            "--rounds",
            "1:6",
            "--models",
            "season_mean,last5,ewma,xpdk_v02",
        ]
    )
    assert rc == 0
    table_out = capsys.readouterr().out
    assert "xpdk_v02" in table_out
    assert "season_mean" in table_out
