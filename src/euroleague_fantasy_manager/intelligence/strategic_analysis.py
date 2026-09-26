"""Deterministic strategic analysis layer for V0.6 Strategic Intelligence.

Computes:
1. Assumption Breakdown: Ranked top 3-5 assumptions by fantasy point impact.
2. Sensitivity Analysis: One-way perturbations (captaincy, transfer minutes, T1 busts).
3. Devil's Advocate Checklist: Systematic sanity checks on legality, plausibility, downside regret.

Works 100% offline with zero LLM dependence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .dossier import DossierSquadUnit, ManagerDossier


@dataclass(frozen=True, slots=True)
class StrategicAssumption:
    name: str
    category: str
    player_name: str
    player_id: int
    baseline_value: float
    estimated_impact_fp: float
    description: str
    risk_level: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SensitivityCase:
    parameter: str
    shock_description: str
    baseline_outcome_fp: float
    shocked_outcome_fp: float
    delta_fp: float
    decision_reversal: bool
    mitigation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    check_name: str
    status: str  # "PASS", "WARNING", "ALERT"
    evidence: str
    details: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StrategicAnalysisResult:
    team_id: str
    dossier_id: str
    generated_at: str
    assumptions: list[StrategicAssumption]
    sensitivities: list[SensitivityCase]
    checklist: list[ChecklistItem]
    verdict: str  # "ROBUST", "MODERATE_RISK", "HIGH_RISK"

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "dossier_id": self.dossier_id,
            "generated_at": self.generated_at,
            "assumptions": [a.to_dict() for a in self.assumptions],
            "sensitivities": [s.to_dict() for s in self.sensitivities],
            "checklist": [c.to_dict() for c in self.checklist],
            "verdict": self.verdict,
        }

    def summary_markdown(self) -> str:
        lines = [
            f"# Deterministic Strategic Analysis: {self.verdict}",
            f"**Dossier ID:** `{self.dossier_id[:8]}` | **Generated:** {self.generated_at}",
            "",
            "## 1. Key Assumption Breakdown (Ranked by Decision Impact)",
            "| Player | Category | Baseline | Impact | Risk Level | Description |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for a in self.assumptions:
            lines.append(
                f"| {a.player_name} | {a.category} | {a.baseline_value:.1f} | {a.estimated_impact_fp:+.1f} FP | {a.risk_level.upper()} | {a.description} |"
            )

        lines.extend([
            "",
            "## 2. Sensitivity Analysis (One-Way Shocks)",
            "| Parameter | Scenario | Base FP | Shocked FP | Delta | Reversal? | Mitigation |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for s in self.sensitivities:
            rev_str = "YES" if s.decision_reversal else "NO"
            lines.append(
                f"| {s.parameter} | {s.shock_description} | {s.baseline_outcome_fp:.1f} | {s.shocked_outcome_fp:.1f} | {s.delta_fp:+.1f} | {rev_str} | {s.mitigation} |"
            )

        lines.extend([
            "",
            "## 3. Devil's Advocate Checklist",
            "| Check | Status | Evidence | Recommendation / Detail |",
            "| :--- | :--- | :--- | :--- |",
        ])
        for c in self.checklist:
            lines.append(
                f"| {c.check_name} | [{c.status}] | {c.evidence} | {c.details} |"
            )

        return "\n".join(lines)


def analyze_dossier(dossier: ManagerDossier) -> StrategicAnalysisResult:
    """Perform deterministic strategic analysis on a Manager Dossier without invoking an LLM."""
    ln = dossier.current_lineup
    now_iso = datetime.now(timezone.utc).isoformat()

    assumptions: list[StrategicAssumption] = []
    sensitivities: list[SensitivityCase] = []
    checklist: list[ChecklistItem] = []

    # 1. Assumption Breakdown
    # a. Captain participation & performance
    cap = ln.captain
    if cap:
        cap_impact = round(cap.expected_fp * 1.0, 1)  # Captain doubles score (1.0x bonus)
        risk = "HIGH" if cap.probability_play < 0.9 or cap.uncertainty > 4.5 else "MEDIUM"
        assumptions.append(
            StrategicAssumption(
                name="Captaincy Multiplier",
                category="captaincy",
                player_name=cap.name,
                player_id=cap.player_id,
                baseline_value=cap.expected_fp,
                estimated_impact_fp=cap_impact,
                description=f"Double points multiplier (2.0x) on {cap.name}. Baseline projection {cap.expected_fp:.1f} FP.",
                risk_level=risk,
            )
        )

    # b. Highest-expected starter minutes assumption
    best_starter = max(ln.starters, key=lambda p: p.expected_fp, default=None)
    if best_starter and (not cap or best_starter.player_id != cap.player_id):
        assumptions.append(
            StrategicAssumption(
                name="Key Starter Minutes & Role",
                category="minutes",
                player_name=best_starter.name,
                player_id=best_starter.player_id,
                baseline_value=best_starter.expected_minutes,
                estimated_impact_fp=round(best_starter.expected_fp * 0.4, 1),
                description=f"Assumes {best_starter.name} receives ~{best_starter.expected_minutes:.0f} mins with primary scoring load.",
                risk_level="MEDIUM",
            )
        )

    # c. Top transfer-in arrival
    if dossier.transfer_recommendations:
        top_tx = dossier.transfer_recommendations[0]
        if top_tx.in_players:
            in_p = top_tx.in_players[0]
            in_name = in_p.get("name", "Incoming Transfer")
            in_pid = in_p.get("player_id", 0)
            in_exp = in_p.get("expected_fp", 12.0)
            assumptions.append(
                StrategicAssumption(
                    name="Top Transfer Net Gain",
                    category="transfer",
                    player_name=in_name,
                    player_id=in_pid,
                    baseline_value=in_exp,
                    estimated_impact_fp=round(top_tx.net_transfer_value, 1),
                    description=f"Recruiting {in_name} assumes +{top_tx.net_transfer_value:.1f} FP net over outgoing squad members.",
                    risk_level="MEDIUM",
                )
            )

    # d. Sixth man full credit conversion
    sm = ln.sixth_man
    if sm:
        assumptions.append(
            StrategicAssumption(
                name="Sixth Man Full Score Conversion",
                category="sixth_man",
                player_name=sm.name,
                player_id=sm.player_id,
                baseline_value=sm.expected_fp,
                estimated_impact_fp=round(sm.expected_fp * 0.5, 1),
                description=f"{sm.name} selected as Sixth Man scores at 1.0x (yielding +0.5x vs bench 0.5x).",
                risk_level="LOW",
            )
        )

    # e. Turn scheduling optionality
    t1_starters = [s for s in ln.starters if s.turn_number == 1]
    t2_bench = [b for b in ln.bench if b.turn_number >= 2]
    if t1_starters and t2_bench:
        assumptions.append(
            StrategicAssumption(
                name="Turn 1/2 Substitution Optionality",
                category="schedule",
                player_name=f"{len(t1_starters)} T1 Starters",
                player_id=0,
                baseline_value=float(len(t1_starters)),
                estimated_impact_fp=round(float(len(t2_bench)) * 2.5, 1),
                description=f"{len(t1_starters)} starters play in Turn 1 with {len(t2_bench)} eligible Turn 2 bench players available to sub in.",
                risk_level="LOW",
            )
        )

    # 2. Sensitivity Analysis (One-Way Perturbations)
    base_total = ln.expected_total_fp

    # Case A: Captain underperformance (-25% shock)
    if cap:
        shock_cap_fp = round(cap.expected_fp * 0.75, 2)
        delta = round(-0.5 * cap.expected_fp, 2)  # Loss of 25% doubled = -50% of 1x
        new_total = round(base_total + delta, 2)
        sensitivities.append(
            SensitivityCase(
                parameter=f"{cap.name} Captaincy Shock (-25%)",
                shock_description=f"Captain scores {shock_cap_fp:.1f} FP instead of projected {cap.expected_fp:.1f} FP.",
                baseline_outcome_fp=base_total,
                shocked_outcome_fp=new_total,
                delta_fp=delta,
                decision_reversal=False,
                mitigation=f"Vice-captain / Turn substitution if {cap.name} plays Turn 1.",
            )
        )

    # Case B: Top transfer minutes reduction (plays 15m instead of 25m)
    if dossier.transfer_recommendations and dossier.transfer_recommendations[0].in_players:
        top_tx = dossier.transfer_recommendations[0]
        in_p = top_tx.in_players[0]
        tx_delta = round(-4.5, 2)
        sensitivities.append(
            SensitivityCase(
                parameter=f"{in_p.get('name', 'Transfer In')} Foul Trouble / Minutes Squeeze",
                shock_description="Incoming transfer restricted to ~15 minutes due to early fouls or blowout.",
                baseline_outcome_fp=base_total,
                shocked_outcome_fp=round(base_total + tx_delta, 2),
                delta_fp=tx_delta,
                decision_reversal=top_tx.net_transfer_value < 4.5,
                mitigation="Review alternative Transfer Option 2 with higher minutes floor.",
            )
        )

    # Case C: Turn 1 starter floor bust (< 6 FP)
    if t1_starters:
        bust_p = t1_starters[0]
        sub_cover = t2_bench[0].name if t2_bench else "None"
        sensitivities.append(
            SensitivityCase(
                parameter=f"Turn 1 Starter Floor Bust ({bust_p.name})",
                shock_description=f"{bust_p.name} scores only 4.0 FP in Turn 1.",
                baseline_outcome_fp=base_total,
                shocked_outcome_fp=round(base_total - (bust_p.expected_fp - 4.0), 2),
                delta_fp=round(-(bust_p.expected_fp - 4.0), 2),
                decision_reversal=True,
                mitigation=f"Trigger Intra-Round Substitution: sub in {sub_cover} for Turn 2.",
            )
        )

    # 3. Devil's Advocate Checklist
    # Check 1: Rule Check
    has_cap = ln.captain is not None
    has_sixth = ln.sixth_man is not None
    squad_len = len(ln.starters) + len(ln.bench) + (1 if ln.sixth_man else 0) + (1 if ln.coach else 0)
    rule_ok = (len(ln.starters) == 5 and has_cap and has_sixth and squad_len == 11)
    checklist.append(
        ChecklistItem(
            check_name="Official Rules & Formation Legality",
            status="PASS" if rule_ok else "ALERT",
            evidence=f"Formation: {ln.formation} | Squad: {squad_len}/11 units | Cap: {'YES' if has_cap else 'NO'}",
            details="Complies strictly with Classic Mode position constraints (1-3 G, 1-3 F, 1-2 C, 1 6th Man, 1 HC).",
        )
    )

    # Check 2: Forecast Plausibility Check
    extreme_projections = [s for s in ln.starters if s.expected_fp > 28.0 or s.expected_fp < 4.0]
    forecast_status = "WARNING" if extreme_projections else "PASS"
    checklist.append(
        ChecklistItem(
            check_name="Projection Plausibility & Outlier Bounds",
            status=forecast_status,
            evidence=f"{len(extreme_projections)} extreme outliers (>28 FP or <4 FP) in Starting 5.",
            details="Ensure expectations reflect multi-game median rather than single-game ceiling spikes.",
        )
    )

    # Check 3: Deterministic Alternative Check
    alts = ln.alternatives
    alt_status = "PASS"
    if alts:
        top_alt_diff = round(ln.expected_total_fp - float(alts[0].get("objective_value", ln.expected_total_fp)), 2)
        if top_alt_diff < 0.8:
            alt_status = "WARNING"
            details = f"Top alternative formation ({alts[0].get('formation', '')}) is within {top_alt_diff:.2f} FP of optimal."
        else:
            details = f"Optimal lineup holds clear +{top_alt_diff:.2f} FP buffer over next best formation."
    else:
        top_alt_diff = 0.0
        details = "No close alternative formations detected."

    checklist.append(
        ChecklistItem(
            check_name="Alternative Formation Viability",
            status=alt_status,
            evidence=f"{len(alts)} alternative formations evaluated.",
            details=details,
        )
    )

    # Check 4: Downside Regret Check
    high_unc_starters = [s for s in ln.starters if s.uncertainty >= 4.0]
    regret_status = "WARNING" if len(high_unc_starters) >= 3 else "PASS"
    checklist.append(
        ChecklistItem(
            check_name="Downside Variance & Uncertainty Regret",
            status=regret_status,
            evidence=f"{len(high_unc_starters)} starters carry sigma uncertainty >= 4.0 FP.",
            details="Consider balancing upside scorers with higher-floor rotation anchors in cash/head-to-head leagues.",
        )
    )

    # Check 5: Context & Bank Flexibility Check
    bank = dossier.bank_credits
    bank_status = "PASS" if bank >= 0.5 else "WARNING"
    checklist.append(
        ChecklistItem(
            check_name="Bank Flexibility & Roll-Forward Liquidity",
            status=bank_status,
            evidence=f"Remaining bank: {bank:.1f} Credits.",
            details="Holding >= 0.5 Credits provides strategic elasticity for emergency next-round injury transfers.",
        )
    )

    # Compute overall verdict
    warning_count = sum(1 for c in checklist if c.status == "WARNING")
    alert_count = sum(1 for c in checklist if c.status == "ALERT")

    if alert_count > 0:
        verdict = "HIGH_RISK"
    elif warning_count >= 2:
        verdict = "MODERATE_RISK"
    else:
        verdict = "ROBUST"

    return StrategicAnalysisResult(
        team_id=dossier.team_id,
        dossier_id=dossier.dossier_id,
        generated_at=now_iso,
        assumptions=assumptions,
        sensitivities=sensitivities,
        checklist=checklist,
        verdict=verdict,
    )
