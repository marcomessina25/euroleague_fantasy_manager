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
        locked_player_ids: Sequence[int] | None = None,
    ) -> list[PlayerProjectionContract]:
        """Optimal initial squad draft recommendation from scratch or completing locked players."""
        market = list(pool or self.prediction_service.get_projections(season, 1))
        if not market:
            return []

        # Deduplicate market by player_id
        seen_pids = set()
        deduped_market: list[PlayerProjectionContract] = []
        for c in market:
            if c.player_id not in seen_pids:
                seen_pids.add(c.player_id)
                deduped_market.append(c)
        market = deduped_market

        locked_set = set(locked_player_ids or [])
        locked_contracts = [c for c in market if c.player_id in locked_set]

        # If user locked all 11 players
        if len(locked_contracts) >= SQUAD_SIZE:
            return locked_contracts[:SQUAD_SIZE]

        def _pos_code(p: Any) -> str:
            if hasattr(p, "short_code"):
                return p.short_code
            try:
                return Position.from_raw(p).short_code
            except Exception:
                return str(p)

        budget_limit_tenths = int(round(budget_credits * 10))

        # 1. Exact Binary Integer Linear Programming (MILP) with scipy
        try:
            import numpy as np
            from scipy.optimize import Bounds, LinearConstraint, milp

            n = len(market)
            obj_weights = np.zeros(n)
            for i, c in enumerate(market):
                if risk_mode.lower() == "conservative":
                    val = c.expected_fp - 0.2 * getattr(c, "uncertainty", 0.0)
                elif risk_mode.lower() == "upside":
                    val = c.expected_fp + 0.2 * getattr(c, "uncertainty", 0.0)
                else:
                    val = c.expected_fp
                obj_weights[i] = -val  # Minimize negative for maximization

            A_rows = []
            b_l = []
            b_u = []

            # Constraint: Budget
            prices = np.array([float(c.price_tenths) for c in market], dtype=float)
            A_rows.append(prices)
            b_l.append(0.0)
            b_u.append(float(budget_limit_tenths))

            # Constraint: Total squad size = 11
            A_rows.append(np.ones(n, dtype=float))
            b_l.append(float(SQUAD_SIZE))
            b_u.append(float(SQUAD_SIZE))

            # Constraints: Position quotas (4G, 4F, 2C, 1HC)
            needed_quotas = {"G": 4, "F": 4, "C": 2, "HC": 1}
            for pos_code, req_quota in needed_quotas.items():
                row = np.array([1.0 if _pos_code(c.position) == pos_code else 0.0 for c in market], dtype=float)
                A_rows.append(row)
                b_l.append(float(req_quota))
                b_u.append(float(req_quota))

            # Constraints: Club quota (max 6 court players per club)
            unique_clubs = set(c.team_id or c.team_code for c in market if _pos_code(c.position) != "HC")
            for club_id in unique_clubs:
                row = np.array(
                    [
                        1.0 if (_pos_code(c.position) != "HC" and (c.team_id or c.team_code) == club_id) else 0.0
                        for c in market
                    ],
                    dtype=float,
                )
                A_rows.append(row)
                b_l.append(0.0)
                b_u.append(6.0)

            # Constraints: Locked players (x_i = 1)
            for i, c in enumerate(market):
                if c.player_id in locked_set:
                    row = np.zeros(n, dtype=float)
                    row[i] = 1.0
                    A_rows.append(row)
                    b_l.append(1.0)
                    b_u.append(1.0)

            A_mat = np.array(A_rows)
            constraints = LinearConstraint(A_mat, b_l, b_u)
            integrality = np.ones(n)
            bounds = Bounds(0.0, 1.0)

            res = milp(c=obj_weights, integrality=integrality, constraints=constraints, bounds=bounds)
            if res.success:
                selected_indices = np.where(res.x > 0.5)[0]
                if len(selected_indices) == SQUAD_SIZE:
                    selected = [market[idx] for idx in selected_indices]
                    val = validate_squad_constraints(selected, budget_tenths=budget_limit_tenths)
                    if val.is_valid:
                        return selected
        except Exception:
            pass

        # 2. Greedy Knapsack Heuristic Fallback
        def _score(c: PlayerProjectionContract) -> float:
            cost = max(1, c.price_tenths)
            return (c.expected_fp * 100.0) / cost

        sorted_pool = sorted(market, key=_score, reverse=True)
        selected = list(locked_contracts)
        pos_counts: dict[str, int] = {"G": 0, "F": 0, "C": 0, "HC": 0}
        club_counts: dict[Any, int] = {}
        for c in selected:
            p_code = _pos_code(c.position)
            if p_code in pos_counts:
                pos_counts[p_code] += 1
            cid = c.team_id or c.team_code
            if p_code != "HC" and cid:
                club_counts[cid] = club_counts.get(cid, 0) + 1

        needed = {"G": 4, "F": 4, "C": 2, "HC": 1}

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

                cid = c.team_id or c.team_code
                if pos != "HC" and cid and club_counts.get(cid, 0) >= 6:
                    continue

                tentative_cost = sum(s.price_tenths for s in selected) + c.price_tenths
                remaining_slots = SQUAD_SIZE - (len(selected) + 1)
                if tentative_cost + (remaining_slots * 40) > budget_limit_tenths:
                    continue

                selected.append(c)
                pos_counts[pos] += 1
                if pos != "HC" and cid:
                    club_counts[cid] = club_counts.get(cid, 0) + 1

        # Fill with cheapest per position if needed
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
        contracts = self.recommend_initial_team(
            season=season,
            budget_credits=budget_credits,
            risk_mode=risk_mode,
            pool=pool,
            locked_player_ids=locked_player_ids,
        )

        budget_limit_tenths = int(round(budget_credits * 10))
        val = validate_squad_constraints(contracts, budget_tenths=budget_limit_tenths)

        player_views = []
        for c in contracts:
            pos_str = c.position.name if hasattr(c.position, "name") else str(c.position)
            player_views.append({
                "player_id": c.player_id,
                "name": c.player_name,
                "position": pos_str,
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
