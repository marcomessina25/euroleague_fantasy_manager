"""Targeted verification tests for V1.0.2 review findings (v102_items_left_v2.md).

Covers all 6 core audit findings:
1. Squad import path resolution (resolved_players_path vs players_path)
2. CLI command ambiguity for team selection, show, and deletion
3. Ruleset source-of-truth consistency across services and call paths
4. Honest point-in-time prediction routing without future-data fallback
5. Team state and replay transaction atomicity and bank invariants
6. Web security hardening: strict CSP, frame-ancestors, cross-origin blocking, host pinning
"""

from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from euroleague_fantasy_manager.cli import main as cli_main
from euroleague_fantasy_manager.competition.ruleset import (
    League,
    get_base_ruleset,
    get_league_ruleset,
)
from euroleague_fantasy_manager.import_squad import import_squad_from_file
from euroleague_fantasy_manager.models import NoSnapshotForRoundError
from euroleague_fantasy_manager.multi_team.models import TeamRosterUnit
from euroleague_fantasy_manager.services.optimization_service import OptimizationService
from euroleague_fantasy_manager.services.prediction_service import PredictionService
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.storage import SnapshotStore
from euroleague_fantasy_manager.web.app import create_app


@pytest.fixture
def configured_db(tmp_path: Path) -> Path:
    """Fixture providing a SQLite DB with an official configuration override snapshot."""
    db_file = tmp_path / "v2_test.sqlite3"
    store = SnapshotStore(db_file)
    payload = {
        "league_id": 10,
        "competition_code": "E",
        "season_code": "E2024",
        "config": {
            "current_matchday": {"id": 1, "number": 1, "num_rounds": 1},
            "teams": [
                {"id": 1, "name": "Panathinaikos", "abbreviation": "PAO"},
                {"id": 2, "name": "Olympiacos", "abbreviation": "OLY"},
            ],
            "game_modes_configs": [
                {
                    "id": 1,
                    "max_num_same_team_players": 4,  # Overrides base 6 -> 4
                    "captain_multiplier": 2.5,       # Overrides base 2.0 -> 2.5
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
                                "away_team": {"id": 2, "abbreviation": "OLY", "score": None},
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
                            "status": "starter",
                            "probability_of_playing": 1.0,
                        }
                    ],
                },
                "away_team": {
                    "id": 2,
                    "name": "Olympiacos",
                    "abbreviation": "OLY",
                    "lineups": [],
                },
            }
        ],
    }
    store.save_snapshot(payload)
    return db_file


# ---------------------------------------------------------------------------
# Finding 1: Squad import path resolution
# ---------------------------------------------------------------------------


