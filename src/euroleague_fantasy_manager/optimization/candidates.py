"""Candidate generation and measurable filtering for transfers (Phase G)."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

from ..models import Position
from .constraints import OptimizationConstraints, PlayerProjectionContract
from .objective import compute_positional_replacement_levels


@dataclass(frozen=True, slots=True)
class CandidatePool:
    """Position-partitioned pool of eligible transfer targets."""

    guards: tuple[PlayerProjectionContract, ...]
    forwards: tuple[PlayerProjectionContract, ...]
    centers: tuple[PlayerProjectionContract, ...]
    coaches: tuple[PlayerProjectionContract, ...]
    is_exhaustive: bool
    total_candidates: int

    def for_position(self, pos: Position) -> tuple[PlayerProjectionContract, ...]:
        if pos == Position.GUARD:
            return self.guards
        elif pos == Position.FORWARD:
            return self.forwards
        elif pos == Position.CENTER:
            return self.centers
        elif pos == Position.HEAD_COACH:
            return self.coaches
        return ()


class CandidateGenerator:
    """Generate and filter transfer candidate targets while preserving exactness."""

    def __init__(
        self,
        constraints: OptimizationConstraints | None = None,
        max_candidates_per_pos: int = 30,
        min_probability_play: float = 0.05,
    ) -> None:
        self.constraints = constraints or OptimizationConstraints()
        self.max_candidates_per_pos = max_candidates_per_pos
        self.min_probability_play = min_probability_play

    def generate_candidates(
        self,
        market: Sequence[PlayerProjectionContract],
        current_squad: Sequence[PlayerProjectionContract],
        exhaustive: bool = False,
    ) -> CandidatePool:
        """Filter market pool into candidate replacements per position."""
        squad_ids = {p.player_id for p in current_squad}

        # Filter out players already in squad
        eligible = [p for p in market if p.player_id not in squad_ids]

        if exhaustive:
            guards = tuple(p for p in eligible if p.position == Position.GUARD)
            forwards = tuple(p for p in eligible if p.position == Position.FORWARD)
            centers = tuple(p for p in eligible if p.position == Position.CENTER)
            coaches = tuple(p for p in eligible if p.position == Position.HEAD_COACH)
            return CandidatePool(
                guards=guards,
                forwards=forwards,
                centers=centers,
                coaches=coaches,
                is_exhaustive=True,
                total_candidates=len(eligible),
            )

        # Non-exhaustive: measure and filter
        replacements = compute_positional_replacement_levels(eligible)

        by_pos: dict[Position, list[PlayerProjectionContract]] = defaultdict(list)
        for p in eligible:
            if p.probability_play < self.min_probability_play:
                continue
            by_pos[p.position].append(p)

        def score_candidate(p: PlayerProjectionContract) -> tuple[float, float, float]:
            rep = replacements.get(p.position, 0.0)
            surplus = p.expected_fp - rep
            efficiency = p.expected_fp / max(0.5, p.credits)
            return (p.expected_fp, surplus, efficiency)

        filtered: dict[Position, list[PlayerProjectionContract]] = {}
        for pos, players in by_pos.items():
            base_limit = self.max_candidates_per_pos
            if pos == Position.CENTER:
                pos_limit = min(base_limit, max(8, int(base_limit * 0.75)))
            elif pos == Position.HEAD_COACH:
                pos_limit = min(base_limit, max(6, int(base_limit * 0.6)))
            else:
                pos_limit = base_limit

            # Multi-tier candidate selection to ensure multi-player trades can balance budget:
            # 1. Top by raw expected points (elite talent)
            top_raw = sorted(
                players,
                key=lambda x: (x.expected_fp, -x.price_tenths, -x.player_id),
                reverse=True,
            )[:pos_limit]

            # 2. Top by value efficiency (expected points per credit)
            top_eff = sorted(
                players,
                key=lambda x: (x.expected_fp / max(0.5, x.credits), x.expected_fp, -x.price_tenths),
                reverse=True,
            )[:pos_limit]

            # 3. Budget enablers (credits <= 8.0, top by expected points)
            budget_cands = sorted(
                [p for p in players if p.credits <= 8.0],
                key=lambda x: (x.expected_fp, -x.price_tenths),
                reverse=True,
            )[:max(4, pos_limit // 2)]

            # Merge unique candidates preserving rank priority
            merged: list[PlayerProjectionContract] = []
            seen_ids: set[int] = set()
            for cand in top_raw + top_eff + budget_cands:
                if cand.player_id not in seen_ids:
                    seen_ids.add(cand.player_id)
                    merged.append(cand)

            filtered[pos] = merged[:pos_limit]

        g = tuple(filtered.get(Position.GUARD, []))
        f = tuple(filtered.get(Position.FORWARD, []))
        c = tuple(filtered.get(Position.CENTER, []))
        hc = tuple(filtered.get(Position.HEAD_COACH, []))

        total = len(g) + len(f) + len(c) + len(hc)
        return CandidatePool(
            guards=g,
            forwards=f,
            centers=c,
            coaches=hc,
            is_exhaustive=False,
            total_candidates=total,
        )
