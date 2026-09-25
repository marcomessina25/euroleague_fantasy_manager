"""Application service for ephemeral what-if scenario simulations (Phase M)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from euroleague_fantasy_manager.optimization.constraints import PlayerProjectionContract
from euroleague_fantasy_manager.services.optimization_service import (
    LineupDecisionView,
    OptimizationService,
)
from euroleague_fantasy_manager.services.prediction_service import PredictionService
from euroleague_fantasy_manager.services.team_service import TeamService


@dataclass
class ScenarioResult:
    """Audited result of an ephemeral what-if scenario compared to baseline."""

    team_id: str
    season: str
    round_number: int
    baseline_lineup: LineupDecisionView
    scenario_lineup: LineupDecisionView
    delta_expected_score: float
    formation_changed: bool
    captain_changed: bool
    starters_added: list[int]
    starters_removed: list[int]
    scenario_inputs: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "season": self.season,
            "round_number": self.round_number,
            "baseline_lineup": self.baseline_lineup.to_dict(),
            "scenario_lineup": self.scenario_lineup.to_dict(),
            "delta_expected_score": round(self.delta_expected_score, 2),
            "formation_changed": self.formation_changed,
            "captain_changed": self.captain_changed,
            "starters_added": self.starters_added,
            "starters_removed": self.starters_removed,
            "scenario_inputs": self.scenario_inputs,
        }


class ScenarioService:
    """Runs isolated disposable simulations without mutating persistent team state."""

    def __init__(
        self,
        team_service: TeamService,
        prediction_service: PredictionService,
        optimization_service: OptimizationService,
    ) -> None:
        self.team_service = team_service
        self.prediction_service = prediction_service
        self.optimization_service = optimization_service

    def simulate(
        self,
        team_id: str,
        season: str = "2026/27",
        round_number: int | None = None,
        rule_out_players: Sequence[int] | None = None,
        force_starters: Sequence[int] | None = None,
        candidate_transfers_out: Sequence[int] | None = None,
        candidate_transfers_in: Sequence[int] | None = None,
        risk_mode_override: str | None = None,
        turn_1_scores: Mapping[int, float] | None = None,
    ) -> ScenarioResult:
        """Execute what-if simulation against ephemeral memory state."""
        team = self.team_service.get_team(team_id)
        rnd = round_number or team.round_number

        # 1. Baseline optimization
        base_risk = team.settings.risk_mode
        baseline_lineup = self.optimization_service.optimize_lineup(
            team_id=team_id,
            season=season,
            round_number=rnd,
            risk_mode=base_risk,
        )

        # 2. Build base projection contracts
        base_contracts = self.optimization_service._resolve_squad_contracts(
            team.squad, season, rnd
        )
        contract_dict = {c.player_id: c for c in base_contracts}

        # 3. Apply transfers if specified
        out_set = set(candidate_transfers_out or [])
        in_list = list(candidate_transfers_in or [])

        if out_set or in_list:
            # Remove transferred out
            for pid in out_set:
                contract_dict.pop(pid, None)

            # Add transferred in from market
            market_dict = self.prediction_service.get_projections_dict(season, rnd)
            for pid in in_list:
                in_c = market_dict.get(pid)
                if in_c:
                    contract_dict[pid] = in_c

        # 4. Apply ruled out players (0.0 FP, 0.0 P(play))
        ruled_out_set = set(rule_out_players or [])
        for pid in ruled_out_set:
            if pid in contract_dict:
                c = contract_dict[pid]
                contract_dict[pid] = PlayerProjectionContract(
                    player_id=c.player_id,
                    player_name=c.player_name,
                    position=c.position,
                    team_id=c.team_id,
                    team_code=c.team_code,
                    price_tenths=c.price_tenths,
                    expected_fp=0.0,
                    probability_play=0.0,
                    expected_minutes=0.0,
                    fp_per_minute=0.0,
                    uncertainty=0.0,
                    prediction_spread=0.0,
                    turn_number=c.turn_number,
                    opponent_code=c.opponent_code,
                    is_home=c.is_home,
                )

        # 5. Apply realized Turn 1 scores
        t1_scores = turn_1_scores or {}
        for pid, score in t1_scores.items():
            if pid in contract_dict:
                c = contract_dict[pid]
                contract_dict[pid] = PlayerProjectionContract(
                    player_id=c.player_id,
                    player_name=c.player_name,
                    position=c.position,
                    team_id=c.team_id,
                    team_code=c.team_code,
                    price_tenths=c.price_tenths,
                    expected_fp=float(score),
                    probability_play=1.0,
                    expected_minutes=c.expected_minutes,
                    fp_per_minute=c.fp_per_minute,
                    uncertainty=0.0,
                    prediction_spread=0.0,
                    turn_number=1,
                    opponent_code=c.opponent_code,
                    is_home=c.is_home,
                )

        # 6. Run scenario lineup optimization
        active_risk = risk_mode_override or base_risk
        scenario_contracts = list(contract_dict.values())
        scenario_lineup = self.optimization_service.optimize_lineup(
            team_id=team_id,
            season=season,
            round_number=rnd,
            risk_mode=active_risk,
            contracts_override=scenario_contracts,
        )

        # 7. Compute deltas
        delta_score = scenario_lineup.expected_total_fp - baseline_lineup.expected_total_fp
        base_starters = set(baseline_lineup.starter_ids)
        scen_starters = set(scenario_lineup.starter_ids)

        return ScenarioResult(
            team_id=team_id,
            season=season,
            round_number=rnd,
            baseline_lineup=baseline_lineup,
            scenario_lineup=scenario_lineup,
            delta_expected_score=round(delta_score, 2),
            formation_changed=(scenario_lineup.formation != baseline_lineup.formation),
            captain_changed=(scenario_lineup.captain_id != baseline_lineup.captain_id),
            starters_added=list(scen_starters - base_starters),
            starters_removed=list(base_starters - scen_starters),
            scenario_inputs={
                "rule_out_players": list(ruled_out_set),
                "force_starters": list(force_starters or []),
                "candidate_transfers_out": list(out_set),
                "candidate_transfers_in": in_list,
                "risk_mode_override": risk_mode_override,
                "turn_1_scores": {k: float(v) for k, v in t1_scores.items()},
            },
        )
