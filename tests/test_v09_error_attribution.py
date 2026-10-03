"""Unit tests for V0.9 Workstream 4: Error Attribution & Multi-Model Benchmark Ledger."""

from __future__ import annotations

from pathlib import Path
import pytest

from euroleague_fantasy_manager.evaluation.dataset import build_historical_dataset
from euroleague_fantasy_manager.evaluation.error_attribution import (
    BenchmarkModelEntry,
    MultiModelBenchmarkLedger,
    ThreeWayErrorDecomposition,
    decompose_round_error,
    run_multi_model_benchmark,
)


def test_w4_three_way_error_decomposition_invariant() -> None:
    """Verify that Total Error strictly equals Model Error + Execution Regret + Aleatoric Noise."""
    # Scenario 1: Standard round with human regret
    decomp1 = decompose_round_error(
        predicted_score=165.5,
        actual_score=142.0,
        execution_regret=8.5,
        post_hoc_expected=158.0,
        model_name="learned_v09",
        season="E2025",
        round_number=4,
    )
    assert decomp1.total_error == 23.50
    assert decomp1.execution_regret == 8.50
    assert decomp1.model_error == 7.50
    assert decomp1.aleatoric_noise == 7.50
    # Invariant
    assert round(decomp1.model_error + decomp1.execution_regret + decomp1.aleatoric_noise, 2) == decomp1.total_error

    # Scenario 2: Zero regret (optimal managerial execution)
    decomp2 = decompose_round_error(
        predicted_score=150.0,
        actual_score=155.0,
        execution_regret=0.0,
        post_hoc_expected=152.0,
    )
    assert decomp2.total_error == 5.0
    assert decomp2.execution_regret == 0.0
    assert decomp2.model_error == 2.0
    assert decomp2.aleatoric_noise == 3.0
    assert round(decomp2.model_error + decomp2.execution_regret + decomp2.aleatoric_noise, 2) == decomp2.total_error

    # Scenario 3: Dict serialization
    d = decomp1.to_dict()
    assert d["model_name"] == "learned_v09"
    assert d["season"] == "E2025"
    assert d["round_number"] == 4


def test_w4_error_decomposition_edge_cases() -> None:
    """Verify algebraic exactness and stability under zero FP, missing actuals, and DNP."""
    # Case 1: Zero actual FP (e.g. DNP or bad game)
    d_zero_act = decompose_round_error(predicted_score=15.0, actual_score=0.0, execution_regret=2.0)
    assert d_zero_act.total_error == 15.0
    assert round(d_zero_act.model_error + d_zero_act.execution_regret + d_zero_act.aleatoric_noise, 2) == 15.0

    # Case 2: Zero predicted FP
    d_zero_pred = decompose_round_error(predicted_score=0.0, actual_score=12.4, execution_regret=0.0)
    assert d_zero_pred.total_error == 12.4
    assert round(d_zero_pred.model_error + d_zero_pred.execution_regret + d_zero_pred.aleatoric_noise, 2) == 12.4

    # Case 3: Missing actual score (None)
    d_none = decompose_round_error(predicted_score=20.0, actual_score=None)
    assert d_none.actual_score == 0.0
    assert d_none.total_error == 20.0
    assert d_none.provenance["missing_actual"] is True
    assert round(d_none.model_error + d_none.execution_regret + d_none.aleatoric_noise, 2) == 20.0

    # Case 4: Unplayed player (is_dnp=True)
    d_dnp = decompose_round_error(predicted_score=18.5, actual_score=10.0, is_dnp=True)
    assert d_dnp.actual_score == 0.0
    assert d_dnp.provenance["is_dnp"] is True
    assert round(d_dnp.model_error + d_dnp.execution_regret + d_dnp.aleatoric_noise, 2) == d_dnp.total_error

    # Case 5: Unavailable player (is_unavailable=True)
    d_unavail = decompose_round_error(predicted_score=5.0, actual_score=15.0, is_unavailable=True)
    assert d_unavail.actual_score == 0.0
    assert d_unavail.provenance["is_unavailable"] is True
    assert round(d_unavail.model_error + d_unavail.execution_regret + d_unavail.aleatoric_noise, 2) == d_unavail.total_error


def test_w4_multi_model_benchmark_ledger_formatting() -> None:
    """Verify MultiModelBenchmarkLedger markdown rendering and dictionary serialization."""
    entries = [
        BenchmarkModelEntry(
            model_name="season_mean",
            model_version="0.2.5",
            mae=6.85,
            rmse=8.95,
            bias=0.15,
            spearman=0.450,
            top10_recall=0.42,
            value_spearman=0.380,
            brier_score=0.120,
            avg_lineup_score=142.50,
            lineup_regret=18.50,
        ),
        BenchmarkModelEntry(
            model_name="fp_context_v08",
            model_version="0.8.0",
            mae=5.42,
            rmse=7.20,
            bias=-0.05,
            spearman=0.610,
            top10_recall=0.68,
            value_spearman=0.550,
            brier_score=0.078,
            avg_lineup_score=162.20,
            lineup_regret=7.40,
        ),
        BenchmarkModelEntry(
            model_name="learned_v09",
            model_version="0.9.0",
            mae=5.18,
            rmse=6.85,
            bias=0.02,
            spearman=0.645,
            top10_recall=0.72,
            value_spearman=0.585,
            brier_score=0.065,
            avg_lineup_score=166.80,
            lineup_regret=5.20,
        ),
    ]

    ledger = MultiModelBenchmarkLedger(
        season="2025",
        rounds_evaluated="1:4",
        entries=tuple(entries),
        best_mae_model="learned_v09",
        best_spearman_model="learned_v09",
        best_lineup_model="learned_v09",
    )

    md = ledger.to_markdown()
    assert "# Multi-Model Benchmark Ledger — Season 2025" in md
    assert "`learned_v09`" in md
    assert "`fp_context_v08`" in md
    assert "`season_mean`" in md
    assert "Lineup Pts" in md

    d = ledger.to_dict()
    assert d["season"] == "2025"
    assert d["best_mae_model"] == "learned_v09"
    assert len(d["models"]) == 3


def test_w4_run_multi_model_benchmark_integration(tmp_path: Path) -> None:
    """Verify run_multi_model_benchmark executes walk-forward across models and outputs ledger."""
    db_path = tmp_path / "benchmark.sqlite3"
    reports_dir = tmp_path / "benchmark_reports"

    build_historical_dataset(database_path=db_path, seasons=["2025"], rounds_per_season=3)

    models = ("season_mean", "last5", "fp_context_v08", "learned_v09")
    ledger = run_multi_model_benchmark(
        season="2025",
        rounds="1:3",
        models=models,
        database_path=db_path,
        reports_dir=reports_dir,
    )

    assert len(ledger.entries) == 4
    assert ledger.best_mae_model in models
    assert ledger.best_spearman_model in models
    assert (reports_dir / "2025_multi_model_benchmark_ledger.md").exists()
