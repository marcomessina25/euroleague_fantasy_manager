from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .backtest import run_walk_forward_evaluation


@dataclass(frozen=True, slots=True)
class ThreeWayErrorDecomposition:
    """Telescoping decomposition of fantasy score error (Section 4.4 of V0.9 spec).

    Algebraic Formulation:
        Total Error = Model Error + Execution Regret + Aleatoric / Residual Component

    Methodological Note:
        The residual component represents a post-hoc residual under the chosen model specification,
        not necessarily an identifiable irreducible basketball noise limit. No causal interpretation
        is made or implied.
    """

    model_name: str
    season: str
    round_number: int
    actual_score: float
    predicted_score: float
    total_error: float
    model_error: float
    execution_regret: float
    aleatoric_noise: float
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def decompose_round_error(
    predicted_score: float,
    actual_score: float | None,
    execution_regret: float = 0.0,
    post_hoc_expected: float | None = None,
    model_name: str = "learned_v09",
    season: str = "E2025",
    round_number: int = 1,
    is_dnp: bool = False,
    is_unavailable: bool = False,
) -> ThreeWayErrorDecomposition:
    """Decompose score discrepancy into Model Error, Execution Regret, and Aleatoric / Residual Component.

    Algebraic Invariant:
        model_error + execution_regret + aleatoric_noise == total_error
    """
    safe_actual = 0.0 if (actual_score is None or is_dnp or is_unavailable) else float(actual_score)
    safe_pred = max(0.0, float(predicted_score))

    tot_err = round(abs(safe_actual - safe_pred), 2)
    regret = round(max(0.0, min(tot_err, float(execution_regret))), 2)

    if post_hoc_expected is not None:
        raw_m_err = abs(safe_pred - float(post_hoc_expected))
    else:
        # Default model error proportion: bias/discrepancy proxy bounded by remaining error
        raw_m_err = 0.35 * (tot_err - regret)

    m_err = round(max(0.0, min(tot_err - regret, raw_m_err)), 2)
    noise = round(max(0.0, tot_err - (m_err + regret)), 2)

    # Clean floating-point precision adjustment on aleatoric noise
    residual_drift = round(tot_err - (m_err + regret + noise), 4)
    if abs(residual_drift) > 0:
        noise = round(noise + residual_drift, 2)

    prov = {
        "is_dnp": is_dnp,
        "is_unavailable": is_unavailable,
        "missing_actual": actual_score is None,
        "decomposed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    return ThreeWayErrorDecomposition(
        model_name=model_name,
        season=season,
        round_number=int(round_number),
        actual_score=round(safe_actual, 2),
        predicted_score=round(safe_pred, 2),
        total_error=tot_err,
        model_error=m_err,
        execution_regret=regret,
        aleatoric_noise=noise,
        provenance=prov,
    )


