"""Hermetic testing fixtures and working tree sentinels (v102 P0.2)."""

from __future__ import annotations

from pathlib import Path
import pytest


@pytest.fixture(autouse=True)
def _hermetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ELF_HOME", str(tmp_path / "elf_home"))
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    from euroleague_fantasy_manager.prediction import learned_models
    learned_models.reset_default_learned_pipeline()
    yield


@pytest.fixture(scope="session", autouse=True)
def _real_tree_untouched():
    root = Path(__file__).resolve().parents[1]
    watched = [root / "data", root / "reports", root / "config"]
    before = {p: p.stat().st_mtime_ns for d in watched if d.exists() for p in d.rglob("*") if p.is_file()}
    yield
    after = {p: p.stat().st_mtime_ns for d in watched if d.exists() for p in d.rglob("*") if p.is_file()}
    assert before == after, f"Tests modified the working tree: {set(after) ^ set(before) or [p for p in after if after[p] != before.get(p)]}"


@pytest.fixture
def learned_dataset_db(tmp_path: Path) -> Path:
    from euroleague_fantasy_manager.evaluation.dataset import build_historical_dataset
    db_file = tmp_path / "learned_dataset.sqlite3"
    build_historical_dataset(database_path=db_file, seasons=["E2024", "E2025"])
    return db_file

@pytest.fixture
def sample_feature_row():
    from tests.helpers import sample_feature_row as _helper
    return _helper()
