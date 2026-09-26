"""Test suite for V0.6 Strategic Intelligence, Manager Dossier, Multi-League & Copilot."""

from __future__ import annotations

from pathlib import Path
import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient

from euroleague_fantasy_manager.competition import (
    CompetitionRuleset,
    EuroCupRuleset,
    EuroLeagueRuleset,
    League,
    get_league_ruleset,
)
from euroleague_fantasy_manager.intelligence.consistency import verify_consistency
from euroleague_fantasy_manager.intelligence.copilot import (
    CopilotAdviceResult,
    generate_copilot_advice,
)
from euroleague_fantasy_manager.intelligence.dossier import (
    ManagerDossier,
    generate_manager_dossier,
)
from euroleague_fantasy_manager.intelligence.providers import (
    BaseLLMProvider,
    HeuristicProvider,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    list_available_providers,
)
from euroleague_fantasy_manager.intelligence.strategic_analysis import (
    StrategicAnalysisResult,
    analyze_dossier,
)
from euroleague_fantasy_manager.cli import main as cli_main
from euroleague_fantasy_manager.multi_team.models import TeamRosterUnit
from euroleague_fantasy_manager.multi_team.store import TeamStore
from euroleague_fantasy_manager.services.decision_service import DecisionService
from euroleague_fantasy_manager.services.team_service import TeamService
from euroleague_fantasy_manager.tracking.models import LineupPayload
from euroleague_fantasy_manager.web.app import create_app
import sqlite3


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    return tmp_path / "test_v06_intelligence.sqlite3"


@pytest.fixture
def team_store(temp_db: Path) -> TeamStore:
    return TeamStore(db_path=temp_db)


@pytest.fixture
def team_service(team_store: TeamStore) -> TeamService:
    return TeamService(store=team_store)


def _seed_sample_team(team_service: TeamService, team_id: str = "t1", league: str = "euroleague") -> None:
    team_service.create_team(
        team_id=team_id,
        name=f"Squad {team_id.upper()}",
        season="2026/27",
        round_number=1,
        turn_number=1,
        bank_tenths=50,
        league=league,
    )
    units = [
        TeamRosterUnit(player_id=101, name="Facundo Campazzo", position="G", team_code="RMB", current_price_tenths=145, is_starter=True, is_captain=True),
        TeamRosterUnit(player_id=102, name="Kendrick Nunn", position="G", team_code="PAO", current_price_tenths=135, is_starter=True),
        TeamRosterUnit(player_id=103, name="Nigel Hayes-Davis", position="F", team_code="FNB", current_price_tenths=140, is_starter=True),
        TeamRosterUnit(player_id=104, name="Nikola Mirotic", position="F", team_code="EA7", current_price_tenths=150, is_starter=True),
        TeamRosterUnit(player_id=105, name="Mathias Lessort", position="C", team_code="PAO", current_price_tenths=160, is_starter=True),
        TeamRosterUnit(player_id=106, name="Shane Larkin", position="G", team_code="EFS", current_price_tenths=130, is_sixth_man=True),
        TeamRosterUnit(player_id=107, name="Kostas Sloukas", position="G", team_code="PAO", current_price_tenths=110, is_bench=True),
        TeamRosterUnit(player_id=108, name="Mario Hezonja", position="F", team_code="RMB", current_price_tenths=115, is_bench=True),
        TeamRosterUnit(player_id=109, name="Nikola Kalinic", position="F", team_code="CZV", current_price_tenths=95, is_bench=True),
        TeamRosterUnit(player_id=110, name="Jan Vesely", position="C", team_code="BAR", current_price_tenths=110, is_bench=True),
        TeamRosterUnit(player_id=111, name="Ergin Ataman", position="HC", team_code="PAO", current_price_tenths=70, is_coach=True),
    ]
    team_service.update_team_squad(team_id=team_id, squad=units)


