"""Formal fantasy constraints and prediction contract for V0.4 decision layer."""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from ..models import Player, Position
from ..rules import (
    COURT_STARTERS_SIZE,
    HEAD_COACH_SIZE,
    LEGAL_COURT_FORMATIONS,
    MAX_BUDGET_TENTHS,
    MAX_PLAYERS_PER_TEAM,
    MAX_TRADES_PER_ROUND,
    SIXTH_MAN_SIZE,
    SQUAD_QUOTAS,
    SQUAD_SIZE,
)


@dataclass(frozen=True, slots=True)
class PlayerProjectionContract:
    """Decoupled canonical prediction contract consumed by the decision layer (V1.0 Section 6.1).

    The prediction subsystem produces projections; the optimization/valuation layer consumes them.
    Downstream decision components must never branch on internal model mechanics.
    """

    player_id: int
    player_name: str
    position: Position
    team_id: int | None = None
    team_code: str = ""
    price_tenths: int = 0
    expected_fp: float = 0.0
    probability_play: float = 1.0
    expected_minutes: float = 0.0
    fp_per_minute: float = 0.0
    uncertainty: float = 0.0
    prediction_spread: float = 0.0
    turn_number: int = 1
    opponent_code: str = ""
    is_home: bool = True
    actual_fp: float | None = None
    has_played: bool = False
    is_bye: bool = False
    pre_round_status: str = "available"
    # Canonical V1.0 contract fields:
    league_id: str = "euroleague"
    season: str = ""
    round_number: int = 1
    decision_cutoff: str | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    points_above_replacement: float = 0.0
    fp_per_credit: float = 0.0
    model_version: str = ""
    feature_version: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    # Rotation & context badges:
    rotation_tier: str = "core_rotation"
    blowout_risk: bool = False
    foul_fragility: str = "LOW"
    congestion_index: float = 0.0
    context_badges: tuple[str, ...] = ()

    @property
    def credits(self) -> float:
        return round(self.price_tenths / 10.0, 1)

    @property
    def price(self) -> float:
        """Canonical alias for credits."""
        return self.credits

    @property
    def play_probability(self) -> float:
        """Canonical alias for probability_play."""
        return self.probability_play

    @property
    def round(self) -> int:
        """Canonical alias for round_number."""
        return self.round_number

    @property
    def cutoff(self) -> str | None:
        """Canonical alias for decision_cutoff."""
        return self.decision_cutoff

    @property
    def par(self) -> float:
        """Canonical alias for points_above_replacement."""
        return self.points_above_replacement

    @property
    def effective_lower_bound(self) -> float:
        """Lower bound: explicit lower_bound if present, else expected_fp - 1.96*uncertainty."""
        if self.lower_bound is not None:
            return round(self.lower_bound, 2)
        return max(0.0, round(self.expected_fp - 1.96 * self.uncertainty, 2))

    @property
    def effective_upper_bound(self) -> float:
        """Upper bound: explicit upper_bound if present, else expected_fp + 1.96*uncertainty."""
        if self.upper_bound is not None:
            return round(self.upper_bound, 2)
        return round(self.expected_fp + 1.96 * self.uncertainty, 2)

    @property
    def effective_fp_per_credit(self) -> float:
        """Points per credit efficiency ratio."""
        if self.fp_per_credit > 0.0:
            return round(self.fp_per_credit, 2)
        if self.credits > 0.0:
            return round(self.expected_fp / self.credits, 2)
        return 0.0

    def validate_contract(self) -> list[str]:
        """Validate projection contract invariants against canonical ranges and types."""
        errors: list[str] = []
        if self.player_id <= 0:
            errors.append(f"player_id must be a positive integer, got {self.player_id}")
        if not isinstance(self.position, Position):
            errors.append(f"position must be an instance of Position enum, got {type(self.position)}")
        if not (0.0 <= self.probability_play <= 1.0):
            errors.append(f"probability_play must be in [0.0, 1.0], got {self.probability_play}")
        if self.expected_minutes < 0.0 or self.expected_minutes > 50.0:
            errors.append(f"expected_minutes must be in [0.0, 50.0], got {self.expected_minutes}")
        if self.expected_fp < -15.0 or self.expected_fp > 100.0:
            errors.append(f"expected_fp out of valid basketball range [-15.0, 100.0], got {self.expected_fp}")
        if self.uncertainty < 0.0:
            errors.append(f"uncertainty cannot be negative, got {self.uncertainty}")
        if self.price_tenths < 0:
            errors.append(f"price_tenths cannot be negative, got {self.price_tenths}")
        if self.turn_number not in (1, 2, 3):
            errors.append(f"turn_number must be in (1, 2, 3), got {self.turn_number}")
        if self.lower_bound is not None and self.upper_bound is not None:
            if self.lower_bound > self.upper_bound:
                errors.append(f"lower_bound ({self.lower_bound}) cannot exceed upper_bound ({self.upper_bound})")
        return errors

    @property
    def is_valid(self) -> bool:
        """Return True if all contract invariants are satisfied."""
        return len(self.validate_contract()) == 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize canonical projection contract to dictionary."""
        return {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "position": self.position.short_code if isinstance(self.position, Position) else str(self.position),
            "team_id": self.team_id,
            "team_code": self.team_code,
            "price_tenths": self.price_tenths,
            "credits": self.credits,
            "expected_fp": round(self.expected_fp, 2),
            "probability_play": round(self.probability_play, 4),
            "expected_minutes": round(self.expected_minutes, 2),
            "fp_per_minute": round(self.fp_per_minute, 4),
            "uncertainty": round(self.uncertainty, 2),
            "prediction_spread": round(self.prediction_spread, 2),
            "lower_bound": self.effective_lower_bound,
            "upper_bound": self.effective_upper_bound,
            "points_above_replacement": round(self.points_above_replacement, 2),
            "fp_per_credit": self.effective_fp_per_credit,
            "turn_number": self.turn_number,
            "opponent_code": self.opponent_code,
            "is_home": self.is_home,
            "actual_fp": self.actual_fp,
            "has_played": self.has_played,
            "is_bye": self.is_bye,
            "pre_round_status": self.pre_round_status,
            "league_id": self.league_id,
            "season": self.season,
            "round_number": self.round_number,
            "decision_cutoff": self.decision_cutoff,
            "model_version": self.model_version,
            "feature_version": self.feature_version,
            "provenance": dict(self.provenance),
            "rotation_tier": self.rotation_tier,
            "blowout_risk": self.blowout_risk,
            "foul_fragility": self.foul_fragility,
            "congestion_index": self.congestion_index,
            "context_badges": list(self.context_badges),
        }

    @classmethod
    def from_player(
        cls,
        player: Player,
        expected_fp: float = 0.0,
        uncertainty: float = 0.0,
        actual_fp: float | None = None,
        has_played: bool = False,
        league_id: str = "euroleague",
        season: str = "",
        round_number: int = 1,
        decision_cutoff: str | None = None,
        model_version: str = "player_baseline",
        feature_version: str = "1.0.0",
        provenance: dict[str, Any] | None = None,
    ) -> "PlayerProjectionContract":
        act = actual_fp if actual_fp is not None else (player.last_match_pts if getattr(player, "has_played", False) else None)
        played = has_played or getattr(player, "has_played", False)
        return cls(
            player_id=player.id,
            player_name=player.name,
            position=player.position,
            team_id=player.team_id,
            team_code=player.team_code,
            price_tenths=player.price_tenths,
            expected_fp=expected_fp,
            probability_play=player.probability_of_playing,
            expected_minutes=0.0,
            fp_per_minute=0.0,
            uncertainty=uncertainty,
            turn_number=player.turn_number,
            actual_fp=act,
            has_played=played,
            league_id=league_id,
            season=season,
            round_number=round_number,
            decision_cutoff=decision_cutoff,
            model_version=model_version,
            feature_version=feature_version,
            provenance=dict(provenance or {}),
        )

    @classmethod
    def from_decomposed(
        cls,
        proj: Any,
        team_id: int | None = None,
    ) -> "PlayerProjectionContract":
        """Convert a V0.3 DecomposedProjection into the decoupled V0.4+ canonical contract."""
        pos_raw = getattr(proj, "position", "G")
        pos_enum = Position.from_raw(pos_raw)
        return cls(
            player_id=int(proj.player_id),
            player_name=str(proj.player_name),
            position=pos_enum,
            team_id=team_id,
            team_code=str(getattr(proj, "team_code", "")),
            price_tenths=int(getattr(proj, "quotation_at_decision_tenths", 0)),
            expected_fp=float(getattr(proj, "expected_fantasy_points", 0.0)),
            probability_play=float(getattr(proj, "play_probability", 1.0)),
            expected_minutes=float(getattr(proj, "expected_minutes_if_play", 0.0)),
            fp_per_minute=float(getattr(proj, "expected_fp_per_min_if_play", 0.0)),
            uncertainty=float(getattr(proj, "sigma", 0.0)),
            prediction_spread=float(getattr(proj, "prediction_spread", 0.0)),
            turn_number=int(getattr(proj, "turn_number", 1)),
            opponent_code=str(getattr(proj, "opponent_team_code", "")),
            is_home=bool(getattr(proj, "home", True)),
            lower_bound=float(getattr(proj, "lower_bound", 0.0)),
            upper_bound=float(getattr(proj, "upper_bound", 0.0)),
            points_above_replacement=float(getattr(proj, "points_above_replacement", 0.0)),
            fp_per_credit=float(getattr(proj, "expected_fp_per_credit", 0.0)),
            rotation_tier=str(getattr(proj, "rotation_tier", "core_rotation")),
            blowout_risk=bool(getattr(proj, "blowout_risk", False)),
            foul_fragility=str(getattr(proj, "foul_fragility", "LOW")),
            congestion_index=float(getattr(proj, "congestion_index", 0.0)),
            context_badges=tuple(getattr(proj, "context_badges", ())),
            model_version=str(getattr(proj, "model_version", "0.3.0")),
            feature_version=str(getattr(proj, "feature_version", "1.0.0")),
            provenance={"cold_start_source": str(getattr(proj, "cold_start_source", ""))},
        )

    @classmethod
    def from_baseline(
        cls,
        player_id: int,
        player_name: str,
        position: Position | str,
        expected_fp: float,
        model_id: str,
        uncertainty: float = 0.0,
        team_id: int | None = None,
        team_code: str = "",
        price_tenths: int = 100,
        turn_number: int = 1,
        opponent_code: str = "",
        is_home: bool = True,
        league_id: str = "euroleague",
        season: str = "",
        round_number: int = 1,
        decision_cutoff: str | None = None,
        model_version: str = "0.2.5",
        feature_version: str = "1.0.0",
        provenance: dict[str, Any] | None = None,
    ) -> "PlayerProjectionContract":
        """Factory for baseline prediction models (season_mean, last5, ewma, etc.)."""
        pos_enum = position if isinstance(position, Position) else Position.from_raw(str(position))
        prov = {"model_id": model_id, "model_family": "baseline"}
        if provenance:
            prov.update(provenance)
        return cls(
            player_id=player_id,
            player_name=player_name,
            position=pos_enum,
            team_id=team_id,
            team_code=team_code,
            price_tenths=price_tenths,
            expected_fp=expected_fp,
            probability_play=1.0,
            expected_minutes=0.0,
            fp_per_minute=0.0,
            uncertainty=uncertainty,
            turn_number=turn_number,
            opponent_code=opponent_code,
            is_home=is_home,
            league_id=league_id,
            season=season,
            round_number=round_number,
            decision_cutoff=decision_cutoff,
            model_version=model_version,
            feature_version=feature_version,
            provenance=prov,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlayerProjectionContract":
        pos = data.get("position")
        pos_enum = pos if isinstance(pos, Position) else Position.from_raw(str(pos))
        price_tenths = int(
            data.get("price_tenths", int(round(float(data.get("credits", data.get("price", 0.0))) * 10)))
        )
        prob = float(data.get("probability_play", data.get("play_probability", 1.0)))
        exp_fp = float(data.get("expected_fp", data.get("expected_pdk", 0.0)))
        sigma = float(data.get("uncertainty", data.get("sigma", data.get("sigma_pdk", 0.0))))
        lower = data.get("lower_bound")
        upper = data.get("upper_bound")
        par = float(data.get("points_above_replacement", data.get("par", 0.0)))
        fp_pc = float(data.get("fp_per_credit", 0.0))

        return cls(
            player_id=int(data["player_id"]),
            player_name=str(data.get("player_name", data.get("name", ""))),
            position=pos_enum,
            team_id=data.get("team_id"),
            team_code=str(data.get("team_code", "")),
            price_tenths=price_tenths,
            expected_fp=exp_fp,
            probability_play=prob,
            expected_minutes=float(data.get("expected_minutes", 0.0)),
            fp_per_minute=float(data.get("fp_per_minute", 0.0)),
            uncertainty=sigma,
            prediction_spread=float(data.get("prediction_spread", 0.0)),
            turn_number=int(data.get("turn_number", 1)),
            opponent_code=str(data.get("opponent_code", data.get("opponent_team_code", ""))),
            is_home=bool(data.get("is_home", True)),
            actual_fp=float(data["actual_fp"]) if data.get("actual_fp") is not None else None,
            has_played=bool(data.get("has_played", False)),
            is_bye=bool(data.get("is_bye", False)),
            pre_round_status=str(data.get("pre_round_status", "available")),
            league_id=str(data.get("league_id", "euroleague")),
            season=str(data.get("season", "")),
            round_number=int(data.get("round_number", data.get("round", 1))),
            decision_cutoff=data.get("decision_cutoff", data.get("cutoff")),
            lower_bound=float(lower) if lower is not None else None,
            upper_bound=float(upper) if upper is not None else None,
            points_above_replacement=par,
            fp_per_credit=fp_pc,
            model_version=str(data.get("model_version", "")),
            feature_version=str(data.get("feature_version", "")),
            provenance=dict(data.get("provenance") or {}),
            rotation_tier=str(data.get("rotation_tier", "core_rotation")),
            blowout_risk=bool(data.get("blowout_risk", False)),
            foul_fragility=str(data.get("foul_fragility", "LOW")),
            congestion_index=float(data.get("congestion_index", 0.0)),
            context_badges=tuple(data.get("context_badges") or ()),
        )


@dataclass(frozen=True, slots=True)
class OptimizationConstraints:
    """Formal deterministic constraint parameters for EuroLeague Fantasy Challenge Classic Mode."""

    squad_size: int = SQUAD_SIZE
    court_starters_size: int = COURT_STARTERS_SIZE
    bench_size: int = SQUAD_SIZE - COURT_STARTERS_SIZE - SIXTH_MAN_SIZE - HEAD_COACH_SIZE  # 4
    sixth_man_size: int = SIXTH_MAN_SIZE
    head_coach_size: int = HEAD_COACH_SIZE
    max_players_per_club: int = MAX_PLAYERS_PER_TEAM
    max_transfers: int = MAX_TRADES_PER_ROUND
    unlimited_transfers: bool = False
    budget_tenths: int | None = MAX_BUDGET_TENTHS
    legal_formations: frozenset[tuple[int, int, int]] = LEGAL_COURT_FORMATIONS
    quotas: dict[Position, int] = field(default_factory=lambda: dict(SQUAD_QUOTAS))

    @classmethod
    def from_ruleset(cls, ruleset: Any) -> "OptimizationConstraints":
        """Instantiate OptimizationConstraints parameterized by a CompetitionRuleset."""
        return cls(
            squad_size=getattr(ruleset, "squad_size", SQUAD_SIZE),
            court_starters_size=getattr(ruleset, "starters_count", COURT_STARTERS_SIZE),
            sixth_man_size=getattr(ruleset, "sixth_man_count", SIXTH_MAN_SIZE),
            head_coach_size=getattr(ruleset, "head_coach_count", HEAD_COACH_SIZE),
            max_players_per_club=getattr(ruleset, "max_court_players_per_club", MAX_PLAYERS_PER_TEAM),
            budget_tenths=int(getattr(ruleset, "budget_credits", 100.0) * 10),
        )


@dataclass(frozen=True, slots=True)
class ConstraintValidationResult:
    is_valid: bool
    errors: tuple[str, ...]

    @classmethod
    def success(cls) -> "ConstraintValidationResult":
        return cls(is_valid=True, errors=())

    @classmethod
    def failure(cls, errors: Sequence[str]) -> "ConstraintValidationResult":
        return cls(is_valid=False, errors=tuple(errors))


def validate_squad_constraints(
    players: Iterable[PlayerProjectionContract | Player],
    budget_tenths: int | None = None,
    constraints: OptimizationConstraints | None = None,
    check_budget: bool = True,
) -> ConstraintValidationResult:
    """Validate that an 11-unit squad satisfies squad size, position quotas, unique players, budget, and club quotas."""
    cfg = constraints or OptimizationConstraints()
    squad = tuple(players)
    errors: list[str] = []

    if len(squad) != cfg.squad_size:
        errors.append(f"Squad must contain exactly {cfg.squad_size} units; received {len(squad)}.")

    ids = [p.player_id if isinstance(p, PlayerProjectionContract) else p.id for p in squad]
    if len(set(ids)) != len(ids):
        errors.append("Squad contains duplicate player IDs.")

    if check_budget:
        effective_budget = budget_tenths if budget_tenths is not None else cfg.budget_tenths
        total_cost = sum(p.price_tenths for p in squad)
        if effective_budget is not None and total_cost > effective_budget:
            errors.append(
                f"Squad total cost {total_cost / 10:.1f} Cr exceeds allowed budget {effective_budget / 10:.1f} Cr."
            )

    pos_counts = Counter(p.position for p in squad)
    for pos, required in cfg.quotas.items():
        actual = pos_counts[pos]
        if actual != required:
            errors.append(f"Position {pos.name} requires {required} units; found {actual}.")

    # Club quota: court players max_players_per_club
    court_players = [p for p in squad if p.position != Position.HEAD_COACH]
    team_counts = Counter(
        (p.team_id if p.team_id is not None else p.team_code)
        for p in court_players
        if (p.team_id is not None or p.team_code)
    )
    for team_key, count in sorted(team_counts.items(), key=lambda x: str(x[0])):
        if count > cfg.max_players_per_club:
            errors.append(f"Club {team_key} has {count} players; maximum allowed is {cfg.max_players_per_club}.")

    if errors:
        return ConstraintValidationResult.failure(errors)
    return ConstraintValidationResult.success()


def validate_lineup_constraints(
    squad: Iterable[PlayerProjectionContract | Player],
    starters: Sequence[int],
    captain_id: int,
    sixth_man_id: int,
    head_coach_id: int,
    constraints: OptimizationConstraints | None = None,
) -> ConstraintValidationResult:
    """Validate Starting 5 formation (G-F-C), Captain, Sixth Man, and Head Coach against official constraints."""
    cfg = constraints or OptimizationConstraints()
    squad_list = list(squad)
    squad_by_id = {
        (p.player_id if isinstance(p, PlayerProjectionContract) else p.id): p
        for p in squad_list
    }
    starter_ids = tuple(starters)
    errors: list[str] = []

    if len(starter_ids) != cfg.court_starters_size:
        errors.append(f"Starting lineup must contain {cfg.court_starters_size} starters; received {len(starter_ids)}.")
    if len(set(starter_ids)) != len(starter_ids):
        errors.append("Starting lineup contains duplicate player IDs.")

    for sid in starter_ids:
        if sid not in squad_by_id:
            errors.append(f"Starter {sid} is not in the squad.")

    known_starters = [squad_by_id[sid] for sid in starter_ids if sid in squad_by_id]
    for p in known_starters:
        if p.position == Position.HEAD_COACH:
            errors.append(f"Head Coach {p.player_id if isinstance(p, PlayerProjectionContract) else p.id} cannot start on court.")

    if len(known_starters) == cfg.court_starters_size and all(p.position != Position.HEAD_COACH for p in known_starters):
        counts = Counter(p.position for p in known_starters)
        formation = (counts[Position.GUARD], counts[Position.FORWARD], counts[Position.CENTER])
        if formation not in cfg.legal_formations:
            legal_str = ", ".join(f"{g}-{f}-{c}" for g, f, c in sorted(cfg.legal_formations))
            errors.append(
                f"Formation {formation[0]}-{formation[1]}-{formation[2]} is illegal. Allowed: {legal_str}."
            )

    if captain_id not in squad_by_id:
        errors.append(f"Captain {captain_id} is not in the squad.")
    elif captain_id not in starter_ids:
        errors.append(f"Captain {captain_id} must be one of the court starters.")

    if sixth_man_id not in squad_by_id:
        errors.append(f"Sixth Man {sixth_man_id} is not in the squad.")
    elif sixth_man_id in starter_ids:
        errors.append(f"Sixth Man {sixth_man_id} cannot be in the Starting 5.")
    elif squad_by_id[sixth_man_id].position == Position.HEAD_COACH:
        errors.append(f"Head Coach {sixth_man_id} cannot be designated Sixth Man.")

    if head_coach_id not in squad_by_id:
        errors.append(f"Head Coach {head_coach_id} is not in the squad.")
    elif squad_by_id[head_coach_id].position != Position.HEAD_COACH:
        errors.append(f"Unit {head_coach_id} is not a Head Coach.")

    if errors:
        return ConstraintValidationResult.failure(errors)
    return ConstraintValidationResult.success()


def validate_transfers_constraints(
    current_squad: Iterable[PlayerProjectionContract | Player],
    out_ids: Sequence[int],
    in_players: Sequence[PlayerProjectionContract | Player],
    bank_tenths: int = 0,
    constraints: OptimizationConstraints | None = None,
) -> tuple[ConstraintValidationResult, int]:
    """Validate 1..4 trades (or unlimited) and return (ValidationResult, remaining_bank_tenths)."""
    cfg = constraints or OptimizationConstraints()
    squad_by_id = {
        (p.player_id if isinstance(p, PlayerProjectionContract) else p.id): p
        for p in current_squad
    }
    errors: list[str] = []

    out_set = set(out_ids)
    if len(out_set) != len(out_ids):
        errors.append("OUT trade list contains duplicate player IDs.")
    if len(in_players) != len(out_ids):
        errors.append(f"Number of OUT units ({len(out_ids)}) must match IN units ({len(in_players)}).")

    trade_count = len(out_ids)
    if not cfg.unlimited_transfers and trade_count > cfg.max_transfers:
        errors.append(f"Requested {trade_count} trades, exceeding maximum allowed {cfg.max_transfers}.")

    for out_id in out_ids:
        if out_id not in squad_by_id:
            errors.append(f"OUT player {out_id} is not in current squad.")

    # Check for duplicate IN players
    in_ids = [p.player_id if isinstance(p, PlayerProjectionContract) else p.id for p in in_players]
    if len(set(in_ids)) != len(in_ids):
        errors.append("IN trade list contains duplicate player IDs.")

    # Check if IN player is already in remaining squad
    remaining_ids = set(squad_by_id.keys()) - out_set
    overlap = remaining_ids.intersection(in_ids)
    if overlap:
        errors.append(f"IN player(s) {sorted(overlap)} already in remaining squad.")

    # Financial check with 0% sell-on tax:
    # budget = bank + sum(sell_price(out))
    # cost = sum(buy_price(in))
    sales_value = sum(squad_by_id[oid].price_tenths for oid in out_ids if oid in squad_by_id)
    purchases_value = sum(p.price_tenths for p in in_players)
    new_bank = bank_tenths + sales_value - purchases_value

    if new_bank < 0:
        errors.append(
            f"Trades require {purchases_value / 10:.1f} Cr but available funds are "
            f"{(bank_tenths + sales_value) / 10:.1f} Cr (deficit: {abs(new_bank) / 10:.1f} Cr)."
        )

    # Check resulting squad position quotas and club quotas
    new_squad: list[PlayerProjectionContract | Player] = [
        squad_by_id[pid] for pid in remaining_ids
    ] + list(in_players)

    squad_res = validate_squad_constraints(new_squad, budget_tenths=None, constraints=cfg, check_budget=False)
    if not squad_res.is_valid:
        errors.extend(squad_res.errors)

    if errors:
        return ConstraintValidationResult.failure(errors), new_bank
    return ConstraintValidationResult.success(), new_bank
