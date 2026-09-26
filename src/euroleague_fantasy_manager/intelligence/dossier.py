"""Deterministic Manager Dossier schema and generator for V0.6 Strategic Intelligence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence
import uuid

from ..competition.ruleset import League, get_league_ruleset
from ..models import Position
from ..optimization.constraints import PlayerProjectionContract
from ..services.optimization_service import OptimizationService
from ..services.prediction_service import PredictionService
from ..services.team_service import TeamService


@dataclass(frozen=True, slots=True)
class DossierSquadUnit:
    player_id: int
    name: str
    position: str
    team_code: str
    role: str
    price_tenths: int
    credits: float
    expected_fp: float
    actual_fp: float | None
    has_played: bool
    expected_minutes: float
    probability_play: float
    uncertainty: float
    turn_number: int
    opponent_code: str
    is_home: bool
    fp_per_credit: float
    points_above_replacement: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DossierLineup:
    starters: list[DossierSquadUnit]
    captain: DossierSquadUnit | None
    sixth_man: DossierSquadUnit | None
    bench: list[DossierSquadUnit]
    coach: DossierSquadUnit | None
    formation: str
    expected_total_fp: float
    realized_total_fp: float
    unplayed_expected_fp: float
    alternatives: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "starters": [u.to_dict() for u in self.starters],
            "captain": self.captain.to_dict() if self.captain else None,
            "sixth_man": self.sixth_man.to_dict() if self.sixth_man else None,
            "bench": [u.to_dict() for u in self.bench],
            "coach": self.coach.to_dict() if self.coach else None,
            "formation": self.formation,
            "expected_total_fp": self.expected_total_fp,
            "realized_total_fp": self.realized_total_fp,
            "unplayed_expected_fp": self.unplayed_expected_fp,
            "alternatives": self.alternatives,
        }


@dataclass(frozen=True, slots=True)
class DossierTransferOption:
    option_id: int
    out_players: list[dict[str, Any]]
    in_players: list[dict[str, Any]]
    gross_gain: float
    transfer_cost: float
    net_transfer_value: float
    remaining_bank_credits: float
    formation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DossierIntraRoundOption:
    can_sub: bool
    projected_gain: float
    suggested_subs: list[dict[str, Any]] = field(default_factory=list)
    suggested_captain: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DossierProvenance:
    dossier_id: str
    generated_at: str
    ruleset_name: str
    competition_code: str
    prediction_model: str
    optimizer_engine: str
    risk_mode: str
    content_hash: str

    @property
    def config_hash(self) -> str:
        return self.content_hash

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["config_hash"] = self.content_hash
        return d


@dataclass(frozen=True, slots=True)
class ManagerDossier:
    """The central deterministic quantitative briefing dossier for V0.6 intelligence."""

    dossier_id: str
    team_id: str
    team_name: str
    league: str
    season: str
    round_number: int
    turn_number: int
    bank_credits: float
    transfers_remaining: int
    current_lineup: DossierLineup
    transfer_recommendations: list[DossierTransferOption]
    intra_round_recommendations: DossierIntraRoundOption
    player_valuations: list[dict[str, Any]]
    schedule_context: list[dict[str, Any]]
    provenance: DossierProvenance

    def to_dict(self) -> dict[str, Any]:
        return {
            "dossier_id": self.dossier_id,
            "team_id": self.team_id,
            "team_name": self.team_name,
            "league": self.league,
            "season": self.season,
            "round_number": self.round_number,
            "turn_number": self.turn_number,
            "bank_credits": self.bank_credits,
            "transfers_remaining": self.transfers_remaining,
            "current_lineup": self.current_lineup.to_dict(),
            "transfer_recommendations": [t.to_dict() for t in self.transfer_recommendations],
            "intra_round_recommendations": self.intra_round_recommendations.to_dict(),
            "player_valuations": self.player_valuations,
            "schedule_context": self.schedule_context,
            "provenance": self.provenance.to_dict(),
        }

    def summary_markdown(self) -> str:
        ln = self.current_lineup
        cap_name = ln.captain.name if ln.captain else "None"
        sm_name = ln.sixth_man.name if ln.sixth_man else "None"
        ch_name = ln.coach.name if ln.coach else "None"

        lines = [
            f"# Manager Dossier: {self.team_name} ({self.league.upper()})",
            f"**Season:** {self.season} | **Round:** {self.round_number} | **Bank:** {self.bank_credits:.1f} Cr | **Transfers:** {self.transfers_remaining}",
            f"**Generated:** {self.provenance.generated_at} (ID: `{self.dossier_id[:8]}`)",
            "",
            "## 1. Optimal Lineup & Court State",
            f"- **Formation:** `{ln.formation}`",
            f"- **Projected Total:** **{ln.expected_total_fp:.2f} FP** (Realized: {ln.realized_total_fp:.2f} FP, Unplayed: {ln.unplayed_expected_fp:.2f} FP)",
            f"- **Captain (2.0x):** {cap_name}",
            f"- **Sixth Man (1.0x):** {sm_name}",
            f"- **Head Coach (1.0x):** {ch_name}",
            "",
            "### Starting Five (1.0x)",
            "| Position | Player | Team | Turn | Exp FP | Actual FP | Status |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for s in ln.starters:
            act_str = f"{s.actual_fp:.1f}" if s.has_played and s.actual_fp is not None else "-"
            stat_str = "Played" if s.has_played else "Upcoming"
            cap_star = " (C)" if ln.captain and s.player_id == ln.captain.player_id else ""
            lines.append(f"| {s.position} | {s.name}{cap_star} | {s.team_code} | T{s.turn_number} | {s.expected_fp:.1f} | {act_str} | {stat_str} |")

        lines.extend([
            "",
            "### Bench (0.5x)",
            "| Position | Player | Team | Turn | Exp FP | Status |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for b in ln.bench:
            b_stat = "Locked (Played)" if b.has_played else "Eligible"
            lines.append(f"| {b.position} | {b.name} | {b.team_code} | T{b.turn_number} | {b.expected_fp:.1f} | {b_stat} |")

        lines.extend([
            "",
            "## 2. Top Transfer Recommendations",
        ])
        if self.transfer_recommendations:
            for opt in self.transfer_recommendations:
                out_names = ", ".join(p["name"] for p in opt.out_players) or "None"
                in_names = ", ".join(p["name"] for p in opt.in_players) or "None"
                lines.append(
                    f"- **Option {opt.option_id}:** Sell `{out_names}` -> Buy `{in_names}` | "
                    f"Net Value: **{opt.net_transfer_value:+.2f} FP** | Rem Bank: {opt.remaining_bank_credits:.1f} Cr"
                )
        else:
            lines.append("No transfer recommendations (or zero available trades).")

        lines.extend([
            "",
            "## 3. Intra-Round Turn Substitutions",
        ])
        if self.intra_round_recommendations.can_sub and self.intra_round_recommendations.suggested_subs:
            lines.append(f"**Projected Gain:** +{self.intra_round_recommendations.projected_gain:.2f} FP")
            for sub in self.intra_round_recommendations.suggested_subs:
                lines.append(f"- Swap `{sub.get('bench_player_name')}` onto court for `{sub.get('court_player_name')}`")
        else:
            lines.append("No beneficial intra-round substitutions available.")

        return "\n".join(lines)


def generate_manager_dossier(
    team_id: str,
    season: str = "2026/27",
    round_number: int | None = None,
    team_service: TeamService | None = None,
    prediction_service: PredictionService | None = None,
    optimization_service: OptimizationService | None = None,
    database_path: Path | str | None = None,
) -> ManagerDossier:
    """Generate a comprehensive deterministic Manager Dossier for a managed team."""
    ts = team_service or TeamService(db_path=database_path or "data/euroleague.sqlite3")
    ps = prediction_service or PredictionService(database_path=database_path or "data/euroleague.sqlite3")
    opt = optimization_service or OptimizationService(team_service=ts, prediction_service=ps)

    team = ts.get_team(team_id)
    rnd = round_number or team.round_number
    league_val = getattr(team, "league", "euroleague") or "euroleague"
    ruleset = get_league_ruleset(league_val)

    # 1. Projections and valuations
    proj_dict = ps.get_projections_dict(season, rnd)
    valuations_map = ps.get_player_valuations(season, rnd)

    # 2. Lineup optimization & court roles
    opt_lineup = opt.optimize_lineup(
        team_id=team_id,
        season=season,
        round_number=rnd,
        risk_mode=team.settings.risk_mode,
        option_value_mode=team.settings.option_value_mode,
    )

    # Build dossier squad units
    def _to_dossier_unit(u: Any, role: str) -> DossierSquadUnit:
        pid = u.player_id if hasattr(u, "player_id") else u.get("player_id", 0)
        c: PlayerProjectionContract | None = proj_dict.get(pid)
        val = valuations_map.get(pid, {})

        pos_str = u.position if hasattr(u, "position") else u.get("position", "G")
        if c and hasattr(c, "position"):
            pos_str = c.position.short_code if hasattr(c.position, "short_code") else str(c.position)
        elif role == "coach" or pos_str in ("HEAD_COACH", "HC"):
            pos_str = "HC"

        price_tenths = u.current_price_tenths if hasattr(u, "current_price_tenths") else u.get("price_tenths", 100)
        name = u.name if hasattr(u, "name") and u.name else (c.player_name if c else f"Player {pid}")
        tcode = u.team_code if hasattr(u, "team_code") and u.team_code else (c.team_code if c else "")
        turn = u.turn_number if hasattr(u, "turn_number") and u.turn_number else (c.turn_number if c else 1)

        has_played = getattr(c, "has_played", False) if c else False
        actual_fp = getattr(c, "actual_fp", None) if c else None
        exp_fp = round(c.expected_fp, 2) if c else round(price_tenths / 10.0, 1)

        return DossierSquadUnit(
            player_id=pid,
            name=name,
            position=pos_str,
            team_code=tcode,
            role=role,
            price_tenths=price_tenths,
            credits=round(price_tenths / 10.0, 1),
            expected_fp=exp_fp,
            actual_fp=round(actual_fp, 2) if actual_fp is not None else None,
            has_played=has_played,
            expected_minutes=round(c.expected_minutes, 1) if c else 20.0,
            probability_play=round(c.probability_play, 2) if c else 1.0,
            uncertainty=round(c.uncertainty, 2) if c else 0.0,
            turn_number=turn,
            opponent_code=c.opponent_code if c else "",
            is_home=c.is_home if c else True,
            fp_per_credit=round(val.get("fp_per_credit", 0.0), 3),
            points_above_replacement=round(val.get("points_above_replacement", 0.0), 2),
        )

    # Sync starters, captain, 6th man, bench from optimal lineup if unassigned
    squad_units = team.squad
    starters_units = [u for u in squad_units if u.is_starter]
    bench_units = [u for u in squad_units if u.is_bench]
    sixth_man_unit = next((u for u in squad_units if u.is_sixth_man), None)
    coach_unit = next((u for u in squad_units if u.is_coach or u.position == "HC"), None)

    if len(starters_units) != 5 or not sixth_man_unit or not coach_unit:
        starters_units = [u for u in squad_units if u.player_id in [p["player_id"] for p in opt_lineup.starters]]
        bench_units = [u for u in squad_units if u.player_id in [p["player_id"] for p in opt_lineup.bench]]
        sixth_man_unit = next((u for u in squad_units if u.player_id == opt_lineup.sixth_man_id), None)
        coach_unit = next((u for u in squad_units if u.player_id == opt_lineup.coach_id or u.position == "HC"), None)

    cap_id = team.captain_id or opt_lineup.captain_id

    dossier_starters = [_to_dossier_unit(u, "starter") for u in starters_units]
    dossier_bench = [_to_dossier_unit(u, "bench") for u in bench_units]
    dossier_sixth = _to_dossier_unit(sixth_man_unit, "sixth_man") if sixth_man_unit else None
    dossier_coach = _to_dossier_unit(coach_unit, "coach") if coach_unit else None

    # Captain reference
    dossier_captain = next((u for u in dossier_starters if u.player_id == cap_id), None)
    if not dossier_captain and dossier_starters:
        dossier_captain = dossier_starters[0]

    # Score breakdown
    realized_fp = 0.0
    unplayed_exp_fp = 0.0

    for s in dossier_starters:
        mult = 2.0 if dossier_captain and s.player_id == dossier_captain.player_id else 1.0
        if s.has_played and s.actual_fp is not None:
            realized_fp += s.actual_fp * mult
        else:
            unplayed_exp_fp += s.expected_fp * mult

    if dossier_sixth:
        if dossier_sixth.has_played and dossier_sixth.actual_fp is not None:
            realized_fp += dossier_sixth.actual_fp * 1.0
        else:
            unplayed_exp_fp += dossier_sixth.expected_fp * 1.0

    for b in dossier_bench:
        if b.has_played and b.actual_fp is not None:
            realized_fp += b.actual_fp * 0.5
        else:
            unplayed_exp_fp += b.expected_fp * 0.5

    if dossier_coach:
        if dossier_coach.has_played and dossier_coach.actual_fp is not None:
            realized_fp += dossier_coach.actual_fp * 1.0
        else:
            unplayed_exp_fp += dossier_coach.expected_fp * 1.0

    tot_proj_fp = round(realized_fp + unplayed_exp_fp, 2)

    current_lineup = DossierLineup(
        starters=dossier_starters,
        captain=dossier_captain,
        sixth_man=dossier_sixth,
        bench=dossier_bench,
        coach=dossier_coach,
        formation=opt_lineup.formation,
        expected_total_fp=tot_proj_fp,
        realized_total_fp=round(realized_fp, 2),
        unplayed_expected_fp=round(unplayed_exp_fp, 2),
        alternatives=list(opt_lineup.alternatives or []),
    )

    # 3. Transfer Recommendations
    transfer_options: list[DossierTransferOption] = []
    try:
        top_tx = opt.suggest_transfers(
            team_id=team_id,
            season=season,
            round_number=rnd,
            max_trades=min(team.transfers_remaining, 3),
            risk_mode=team.settings.risk_mode,
            top_n=3,
        )
        for idx, rec in enumerate(top_tx, start=1):
            transfer_options.append(
                DossierTransferOption(
                    option_id=idx,
                    out_players=rec.get("transfers_out", []),
                    in_players=rec.get("transfers_in", []),
                    gross_gain=float(rec.get("gross_score_gain", 0.0)),
                    transfer_cost=float(rec.get("transfer_cost", 0.0)),
                    net_transfer_value=float(rec.get("net_transfer_value", 0.0)),
                    remaining_bank_credits=float(rec.get("remaining_bank_credits", 0.0)),
                    formation=str(rec.get("formation", "2-2-1")),
                )
            )
    except Exception:
        pass

    # 4. Intra-Round Substitutions
    intra_round = DossierIntraRoundOption(can_sub=False, projected_gain=0.0)
    try:
        # Check turn sub options
        turn_sub_res = opt.simulate_intra_round_substitutions(
            team_id=team_id,
            season=season,
            round_number=rnd,
        )
        gain = float(turn_sub_res.get("net_gain", 0.0))
        subs = turn_sub_res.get("substitutions", [])
        cap_switch = turn_sub_res.get("captain_switch")
        if gain > 0:
            intra_round = DossierIntraRoundOption(
                can_sub=True,
                projected_gain=gain,
                suggested_subs=subs,
                suggested_captain=cap_switch,
            )
    except Exception:
        pass

    # 5. Provenance & Hashes
    dossier_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    raw_facts = f"{team_id}:{rnd}:{tot_proj_fp}:{len(transfer_options)}"
    content_hash = hashlib.sha256(raw_facts.encode("utf-8")).hexdigest()[:16]

    provenance = DossierProvenance(
        dossier_id=dossier_id,
        generated_at=now_iso,
        ruleset_name=ruleset.name,
        competition_code=ruleset.competition_code,
        prediction_model="decomposed_v051",
        optimizer_engine="bounded_milp_v051",
        risk_mode=team.settings.risk_mode,
        content_hash=content_hash,
    )

    return ManagerDossier(
        dossier_id=dossier_id,
        team_id=team.team_id,
        team_name=team.name,
        league=league_val,
        season=season,
        round_number=rnd,
        turn_number=team.turn_number,
        bank_credits=round(team.bank_tenths / 10.0, 1),
        transfers_remaining=team.transfers_remaining,
        current_lineup=current_lineup,
        transfer_recommendations=transfer_options,
        intra_round_recommendations=intra_round,
        player_valuations=list(valuations_map.values())[:30],
        schedule_context=[],
        provenance=provenance,
    )