# =========================================================================
# 1. Multi-League Rulesets & Strict Parsing Tests
# =========================================================================
def test_strict_league_parsing() -> None:
    # 1. Valid EuroLeague aliases and formats
    for val in ("euroleague", "el", "EL", "e", "10", "EuroLeague", "euro_league", "euro-league", "euroleaguefantasy"):
        assert League.from_str(val) == League.EUROLEAGUE

    # 2. Valid EuroCup aliases and formats
    for val in ("eurocup", "ec", "EC", "u", "11", "EuroCup", "euro_cup", "euro-cup", "eurocupfantasy"):
        assert League.from_str(val) == League.EUROCUP

    # 3. Existing enum instances
    assert League.from_str(League.EUROLEAGUE) == League.EUROLEAGUE
    assert League.from_str(League.EUROCUP) == League.EUROCUP

    # 4. Unknown non-empty values must fail explicitly with ValueError
    for unknown in ("nba", "foo", "bcl", "acb", "liga_endesa", "invalid", 123):
        with pytest.raises(ValueError, match="Unsupported or unknown league"):
            League.from_str(unknown)

    # 5. Malformed or empty values must fail explicitly with ValueError
    for malformed in ("", "   ", None):
        with pytest.raises(ValueError, match="League identifier cannot be empty or None"):
            League.from_str(malformed)  # type: ignore

    # 6. Ruleset getter behavior
    assert get_league_ruleset(None).league == League.EUROLEAGUE
    assert get_league_ruleset("eurocup").league == League.EUROCUP
    assert get_league_ruleset(League.EUROCUP).league == League.EUROCUP
    with pytest.raises(ValueError):
        get_league_ruleset("unknown_league")


def test_shared_engine_ruleset_semantics() -> None:
    el_rules = get_league_ruleset(League.EUROLEAGUE)
    ec_rules = get_league_ruleset("eurocup")

    assert isinstance(el_rules, CompetitionRuleset)
    assert isinstance(ec_rules, CompetitionRuleset)
    assert el_rules.league == League.EUROLEAGUE
    assert ec_rules.league == League.EUROCUP

    # Shared squad constraints
    assert el_rules.squad_size == ec_rules.squad_size == 11
    assert el_rules.starters_count == ec_rules.starters_count == 5
    assert el_rules.sixth_man_count == ec_rules.sixth_man_count == 1
    assert el_rules.bench_count == ec_rules.bench_count == 4
    assert el_rules.head_coach_count == ec_rules.head_coach_count == 1
    assert el_rules.valid_formations == ec_rules.valid_formations
    assert el_rules.scoring_multipliers["captain"] == ec_rules.scoring_multipliers["captain"] == 2.0
    assert el_rules.scoring_multipliers["bench"] == ec_rules.scoring_multipliers["bench"] == 0.5

    # Competition-specific identifiers
    assert el_rules.competition_code == "E"
    assert ec_rules.competition_code == "U"
    assert el_rules.league_id == 10
    assert ec_rules.league_id == 11


def test_six_team_capacity_and_league_persistence(team_service: TeamService, team_store: TeamStore) -> None:
    # Create 6 teams alternating leagues
    for i in range(1, 7):
        lg = "eurocup" if i % 2 == 0 else "euroleague"
        t = team_service.create_team(
            team_id=f"team_{i}",
            name=f"Team {i}",
            season="2026/27",
            league=lg,
        )
        assert t.league == lg

    # 7th team must raise ValueError
    with pytest.raises(ValueError, match="Maximum limit of 6 teams reached"):
        team_service.create_team(team_id="team_7", name="Team 7", season="2026/27")

    # Verify database persistence round-trip
    teams = team_store.list_teams()
    assert len(teams) == 6
    assert teams[0].league == "euroleague"
    assert teams[1].league == "eurocup"

    # Isolation check: mutating team 1 squad does not leak to team 2
    u = [TeamRosterUnit(player_id=999, name="Test Unit", position="G", team_code="TST", current_price_tenths=100, is_starter=True)]
    team_service.update_team_squad("team_1", u)
    assert len(team_store.get_team("team_1").squad) == 1
    assert len(team_store.get_team("team_2").squad) == 0


