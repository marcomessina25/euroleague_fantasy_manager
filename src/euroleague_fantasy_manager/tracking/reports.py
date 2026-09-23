"""Formatting utilities, ASCII tables, and CSV exporters for V0.45 tracking reports."""

import csv
import io
from pathlib import Path
from typing import Sequence

from .evaluator import ClosedLoopSummary
from .models import DecisionOutcome, DecisionRecord


def format_decision_detail(decision: DecisionRecord, outcome: DecisionOutcome | None = None) -> str:
    """Format a detailed view of a single DecisionRecord and optional realization outcome."""
    lines: list[str] = [
        "=" * 72,
        f"  V0.45 FANTASY DECISION RECORD: {decision.decision_id}",
        "=" * 72,
        f"  Team:       {decision.team_id}  |  Season: {decision.season}  |  Round: R{decision.round_number:02d} (Turn {decision.turn_number})",
        f"  Type:       {decision.decision_type.value.upper()}  |  Override: {'YES' if decision.is_override else 'NO'}",
        f"  Timestamp:  {decision.created_at}",
        f"  Model:      {decision.provenance.model_id} (v{decision.provenance.model_version})",
        f"  Risk Mode:  {decision.provenance.risk_mode} (lambda={decision.provenance.risk_lambda})",
        "-" * 72,
    ]

    if decision.actual_lineup:
        act = decision.actual_lineup
        lines.extend([
            "  CHOSEN LINEUP:",
            f"    Formation:    {act.formation}",
            f"    Starters:     {list(act.starter_ids)}",
            f"    Captain:      Player {act.captain_id} (2.0x)",
            f"    Sixth Man:    Player {act.sixth_man_id} (1.0x)",
            f"    Bench:        {list(act.bench_ids)} (0.5x)",
            f"    Head Coach:   Coach {act.head_coach_id} (1.0x)",
        ])

    if decision.recommended_lineup:
        rec = decision.recommended_lineup
        lines.extend([
            "",
            "  MODEL RECOMMENDATION:",
            f"    Formation:    {rec.formation}",
            f"    Starters:     {list(rec.starter_ids)}",
            f"    Captain:      Player {rec.captain_id}",
            f"    Sixth Man:    Player {rec.sixth_man_id}",
            f"    Expected:     {rec.expected_score:.2f} FP",
        ])

    if decision.actual_squad_ids:
        lines.extend([
            "",
            f"  CHOSEN SQUAD ({len(decision.actual_squad_ids)} units):",
            f"    {list(decision.actual_squad_ids)}",
        ])

    if decision.recommended_squad_ids:
        lines.extend([
            "",
            f"  RECOMMENDED SQUAD ({len(decision.recommended_squad_ids)} units):",
            f"    {list(decision.recommended_squad_ids)}",
        ])

    if decision.notes:
        lines.extend(["", f"  NOTES: {decision.notes}"])

    if outcome:
        lines.extend([
            "-" * 72,
            "  REALIZED OUTCOME & REGRET (POST-ROUND):",
            f"    Human Actual Score:        {outcome.human_actual_score:.2f} FP",
            f"    Model Recommended Score:   {outcome.recommended_actual_score:.2f} FP",
            f"    Hindsight Oracle Score:    {outcome.oracle_actual_score:.2f} FP",
            f"    Human Regret:              {outcome.human_regret:.2f} FP",
            f"    Model Regret:              {outcome.model_regret:.2f} FP",
            f"    Human vs Model Difference: {outcome.human_vs_model:+.2f} FP",
            f"    Captain Regret:            {outcome.captain_regret:.2f} FP",
            f"    Sixth Man Regret:          {outcome.sixth_man_regret:.2f} FP",
            f"    Bench Regret:              {outcome.bench_regret:.2f} FP",
            f"    Prediction MAE:            {outcome.prediction_mae:.2f} FP (Bias: {outcome.prediction_bias:+.2f})",
        ])

    lines.append("=" * 72)
    return "\n".join(lines)


def format_decisions_table(decisions: Sequence[DecisionRecord]) -> str:
    """Format a tabular list of logged decisions."""
    if not decisions:
        return "No decisions logged matching the query criteria."

    lines = [
        "=" * 88,
        "  V0.45 LOGGED FANTASY DECISIONS",
        "=" * 88,
        f"{'ID':<28} | {'Round':<6} | {'Turn':<4} | {'Type':<10} | {'Override':<8} | {'Formation':<9} | {'Cap':<5}",
        "-" * 88,
    ]

    for d in decisions:
        form = d.actual_lineup.formation if d.actual_lineup else "-"
        cap = str(d.actual_lineup.captain_id) if d.actual_lineup else "-"
        lines.append(
            f"{d.decision_id:<28} | R{d.round_number:<5} | T{d.turn_number:<3} | {d.decision_type.value:<10} | "
            f"{('Yes' if d.is_override else 'No'):<8} | {form:<9} | {cap:<5}"
        )

    lines.append("=" * 88)
    return "\n".join(lines)


def export_closed_loop_csv(summary: ClosedLoopSummary, output_path: Path | str) -> Path:
    """Export closed loop round-by-round evaluation metrics to CSV."""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "round_number",
        "turn_number",
        "decision_id",
        "decision_type",
        "is_override",
        "human_score",
        "rec_score",
        "oracle_score",
        "human_regret",
        "model_regret",
        "captain_regret",
        "prediction_mae",
    ]

    with open(p, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in summary.round_details:
            writer.writerow(row)

    return p
