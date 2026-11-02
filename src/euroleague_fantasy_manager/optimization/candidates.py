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
        max_candidates_per_pos: int = 15,
        min_probability_play: float = 0.05,
    ) -> None:
        if constraints is None:
            from euroleague_fantasy_manager.competition.ruleset import get_league_ruleset
            self.constraints = OptimizationConstraints.from_ruleset(get_league_ruleset())
        else:
            self.constraints = constraints
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

        # Measure and filter
        replacements = compute_positional_replacement_levels(eligible)

        by_pos: dict[Position, list[PlayerProjectionContract]] = defaultdict(list)
        for p in eligible:
            if not exhaustive and p.probability_play < self.min_probability_play:
                continue
            by_pos[p.position].append(p)

        def score_candidate(p: PlayerProjectionContract) -> tuple[float, float, float]:
            rep = replacements.get(p.position, 0.0)
            surplus = p.expected_fp - rep
            efficiency = p.expected_fp / max(0.5, p.credits)
            return (p.expected_fp, surplus, efficiency)

        filtered: dict[Position, list[PlayerProjectionContract]] = {}
        for pos, players in by_pos.items():
            sorted_players = sorted(
                players,
                key=lambda x: (
                    score_candidate(x)[0],
                    score_candidate(x)[1],
                    score_candidate(x)[2],
                    -x.price_tenths,
                    -x.player_id,
                ),
                reverse=True,
            )
            if exhaustive:
                filtered[pos] = sorted_players
            else:
                limit = self.max_candidates_per_pos
                if pos == Position.CENTER:
                    limit = min(limit, max(4, limit // 2))
                elif pos == Position.HEAD_COACH:
                    limit = min(limit, max(2, limit // 2))
                filtered[pos] = sorted_players[:limit]

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
            is_exhaustive=exhaustive,
            total_candidates=total,
        )