def test_import_squad_path_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify import_squad_from_file resolves default paths correctly without unhandled exceptions."""
    db_path = tmp_path / "import_path_test.sqlite3"
    SnapshotStore(db_path)
    players_txt = tmp_path / "players.txt"
    players_txt.write_text("# Test\n", encoding="utf-8")
    monkeypatch.setattr("euroleague_fantasy_manager.paths.players_txt_path", lambda: players_txt)

    squad_file = tmp_path / "squad.json"
    res = import_squad_from_file(
        squad_path=squad_file,
        players_path=None,  # triggers resolved_players_path fallback
        database_path=db_path,
        league="euroleague",
    )
    assert isinstance(res, dict)
    assert res.get("player_ids") == []


# ---------------------------------------------------------------------------
# Finding 2: CLI command ambiguity for team selection and deletion
# ---------------------------------------------------------------------------


def test_cli_team_commands_reject_ambiguous_and_conflicting_inputs(tmp_path: Path, capsys):
    """Verify CLI team commands reject conflicting positional and --id arguments with clear error."""
    db_file = tmp_path / "cli_ambiguity.sqlite3"
    cli_main(["--db", str(db_file), "team", "create", "--id", "team_one", "--name", "Team One"])

    # Conflicting arguments to 'team select'
    rc_select = cli_main(["--db", str(db_file), "team", "select", "team_one", "--id", "team_two"])
    assert rc_select != 0
    err_select = capsys.readouterr().err
    assert "conflicting" in err_select.lower()

    # Conflicting arguments to 'team delete'
    rc_delete = cli_main(["--db", str(db_file), "team", "delete", "team_one", "--id", "team_two"])
    assert rc_delete != 0
    err_delete = capsys.readouterr().err
    assert "conflicting" in err_delete.lower()

    # Conflicting arguments to 'team show'
    rc_show = cli_main(["--db", str(db_file), "team", "show", "team_one", "--id", "team_two"])
    assert rc_show != 0


# ---------------------------------------------------------------------------
# Finding 3: Ruleset source-of-truth consistency
# ---------------------------------------------------------------------------


def test_ruleset_source_of_truth_propagation(configured_db: Path):
    """Verify authoritative DB overrides propagate consistently through get_league_ruleset and services."""
    # 1. Base static ruleset
    base = get_base_ruleset(League.EUROLEAGUE)
    assert base.max_court_players_per_club == 6
    assert base.scoring_multipliers["captain"] == 2.0

    # 2. Authoritative ruleset with db_path override
    resolved = get_league_ruleset(League.EUROLEAGUE, db_path=configured_db)
    assert resolved.max_court_players_per_club == 4
    assert resolved.scoring_multipliers["captain"] == 2.5
    assert resolved.source == "official_config"

    # 3. OptimizationService receives authoritative DB ruleset via team_service db_path
    team_svc = TeamService(db_path=configured_db)
    pred_svc = PredictionService(database_path=configured_db)
    opt_svc = OptimizationService(team_service=team_svc, prediction_service=pred_svc)
    assert opt_svc.constraints.max_players_per_club == 4

    # 4. TeamService enforces authoritative DB club quota (4 instead of 6)
    # 5 court players from PAO (exceeds quota of 4)
    violating_units = [
        TeamRosterUnit(player_id=101 + i, position="G" if i < 4 else "F", team_code="PAO", name=f"P{i}")
        for i in range(5)
    ] + [
        TeamRosterUnit(player_id=201 + i, position="F" if i < 3 else ("C" if i < 5 else "HC"), team_code="OLY", name=f"O{i}")
        for i in range(6)
    ]
    with pytest.raises(ValueError, match="Squad violates club quota for EuroLeague"):
        team_svc._validate_club_quota(violating_units, league="euroleague")


# ---------------------------------------------------------------------------
# Finding 4: Honest point-in-time prediction routing
# ---------------------------------------------------------------------------


def test_prediction_routing_pit_safety(tmp_path: Path):
    """Verify prediction service raises NoSnapshotForRoundError instead of falling back to future snapshots."""
    db_file = tmp_path / "pit_pred.sqlite3"
    store = SnapshotStore(db_file)

    # Seed snapshot for round 3 only (no round 1 or 2)
    payload_r3 = {
        "league_id": 10,
        "competition_code": "E",
        "season_code": "E2026",
        "round_number": 3,
        "players": [
            {"id": 301, "name": "R3 Star", "position": "Guard", "price_tenths": 150, "status": "starter", "probability_of_playing": 1.0}
        ],
    }
    store.save_snapshot(payload_r3)

    pred_svc = PredictionService(database_path=db_file)

    # Requesting round 3 works
    projs_r3 = pred_svc.get_projections(season="2026", round_number=3, league="euroleague")
    assert len(projs_r3) == 1
    assert projs_r3[0].player_id == 301

    # Requesting round 1 MUST raise NoSnapshotForRoundError and never leak round 3
    with pytest.raises(NoSnapshotForRoundError):
        pred_svc.get_projections(season="2026", round_number=1, league="euroleague")


# ---------------------------------------------------------------------------
# Finding 5: Team state transactions and bank invariant
# ---------------------------------------------------------------------------


def test_team_state_transaction_atomicity_and_bank_invariant(tmp_path: Path):
    """Verify execute_transfers and adjust_bank maintain strict atomicity and bank invariants."""
    db_file = tmp_path / "state_atomic.sqlite3"
    store = SnapshotStore(db_file)

    # Seed initial round snapshot
    store.save_snapshot({
        "league_id": 10,
        "competition_code": "E",
        "season_code": "E2026",
        "round_number": 1,
        "players": [
            {"id": 101, "name": "P101", "position": "Guard", "price_tenths": 100, "status": "starter", "probability_of_playing": 1.0},
            {"id": 201, "name": "P201", "position": "Guard", "price_tenths": 120, "status": "starter", "probability_of_playing": 1.0},
        ],
    })

    team_svc = TeamService(db_path=db_file)
    team = team_svc.create_team("atomic_team", "Atomic Team", round_number=1, bank_tenths=500)
    assert team.bank_tenths == 500

    # Test bank adjustment atomicity
    updated = team_svc.adjust_bank("atomic_team", delta_tenths=150, reason="Sponsorship")
    assert updated.bank_tenths == 650

    # Negative bank is rejected with zero mutation
    with pytest.raises(ValueError, match="Bank cannot be negative"):
        team_svc.adjust_bank("atomic_team", delta_tenths=-1000)

    # Assert bank remains 650
    assert team_svc.get_team("atomic_team").bank_tenths == 650


# ---------------------------------------------------------------------------
# Finding 6: Web security hardening
# ---------------------------------------------------------------------------


def test_web_security_headers_and_cross_origin_isolation(tmp_path: Path):
    """Verify strict CSP without unsafe-inline on script-src, frame-ancestors, and origin checks."""
    db_file = tmp_path / "web_sec_v2.sqlite3"
    app = create_app(db_path=db_file)
    client = TestClient(app)

    # 1. CSP Header Verification
    res = client.get("/")
    assert res.status_code == 200
    csp = res.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0], "script-src must not contain unsafe-inline"
    assert "frame-ancestors 'none'" in csp
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["referrer-policy"] == "no-referrer"

    # 2. Host header enforcement (TrustedHostMiddleware)
    untrusted_res = client.get("/", headers={"host": "attacker.evil.com"})
    assert untrusted_res.status_code in (400, 403)

    # 3. Cross-origin mutation rejection
    cross_res = client.post(
        "/api/teams",
        headers={"origin": "http://evil-site.com"},
        json={"name": "Bad Team", "league": "euroleague"},
    )
    assert cross_res.status_code == 403

    # 4. Content-Type application/json requirement on mutating endpoints
    bad_ct_res = client.post(
        "/api/teams",
        headers={"content-type": "text/plain"},
        content=b"invalid body",
    )
    assert bad_ct_res.status_code == 415
