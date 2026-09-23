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
            return {
                "player_id": c.player_id,
                "name": c.player_name,
                "position": c.position.name if hasattr(c.position, "name") else str(c.position),
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
        beam_width: int = 5,
    ) -> MultiRoundPlan:
        """Run beam search multi-round transfer planner across N rounds."""
        team = self.team_service.get_team(team_id)
        s_rnd = start_round or team.round_number

        pool_by_round: dict[int, list[PlayerProjectionContract]] = {}
        for r in range(s_rnd, s_rnd + horizon):
            pool_by_round[r] = self.prediction_service.get_projections(season, r)

        squad_contracts = self._resolve_squad_contracts(team.squad, season, s_rnd)

        return self.multi_round_optimizer.optimize_multi_round(
            initial_squad=squad_contracts,
            pool_by_round=pool_by_round,
            start_round=s_rnd,
            horizon=horizon,
            initial_bank_tenths=team.bank_tenths,
            discount_gamma=gamma,
            beam_width=beam_width,
        )

    def recommend_initial_team(
        self,
        season: str = "2026/27",
        budget_credits: float = 100.0,
        risk_mode: str = "expected",
        pool: Sequence[PlayerProjectionContract] | None = None,
    ) -> list[PlayerProjectionContract]:
        """Greedy knapsack draft recommendation for pre-season team creation (V0.5 Bridge)."""
        market = list(pool or self.prediction_service.get_projections(season, 1))
        if not market:
            return []

        # Sort market by expected_fp / price_tenths ratio (value density)
        def _score(c: PlayerProjectionContract) -> float:
            cost = max(1, c.price_tenths)
            return (c.expected_fp * 100.0) / cost

        sorted_pool = sorted(market, key=_score, reverse=True)

        budget_limit_tenths = int(budget_credits * 10)
        selected: list[PlayerProjectionContract] = []
        club_counts: dict[int, int] = {}
        pos_counts: dict[str, int] = {"G": 0, "F": 0, "C": 0, "HC": 0}
        needed = {"G": 4, "F": 4, "C": 2, "HC": 1}

        def _pos_code(p: Any) -> str:
            if hasattr(p, "short_code"):
                return p.short_code
            try:
                return Position.from_raw(p).short_code
            except Exception:
                return str(p)

        # Select position requirements
        for pos, quota in needed.items():
            for c in sorted_pool:
                c_pos = _pos_code(c.position)
                if c_pos != pos:
                    continue
                if pos_counts[pos] >= quota:
                    break
                if c.player_id in [s.player_id for s in selected]:
                    continue

                # Club constraint (max 6 court players per club)
                cid = c.team_id or 0
                if pos != "HC" and club_counts.get(cid, 0) >= 6:
                    continue

                # Tentative budget check
                tentative_cost = sum(s.price_tenths for s in selected) + c.price_tenths
                # Leave at least 5.0 cr for remaining empty slots
                remaining_slots = SQUAD_SIZE - (len(selected) + 1)
                if tentative_cost + (remaining_slots * 50) > budget_limit_tenths:
                    continue

                selected.append(c)
                pos_counts[pos] += 1
                if pos != "HC":
                    club_counts[cid] = club_counts.get(cid, 0) + 1

        # If not enough picked due to budget, fill with cheapest available per position
        for pos, quota in needed.items():
            while pos_counts[pos] < quota:
                cheapest = sorted(
                    [c for c in sorted_pool if _pos_code(c.position) == pos and c.player_id not in [s.player_id for s in selected]],
                    key=lambda c: c.price_tenths,
                )
                if not cheapest:
                    break
                pick = cheapest[0]
                selected.append(pick)
                pos_counts[pos] += 1

        return selected

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