@dataclass(frozen=True, slots=True)
class BenchmarkModelEntry:
    model_name: str
    model_version: str
    mae: float
    rmse: float
    bias: float
    spearman: float
    top10_recall: float
    value_spearman: float
    brier_score: float
    avg_lineup_score: float
    lineup_regret: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MultiModelBenchmarkLedger:
    season: str
    rounds_evaluated: str
    entries: tuple[BenchmarkModelEntry, ...]
    best_mae_model: str
    best_spearman_model: str
    best_lineup_model: str
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "rounds_evaluated": self.rounds_evaluated,
            "best_mae_model": self.best_mae_model,
            "best_spearman_model": self.best_spearman_model,
            "best_lineup_model": self.best_lineup_model,
            "provenance": self.provenance,
            "models": [e.to_dict() for e in self.entries],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Multi-Model Benchmark Ledger — Season {self.season}",
            "",
            f"- **Rounds Evaluated**: {self.rounds_evaluated}",
            f"- **Point Accuracy Leader (Lowest MAE)**: `{self.best_mae_model}`",
            f"- **Rank Correlation Leader (Highest Spearman)**: `{self.best_spearman_model}`",
            f"- **Lineup Simulation Leader (Highest Actual Points)**: `{self.best_lineup_model}`",
        ]
        if self.provenance:
            gen_at = self.provenance.get("generated_at", "N/A")
            lines.append(f"- **Benchmark Provenance**: Generated at `{gen_at}`")
        lines.extend(
            [
                "",
                "| Model | Version | MAE | RMSE | Bias | Spearman | Top-10 | Value Rho | Brier | Lineup Pts | Lineup Regret |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for e in self.entries:
            lines.append(
                f"| `{e.model_name}` | `{e.model_version}` | {e.mae:.2f} | {e.rmse:.2f} | {e.bias:+.2f} | "
                f"{e.spearman:.3f} | {e.top10_recall:.2f} | {e.value_spearman:.3f} | {e.brier_score:.3f} | "
                f"{e.avg_lineup_score:.2f} | {e.lineup_regret:.2f} |"
            )
        return "\n".join(lines)


def run_multi_model_benchmark(
    season: str = "2025",
    rounds: str = "1:4",
    models: Sequence[str] = (
        "season_mean",
        "last5",
        "xpdk_v02",
        "fp_decomposed_v03",
        "fp_context_v08",
        "learned_v09",
    ),
    database_path: Path | None = None,
    reports_dir: Path | None = None,
) -> MultiModelBenchmarkLedger:
    """Execute walk-forward benchmark comparing all model generations across historical seasons."""
    kwargs: dict[str, Any] = {
        "season": season,
        "rounds": rounds,
        "models": models,
    }
    if database_path is not None:
        kwargs["database_path"] = database_path
    if reports_dir is not None:
        kwargs["reports_dir"] = reports_dir

    wf_res = run_walk_forward_evaluation(**kwargs)

    entries: list[BenchmarkModelEntry] = []
    ms_by_name = {m["model_name"]: m for m in wf_res.get("models", [])}
    ds_by_name = {d["model_name"]: d for d in wf_res.get("lineup_decisions", [])}

    for m_name in models:
        m_canon = m_name.strip().lower()
        # Find match in results
        ms = next((v for k, v in ms_by_name.items() if k.lower() == m_canon), None)
        ds = next((v for k, v in ds_by_name.items() if k.lower() == m_canon), None)
        if ms is None:
            continue

        entries.append(
            BenchmarkModelEntry(
                model_name=ms["model_name"],
                model_version=ms.get("model_version", "0.0.0"),
                mae=float(ms.get("mae", 0.0)),
                rmse=float(ms.get("rmse", 0.0)),
                bias=float(ms.get("bias", 0.0)),
                spearman=float(ms.get("spearman", 0.0)),
                top10_recall=float(ms.get("top10_recall", 0.0)),
                value_spearman=float(ms.get("value_spearman", 0.0)),
                brier_score=float(ms.get("brier_score", 0.0)),
                avg_lineup_score=float(ds.get("avg_recommended_actual_score", 0.0)) if ds else 0.0,
                lineup_regret=float(ds.get("avg_lineup_regret", 0.0)) if ds else 0.0,
            )
        )

    best_mae = min(entries, key=lambda e: e.mae).model_name if entries else ""
    best_spearman = max(entries, key=lambda e: e.spearman).model_name if entries else ""
    best_lineup = max(entries, key=lambda e: e.avg_lineup_score).model_name if entries else ""

    ledger = MultiModelBenchmarkLedger(
        season=str(season),
        rounds_evaluated=str(rounds),
        entries=tuple(entries),
        best_mae_model=best_mae,
        best_spearman_model=best_spearman,
        best_lineup_model=best_lineup,
        provenance={
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "dataset_version": wf_res.get("dataset_version", "historical-v0.2.5-001"),
            "models_evaluated": list(models),
        },
    )

    if reports_dir is not None:
        out_file = Path(reports_dir) / f"{str(season).lower()}_multi_model_benchmark_ledger.md"
        out_file.write_text(ledger.to_markdown(), encoding="utf-8")

    return ledger
