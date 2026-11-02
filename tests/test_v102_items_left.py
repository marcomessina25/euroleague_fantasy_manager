"""Targeted regression tests for v102 review items (v102_items_left.md):
- Item 1: Squad import path resolution (import_squad_from_file with default/explicit players_path)
- Item 2: CLI team commands argument normalization and conflict rejection (team select, delete, show)
- Item 3: Ruleset source-of-truth reconciliation across call paths
"""

from __future__ import annotations

from pathlib import Path
import pytest

from euroleague_fantasy_manager.cli import main as cli_main
from euroleague_fantasy_manager.competition.ruleset import (
    League,
    get_base_ruleset,
    get_league_ruleset,
    resolve_ruleset,
)
from euroleague_fantasy_manager.import_squad import import_squad_from_file
from euroleague_fantasy_manager.storage import SnapshotStore


@pytest.fixture
def clean_db(tmp_path: Path) -> Path:
    """Initialize an isolated test database with a minimal snapshot containing official game_modes_configs."""
    db_path = tmp_path / "test_items_left.sqlite3"
    store = SnapshotStore(db_path)
    payload = {
        "league_id": 10,
        "competition_code": "E",
        "season_code": "E2024",
        "config": {
            "current_matchday": {"id": 1, "number": 1, "num_rounds": 1},
            "teams": [{"id": 1, "name": "Panathinaikos", "abbreviation": "PAO"}],
            "game_modes_configs": [
                {
                    "id": 1,
                    "max_num_same_team_players": 4,
                    "captain_multiplier": 2.5,
                }
            ],
        },
        "schedules": [
            {
                "number": 1,
                "rounds": [
                    {
                        "number": 1,
                        "matches": [
                            {
                                "id": 101,
                                "started_at": "2024-10-03T18:00:00Z",
                                "status": "scheduled",
                                "home_team": {"id": 1, "abbreviation": "PAO", "score": None},
                                "away_team": {"id": 1, "abbreviation": "PAO", "score": None},
                            }
                        ],
                    }
                ],
            }
        ],
        "match_lineups": [
            {
                "turn_number": 1,
                "status": "scheduled",
                "home_team": {
                    "id": 1,
                    "name": "Panathinaikos",
                    "abbreviation": "PAO",
                    "lineups": [
                        {
                            "id": 1001,
                            "team_id": 1,
                            "first_name": "Kendrick",
                            "last_name": "Nunn",
                            "position": "Guard",
                            "quotation": 15.0,
                            "pts": 18.0,
                        }
                    ],
                },
                "away_team": {
                    "id": 1,
                    "name": "Panathinaikos",
                    "abbreviation": "PAO",
                    "lineups": [],
                },
            }
        ],
    }
    store.save_snapshot(payload)
    return db_path


# --- ITEM 1: Squad Import Path Resolution ---


def test_import_squad_from_file_resolves_default_players_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Item 1: import_squad_from_file does not fail with AttributeError when players_path is None."""
    db_path = tmp_path / "import_test.sqlite3"
    SnapshotStore(db_path)

    # Mock paths.players_txt_path() to point to a temporary test file
    players_txt = tmp_path / "players.txt"
    players_txt.write_text("# Empty players list\n", encoding="utf-8")
    monkeypatch.setattr("euroleague_fantasy_manager.paths.players_txt_path", lambda: players_txt)

    squad_json = tmp_path / "squad.json"

    # Call with players_path=None (default path resolution)
    squad_data = import_squad_from_file(
        squad_path=squad_json,
        players_path=None,
        database_path=db_path,
        league="euroleague",
    )
    assert isinstance(squad_data, dict)
    assert "player_ids" in squad_data
    assert squad_data["player_ids"] == []


def test_import_squad_from_file_with_concrete_players_path(tmp_path: Path) -> None:
    """Item 1: import_squad_from_file correctly uses explicitly passed players_path."""
    db_path = tmp_path / "import_test2.sqlite3"
    SnapshotStore(db_path)

    custom_players = tmp_path / "custom_players.txt"
    custom_players.write_text("# Custom player list\n", encoding="utf-8")

    squad_json = tmp_path / "squad.json"

    squad_data = import_squad_from_file(
        squad_path=squad_json,
        players_path=custom_players,
        database_path=db_path,
        league="euroleague",
    )
    assert isinstance(squad_data, dict)
    assert "player_ids" in squad_data
    assert squad_data["player_ids"] == []


# --- ITEM 2: CLI Team Command Arguments Ambiguity & Conflict Rejection ---


def test_cli_team_commands_positional_and_id_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Item 2: team select / delete / show accept positional OR --id, accept identical, but reject conflicting."""
    db_path = tmp_path / "cli_team_test.sqlite3"
    # Create team
    code = cli_main(["--db", str(db_path), "team", "create", "--id", "alpha_team", "--name", "Alpha"])
    assert code == 0

    # 1. Positional only works
    code = cli_main(["--db", str(db_path), "team", "select", "alpha_team"])
    assert code == 0

    # 2. --id only works
    code = cli_main(["--db", str(db_path), "team", "select", "--id", "alpha_team"])
    assert code == 0

    # 3. Identical both positional and --id works
    code = cli_main(["--db", str(db_path), "team", "select", "alpha_team", "--id", "alpha_team"])
    assert code == 0

    # 4. Conflicting positional and --id is rejected with non-zero exit code
    code = cli_main(["--db", str(db_path), "team", "select", "alpha_team", "--id", "beta_team"])
    assert code != 0
    err = capsys.readouterr().err
    assert "conflicting" in err.lower()

    # 5. Missing team ID is rejected with non-zero exit code
    code = cli_main(["--db", str(db_path), "team", "select"])
    assert code != 0

    # Test same conflict logic on team show
    code = cli_main(["--db", str(db_path), "team", "show", "alpha_team", "--id", "beta_team"])
    assert code != 0

    # Test same conflict logic on team delete
    code = cli_main(["--db", str(db_path), "team", "delete", "alpha_team", "--id", "beta_team"])
    assert code != 0

    # Test team delete positional works
    code = cli_main(["--db", str(db_path), "team", "delete", "alpha_team"])
    assert code == 0


# --- ITEM 3: Authoritative Ruleset Reconciliation ---


def test_ruleset_official_override_reconciliation(clean_db: Path) -> None:
    """Item 3: resolve_ruleset resolves official game rules from DB while get_base_ruleset preserves static defaults."""
    # Base fallback ruleset
    base = get_base_ruleset(League.EUROLEAGUE)
    assert base.max_court_players_per_club == 6
    assert base.scoring_multipliers["captain"] == 2.0
    assert base.source == "fallback"

    # Resolved ruleset from clean_db containing game_modes_configs (quota=4, captain=2.5)
    resolved = resolve_ruleset(League.EUROLEAGUE, db_path=clean_db)
    assert resolved.max_court_players_per_club == 4
    assert resolved.scoring_multipliers["captain"] == 2.5
    assert resolved.source == "official_config"


def test_get_league_ruleset_delegates_to_resolve_ruleset(clean_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Item 3: get_league_ruleset delegates to resolve_ruleset and queries default db when available."""
    # When default DB is pointed to clean_db, get_league_ruleset() picks up official rules
    monkeypatch.setattr("euroleague_fantasy_manager.paths.database_path", lambda: clean_db)

    ruleset = get_league_ruleset(League.EUROLEAGUE)
    assert ruleset.max_court_players_per_club == 4
    assert ruleset.scoring_multipliers["captain"] == 2.5
    assert ruleset.source == "official_config"
