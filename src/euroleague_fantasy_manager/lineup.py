"""Turn-Aware Lineup, Sixth-Man, Bench, and Captaincy Optimizer (`elf lineup`) with T1->T2 Real Option Value."""

from collections import Counter
from dataclasses import asdict, dataclass
from itertools import combinations
import json
from pathlib import Path
from typing import Any, Iterable

from .expected_points import PlayerProjection, project_all_players
from .fixtures import DATABASE_PATH, DEFAULT_SQUAD_PATH, PROJECT_ROOT, get_current_round, normal_cdf, normal_pdf
from .models import Player, Position
from .rules import (
    BENCH_MULTIPLIER,
    CAPTAIN_MULTIPLIER,
    HEAD_COACH_MULTIPLIER,
    LEGAL_COURT_FORMATIONS,
    SIXTH_MAN_MULTIPLIER,
    STARTER_MULTIPLIER,
    validate_court_lineup,
)
from .squad_state import load_current_squad
from .storage import SnapshotStore

LINEUP_REPORT_PATH = PROJECT_ROOT / "reports" / "lineup_report.json"


@dataclass(frozen=True, slots=True)
class LineupRecommendation:
    round_number: int
    formation: str
    captain_id: int
    captain_name: str
    vice_captain_id: int
    vice_captain_name: str
    sixth_man_id: int
    sixth_man_name: str
    head_coach_id: int
    head_coach_name: str
    starter_ids: tuple[int, ...]
    bench_ids: tuple[int, ...]
    static_xpdk: float
    captain_option_bonus_xpdk: float
    slot_option_bonus_xpdk: float
    total_turn_adjusted_xpdk: float
    is_valid: bool
    validation_errors: tuple[str, ...]
    starters_detail: tuple[dict[str, Any], ...]
    sixth_man_detail: dict[str, Any]
    bench_detail: tuple[dict[str, Any], ...]
    head_coach_detail: dict[str, Any]


def gaussian_call_option(mu_backup: float, mu_primary: float, sigma_primary: float) -> float:
    """Compute E[max(0, mu_backup - S_primary)] where S_primary ~ N(mu_primary, sigma_primary^2).

    Represents the expected improvement when we observe S_primary in Turn 1 and switch to
    the Turn 2 backup (with expectation mu_backup) whenever S_primary < mu_backup.
    """
    if sigma_primary <= 0.05:
        return max(0.0, mu_backup - mu_primary)
    z = (mu_backup - mu_primary) / sigma_primary
    return max(0.0, (mu_backup - mu_primary) * normal_cdf(z) + sigma_primary * normal_pdf(z))


def _can_substitute_into_valid_formation(
    starters: tuple[Player, ...],
    out_starter: Player,
    in_bench: Player,
) -> bool:
    """Return True if swapping `out_starter` with `in_bench` leaves a legal G-F-C formation."""
    if out_starter.position == in_bench.position:
        return True
    new_counts = Counter(p.position for p in starters if p.id != out_starter.id)
    new_counts[in_bench.position] += 1
    formation = (
        new_counts[Position.GUARD],
        new_counts[Position.FORWARD],
        new_counts[Position.CENTER],
    )
    return formation in LEGAL_COURT_FORMATIONS


