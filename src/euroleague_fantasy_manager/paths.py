"""Central path resolution for euroleague-fantasy-manager."""

from __future__ import annotations

import os
from pathlib import Path


def elf_home() -> Path:
    """Root for data/config/reports. ELF_HOME env var, else the source checkout, else CWD."""
    env = os.environ.get("ELF_HOME")
    if env:
        return Path(env).expanduser().resolve()
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "pyproject.toml").is_file():
        return checkout.resolve()
    return Path.cwd().resolve()


def database_path() -> Path:
    """Default database path."""
    return elf_home() / "data" / "euroleague.sqlite3"


def raw_archive_dir(db_path: Path | None = None) -> Path:
    """Raw archive directory, defaulting to next to database or under elf_home/data/raw."""
    return (Path(db_path).resolve().parent if db_path else elf_home() / "data") / "raw"


def squad_config_path() -> Path:
    """Default current squad config path."""
    return elf_home() / "config" / "current_squad.json"


def players_txt_path() -> Path:
    """Default players.txt path."""
    return elf_home() / "players.txt"


def eval_reports_dir() -> Path:
    """Default evaluation reports directory."""
    return elf_home() / "reports" / "evaluation"
