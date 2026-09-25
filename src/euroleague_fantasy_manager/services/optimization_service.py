"""Application service for lineup, transfer, and multi-round optimization."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from euroleague_fantasy_manager.models import Position
from euroleague_fantasy_manager.rules import (
    COURT_STARTERS_SIZE,
    SQUAD_QUOTAS,
    SQUAD_SIZE,
)
from euroleague_fantasy_manager.multi_team.models import TeamRosterUnit
from euroleague_fantasy_manager.optimization.constraints import (
    OptimizationConstraints,
    PlayerProjectionContract,
    validate_squad_constraints,
)
from euroleague_fantasy_manager.optimization.initial_team import (
    optimize_initial_team,
    optimize_initial_team_detailed,
)
from euroleague_fantasy_manager.optimization.lineup import (
    FixedSquadLineupOptimizer,
    OptimalLineupDecision,
    brute_force_exhaustive_lineup,
)
from euroleague_fantasy_manager.optimization.multi_round import (
    MultiRoundOptimizer,
    MultiRoundPlan,
)
from euroleague_fantasy_manager.optimization.objective import RiskMode
from euroleague_fantasy_manager.optimization.transfers import (
    TransferOptimizationResult,
    TransferOptimizer,
)
from euroleague_fantasy_manager.services.prediction_service import PredictionService
from euroleague_fantasy_manager.services.team_service import TeamService


@dataclass
class LineupDecisionView:
    """Serializable view of an optimal lineup decision for GUI and API clients."""

    formation: str
    starter_ids: list[int]
    captain_id: int
    sixth_man_id: int
    bench_ids: list[int]
    coach_id: int
    expected_total_fp: float
    starter_score: float
    captain_bonus: float
    sixth_man_score: float
    bench_score: float
    coach_score: float
    is_valid: bool
    unpruned_oracle_match: bool
    starters: list[dict[str, Any]]
    captain: dict[str, Any]
    sixth_man: dict[str, Any]
    bench: list[dict[str, Any]]
    coach: dict[str, Any]
    alternatives: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OptimizationService:
    """Orchestrates deterministic optimizations for teams and GUI workstations."""

    def __init__(
        self,
        team_service: TeamService,
        prediction_service: PredictionService,
        constraints: OptimizationConstraints | None = None,
    ) -> None:
        self.team_service = team_service
        self.prediction_service = prediction_service
        self.constraints = constraints or OptimizationConstraints()
        self.lineup_optimizer = FixedSquadLineupOptimizer(constraints=self.constraints)
        self.transfer_optimizer = TransferOptimizer(constraints=self.constraints)
        self.multi_round_optimizer = MultiRoundOptimizer(constraints=self.constraints)

    def optimize_lineup(
        self,
        team_id: str,
        season: str = "2026/27",
        round_number: int | None = None,
        risk_mode: str = "expected",
        risk_lambda: float = 0.5,
        option_value_mode: str = "captain_eligible",
        contracts_override: Sequence[PlayerProjectionContract] | None = None,
    ) -> LineupDecisionView:
        """Compute optimal lineup, captain, sixth man, and bench for a team's squad."""
        team = self.team_service.get_team(team_id)
        rnd = round_number or team.round_number

        squad_contracts = (
            list(contracts_override)
            if contracts_override is not None
            else self._resolve_squad_contracts(team.squad, season, rnd)
        )

        r_mode = RiskMode.from_str(risk_mode)
        include_opt_val = (option_value_mode.lower() != "none")

        optimizer = FixedSquadLineupOptimizer(
            constraints=self.constraints,
            risk_mode=r_mode,
            risk_lambda=risk_lambda,
            include_option_value=include_opt_val,
        )
        opt_decision = optimizer.optimize(
            squad=squad_contracts,
            round_number=rnd,
        )

        # Oracle cross-validation
        oracle_decision = brute_force_exhaustive_lineup(
            squad=squad_contracts,
            risk_mode=r_mode,
            risk_lambda=risk_lambda,
            include_option_value=include_opt_val,
        )
        oracle_match = (
            abs(opt_decision.objective_value - oracle_decision.objective_value) < 1e-4
            and opt_decision.formation.replace("(", "").replace(")", "").replace(",", "-")
            == oracle_decision.formation.replace("(", "").replace(")", "").replace(",", "-")
        )

        contract_map = {c.player_id: c for c in squad_contracts}

        def _fmt(pid: int) -> dict[str, Any]:
            c = contract_map.get(pid)
            if not c:
                return {"player_id": pid, "name": f"Player {pid}", "position": "G", "expected_fp": 0.0}
            pos_code = c.position.short_code if hasattr(c.position, "short_code") else (
                Position.from_raw(c.position).short_code if hasattr(Position, "from_raw") else str(c.position)
            )
            return {
                "player_id": c.player_id,
                "name": c.player_name,
                "position": pos_code,
                "position_name": c.position.name if hasattr(c.position, "name") else str(c.position),
                "team_code": c.team_code,
                "price_tenths": c.price_tenths,
                "credits": c.credits,
                "expected_fp": round(c.expected_fp, 2),
                "probability_play": round(c.probability_play, 2),
                "uncertainty": round(c.uncertainty, 2),
                "turn_number": c.turn_number,
                "opponent_code": c.opponent_code,
                "is_home": c.is_home,
            }

        starters = [_fmt(pid) for pid in opt_decision.starter_ids]
        captain = _fmt(opt_decision.captain_id)
        sixth_man = _fmt(opt_decision.sixth_man_id)
        bench = [_fmt(pid) for pid in opt_decision.bench_ids]
        coach = _fmt(opt_decision.head_coach_id)

        alts: list[dict[str, Any]] = []
        for alt in opt_decision.alternatives:
            alts.append({
                "formation": alt.formation,
                "expected_score": round(alt.expected_score, 2),
                "starter_ids": list(alt.starter_ids),
                "captain_id": alt.captain_id,
                "sixth_man_id": alt.sixth_man_id,
            })

        return LineupDecisionView(
            formation=opt_decision.formation,
            starter_ids=list(opt_decision.starter_ids),
            captain_id=opt_decision.captain_id,
            sixth_man_id=opt_decision.sixth_man_id,
            bench_ids=list(opt_decision.bench_ids),
            coach_id=opt_decision.head_coach_id,
            expected_total_fp=round(opt_decision.expected_score, 2),
            starter_score=round(opt_decision.breakdown.starter_score, 2),
            captain_bonus=round(opt_decision.breakdown.captain_bonus, 2),
            sixth_man_score=round(opt_decision.breakdown.sixth_man_score, 2),
            bench_score=round(opt_decision.breakdown.bench_score, 2),
            coach_score=round(opt_decision.breakdown.head_coach_score, 2),
            is_valid=opt_decision.is_valid,
            unpruned_oracle_match=oracle_match,
            starters=starters,
            captain=captain,
            sixth_man=sixth_man,
            bench=bench,
            coach=coach,
            alternatives=alts,
        )

    def optimize_transfers(
        self,
        team_id: str,
        season: str = "2026/27",
        round_number: int | None = None,
        max_trades: int = 1,
        unlimited: bool = False,
        candidate_pool: Sequence[PlayerProjectionContract] | None = None,
        exhaustive: bool = False,
    ) -> TransferOptimizationResult:
        """Find optimal trade combinations for the team."""
        team = self.team_service.get_team(team_id)
        rnd = round_number or team.round_number

        squad_contracts = self._resolve_squad_contracts(team.squad, season, rnd)
        market = (
            list(candidate_pool)
            if candidate_pool is not None
            else self.prediction_service.get_projections(season, rnd)
        )

        return self.transfer_optimizer.optimize_transfers(
            current_squad=squad_contracts,
            market=market,
            bank_tenths=team.bank_tenths,
            round_number=rnd,
            max_trades=max_trades,
            unlimited=unlimited,
            exhaustive_candidates=exhaustive,
        )

    def plan_multi_round(
        self,
        team_id: str,
        season: str = "2026/27",
        start_round: int | None = None,
        horizon: int = 3,
        gamma: float = 0.95,
        beam_width: int = 4,
    ) -> MultiRoundPlan:
        """Run beam search multi-round transfer planner across N rounds."""
        team = self.team_service.get_team(team_id)
        s_rnd = start_round or team.round_number

        pool_by_round: dict[int, list[PlayerProjectionContract]] = {}
        for r in range(s_rnd, s_rnd + horizon):
            pool_by_round[r] = self.prediction_service.get_projections(season, r)

        squad_contracts = self._resolve_squad_contracts(team.squad, season, s_rnd)

        self.multi_round_optimizer.discount_factor = gamma
        self.multi_round_optimizer.branching_factor = beam_width

        return self.multi_round_optimizer.optimize_multi_round(
            start_round=s_rnd,
            horizon=horizon,
            initial_squad=squad_contracts,
            projections_by_round=pool_by_round,
            initial_bank_tenths=team.bank_tenths,
        )

    def recommend_initial_team(
        self,
        season: str = "2026/27",
        budget_credits: float = 100.0,
        risk_mode: str = "expected",
        pool: Sequence[PlayerProjectionContract] | None = None,
        locked_player_ids: Sequence[int] | None = None,
    ) -> list[PlayerProjectionContract]:
        """Optimal initial squad draft recommendation from scratch or completing locked players."""
        market = list(pool or self.prediction_service.get_projections(season, 1))
        if not market:
            return []
        try:
            return optimize_initial_team(
                pool=market,
                budget_credits=budget_credits,
                risk_mode=risk_mode,
                locked_player_ids=locked_player_ids,
            )
        except ValueError:
            return []

    def suggest_initial_team(
        self,
        season: str = "2026/27",
        budget_credits: float = 100.0,
        risk_mode: str = "expected",
        locked_player_ids: Sequence[int] | None = None,
        pool: Sequence[PlayerProjectionContract] | None = None,
    ) -> dict[str, Any]:
        """Suggest optimal 11-player squad with breakdown and validation for GUI."""
        locked_set = set(locked_player_ids or [])
        market = list(pool or self.prediction_service.get_projections(season, 1))
        budget_limit_tenths = int(round(budget_credits * 10))

        if not market:
            return {
                "suggested_player_ids": [],
                "players": [],
                "total_credits": 0.0,
                "remaining_credits": budget_credits,
                "expected_total_fp": 0.0,
                "is_valid": False,
                "validation_errors": ["No player projections available."],
                "objective": "round_1_expected_fp_maximization",
                "strategy_description": "Round-1 starting squad optimization under budget & fantasy rules",
            }

        try:
            detailed = optimize_initial_team_detailed(
                pool=market,
                budget_credits=budget_credits,
                risk_mode=risk_mode,
                locked_player_ids=locked_player_ids,
            )
            contracts = detailed.squad
            obj_name = detailed.objective_name
            strat_desc = detailed.strategy_description
        except ValueError as e:
            return {
                "suggested_player_ids": [],
                "players": [],
                "total_credits": 0.0,
                "remaining_credits": budget_credits,
                "expected_total_fp": 0.0,
                "is_valid": False,
                "validation_errors": [str(e)],
                "objective": "round_1_expected_fp_maximization",
                "strategy_description": "Round-1 starting squad optimization under budget & fantasy rules",
            }

        val = validate_squad_constraints(contracts, budget_tenths=budget_limit_tenths)

        player_views = []
        for c in contracts:
            pos_code = c.position.short_code if hasattr(c.position, "short_code") else (
                Position.from_raw(c.position).short_code if hasattr(Position, "from_raw") else str(c.position)
            )
            player_views.append({
                "player_id": c.player_id,
                "name": c.player_name,
                "position": pos_code,
                "position_name": c.position.name if hasattr(c.position, "name") else str(c.position),
                "team_code": c.team_code,
                "price_tenths": c.price_tenths,
                "credits": round(c.price_tenths / 10.0, 1),
                "expected_fp": round(c.expected_fp, 2),
                "probability_play": round(c.probability_play, 2),
                "is_locked": c.player_id in locked_set,
                "turn_number": c.turn_number,
                "opponent_code": c.opponent_code,
                "is_home": c.is_home,
            })

        total_cost_tenths = sum(c.price_tenths for c in contracts)
        total_exp_fp = sum(c.expected_fp for c in contracts)

        return {
            "suggested_player_ids": [c.player_id for c in contracts],
            "players": player_views,
            "total_credits": round(total_cost_tenths / 10.0, 1),
            "remaining_credits": round((budget_limit_tenths - total_cost_tenths) / 10.0, 1),
            "expected_total_fp": round(total_exp_fp, 2),
            "is_valid": val.is_valid,
            "validation_errors": list(val.errors),
            "objective": obj_name,
            "strategy_description": strat_desc,
        }

    def _resolve_squad_contracts(
        self,
        squad_units: Sequence[TeamRosterUnit],
        season: str,
        round_number: int,
    ) -> list[PlayerProjectionContract]:
        """Convert TeamRosterUnits into valid PlayerProjectionContracts."""
        projections_dict = self.prediction_service.get_projections_dict(season, round_number)
        contracts: list[PlayerProjectionContract] = []

        for unit in squad_units:
            proj = projections_dict.get(unit.player_id)
            if proj is not None:
                contracts.append(proj)
            else:
                # Synthesize valid contract from unit metadata
                pos = Position.from_raw(unit.position)
                contracts.append(
                    PlayerProjectionContract(
                        player_id=unit.player_id,
                        player_name=unit.name or f"Player {unit.player_id}",
                        position=pos,
                        team_id=None,
                        team_code=unit.team_code or "UNK",
                        price_tenths=unit.current_price_tenths,
                        expected_fp=10.0 if pos != Position.HEAD_COACH else 8.0,
                        probability_play=1.0,
                        expected_minutes=20.0,
                        turn_number=unit.turn_number,
                    )
                )

        return contracts