def compute_turn_option_bonuses(
    starters: tuple[Player, ...],
    sixth_man: Player,
    bench: tuple[Player, ...],
    captain: Player,
    vice_captain: Player,
    projections: dict[int, PlayerProjection],
) -> tuple[float, float]:
    """Compute (captain_option_bonus_xpdk, slot_option_bonus_xpdk) from T1 -> T2/T3 substitution rights."""
    cap_proj = projections[captain.id]
    vc_proj = projections[vice_captain.id]

    # 1. Captaincy switch option value (if Captain plays in an earlier Turn than Vice-Captain)
    cap_option_bonus = 0.0
    if cap_proj.turn_number < vc_proj.turn_number and vc_proj.expected_pdk > 0.0:
        cap_option_bonus = gaussian_call_option(
            mu_backup=vc_proj.expected_pdk,
            mu_primary=cap_proj.expected_pdk,
            sigma_primary=cap_proj.sigma_pdk,
        )

    # 2. Field/Sixth-Man (1.0x) vs Bench (0.5x) substitution option value:
    # Active 1.0x players in earlier turns can be swapped for 0.5x bench players in later turns
    active_1x = list(starters) + [sixth_man]
    early_active = [
        p for p in active_1x
        if projections[p.id].turn_number == 1 and projections[p.id].expected_pdk > 0.0
    ]
    late_bench = [
        b for b in bench
        if projections[b.id].turn_number > 1 and projections[b.id].expected_pdk > 0.0
    ]

    early_active.sort(key=lambda p: projections[p.id].expected_pdk)
    late_bench.sort(key=lambda p: projections[p.id].expected_pdk, reverse=True)

    used_bench_ids: set[int] = set()
    slot_option_bonus = 0.0

    for primary in early_active:
        p_proj = projections[primary.id]
        for backup in late_bench:
            if backup.id in used_bench_ids:
                continue
            # Sixth man can be any court position; starter swap must preserve legal formation
            is_legal_swap = (
                primary.id == sixth_man.id
                or _can_substitute_into_valid_formation(starters, primary, backup)
            )
            if is_legal_swap:
                b_proj = projections[backup.id]
                # Gain is 0.5 * E[max(0, mu_backup - S_primary)] because bench already scores 0.5x
                slot_option_bonus += 0.5 * gaussian_call_option(
                    mu_backup=b_proj.expected_pdk,
                    mu_primary=p_proj.expected_pdk,
                    sigma_primary=p_proj.sigma_pdk,
                )
                used_bench_ids.add(backup.id)
                break

    return round(cap_option_bonus, 2), round(slot_option_bonus, 2)


