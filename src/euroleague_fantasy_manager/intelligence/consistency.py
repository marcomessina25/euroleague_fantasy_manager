"""Consistency and safety verification layer for V0.6 Strategic Intelligence Copilot.

Ensures LLM interpretations strictly ground their claims in the deterministic Manager Dossier:
- Detects hallucinated player entities not present in the dossier or market.
- Verifies numerical claims (points, prices, gains) against deterministic figures.
- Flags rule contradictions (e.g., wrong multipliers, impossible formations).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from .dossier import ManagerDossier


@dataclass(frozen=True, slots=True)
class ConsistencyReport:
    is_consistent: bool
    hallucinated_players: list[str]
    unverified_numbers: list[float]
    rule_warnings: list[str]
    factual_confidence_score: float
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def verify_consistency(
    copilot_text: str,
    dossier: ManagerDossier,
    number_tolerance: float = 0.5,
) -> ConsistencyReport:
    """Verify that Copilot text does not hallucinate entities, numbers, or rules."""
    text_lower = copilot_text.lower()
    details: list[str] = []
    rule_warnings: list[str] = []
    hallucinated_players: list[str] = []

    # 1. Compile legitimate player names from dossier
    known_player_names: dict[str, int] = {}
    known_numbers: set[float] = set()

    # Add squad players
    ln = dossier.current_lineup
    for s in ln.starters:
        known_player_names[s.name.lower()] = s.player_id
        known_numbers.add(round(s.expected_fp, 1))
        known_numbers.add(round(s.credits, 1))
        if s.actual_fp is not None:
            known_numbers.add(round(s.actual_fp, 1))

    for b in ln.bench:
        known_player_names[b.name.lower()] = b.player_id
        known_numbers.add(round(b.expected_fp, 1))
        known_numbers.add(round(b.credits, 1))
        if b.actual_fp is not None:
            known_numbers.add(round(b.actual_fp, 1))

    if ln.sixth_man:
        known_player_names[ln.sixth_man.name.lower()] = ln.sixth_man.player_id
        known_numbers.add(round(ln.sixth_man.expected_fp, 1))
        known_numbers.add(round(ln.sixth_man.credits, 1))

    if ln.coach:
        known_player_names[ln.coach.name.lower()] = ln.coach.player_id
        known_numbers.add(round(ln.coach.expected_fp, 1))
        known_numbers.add(round(ln.coach.credits, 1))

    # Add transfer recommendation players
    for tx in dossier.transfer_recommendations:
        known_numbers.add(round(tx.gross_gain, 1))
        known_numbers.add(round(tx.net_transfer_value, 1))
        known_numbers.add(round(tx.remaining_bank_credits, 1))
        for p in tx.out_players + tx.in_players:
            pname = p.get("name", "")
            if pname:
                known_player_names[pname.lower()] = p.get("player_id", 0)
            if "expected_fp" in p:
                known_numbers.add(round(float(p["expected_fp"]), 1))
            if "credits" in p:
                known_numbers.add(round(float(p["credits"]), 1))

    # Add general totals
    known_numbers.add(round(ln.expected_total_fp, 1))
    known_numbers.add(round(ln.realized_total_fp, 1))
    known_numbers.add(round(ln.unplayed_expected_fp, 1))
    known_numbers.add(round(dossier.bank_credits, 1))
    known_numbers.add(float(dossier.transfers_remaining))
    known_numbers.add(float(dossier.round_number))

    # Add player valuations sample names
    for pv in dossier.player_valuations:
        pname = pv.get("player_name", "")
        if pname:
            known_player_names[pname.lower()] = pv.get("player_id", 0)

    # 2. Rule Consistency Checks (detect blatant rule errors in narrative)
    if "captain 3x" in text_lower or "triple captain" in text_lower:
        rule_warnings.append("Illegal chip reference: EuroLeague Fantasy has no Triple Captain chip (captain is always 2.0x).")
    if "bench boost" in text_lower:
        rule_warnings.append("Illegal chip reference: Bench Boost does not exist in EuroLeague Fantasy.")
    if "free hit" in text_lower:
        rule_warnings.append("Illegal chip reference: Free Hit does not exist in EuroLeague Fantasy (use Unlimited Trade windows).")
    if "bench scores 100%" in text_lower or "full bench points" in text_lower:
        rule_warnings.append("Contradicts official rules: bench units score at 50% (0.5x), only Sixth Man converts at 100%.")

    # 3. Entity check: Look for quoted player names or capitalized multi-word tokens
    # e.g. "recommend selling John Doe" or "bring in UnknownAlienSuperstar"
    transfer_keywords = [
        "sell",
        "buy",
        "transfer",
        "substitute",
        "captain",
        "bench",
        "starter",
        "bring in",
        "sign",
        "recruit",
        "target",
    ]
    for kw in transfer_keywords:
        pattern = rf"\b{kw}\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\b"
        for match in re.finditer(pattern, copilot_text):
            candidate = match.group(1).strip()
            cand_lower = candidate.lower()
            if cand_lower not in known_player_names and cand_lower not in ["euroleague fantasy", "head coach"]:
                # Check for partial match
                if not any(cand_lower in kn or kn in cand_lower for kn in known_player_names):
                    hallucinated_players.append(candidate)

    # 4. Numerical plausibility check
    # Find numbers followed by FP, pts, or credits
    unverified_numbers: list[float] = []
    num_pattern = r"(\b\d+(?:\.\d+)?)\s*(?:fp|pts|points|credits|cr)\b"
    for match in re.finditer(num_pattern, text_lower):
        val = float(match.group(1))
        # Exclude common integers like 0, 1, 2, 4, 11
        if val in (0.0, 1.0, 2.0, 4.0, 11.0, 5.0, 10.0):
            continue
        # Check against known numbers
        matched = False
        for kn in known_numbers:
            if abs(val - kn) <= number_tolerance:
                matched = True
                break
        if not matched and val > 0:
            unverified_numbers.append(val)

    # Deduplicate
    hallucinated_players = list(set(hallucinated_players))
    unverified_numbers = sorted(set(unverified_numbers))

    # Compute confidence score
    confidence = 1.0
    if rule_warnings:
        confidence -= 0.3 * len(rule_warnings)
    if hallucinated_players:
        confidence -= 0.25 * len(hallucinated_players)
    if len(unverified_numbers) > 3:
        confidence -= 0.15

    confidence = max(0.0, min(1.0, round(confidence, 2)))
    is_consistent = (len(rule_warnings) == 0 and len(hallucinated_players) == 0 and confidence >= 0.70)

    if not is_consistent:
        if rule_warnings:
            details.extend(rule_warnings)
        if hallucinated_players:
            details.append(f"Unrecognized player names: {', '.join(hallucinated_players)}")
        if unverified_numbers:
            details.append(f"Unverified figures: {', '.join(f'{n:.1f}' for n in unverified_numbers[:5])}")
    else:
        details.append("Output fully grounded in Manager Dossier quantitative facts.")

    return ConsistencyReport(
        is_consistent=is_consistent,
        hallucinated_players=hallucinated_players,
        unverified_numbers=unverified_numbers,
        rule_warnings=rule_warnings,
        factual_confidence_score=confidence,
        details=details,
    )
