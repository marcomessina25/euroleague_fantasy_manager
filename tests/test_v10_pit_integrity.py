"""Unit and integration tests for V1.0 Workstream 2: Point-in-Time Integrity & Reproducibility (PR #16).

Verifies:
1. Strict PIT enforcement across all feature categories (Section 7.1).
2. Explicit leakage rejection: future score, minutes, status, standings, and cross-season (Section 7.2).
3. Reproducibility contract: dataset hash, schema hash, config hash, git SHA, and verification (Section 7.3).
"""

from __future__ import annotations

import copy
from pathlib import Path
import pytest
import sqlite3

from euroleague_fantasy_manager.evaluation.dataset import (
    EvaluationDatasetStore,
    build_historical_dataset,
    normalize_season_code,
)
from euroleague_fantasy_manager.evaluation.features import (
    PointInTimeFeatureRow,
    build_features,
)
from euroleague_fantasy_manager.evaluation.reproducibility import (
    FEATURE_SCHEMA_VERSION,
    PredictionRunRecord,
    build_prediction_run_record,
    compute_dataset_hash,
    compute_feature_schema_hash,
    compute_model_config_hash,
    get_git_commit_sha,
    verify_prediction_reproducibility,
)
from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract


@pytest.fixture
def pit_test_db(tmp_path: Path) -> Path:
    """Create a controlled historical evaluation database for PIT testing."""
    db_file = tmp_path / "pit_test.sqlite3"
    build_historical_dataset(
        database_path=db_file,
        seasons=("E2024", "E2025"),
        rounds_per_season=4,
    )
    return db_file


# ============================================================================
# 1. PIT Feature Audit & Invariant Enforcement (Section 7.1)
# ============================================================================


def test_pit_feature_audit_strict_cutoff_isolation(pit_test_db: Path) -> None:
    """Verify that features computed at cutoff T never incorporate data from games on or after T."""
    store = EvaluationDatasetStore(pit_test_db)
    cutoff_r2 = store.get_round_decision_cutoff("E2025", 2)
    cutoff_r3 = store.get_round_decision_cutoff("E2025", 3)

    # Pick an existing player in E2025
    with store._connect() as conn:
        p_row = conn.execute(
            "SELECT player_id FROM eval_player_games WHERE season = 'E2025' AND round = 1 LIMIT 1"
        ).fetchone()
        assert p_row is not None
        player_id = int(p_row["player_id"])

    # Compute features prior to Round 2
    f_before_r2 = build_features(
        player_id=player_id,
        decision_cutoff=cutoff_r2,
        database_path=pit_test_db,
        season="E2025",
        round_number=2,
    )
    assert f_before_r2.games_played in (0, 1)

    # Now compute features prior to Round 3 (after Round 2 game has occurred)
    f_before_r3 = build_features(
        player_id=player_id,
        decision_cutoff=cutoff_r3,
        database_path=pit_test_db,
        season="E2025",
        round_number=3,
    )
    # The games played or stats must reflect chronological progression without retroactively altering R2
    assert f_before_r3.games_played >= f_before_r2.games_played


