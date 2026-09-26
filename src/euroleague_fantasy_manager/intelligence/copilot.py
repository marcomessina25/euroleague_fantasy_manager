"""LLM Copilot orchestration and persona analysis layer for V0.6 Strategic Intelligence.

Coordinates:
- Structured Manager Dossier + Deterministic Strategic Signals
- Specialized Personas (Manager Briefing, Devil's Advocate, Tactical Analyst, Strategic Planner)
- Multi-provider execution (OpenAI, Gemini, Claude, OpenRouter, Local, Heuristic)
- Guaranteed zero-mutation of persistent team state
- Fault isolation: Graceful fallback to HeuristicProvider on provider timeouts, rate limits, or network errors
- Post-generation consistency verification
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
from typing import Any

from .consistency import ConsistencyReport, verify_consistency
from .dossier import ManagerDossier, generate_manager_dossier
from .providers import (
    BaseLLMProvider,
    HeuristicProvider,
    ProviderError,
    ProviderRequest,
    get_provider,
)
from .strategic_analysis import StrategicAnalysisResult, analyze_dossier

logger = logging.getLogger(__name__)

PERSONA_PROMPTS = {
    "briefing": (
        "You are the Lead Analytical Strategist for an elite EuroLeague Fantasy manager. "
        "Your role is to deliver a concise, crisp Manager Briefing summarizing current squad readiness, "
        "the optimal Starting Five, captaincy choice, and recommended transfer moves. "
        "Strictly ground all statements in the provided Manager Dossier. Do not invent players or rules."
    ),
    "devil_advocate": (
        "You are the Devil's Advocate for an elite EuroLeague Fantasy manager. "
        "Your role is to aggressively challenge complacency and groupthink. "
        "Question fragile projections, identify minute-squeeze rotation risks, expose fixture traps, "
        "and scrutinize whether the top transfer option is truly worth the budget. "
        "Be constructively skeptical, intellectually honest, and focus on downside regret."
    ),
    "tactical_analyst": (
        "You are the Tactical Rotation & Matchup Specialist for EuroLeague Fantasy. "
        "Analyze Turn 1 vs Turn 2 substitution timing, foul trouble sensitivity, pace and defensive matchups, "
        "and how the Sixth Man (1.0x) and Bench (0.5x) units provide critical optionality."
    ),
    "strategic_planner": (
        "You are the Long-Range Squad Architect for EuroLeague Fantasy. "
        "Focus on multi-round budget elasticity, bank liquidity, injury cushion, "
        "and timing of major roster overhauls around upcoming double-round weeks or unlimited trade windows."
    ),
}


@dataclass(frozen=True, slots=True)
class CopilotAdviceResult:
    dossier_id: str
    team_id: str
    team_name: str
    league: str
    persona: str
    provider: str
    model: str
    analysis_text: str
    consistency: ConsistencyReport
    is_fallback: bool
    fallback_reason: str | None
    latency_ms: float
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dossier_id": self.dossier_id,
            "team_id": self.team_id,
            "team_name": self.team_name,
            "league": self.league,
            "persona": self.persona,
            "provider": self.provider,
            "model": self.model,
            "analysis_text": self.analysis_text,
            "consistency": self.consistency.to_dict(),
            "is_fallback": self.is_fallback,
            "fallback_reason": self.fallback_reason,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp,
        }


def generate_copilot_advice(
    dossier: ManagerDossier | None = None,
    team_id: str | None = None,
    season: str = "2026/27",
    round_number: int | None = None,
    persona: str = "briefing",
    provider_name: str = "heuristic",
    api_key: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    database_path: Any | None = None,
) -> CopilotAdviceResult:
    """Generate intelligent strategic advice grounded in deterministic facts with zero state mutation."""
    # 1. Obtain or generate Manager Dossier
    if dossier is None:
        if not team_id:
            raise ValueError("Either 'dossier' or 'team_id' must be provided.")
        dossier = generate_manager_dossier(
            team_id=team_id,
            season=season,
            round_number=round_number,
            database_path=database_path,
        )

    # 2. Compute deterministic strategic signals
    strat_result = analyze_dossier(dossier)

    # 3. Select Persona system prompt
    norm_persona = persona.strip().lower()
    system_prompt = PERSONA_PROMPTS.get(norm_persona, PERSONA_PROMPTS["briefing"])
    system_prompt += (
        "\n\nSTRICT BOUNDARY CONSTRAINTS:\n"
        "1. Never attempt to execute or apply changes; you are purely an advisory challenger.\n"
        "2. Do not invent player names, points, or prices outside the dossier.\n"
        "3. Official scoring rules: Captain scores 2.0x, Sixth Man scores 1.0x, Starters score 1.0x, Bench scores 0.5x, Head Coach scores 1.0x.\n"
        "4. Turn rules: Bench players who already played are locked at 0.5x and cannot sub onto the court."
    )

    # 4. Construct grounded analysis prompt
    dossier_summary = {
        "team_name": dossier.team_name,
        "league": dossier.league,
        "season": dossier.season,
        "round_number": dossier.round_number,
        "bank_credits": dossier.bank_credits,
        "transfers_remaining": dossier.transfers_remaining,
        "formation": dossier.current_lineup.formation,
        "projected_total_fp": dossier.current_lineup.expected_total_fp,
        "realized_total_fp": dossier.current_lineup.realized_total_fp,
        "unplayed_expected_fp": dossier.current_lineup.unplayed_expected_fp,
        "captain": dossier.current_lineup.captain.name if dossier.current_lineup.captain else "None",
        "sixth_man": dossier.current_lineup.sixth_man.name if dossier.current_lineup.sixth_man else "None",
        "starting_five": [
            {"name": p.name, "pos": p.position, "exp_fp": p.expected_fp, "actual_fp": p.actual_fp, "turn": p.turn_number}
            for p in dossier.current_lineup.starters
        ],
        "bench": [
            {"name": p.name, "pos": p.position, "exp_fp": p.expected_fp, "has_played": p.has_played, "turn": p.turn_number}
            for p in dossier.current_lineup.bench
        ],
        "top_transfers": [
            {
                "option": tx.option_id,
                "out": [p["name"] for p in tx.out_players],
                "in": [p["name"] for p in tx.in_players],
                "net_value": tx.net_transfer_value,
                "remaining_bank": tx.remaining_bank_credits,
            }
            for tx in dossier.transfer_recommendations[:3]
        ],
        "intra_round_subs": {
            "can_sub": dossier.intra_round_recommendations.can_sub,
            "projected_gain": dossier.intra_round_recommendations.projected_gain,
            "suggestions": dossier.intra_round_recommendations.suggested_subs,
        },
        "deterministic_verdict": strat_result.verdict,
        "top_assumptions": [
            {"name": a.name, "player": a.player_name, "impact": a.estimated_impact_fp, "risk": a.risk_level}
            for a in strat_result.assumptions[:3]
        ],
        "sensitivities": [
            {"scenario": s.shock_description, "delta": s.delta_fp, "reversal": s.decision_reversal}
            for s in strat_result.sensitivities[:2]
        ],
    }

    user_prompt = (
        f"Review the following quantitative Manager Dossier and provide your strategic analysis:\n\n"
        f"```json\n{json.dumps(dossier_summary, indent=2)}\n```\n\n"
        f"Provide your structured advice in markdown."
    )

    # 5. Execute Provider call with safe fallback
    provider = get_provider(provider_name, api_key=api_key, model=model)
    req = ProviderRequest(
        prompt=user_prompt,
        system_prompt=system_prompt,
        model=model,
        temperature=temperature,
    )

    is_fallback = False
    fallback_reason = None

    try:
        resp = provider.generate(req)
        analysis_text = resp.content
        used_provider = resp.provider
        used_model = resp.model
        latency = resp.latency_ms
    except Exception as e:
        logger.warning("Primary provider '%s' failed: %s. Falling back to HeuristicProvider.", provider_name, e)
        fallback = HeuristicProvider()
        resp = fallback.generate(req)
        analysis_text = resp.content
        used_provider = fallback.name
        used_model = fallback.default_model or "deterministic-heuristic"
        latency = resp.latency_ms
        is_fallback = True
        fallback_reason = str(e)

    # 6. Post-generation consistency check
    consistency = verify_consistency(analysis_text, dossier)

    now_iso = datetime.now(timezone.utc).isoformat()
    return CopilotAdviceResult(
        dossier_id=dossier.dossier_id,
        team_id=dossier.team_id,
        team_name=dossier.team_name,
        league=dossier.league,
        persona=norm_persona,
        provider=used_provider,
        model=used_model,
        analysis_text=analysis_text,
        consistency=consistency,
        is_fallback=is_fallback,
        fallback_reason=fallback_reason,
        latency_ms=latency,
        timestamp=now_iso,
    )
