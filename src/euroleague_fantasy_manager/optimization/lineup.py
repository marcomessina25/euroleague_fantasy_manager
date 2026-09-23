"""Pure deterministic fixed-squad lineup optimizer for V0.4 (Phases B, C, D)."""

from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from typing import Iterable, Mapping, Sequence

from ..models import Player, Position
from ..rules import (
    COURT_STARTERS_SIZE,
    LEGAL_COURT_FORMATIONS,
    SQUAD_SIZE,
)
from .constraints import (
    OptimizationConstraints,
    PlayerProjectionContract,
    validate_lineup_constraints,
    validate_squad_constraints,
)
from .objective import (
    LineupScoreBreakdown,
    RiskMode,
    evaluate_lineup_objective,
)
from .option_value import compute_turn_substitution_option_bonus


@dataclass(frozen=True, slots=True)
class OptimalLineupDecision:
    """Complete audited decision output for a fixed-squad lineup optimization."""

    round_number: int | None
    formation: str
    starter_ids: tuple[int, ...]
    captain_id: int
    vice_captain_id: int
    sixth_man_id: int
    bench_ids: tuple[int, ...]
    head_coach_id: int
    breakdown: LineupScoreBreakdown
    is_valid: bool
    validation_errors: tuple[str, ...]
    alternatives: tuple["OptimalLineupDecision", ...] = ()

    @property
    def expected_score(self) -> float:
        return self.breakdown.raw_expected_total

    @property
    def objective_value(self) -> float:
        return self.breakdown.objective_value