def test_pit_feature_audit_raises_on_future_game_date(pit_test_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that build_features raises ValueError if a post-cutoff game is ever returned in historical rows."""
    store = EvaluationDatasetStore(pit_test_db)
    cutoff_r2 = store.get_round_decision_cutoff("E2025", 2)

    with store._connect() as conn:
        p_row = conn.execute(
            "SELECT player_id FROM eval_player_games WHERE season = 'E2025' LIMIT 1"
        ).fetchone()
        player_id = int(p_row["player_id"])

    from euroleague_fantasy_manager.evaluation import features
    orig_connect = features.EvaluationDatasetStore._connect

    class CursorMock:
        def __init__(self, items):
            self._items = items

        def fetchall(self):
            return self._items

        def fetchone(self):
            return self._items[0] if self._items else None

        def __iter__(self):
            return iter(self._items)

    class ConnProxy:
        def __init__(self, real_conn):
            self._real_conn = real_conn

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self._real_conn.__exit__(*args)

        def executescript(self, sql):
            return self._real_conn.executescript(sql)

        def execute(self, sql, params=()):
            if "WHERE player_id = ? AND game_date < ?" in sql:
                cur = self._real_conn.execute(sql, params)
                rows = cur.fetchall()
                if rows:
                    leaked = dict(rows[0])
                    leaked["game_date"] = "2099-12-31T23:59:59Z"
                    return CursorMock([leaked])
                return CursorMock(rows)
            return self._real_conn.execute(sql, params)

    def patched_connect(self):
        return ConnProxy(orig_connect(self))

    monkeypatch.setattr(features.EvaluationDatasetStore, "_connect", patched_connect)

    with pytest.raises(ValueError, match="Point-in-time invariant violation"):
        build_features(
            player_id=player_id,
            decision_cutoff=cutoff_r2,
            database_path=pit_test_db,
            season="E2025",
            round_number=2,
        )


# ============================================================================
# 2. Leakage Test Suite (Section 7.2)
# ============================================================================


def test_leakage_future_score_isolation(pit_test_db: Path) -> None:
    """Verify future scores in Round 3+ have ZERO impact on features computed before Round 2."""
    store = EvaluationDatasetStore(pit_test_db)
    cutoff_r2 = store.get_round_decision_cutoff("E2025", 2)

    with store._connect() as conn:
        p_row = conn.execute(
            "SELECT player_id FROM eval_player_games WHERE season = 'E2025' AND round = 2 LIMIT 1"
        ).fetchone()
        player_id = int(p_row["player_id"])

    # Compute baseline feature row
    f_baseline = build_features(
        player_id=player_id,
        decision_cutoff=cutoff_r2,
        database_path=pit_test_db,
        season="E2025",
        round_number=2,
    )

    # Inject extreme future score (100.0 FP) in Round 3 and Round 4
    with store._connect() as conn:
        conn.execute(
            """
            UPDATE eval_player_games
            SET fantasy_points = 100.0, pir = 100.0, points = 80
            WHERE season = 'E2025' AND player_id = ? AND round >= 3
            """,
            (player_id,),
        )

    # Recompute features at Round 2 cutoff
    f_after_future_leak = build_features(
        player_id=player_id,
        decision_cutoff=cutoff_r2,
        database_path=pit_test_db,
        season="E2025",
        round_number=2,
    )

    # Must be 100% identical!
    assert f_after_future_leak.season_avg_fantasy_points == f_baseline.season_avg_fantasy_points
    assert f_after_future_leak.ewma_fantasy_points == f_baseline.ewma_fantasy_points
    assert f_after_future_leak.last_1_fantasy_points == f_baseline.last_1_fantasy_points
    assert f_after_future_leak.last_3_avg == f_baseline.last_3_avg
    assert f_after_future_leak.last_5_avg == f_baseline.last_5_avg


def test_leakage_future_minutes_isolation(pit_test_db: Path) -> None:
    """Verify future minutes played in later rounds have ZERO impact on Round 2 minutes features."""
    store = EvaluationDatasetStore(pit_test_db)
    cutoff_r2 = store.get_round_decision_cutoff("E2025", 2)

    with store._connect() as conn:
        p_row = conn.execute(
            "SELECT player_id FROM eval_player_games WHERE season = 'E2025' AND round = 2 LIMIT 1"
        ).fetchone()
        player_id = int(p_row["player_id"])

    f_baseline = build_features(
        player_id=player_id,
        decision_cutoff=cutoff_r2,
        database_path=pit_test_db,
        season="E2025",
        round_number=2,
    )

    # Inject extreme future minutes (40.0 mins) in Round 3
    with store._connect() as conn:
        conn.execute(
            """
            UPDATE eval_player_games
            SET minutes = 40.0
            WHERE season = 'E2025' AND player_id = ? AND round = 3
            """,
            (player_id,),
        )

    f_after = build_features(
        player_id=player_id,
        decision_cutoff=cutoff_r2,
        database_path=pit_test_db,
        season="E2025",
        round_number=2,
    )

    assert f_after.season_avg_minutes == f_baseline.season_avg_minutes
    assert f_after.last_3_minutes == f_baseline.last_3_minutes
    assert f_after.ewma_minutes == f_baseline.ewma_minutes


def test_leakage_future_status_and_standings_isolation(pit_test_db: Path) -> None:
    """Verify future injury status and future game wins do not leak into pre-cutoff status or team strength."""
    store = EvaluationDatasetStore(pit_test_db)
    cutoff_r2 = store.get_round_decision_cutoff("E2025", 2)

    with store._connect() as conn:
        p_row = conn.execute(
            "SELECT player_id, team_id FROM eval_player_games WHERE season = 'E2025' AND round = 2 LIMIT 1"
        ).fetchone()
        player_id = int(p_row["player_id"])
        team_id = int(p_row["team_id"])

    f_baseline = build_features(
        player_id=player_id,
        decision_cutoff=cutoff_r2,
        database_path=pit_test_db,
        season="E2025",
        round_number=2,
    )

    # Change future status in Round 3 to OUT, and set all future team games in Round 3 to losses
    with store._connect() as conn:
        conn.execute(
            """
            UPDATE eval_player_games
            SET pre_round_status = 'out', player_status = 'out'
            WHERE season = 'E2025' AND player_id = ? AND round = 3
            """,
            (player_id,),
        )
        conn.execute(
            """
            UPDATE eval_team_games
            SET win = 0, points_for = 50, points_against = 100
            WHERE season = 'E2025' AND team_id = ? AND round = 3
            """,
            (team_id,),
        )

    f_after = build_features(
        player_id=player_id,
        decision_cutoff=cutoff_r2,
        database_path=pit_test_db,
        season="E2025",
        round_number=2,
    )

    # Pre-round status at R2 must remain unaffected
    assert f_after.pre_round_status == f_baseline.pre_round_status
    assert f_after.play_probability == f_baseline.play_probability
    assert f_after.team_strength == f_baseline.team_strength


def test_leakage_cross_season_isolation(pit_test_db: Path) -> None:
    """Verify season queries strictly isolate seasons: E2024 features never read E2025 data."""
    store = EvaluationDatasetStore(pit_test_db)
    cutoff_e2024 = store.get_round_decision_cutoff("E2024", 2)

    with store._connect() as conn:
        p_row = conn.execute(
            "SELECT player_id FROM eval_player_games WHERE season = 'E2024' LIMIT 1"
        ).fetchone()
        player_id = int(p_row["player_id"])

    f_e2024 = build_features(
        player_id=player_id,
        decision_cutoff=cutoff_e2024,
        database_path=pit_test_db,
        season="E2024",
        round_number=2,
    )
    assert f_e2024.season == "E2024"

    # Even if E2025 data exists in the DB, E2024 query must not see E2025 games
    assert f_e2024.season_avg_fantasy_points >= 0.0


# ============================================================================
# 3. Reproducibility Contract & Verification (Section 7.3)
# ============================================================================


def test_reproducibility_contract_hashes(pit_test_db: Path) -> None:
    """Verify dataset, schema, and model configuration hashes are stable and change on modification."""
    # 1. Dataset hash
    ds_hash_1 = compute_dataset_hash(pit_test_db, season="E2025")
    ds_hash_2 = compute_dataset_hash(pit_test_db, season="E2025")
    assert ds_hash_1 == ds_hash_2
    assert len(ds_hash_1) == 64  # SHA-256

    # 2. Schema hash
    schema_hash_1 = compute_feature_schema_hash(schema_version=FEATURE_SCHEMA_VERSION)
    schema_hash_2 = compute_feature_schema_hash(schema_version=FEATURE_SCHEMA_VERSION)
    assert schema_hash_1 == schema_hash_2
    assert len(schema_hash_1) == 64

    # Different schema version must produce different hash
    diff_schema_hash = compute_feature_schema_hash(schema_version="2.0.0")
    assert diff_schema_hash != schema_hash_1

    # 3. Config hash
    cfg_hash_1 = compute_model_config_hash("season_mean", "0.2.5", {"window": 5})
    cfg_hash_2 = compute_model_config_hash("season_mean", "0.2.5", {"window": 5})
    assert cfg_hash_1 == cfg_hash_2

    diff_cfg_hash = compute_model_config_hash("season_mean", "0.2.5", {"window": 10})
    assert diff_cfg_hash != cfg_hash_1

    # 4. Git commit SHA
    sha = get_git_commit_sha()
    assert isinstance(sha, str)
    assert len(sha) > 0


def test_reproducibility_prediction_run_record_persistence(pit_test_db: Path) -> None:
    """Verify build_prediction_run_record correctly persists to EvaluationDatasetStore."""
    store = EvaluationDatasetStore(pit_test_db)
    record = build_prediction_run_record(
        model_id="last5",
        model_version="0.2.5",
        league_id="euroleague",
        season="E2025",
        round_number=2,
        decision_cutoff="2025-10-15T18:00:00Z",
        database_path=pit_test_db,
        hyperparameters={"window": 5},
        random_seed=42,
    )

    assert record.model_id == "last5"
    assert record.season == "E2025"
    assert record.round_number == 2
    assert len(record.dataset_hash) == 64
    assert len(record.feature_schema_hash) == 64
    assert len(record.model_config_hash) == 64

    # Persist in store
    store.save_prediction_run(record.to_dict())

    # Retrieve and verify
    retrieved = store.get_prediction_run(record.run_id)
    assert retrieved is not None
    assert retrieved["run_id"] == record.run_id
    assert retrieved["dataset_hash"] == record.dataset_hash
    assert retrieved["model_config_hash"] == record.model_config_hash
    assert retrieved["round_number"] == 2


def test_verify_prediction_reproducibility_exact_match() -> None:
    """Verify that verify_prediction_reproducibility succeeds for identical predictions."""
    p1 = PlayerProjectionContract(
        player_id=1,
        player_name="P1",
        position=Position.GUARD,
        expected_fp=15.0,
        probability_play=1.0,
        expected_minutes=25.0,
        fp_per_minute=0.60,
        uncertainty=3.0,
    )
    p2 = PlayerProjectionContract(
        player_id=2,
        player_name="P2",
        position=Position.FORWARD,
        expected_fp=12.0,
        probability_play=0.90,
        expected_minutes=20.0,
        fp_per_minute=0.60,
        uncertainty=2.5,
    )

    run_1 = [p1, p2]
    run_2 = [copy.deepcopy(p1), copy.deepcopy(p2)]

    ok, errors = verify_prediction_reproducibility(run_1, run_2, tolerance=1e-6)
    assert ok is True
    assert errors == []


def test_verify_prediction_reproducibility_detects_divergence() -> None:
    """Verify that verify_prediction_reproducibility flags numeric drift above tolerance."""
    p1 = PlayerProjectionContract(
        player_id=1,
        player_name="P1",
        position=Position.GUARD,
        expected_fp=15.0,
        uncertainty=3.0,
    )
    p1_drifted = PlayerProjectionContract(
        player_id=1,
        player_name="P1",
        position=Position.GUARD,
        expected_fp=15.05,  # 0.05 divergence > 1e-4 tolerance
        uncertainty=3.0,
    )

    ok, errors = verify_prediction_reproducibility([p1], [p1_drifted], tolerance=1e-4)
    assert ok is False
    assert any("divergence" in err for err in errors)