# =========================================================================
# 2. Manager Dossier Determinism & Provenance Tests
# =========================================================================
def test_deterministic_manager_dossier_generation(team_service: TeamService, temp_db: Path) -> None:
    _seed_sample_team(team_service, team_id="team_el", league="euroleague")

    dossier1 = generate_manager_dossier(team_id="team_el", team_service=team_service, database_path=temp_db)
    dossier2 = generate_manager_dossier(team_id="team_el", team_service=team_service, database_path=temp_db)

    # Identical deterministic facts and hash
    assert dossier1.provenance.config_hash == dossier2.provenance.config_hash
    assert dossier1.current_lineup.expected_total_fp == dossier2.current_lineup.expected_total_fp
    assert dossier1.league == "euroleague"
    assert len(dossier1.current_lineup.starters) == 5
    assert dossier1.current_lineup.captain is not None
    assert dossier1.current_lineup.sixth_man is not None
    assert dossier1.current_lineup.coach is not None
    assert len(dossier1.current_lineup.bench) == 4

    # Markdown summary check
    md = dossier1.summary_markdown()
    assert "Manager Dossier" in md
    assert "Starting Five" in md
    assert "Facundo Campazzo" in md


# =========================================================================
# 3. Deterministic Strategic Analysis (100% Offline, LLM Disabled)
# =========================================================================
def test_deterministic_strategic_analysis_offline(team_service: TeamService, temp_db: Path) -> None:
    _seed_sample_team(team_service, team_id="team_el", league="euroleague")
    dossier = generate_manager_dossier(team_id="team_el", team_service=team_service, database_path=temp_db)

    strat = analyze_dossier(dossier)
    assert isinstance(strat, StrategicAnalysisResult)
    assert strat.dossier_id == dossier.dossier_id

    # 1. Key Assumptions (ranked)
    assert len(strat.assumptions) >= 2
    assert any(a.category == "captaincy" for a in strat.assumptions)
    assert any(a.risk_level.lower() in ("high", "medium", "low") for a in strat.assumptions)

    # 2. Sensitivities
    assert len(strat.sensitivities) >= 2
    cap_sens = next((s for s in strat.sensitivities if "Captain" in s.parameter), None)
    assert cap_sens is not None
    assert cap_sens.delta_fp != 0.0

    # 3. Devil's Advocate Checklist
    checklist_names = [c.check_name for c in strat.checklist]
    assert any("Legality" in name for name in checklist_names)
    assert any("Plausibility" in name for name in checklist_names)
    assert any("Alternative" in name for name in checklist_names)
    assert any("Regret" in name for name in checklist_names)
    assert any("Liquidity" in name for name in checklist_names)
    assert all(c.status in ("PASS", "WARNING") for c in strat.checklist)


# =========================================================================
# 4. LLM Copilot & Zero-Mutation Invariant
# =========================================================================
def test_heuristic_copilot_advice_zero_mutation(team_service: TeamService, temp_db: Path) -> None:
    _seed_sample_team(team_service, team_id="team_el", league="euroleague")

    # Capture initial database state
    initial_team = team_service.get_team("team_el")
    initial_squad_ids = [u.player_id for u in initial_team.squad]
    initial_bank = initial_team.bank_tenths

    dossier = generate_manager_dossier(team_id="team_el", team_service=team_service, database_path=temp_db)

    # Run advice with persona = devil_advocate
    advice = generate_copilot_advice(
        dossier=dossier,
        persona="devil_advocate",
        provider_name="heuristic",
        database_path=temp_db,
    )

    assert isinstance(advice, CopilotAdviceResult)
    assert advice.persona == "devil_advocate"
    assert advice.provider == "heuristic"
    assert not advice.is_fallback
    assert "DEVIL'S ADVOCATE CRITIQUE" in advice.analysis_text
    assert advice.consistency.is_consistent

    # VERIFY ZERO-MUTATION: Persistent squad and bank are completely unchanged
    after_team = team_service.get_team("team_el")
    after_squad_ids = [u.player_id for u in after_team.squad]
    assert after_squad_ids == initial_squad_ids
    assert after_team.bank_tenths == initial_bank


