"""Strategic Intelligence & LLM Copilot layer for V0.6."""

from .consistency import ConsistencyReport, verify_consistency
from .copilot import CopilotAdviceResult, generate_copilot_advice
from .dossier import ManagerDossier, generate_manager_dossier
from .providers import (
    BaseLLMProvider,
    GeminiProvider,
    HeuristicProvider,
    LocalProvider,
    OpenAIProvider,
    OpenRouterProvider,
    get_provider,
    list_available_providers,
)
from .strategic_analysis import (
    ChecklistItem,
    SensitivityCase,
    StrategicAnalysisResult,
    StrategicAssumption,
    analyze_dossier,
)

__all__ = [
    "ManagerDossier",
    "generate_manager_dossier",
    "StrategicAssumption",
    "SensitivityCase",
    "ChecklistItem",
    "StrategicAnalysisResult",
    "analyze_dossier",
    "BaseLLMProvider",
    "HeuristicProvider",
    "GeminiProvider",
    "OpenAIProvider",
    "OpenRouterProvider",
    "LocalProvider",
    "get_provider",
    "list_available_providers",
    "ConsistencyReport",
    "verify_consistency",
    "CopilotAdviceResult",
    "generate_copilot_advice",
]
