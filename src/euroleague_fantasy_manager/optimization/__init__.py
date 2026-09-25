"""EuroLeague Fantasy Challenge Decision & Optimization Layer (V0.4).

Core boundary: V0.3 predicts. V0.4 decides.
"""

from .backtest import (
    HistoricalDecisionBacktester,
    OptimizationBacktestSummary,
    RoundBacktestResult,
    score_lineup_with_actuals,
)
from .candidates import CandidateGenerator, CandidatePool
from .constraints import (
    ConstraintValidationResult,
    OptimizationConstraints,
    PlayerProjectionContract,
    validate_lineup_constraints,
    validate_squad_constraints,
    validate_transfers_constraints,
)
from .lineup import (
    FixedSquadLineupOptimizer,
    OptimalLineupDecision,
    brute_force_exhaustive_lineup,
)
from .multi_round import (
    MultiRoundOptimizer,
    MultiRoundPlan,
    RoundDecisionStep,
)
from .objective import (
    LineupScoreBreakdown,
    RiskMode,
    compute_positional_replacement_levels,
    evaluate_lineup_objective,
)
from .option_value import (
    compute_captain_option_value,
    compute_turn_substitution_option_bonus,
)
from .initial_team import (
    InitialTeamOptimizationResult,
    InitialTeamRiskMode,
    optimize_initial_team,
    optimize_initial_team_detailed,
)
from .transfers import (
    TransferOptimizationResult,
    TransferOptimizer,
    TransferRecommendation,
)

__all__ = [
    "ConstraintValidationResult",
    "OptimizationConstraints",
    "PlayerProjectionContract",
    "validate_lineup_constraints",
    "validate_squad_constraints",
    "validate_transfers_constraints",
    "RiskMode",
    "LineupScoreBreakdown",
    "evaluate_lineup_objective",
    "compute_positional_replacement_levels",
    "compute_captain_option_value",
    "compute_turn_substitution_option_bonus",
    "FixedSquadLineupOptimizer",
    "OptimalLineupDecision",
    "brute_force_exhaustive_lineup",
    "CandidateGenerator",
    "CandidatePool",
    "InitialTeamOptimizationResult",
    "InitialTeamRiskMode",
    "optimize_initial_team",
    "optimize_initial_team_detailed",
    "TransferOptimizer",
    "TransferRecommendation",
    "TransferOptimizationResult",
    "MultiRoundOptimizer",
    "MultiRoundPlan",
    "RoundDecisionStep",
    "HistoricalDecisionBacktester",
    "OptimizationBacktestSummary",
    "RoundBacktestResult",
    "score_lineup_with_actuals",
]