# =========================================================================
# 5. Provider Failure Isolation & Graceful Fallback
# =========================================================================
class FailingMockProvider(BaseLLMProvider):
    def __init__(self) -> None:
        super().__init__(name="failing_mock", api_key="dummy_key", default_model="mock-error-v1")

    def is_available(self) -> bool:
        return True

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        raise ProviderError("API Connection Timeout (504 Gateway Timeout)")


def test_provider_failure_isolation_and_fallback(team_service: TeamService, temp_db: Path) -> None:
    _seed_sample_team(team_service, team_id="team_el", league="euroleague")
    dossier = generate_manager_dossier(team_id="team_el", team_service=team_service, database_path=temp_db)

    with patch("euroleague_fantasy_manager.intelligence.copilot.get_provider", return_value=FailingMockProvider()):
        advice = generate_copilot_advice(
            dossier=dossier,
            persona="briefing",
            provider_name="failing_mock",
            database_path=temp_db,
        )

        # Must not crash, but fall back seamlessly to heuristic
        assert advice.is_fallback is True
        assert advice.fallback_reason is not None
        assert "API Connection Timeout" in advice.fallback_reason
        assert "MANAGER BRIEFING" in advice.analysis_text
        assert advice.provider == "heuristic"


# =========================================================================
# 6. Consistency Verification Tests
# =========================================================================
def test_consistency_verification_grounding(team_service: TeamService, temp_db: Path) -> None:
    _seed_sample_team(team_service, team_id="team_el", league="euroleague")
    dossier = generate_manager_dossier(team_id="team_el", team_service=team_service, database_path=temp_db)

    # 1. Clean grounded text
    clean_text = (
        f"Facundo Campazzo is captain ({dossier.current_lineup.captain.expected_fp:.1f} FP). "
        f"Mathias Lessort and Kendrick Nunn anchor the starting lineup."
    )
    rep_clean = verify_consistency(clean_text, dossier)
    assert rep_clean.is_consistent
    assert len(rep_clean.rule_warnings) == 0
    assert len(rep_clean.hallucinated_players) == 0

    # 2. Hallucinated fantasy chip / Premier league rule
    bad_rule_text = "You should activate your Free Hit chip or Triple Captain this round."
    rep_bad_rule = verify_consistency(bad_rule_text, dossier)
    assert not rep_bad_rule.is_consistent
    assert any("Free Hit" in v for v in rep_bad_rule.rule_warnings)

    # 3. Hallucinated player name
    bad_player_text = "Sell Mathias Lessort and bring in UnknownAlienSuperstar for 20 credits."
    rep_bad_player = verify_consistency(bad_player_text, dossier)
    assert not rep_bad_player.is_consistent
    assert any("UnknownAlienSuperstar" in h for h in rep_bad_player.hallucinated_players)


# =========================================================================
# 7. EuroCup Compatibility Test
# =========================================================================
def test_eurocup_dossier_compatibility(team_service: TeamService, temp_db: Path) -> None:
    _seed_sample_team(team_service, team_id="team_ec", league="eurocup")
    dossier = generate_manager_dossier(team_id="team_ec", team_service=team_service, database_path=temp_db)

    assert dossier.league == "eurocup"
    assert dossier.current_lineup.starters is not None
    strat = analyze_dossier(dossier)
    assert strat.dossier_id == dossier.dossier_id