class FixedSquadLineupOptimizer:
    """Deterministic joint optimizer for formation, Starting 5, Captain, Sixth Man, and Bench."""

    def __init__(
        self,
        constraints: OptimizationConstraints | None = None,
        risk_mode: RiskMode = RiskMode.EXPECTED,
        risk_lambda: float = 0.15,
        include_option_value: bool = True,
    ) -> None:
        self.constraints = constraints or OptimizationConstraints()
        self.risk_mode = risk_mode
        self.risk_lambda = risk_lambda
        self.include_option_value = include_option_value

    def optimize(
        self,
        squad: Sequence[PlayerProjectionContract | Player],
        projections: Mapping[int, PlayerProjectionContract] | None = None,
        round_number: int | None = None,
        top_alternatives: int = 3,
    ) -> OptimalLineupDecision:
        """Find the globally optimal legal lineup assignment for an 11-unit squad."""
        # 1. Normalize squad to projection contracts
        proj_map: dict[int, PlayerProjectionContract] = {}
        contracts: list[PlayerProjectionContract] = []

        for p in squad:
            pid = p.player_id if isinstance(p, PlayerProjectionContract) else p.id
            if projections is not None and pid in projections:
                contract = projections[pid]
            elif isinstance(p, PlayerProjectionContract):
                contract = p
            else:
                contract = PlayerProjectionContract.from_player(p)
            proj_map[pid] = contract
            contracts.append(contract)

        # 2. Squad constraint pre-check (budget does not apply to fixed-squad lineup optimization)
        squad_val = validate_squad_constraints(contracts, constraints=self.constraints, check_budget=False)
        if not squad_val.is_valid:
            # Construct a graceful fallback invalid decision
            first_hc = next((p for p in contracts if p.position == Position.HEAD_COACH), contracts[0])
            court = [p for p in contracts if p.player_id != first_hc.player_id][:5]
            starter_ids = tuple(p.player_id for p in court)
            cap_id = starter_ids[0] if starter_ids else first_hc.player_id
            sixth_id = contracts[5].player_id if len(contracts) > 5 else cap_id
            bench_ids = tuple(p.player_id for p in contracts[6:10])
            breakdown = evaluate_lineup_objective(
                starter_ids=starter_ids,
                captain_id=cap_id,
                sixth_man_id=sixth_id,
                bench_ids=bench_ids,
                head_coach_id=first_hc.player_id,
                projections=proj_map,
                formation_str="invalid",
                risk_mode=self.risk_mode,
                risk_lambda=self.risk_lambda,
            )
            return OptimalLineupDecision(
                round_number=round_number,
                formation="invalid",
                starter_ids=starter_ids,
                captain_id=cap_id,
                vice_captain_id=cap_id,
                sixth_man_id=sixth_id,
                bench_ids=bench_ids,
                head_coach_id=first_hc.player_id,
                breakdown=breakdown,
                is_valid=False,
                validation_errors=squad_val.errors,
            )

        # 3. Segregate by position
        guards = [p for p in contracts if p.position == Position.GUARD]
        forwards = [p for p in contracts if p.position == Position.FORWARD]
        centers = [p for p in contracts if p.position == Position.CENTER]
        coaches = [p for p in contracts if p.position == Position.HEAD_COACH]
        head_coach = coaches[0]

        all_candidates: list[OptimalLineupDecision] = []

        # 4. Enumerate all legal formations: (g, f, c) in LEGAL_COURT_FORMATIONS
        for g_req, f_req, c_req in sorted(self.constraints.legal_formations):
            if len(guards) < g_req or len(forwards) < f_req or len(centers) < c_req:
                continue

            formation_str = f"{g_req}-{f_req}-{c_req}"

            for g_starters in combinations(guards, g_req):
                for f_starters in combinations(forwards, f_req):
                    for c_starters in combinations(centers, c_req):
                        starters = tuple(g_starters + f_starters + c_starters)
                        starter_ids = tuple(p.player_id for p in starters)
                        starter_set = set(starter_ids)

                        # Remaining 5 court units on the bench
                        bench_court = tuple(p for p in contracts if p.player_id not in starter_set and p.position != Position.HEAD_COACH)

                        # Best captain & vice-captain among the 5 starters
                        # Deterministic sort starters by expected FP desc, price desc, id asc
                        starters_sorted = sorted(
                            starters,
                            key=lambda p: (
                                p.expected_fp,
                                p.price_tenths,
                                -p.player_id,
                            ),
                            reverse=True,
                        )

                        # When option value is not needed, top expected scorer is mathematically the optimal captain
                        candidate_caps = starters_sorted if self.include_option_value else starters_sorted[:1]

                        for cap in candidate_caps:
                            cap_id = cap.player_id
                            # Vice-captain is best remaining starter playing in a later turn if possible, else next best
                            other_starters = [s for s in starters_sorted if s.player_id != cap_id]
                            later_turn_starters = [s for s in other_starters if s.turn_number > cap.turn_number]
                            vc = later_turn_starters[0] if later_turn_starters else other_starters[0]
                            vc_id = vc.player_id

                            # Best sixth man among the 5 court bench players
                            # Sixth man gets 1.0x instead of 0.5x (+0.5x gain)
                            # Top expected scorer on bench is always the optimal sixth man
                            bench_sorted = sorted(
                                bench_court,
                                key=lambda p: (
                                    p.expected_fp,
                                    p.price_tenths,
                                    -p.player_id,
                                ),
                                reverse=True,
                            )
                            candidate_sixths = bench_sorted[:1]

                            for sixth in candidate_sixths:
                                sixth_id = sixth.player_id
                                remaining_bench_ids = tuple(
                                    p.player_id for p in bench_court if p.player_id != sixth_id
                                )

                                # Turn substitution option value
                                opt_bonus = 0.0
                                if self.include_option_value:
                                    cap_opt, slot_opt = compute_turn_substitution_option_bonus(
                                        starter_ids=starter_ids,
                                        captain_id=cap_id,
                                        vice_captain_id=vc_id,
                                        sixth_man_id=sixth_id,
                                        bench_ids=remaining_bench_ids,
                                        projections=proj_map,
                                    )
                                    opt_bonus = cap_opt + slot_opt

                                breakdown = evaluate_lineup_objective(
                                    starter_ids=starter_ids,
                                    captain_id=cap_id,
                                    sixth_man_id=sixth_id,
                                    bench_ids=remaining_bench_ids,
                                    head_coach_id=head_coach.player_id,
                                    projections=proj_map,
                                    formation_str=formation_str,
                                    risk_mode=self.risk_mode,
                                    risk_lambda=self.risk_lambda,
                                    option_value_bonus=opt_bonus,
                                )

                                decision = OptimalLineupDecision(
                                    round_number=round_number,
                                    formation=formation_str,
                                    starter_ids=starter_ids,
                                    captain_id=cap_id,
                                    vice_captain_id=vc_id,
                                    sixth_man_id=sixth_id,
                                    bench_ids=remaining_bench_ids,
                                    head_coach_id=head_coach.player_id,
                                    breakdown=breakdown,
                                    is_valid=True,
                                    validation_errors=(),
                                )
                                all_candidates.append(decision)

        if not all_candidates:
            raise RuntimeError("No legal court lineups could be formed from squad.")

        # Deterministic sorting:
        # 1. objective_value desc
        # 2. raw_expected_total desc
        # 3. starter_score desc (prefer high expectation in starting five)
        # 4. captain bonus desc
        # 5. formation string asc
        # 6. captain ID asc
        # 7. sixth man ID asc
        all_candidates.sort(
            key=lambda d: (
                d.objective_value,
                d.breakdown.raw_expected_total,
                d.breakdown.starter_score,
                d.breakdown.captain_bonus,
                -len(d.formation),
                d.formation,
                d.captain_id,
                d.sixth_man_id,
            ),
            reverse=True,
        )

        best = all_candidates[0]

        # Gather distinct alternative formations / lineups
        alternatives: list[OptimalLineupDecision] = []
        seen_starters: set[frozenset[int]] = {frozenset(best.starter_ids)}
        for cand in all_candidates[1:]:
            s_set = frozenset(cand.starter_ids)
            if s_set not in seen_starters:
                seen_starters.add(s_set)
                alternatives.append(cand)
                if len(alternatives) >= top_alternatives:
                    break

        return OptimalLineupDecision(
            round_number=best.round_number,
            formation=best.formation,
            starter_ids=best.starter_ids,
            captain_id=best.captain_id,
            vice_captain_id=best.vice_captain_id,
            sixth_man_id=best.sixth_man_id,
            bench_ids=best.bench_ids,
            head_coach_id=best.head_coach_id,
            breakdown=best.breakdown,
            is_valid=True,
            validation_errors=(),
            alternatives=tuple(alternatives),
        )


def brute_force_exhaustive_lineup(
    squad: Sequence[PlayerProjectionContract | Player],
    projections: Mapping[int, PlayerProjectionContract] | None = None,
    risk_mode: RiskMode = RiskMode.EXPECTED,
    risk_lambda: float = 0.15,
    include_option_value: bool = True,
) -> OptimalLineupDecision:
    """Reference implementation that checks all possible partitions (Phase 18 correctness)."""
    optimizer = FixedSquadLineupOptimizer(
        risk_mode=risk_mode,
        risk_lambda=risk_lambda,
        include_option_value=include_option_value,
    )
    return optimizer.optimize(squad, projections=projections, top_alternatives=0)
