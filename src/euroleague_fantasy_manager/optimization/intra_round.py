"""Intra-Round Substitution Optimizer for EuroLeague Fantasy Challenge.

Evaluates and computes mathematically optimal legal substitutions between
the active court/sixth man and bench units across game turns (T1 -> T2 -> T3).

Core EuroLeague Fantasy Challenge Rules:
1. Bench players whose match has already started/finished ('has_played' == True)
   are locked on the bench at 0.5x multiplier and CANNOT enter the court or sixth man.
2. Bench players who have NOT played yet ('has_played' == False) are eligible
   to be subbed into Starters (1.0x / 2.0x for captain) or Sixth Man (1.0x).
3. Active Starters and Sixth Man (whether they have played or not) can be subbed
   out to the bench (multiplier becomes 0.5x).
4. The Head Coach is fixed and out of the substitution simulator (1.0x).
5. The Starting 5 must satisfy EuroLeague formation quotas:
   - 1 to 3 Guards (G)
   - 1 to 3 Forwards (F)
   - 1 to 2 Centers (C)
   - Exactly 5 starters
6. Exactly 1 Sixth Man (any eligible court player not in Starting 5, 1.0x).
7. Exactly 4 Bench units (all locked played bench players must be in bench, 0.5x).
8. Captaincy:
   - Must be one of the Starting 5 (2.0x).
   - If current captain has already played, captaincy can be retained (if score was good)
     or switched to a starter who has NOT played yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Mapping, Sequence

from euroleague_fantasy_manager.models import Position


def _normalize_pos(pos: Any) -> str:
    if hasattr(pos, "short_code"):
        return str(pos.short_code).upper()
    if hasattr(pos, "name"):
        p = str(pos.name).upper()
    else:
        p = str(pos).upper()
    if "GUARD" in p or p == "G" or p == "1":
        return "G"
    if "FORWARD" in p or p == "F" or p == "2":
        return "F"
    if "CENTER" in p or p == "C" or p == "3":
        return "C"
    if "COACH" in p or p == "HC" or p == "4":
        return "HC"
    return p


@dataclass(frozen=True)
class IntraRoundPlayerUnit:
    """Player representation in the intra-round substitution context."""

    player_id: int
    name: str
    position: str  # G, F, C, HC
    team_code: str = ""
    credits: float = 10.0
    turn_number: int = 1
    has_played: bool = False
    actual_fp: float | None = None
    expected_fp: float = 0.0
    current_role: str = "starter"  # starter, sixth_man, bench, coach
    is_captain: bool = False

    @property
    def effective_fp(self) -> float:
        """Realized points if played, otherwise expected projection."""
        if self.has_played and self.actual_fp is not None:
            return float(self.actual_fp)
        return float(self.expected_fp)

    @property
    def is_coach(self) -> bool:
        return self.position == "HC" or self.current_role == "coach"


@dataclass
class IntraRoundSubstitutionResult:
    """Optimal legal intra-round substitution decision package."""

    baseline_total_fp: float
    optimized_total_fp: float
    net_gain: float
    starter_ids: list[int]
    captain_id: int
    sixth_man_id: int
    bench_ids: list[int]
    coach_id: int
    formation: str
    substitutions: list[dict[str, Any]] = field(default_factory=list)
    captain_changed: bool = False
    captain_change_detail: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_total_fp": round(self.baseline_total_fp, 2),
            "baseline_score": round(self.baseline_total_fp, 2),
            "optimized_total_fp": round(self.optimized_total_fp, 2),
            "optimal_score": round(self.optimized_total_fp, 2),
            "net_gain": round(self.net_gain, 2),
            "starter_ids": self.starter_ids,
            "captain_id": self.captain_id,
            "sixth_man_id": self.sixth_man_id,
            "bench_ids": self.bench_ids,
            "coach_id": self.coach_id,
            "formation": self.formation,
            "substitutions": self.substitutions,
            "recommended_substitutions": self.substitutions,
            "captain_changed": self.captain_changed,
            "captain_change_detail": self.captain_change_detail,
        }


class IntraRoundSubstitutionOptimizer:
    """Mathematical optimizer for legal intra-round bench-to-court substitutions."""

    def optimize(
        self,
        squad_units: Sequence[IntraRoundPlayerUnit],
        captain_id: int | None = None,
    ) -> IntraRoundSubstitutionResult:
        """Find the optimal legal intra-round substitutions within the manager's team."""
        # 1. Separate coach from court players
        coach_unit = next((u for u in squad_units if u.is_coach), None)
        court_units = [u for u in squad_units if not u.is_coach]
        coach_id = coach_unit.player_id if coach_unit else 0
        coach_fp = coach_unit.effective_fp if coach_unit else 0.0

        unit_by_id = {u.player_id: u for u in squad_units}

        # Determine current layout
        curr_starters = [u for u in court_units if u.current_role == "starter"]
        curr_sixth = next((u for u in court_units if u.current_role == "sixth_man"), None)
        curr_bench = [u for u in court_units if u.current_role == "bench"]

        curr_cap_id = captain_id
        if not curr_cap_id:
            cap_u = next((u for u in court_units if u.is_captain), None)
            curr_cap_id = cap_u.player_id if cap_u else (curr_starters[0].player_id if curr_starters else 0)

        # Baseline score calculation
        baseline_fp = coach_fp
        for u in curr_starters:
            mult = 2.0 if u.player_id == curr_cap_id else 1.0
            baseline_fp += u.effective_fp * mult
        if curr_sixth:
            baseline_fp += curr_sixth.effective_fp * 1.0
        for u in curr_bench:
            baseline_fp += u.effective_fp * 0.5

        # 2. Rule Enforcement:
        # Bench players who have ALREADY played cannot enter the court or sixth man!
        # They MUST remain on the bench.
        locked_bench_units = [u for u in curr_bench if u.has_played]
        locked_bench_ids = {u.player_id for u in locked_bench_units}

        # Available court candidates for Starters, Sixth Man, and remaining Bench slots
        allocatable_court_units = [u for u in court_units if u.player_id not in locked_bench_ids]
        allocatable_ids = {u.player_id for u in allocatable_court_units}

        # We need to select 5 Starters from allocatable_court_units
        best_score = baseline_fp
        best_starters: tuple[int, ...] = tuple(u.player_id for u in curr_starters)
        best_sixth: int = curr_sixth.player_id if curr_sixth else 0
        best_bench: tuple[int, ...] = tuple(u.player_id for u in curr_bench)
        best_cap: int = curr_cap_id
        best_formation = "2-2-1"

        # Precompute positions
        pos_map = {u.player_id: _normalize_pos(u.position) for u in court_units}
        score_map = {u.player_id: u.effective_fp for u in court_units}
        played_map = {u.player_id: u.has_played for u in court_units}

        # Iterate over all legal 5-starter combinations from allocatable units
        for starter_combo in combinations(allocatable_court_units, 5):
            s_ids = tuple(u.player_id for u in starter_combo)
            g_cnt = sum(1 for pid in s_ids if pos_map[pid] == "G")
            f_cnt = sum(1 for pid in s_ids if pos_map[pid] == "F")
            c_cnt = sum(1 for pid in s_ids if pos_map[pid] == "C")

            # Check legal EuroLeague formation: 1-3 G, 1-3 F, 1-2 C
            if not (1 <= g_cnt <= 3 and 1 <= f_cnt <= 3 and 1 <= c_cnt <= 2):
                continue

            formation = f"{g_cnt}-{f_cnt}-{c_cnt}"
            s_ids_set = set(s_ids)
            remaining_for_sixth_and_bench = [u for u in allocatable_court_units if u.player_id not in s_ids_set]

            # Choose 1 Sixth Man from the remaining allocatable units
            for sixth_u in remaining_for_sixth_and_bench:
                sixth_id = sixth_u.player_id
                remaining_bench_ids = tuple(
                    u.player_id for u in remaining_for_sixth_and_bench if u.player_id != sixth_id
                ) + tuple(locked_bench_ids)

                if len(remaining_bench_ids) != 4:
                    continue

                # Determine legal Captaincy for this starting 5
                # Captain options:
                # 1. Retain current captain (if he is in this starter combo)
                # 2. Or any starter who has NOT played yet (has_played == False)
                # Note: A player who already played cannot BECOME the new captain if not already captain!
                candidate_caps: list[int] = []
                if curr_cap_id in s_ids_set:
                    candidate_caps.append(curr_cap_id)
                for pid in s_ids:
                    if not played_map[pid] and pid not in candidate_caps:
                        candidate_caps.append(pid)

                if not candidate_caps:
                    candidate_caps = [s_ids[0]]

                for cap_id in candidate_caps:
                    score = coach_fp
                    for pid in s_ids:
                        mult = 2.0 if pid == cap_id else 1.0
                        score += score_map[pid] * mult
                    score += score_map[sixth_id] * 1.0
                    for pid in remaining_bench_ids:
                        score += score_map[pid] * 0.5

                    if score > best_score + 1e-4:
                        best_score = score
                        best_starters = s_ids
                        best_sixth = sixth_id
                        best_bench = remaining_bench_ids
                        best_cap = cap_id
                        best_formation = formation

        net_gain = max(0.0, round(best_score - baseline_fp, 2))

        # Detect swaps and generate explanation
        curr_starter_set = {u.player_id for u in curr_starters}
        new_starter_set = set(best_starters)
        curr_bench_set = {u.player_id for u in curr_bench}
        new_bench_set = set(best_bench)

        # Starters moving to bench
        moved_to_bench = [unit_by_id[pid] for pid in (curr_starter_set & new_bench_set)]
        # Bench moving to starters
        moved_to_starters = [unit_by_id[pid] for pid in (curr_bench_set & new_starter_set)]

        # Sixth man transitions
        if curr_sixth and best_sixth != curr_sixth.player_id:
            if curr_sixth.player_id in new_bench_set:
                moved_to_bench.append(curr_sixth)
            if best_sixth in curr_bench_set:
                moved_to_starters.append(unit_by_id[best_sixth])

        substitutions_list = []
        for out_u, in_u in zip(moved_to_bench, moved_to_starters):
            substitutions_list.append({
                "out_player": {
                    "player_id": out_u.player_id,
                    "name": out_u.name,
                    "position": out_u.position,
                    "score": out_u.effective_fp,
                    "has_played": out_u.has_played,
                },
                "in_player": {
                    "player_id": in_u.player_id,
                    "name": in_u.name,
                    "position": in_u.position,
                    "score": in_u.effective_fp,
                    "has_played": in_u.has_played,
                },
                "projected_gain": round((in_u.effective_fp - out_u.effective_fp) * 0.5, 2),
            })

        cap_changed = (best_cap != curr_cap_id)
        cap_detail = None
        if cap_changed and curr_cap_id in unit_by_id and best_cap in unit_by_id:
            old_c = unit_by_id[curr_cap_id]
            new_c = unit_by_id[best_cap]
            cap_detail = {
                "old_captain": {"player_id": old_c.player_id, "name": old_c.name, "score": old_c.effective_fp},
                "new_captain": {"player_id": new_c.player_id, "name": new_c.name, "score": new_c.effective_fp},
                "captain_gain": round(new_c.effective_fp - old_c.effective_fp, 2),
            }

        return IntraRoundSubstitutionResult(
            baseline_total_fp=round(baseline_fp, 2),
            optimized_total_fp=round(best_score, 2),
            net_gain=net_gain,
            starter_ids=list(best_starters),
            captain_id=best_cap,
            sixth_man_id=best_sixth,
            bench_ids=list(best_bench),
            coach_id=coach_id,
            formation=best_formation,
            substitutions=substitutions_list,
            captain_changed=cap_changed,
            captain_change_detail=cap_detail,
        )