# =========================================================================
# 8. FastAPI Intelligence & Copilot Endpoints Test
# =========================================================================
def test_fastapi_intelligence_routes(temp_db: Path) -> None:
    app = create_app(db_path=temp_db)
    client = TestClient(app)

    # 1. Available providers
    res_prov = client.get("/api/workstation/copilot/providers")
    assert res_prov.status_code == 200
    providers = res_prov.json()
    assert any(p["provider_name"] == "heuristic" for p in providers)

    # 2. Generate dossier
    res_dos = client.get("/api/workstation/dossier?team_id=team_1")
    assert res_dos.status_code == 200
    dos_data = res_dos.json()
    assert "dossier_id" in dos_data
    assert "current_lineup" in dos_data

    # 3. Deterministic strategic analysis
    res_strat = client.get("/api/workstation/strategic-analysis?team_id=team_1")
    assert res_strat.status_code == 200
    strat_data = res_strat.json()
    assert "assumptions" in strat_data
    assert "checklist" in strat_data

    # 4. Copilot advise
    res_advise = client.post(
        "/api/workstation/copilot/advise",
        json={
            "team_id": "team_1",
            "persona": "briefing",
            "provider": "heuristic",
            "tier": "standard",
        },
    )
    assert res_advise.status_code == 200
    adv_data = res_advise.json()
    assert "analysis_text" in adv_data
    assert adv_data["persona"] == "briefing"
    assert adv_data["provider"] == "heuristic"
    assert not adv_data["is_fallback"]


# =========================================================================
# 9. CLI Read-Only & Zero-Mutation Invariant Tests
# =========================================================================
def test_cli_advise_read_only(temp_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # 1. advise with empty DB returns code 1 and error
    exit_code = cli_main(["--db", str(temp_db), "advise"])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "Error: No fantasy team found" in out

    # Verify no persistent team was created
    store = TeamStore(db_path=temp_db)
    assert len(store.list_teams()) == 0

    # 2. advise with non-existent team ID returns code 1 and error
    exit_code_team = cli_main(["--db", str(temp_db), "advise", "--team", "ghost_squad"])
    assert exit_code_team == 1
    out_team = capsys.readouterr().out
    assert "Error: Team 'ghost_squad' not found" in out_team
    assert len(store.list_teams()) == 0


def _dump_db_state(db_path: Path) -> dict[str, list[dict[str, object]]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
            ).fetchall()
        ]
        dump: dict[str, list[dict[str, object]]] = {}
        for tbl in tables:
            rows = conn.execute(f"SELECT * FROM {tbl} ORDER BY rowid;").fetchall()
            dump[tbl] = [dict(r) for r in rows]
        return dump


class MockSuccessLLMProvider(BaseLLMProvider):
    def __init__(self) -> None:
        super().__init__(name="mock_llm", api_key="dummy_key", default_model="mock-v1")

    def is_available(self) -> bool:
        return True

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            content="Briefing: Squad is well structured with Facundo Campazzo as captain.",
            provider=self.name,
            model="mock-v1",
            latency_ms=12.5,
        )