def optimize_court_lineup(
    squad: Iterable[Player],
    projections: dict[int, PlayerProjection],
    round_number: int = 1,
) -> LineupRecommendation:
    """Exhaustively evaluate all legal Starting 5 formations, 6th Man, 4 Bench, and Captain assignments."""
    squad_list = list(squad)
    coaches = [p for p in squad_list if p.position == Position.HEAD_COACH]
    court_players = [p for p in squad_list if p.position != Position.HEAD_COACH]

    if len(coaches) != 1 or len(court_players) != 10:
        raise ValueError(
            f"Lineup optimizer requires 10 court players and 1 Head Coach; received {len(court_players)} players and {len(coaches)} coaches."
        )

    head_coach = coaches[0]
    coach_proj = projections[head_coach.id]

    best_score: tuple[float, float] = (-1e9, -1e9)
    best_config: tuple[
        tuple[Player, ...],
        Player,
        tuple[Player, ...],
        Player,
        Player,
        str,
        float,
        float,
        float,
    ] | None = None

    for starters in combinations(court_players, 5):
        pos_counts = Counter(p.position for p in starters)
        formation_tuple = (
            pos_counts[Position.GUARD],
            pos_counts[Position.FORWARD],
            pos_counts[Position.CENTER],
        )
        if formation_tuple not in LEGAL_COURT_FORMATIONS:
            continue

        formation_str = f"{formation_tuple[0]}-{formation_tuple[1]}-{formation_tuple[2]}"
        starter_id_set = {p.id for p in starters}
        non_starters = [p for p in court_players if p.id not in starter_id_set]

        starters_sum = sum(projections[p.id].expected_pdk for p in starters)

        for sixth_man in non_starters:
            bench = tuple(
                sorted(
                    (p for p in non_starters if p.id != sixth_man.id),
                    key=lambda p: (projections[p.id].expected_pdk, -projections[p.id].turn_number),
                    reverse=True,
                )
            )
            bench_half_sum = 0.5 * sum(projections[b.id].expected_pdk for b in bench)
            sixth_xp = projections[sixth_man.id].expected_pdk

            for captain in starters:
                cap_xp = projections[captain.id].expected_pdk
                static_xpdk = (
                    coach_proj.expected_pdk
                    + starters_sum
                    + cap_xp  # extra 1.0x for 2.0x Captain
                    + sixth_xp
                    + bench_half_sum
                )

                # Best Vice-Captain (prefer later-turn starter or 6th man for T1->T2 captain switch)
                vc_candidates = [p for p in list(starters) + [sixth_man] if p.id != captain.id]
                vc_candidates.sort(
                    key=lambda p: (
                        1 if projections[p.id].turn_number > projections[captain.id].turn_number else 0,
                        projections[p.id].expected_pdk,
                    ),
                    reverse=True,
                )
                vice_captain = vc_candidates[0]

                cap_opt, slot_opt = compute_turn_option_bonuses(
                    starters=starters,
                    sixth_man=sixth_man,
                    bench=bench,
                    captain=captain,
                    vice_captain=vice_captain,
                    projections=projections,
                )
                total_xpdk = round(static_xpdk + cap_opt + slot_opt, 2)
                candidate_key = (total_xpdk, round(starters_sum, 2))

                if candidate_key > best_score:
                    best_score = candidate_key
                    best_config = (
                        starters,
                        sixth_man,
                        bench,
                        captain,
                        vice_captain,
                        formation_str,
                        round(static_xpdk, 2),
                        cap_opt,
                        slot_opt,
                    )

    if best_config is None:
        raise RuntimeError("Could not find any legal court lineup for the provided 11-unit squad.")

    (
        win_starters,
        win_sixth,
        win_bench,
        win_cap,
        win_vc,
        win_formation,
        win_static,
        win_cap_opt,
        win_slot_opt,
    ) = best_config

    starter_ids = tuple(p.id for p in win_starters)
    bench_ids = tuple(p.id for p in win_bench)

    validation = validate_court_lineup(
        squad=squad_list,
        starters=starter_ids,
        captain_id=win_cap.id,
        sixth_man_id=win_sixth.id,
        head_coach_id=head_coach.id,
    )

    def _unit_card(unit: Player, role: str, mult: float) -> dict[str, Any]:
        proj = projections[unit.id]
        return {
            "id": unit.id,
            "name": unit.name,
            "position": unit.position.short_code,
            "team": unit.team_code,
            "opponent": proj.opponent_code,
            "venue": "H" if proj.is_home else "A",
            "turn": proj.turn_number,
            "fdr": proj.fdr,
            "role": role,
            "multiplier": mult,
            "raw_xpdk": proj.expected_pdk,
            "effective_xpdk": round(proj.expected_pdk * mult, 2),
        }

    starters_cards = tuple(
        _unit_card(
            p,
            "CAPTAIN" if p.id == win_cap.id else ("VICE_CAPTAIN" if p.id == win_vc.id else "STARTER"),
            CAPTAIN_MULTIPLIER if p.id == win_cap.id else STARTER_MULTIPLIER,
        )
        for p in win_starters
    )
    sixth_card = _unit_card(win_sixth, "SIXTH_MAN", SIXTH_MAN_MULTIPLIER)
    bench_cards = tuple(_unit_card(b, "BENCH", BENCH_MULTIPLIER) for b in win_bench)
    coach_card = _unit_card(head_coach, "HEAD_COACH", HEAD_COACH_MULTIPLIER)

    return LineupRecommendation(
        round_number=round_number,
        formation=win_formation,
        captain_id=win_cap.id,
        captain_name=win_cap.name,
        vice_captain_id=win_vc.id,
        vice_captain_name=win_vc.name,
        sixth_man_id=win_sixth.id,
        sixth_man_name=win_sixth.name,
        head_coach_id=head_coach.id,
        head_coach_name=head_coach.name,
        starter_ids=starter_ids,
        bench_ids=bench_ids,
        static_xpdk=win_static,
        captain_option_bonus_xpdk=win_cap_opt,
        slot_option_bonus_xpdk=win_slot_opt,
        total_turn_adjusted_xpdk=round(win_static + win_cap_opt + win_slot_opt, 2),
        is_valid=validation.is_valid,
        validation_errors=validation.errors,
        starters_detail=starters_cards,
        sixth_man_detail=sixth_card,
        bench_detail=bench_cards,
        head_coach_detail=coach_card,
    )


def generate_lineup_report(
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    round_number: int | None = None,
    report_path: Path | None = LINEUP_REPORT_PATH,
) -> dict[str, Any]:
    """Load current squad, compute projections, optimize Starting 5 + 6th Man + Captain, and persist JSON report."""
    state = load_current_squad(squad_path)
    store = SnapshotStore(database_path)
    target_round = round_number if round_number is not None else (state.round_number or get_current_round(store))

    players_by_id = {p.id: p for p in store.load_latest_players()}
    squad_players = [players_by_id[pid] for pid in state.player_ids if pid in players_by_id]
    projections = project_all_players(database_path=database_path, round_number=target_round)

    recommendation = optimize_court_lineup(
        squad=squad_players,
        projections=projections,
        round_number=target_round,
    )
    payload = asdict(recommendation)
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload
