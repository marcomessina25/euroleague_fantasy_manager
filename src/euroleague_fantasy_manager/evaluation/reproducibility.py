"""Point-in-Time reproducibility and provenance contract for V1.0 (Workstream 2).

Provides cryptographic hashing of:
- dataset snapshot (eval database state);
- feature schema and definitions;
- model architecture and hyperparameters;
- code version (Git commit SHA);
- random seed and execution metadata.

Enforces deterministic reproducibility across identical inputs and configurations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any, Mapping, Sequence

from ..fixtures import DATABASE_PATH
from ..optimization.constraints import PlayerProjectionContract


FEATURE_SCHEMA_VERSION = "1.3.0"


def get_git_commit_sha(repo_root: Path | None = None) -> str:
    """Retrieve current Git commit SHA or return fallback identifier."""
    try:
        root = repo_root or Path(__file__).resolve().parents[3]
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return "git_sha_unavailable"


def compute_dataset_hash(database_path: Path = DATABASE_PATH, season: str | None = None) -> str:
    """Compute a deterministic SHA-256 fingerprint of the evaluation dataset."""
    db_path = Path(database_path)
    if not db_path.exists():
        return hashlib.sha256(b"empty_or_missing_dataset").hexdigest()

    h = hashlib.sha256()
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('eval_player_games', 'eval_team_games', 'eval_players', 'eval_rounds') ORDER BY name"
                ).fetchall()
            ]
            if not tables:
                return hashlib.sha256(b"no_eval_tables").hexdigest()

            for table in tables:
                h.update(table.encode("utf-8"))
                if season and table in ("eval_player_games", "eval_team_games", "eval_rounds"):
                    rows = conn.execute(
                        f"SELECT COUNT(*) AS cnt FROM {table} WHERE season = ?",
                        (season,),
                    ).fetchone()
                else:
                    rows = conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()
                h.update(str(rows["cnt"]).encode("utf-8"))

            if "eval_player_games" in tables:
                query = "SELECT season, round, game_id, player_id, fantasy_points, minutes FROM eval_player_games"
                params: tuple[Any, ...] = ()
                if season:
                    query += " WHERE season = ?"
                    params = (season,)
                query += " ORDER BY season, round, game_id, player_id LIMIT 500"
                for row in conn.execute(query, params):
                    h.update(
                        f"{row['season']}:{row['round']}:{row['game_id']}:{row['player_id']}:{row['fantasy_points']}:{row['minutes']}".encode("utf-8")
                    )
    except Exception:
        h.update(b"hash_read_exception")

    return h.hexdigest()


def compute_feature_schema_hash(
    feature_names: Sequence[str] | None = None,
    schema_version: str = FEATURE_SCHEMA_VERSION,
) -> str:
    """Compute deterministic SHA-256 hash of feature names and schema definition."""
    if feature_names is None:
        from .features import PointInTimeFeatureRow
        import dataclasses

        feature_names = sorted(f.name for f in dataclasses.fields(PointInTimeFeatureRow))

    canonical_repr = f"version={schema_version};features={','.join(sorted(feature_names))}"
    return hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()


def compute_model_config_hash(
    model_id: str,
    model_version: str = "1.0.0",
    hyperparameters: Mapping[str, Any] | None = None,
) -> str:
    """Compute deterministic SHA-256 hash of model identifier and configuration hyperparameters."""
    hp = dict(hyperparameters or {})
    norm_json = json.dumps(hp, sort_keys=True)
    canonical_repr = f"model_id={model_id.lower().strip()};version={model_version};params={norm_json}"
    return hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PredictionRunRecord:
    """Complete provenance and reproducibility record for a point-in-time prediction execution."""

    run_id: str
    model_id: str
    model_version: str
    league_id: str
    season: str
    round_number: int
    decision_cutoff: str
    dataset_hash: str
    feature_schema_hash: str
    model_config_hash: str
    git_sha: str
    random_seed: int
    created_at: str
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    provenance_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "league_id": self.league_id,
            "season": self.season,
            "round_number": self.round_number,
            "decision_cutoff": self.decision_cutoff,
            "dataset_hash": self.dataset_hash,
            "feature_schema_hash": self.feature_schema_hash,
            "model_config_hash": self.model_config_hash,
            "git_sha": self.git_sha,
            "random_seed": self.random_seed,
            "created_at": self.created_at,
            "hyperparameters": dict(self.hyperparameters),
            "provenance_metadata": dict(self.provenance_metadata),
        }


def build_prediction_run_record(
    model_id: str,
    model_version: str,
    league_id: str,
    season: str,
    round_number: int,
    decision_cutoff: str,
    database_path: Path = DATABASE_PATH,
    hyperparameters: Mapping[str, Any] | None = None,
    random_seed: int = 42,
    provenance_metadata: Mapping[str, Any] | None = None,
    run_id: str | None = None,
) -> PredictionRunRecord:
    """Factory creating an audited, reproducible PredictionRunRecord."""
    now_iso = datetime.now(timezone.utc).isoformat()
    ds_hash = compute_dataset_hash(database_path=database_path, season=season)
    schema_hash = compute_feature_schema_hash()
    config_hash = compute_model_config_hash(
        model_id=model_id,
        model_version=model_version,
        hyperparameters=hyperparameters,
    )
    git_sha = get_git_commit_sha()

    if run_id is None:
        short_ds = ds_hash[:8]
        short_cfg = config_hash[:8]
        run_id = f"run_{model_id}_{season}_R{round_number}_{short_ds}_{short_cfg}"

    return PredictionRunRecord(
        run_id=run_id,
        model_id=model_id,
        model_version=model_version,
        league_id=league_id,
        season=season,
        round_number=round_number,
        decision_cutoff=decision_cutoff,
        dataset_hash=ds_hash,
        feature_schema_hash=schema_hash,
        model_config_hash=config_hash,
        git_sha=git_sha,
        random_seed=random_seed,
        created_at=now_iso,
        hyperparameters=dict(hyperparameters or {}),
        provenance_metadata=dict(provenance_metadata or {}),
    )


def verify_prediction_reproducibility(
    run_1_projections: Sequence[PlayerProjectionContract | dict[str, Any]],
    run_2_projections: Sequence[PlayerProjectionContract | dict[str, Any]],
    tolerance: float = 1e-6,
) -> tuple[bool, list[str]]:
    """Verify that two independent prediction runs produced identical results within numerical tolerance."""
    errors: list[str] = []

    def _extract_dict(item: PlayerProjectionContract | dict[str, Any]) -> dict[str, Any]:
        if isinstance(item, PlayerProjectionContract):
            return item.to_dict()
        return dict(item)

    dict_1 = {p["player_id"]: p for p in (_extract_dict(x) for x in run_1_projections)}
    dict_2 = {p["player_id"]: p for p in (_extract_dict(x) for x in run_2_projections)}

    if set(dict_1.keys()) != set(dict_2.keys()):
        missing_in_2 = set(dict_1.keys()) - set(dict_2.keys())
        missing_in_1 = set(dict_2.keys()) - set(dict_1.keys())
        if missing_in_2:
            errors.append(f"Run 2 missing player IDs: {sorted(missing_in_2)}")
        if missing_in_1:
            errors.append(f"Run 1 missing player IDs: {sorted(missing_in_1)}")
        return False, errors

    numeric_fields = (
        "expected_fp",
        "probability_play",
        "expected_minutes",
        "fp_per_minute",
        "uncertainty",
        "lower_bound",
        "upper_bound",
    )

    for pid in sorted(dict_1.keys()):
        p1 = dict_1[pid]
        p2 = dict_2[pid]
        for field_name in numeric_fields:
            val1 = p1.get(field_name)
            val2 = p2.get(field_name)
            if val1 is not None and val2 is not None:
                diff = abs(float(val1) - float(val2))
                if diff > tolerance:
                    errors.append(
                        f"Player {pid} field {field_name!r} divergence: {val1} vs {val2} (diff={diff} > {tolerance})"
                    )

    return len(errors) == 0, errors