def test_strong_zero_mutation_invariant(team_service: TeamService, temp_db: Path) -> None:
    # 1. Seed complete persistent state: team, squad, checkpoint, and decision
    _seed_sample_team(team_service, team_id="team_inv", league="euroleague")
    team_service.store.save_round_checkpoint(
        team_id="team_inv",
        round_number=1,
        season="2026/27",
        bank_tenths=50,
        transfers_remaining=4,
        squad=team_service.get_team("team_inv").squad,
    )

    dec_svc = DecisionService(db_path=temp_db)
    lineup = LineupPayload(
        formation="2-2-1",
        starter_ids=(101, 102, 103, 104, 105),
        captain_id=101,
        sixth_man_id=106,
        bench_ids=(107, 108, 109, 110),
        head_coach_id=111,
    )
    dec_svc.log_lineup(
        team_id="team_inv",
        season="2026/27",
        round_number=1,
        turn_number=1,
        recommended_lineup=lineup,
        notes="Pre-analysis baseline",
    )

    # Pre-initialize schema stores
    from euroleague_fantasy_manager.evaluation.dataset import EvaluationDatasetStore
    from euroleague_fantasy_manager.services.prediction_service import PredictionService
    from euroleague_fantasy_manager.services.optimization_service import OptimizationService
    from euroleague_fantasy_manager.storage import SnapshotStore
    _ = SnapshotStore(temp_db)
    _ = EvaluationDatasetStore(database_path=temp_db)
    ps = PredictionService(database_path=temp_db)
    _ = OptimizationService(team_service=team_service, prediction_service=ps)

    # Capture initial SQLite snapshot across all tables
    state_before = _dump_db_state(temp_db)
    assert len(state_before["managed_teams"]) == 1
    assert len(state_before["managed_team_squads"]) == 11
    assert len(state_before["team_round_checkpoints"]) == 1
    assert len(state_before["decision_logs"]) == 1

    # 2. Run Manager Dossier generation
    dossier = generate_manager_dossier(team_id="team_inv", team_service=team_service, database_path=temp_db)

    # 3. Run Deterministic Strategic Analysis
    strat = analyze_dossier(dossier)
    assert strat.dossier_id == dossier.dossier_id

    # 4. Run Heuristic Copilot Advice
    advice_h = generate_copilot_advice(
        dossier=dossier,
        persona="briefing",
        provider_name="heuristic",
        database_path=temp_db,
    )
    assert advice_h.provider == "heuristic"

    # 5. Run Mock LLM Copilot Advice
    with patch("euroleague_fantasy_manager.intelligence.copilot.get_provider", return_value=MockSuccessLLMProvider()):
        advice_m = generate_copilot_advice(
            dossier=dossier,
            persona="devil_advocate",
            provider_name="mock_llm",
            database_path=temp_db,
        )
        assert advice_m.provider == "mock_llm"

    # 6. Capture post-analysis snapshot across all tables
    state_after = _dump_db_state(temp_db)

    # 7. Assert 100% zero-mutation invariant: all persistent tables and records are identical
    assert state_before == state_after


# =========================================================================
# 10. Mixed-League Six-Team Isolation & Content Hash Tests
# =========================================================================
def test_mixed_league_six_team_isolation(team_service: TeamService, temp_db: Path) -> None:
    leagues = {
        "team_a": "euroleague",
        "team_b": "euroleague",
        "team_c": "eurocup",
        "team_d": "euroleague",
        "team_e": "eurocup",
        "team_f": "eurocup",
    }
    for tid, lg in leagues.items():
        _seed_sample_team(team_service, team_id=tid, league=lg)

    teams = team_service.list_teams()
    assert len(teams) == 6
    for t in teams:
        assert t.league == leagues[t.team_id]

    dossier_a = generate_manager_dossier("team_a", team_service=team_service, database_path=temp_db)
    assert dossier_a.league == "euroleague"
    assert dossier_a.provenance.ruleset_name == "EuroLeague Fantasy Challenge"
    assert dossier_a.provenance.competition_code == "E"

    dossier_c = generate_manager_dossier("team_c", team_service=team_service, database_path=temp_db)
    assert dossier_c.league == "eurocup"
    assert dossier_c.provenance.ruleset_name == "EuroCup Fantasy Challenge"
    assert dossier_c.provenance.competition_code == "U"

    # Modifying team_c bank does not alter team_a
    team_service.update_team("team_c", bank_tenths=300)
    assert team_service.get_team("team_c").bank_tenths == 300
    assert team_service.get_team("team_a").bank_tenths == 50


def test_provenance_content_hash_invariance_to_timestamp(team_service: TeamService, temp_db: Path) -> None:
    _seed_sample_team(team_service, team_id="team_hash", league="euroleague")

    dossier1 = generate_manager_dossier(team_id="team_hash", team_service=team_service, database_path=temp_db)
    dossier2 = generate_manager_dossier(team_id="team_hash", team_service=team_service, database_path=temp_db)

    # Content hash is identical across runs
    assert dossier1.provenance.content_hash == dossier2.provenance.content_hash
    assert dossier1.provenance.config_hash == dossier2.provenance.config_hash

    # Provenance content_hash depends strictly on quantitative inputs (team_id, round, proj FP, transfer options)
    # and is unaffected even when generated_at and dossier_id vary
    assert dossier1.dossier_id != dossier2.dossier_id

