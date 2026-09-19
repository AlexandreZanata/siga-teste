"""Val-loss tracking para os próximos LoRAs (F15, ADR-025 em docs/09).

Hoje `val_loss_trend` existe só como narrativa escrita à mão
(`training/lora_progression.py`, P07). Este módulo é a infraestrutura
determinística que faltava para o protocolo de `docs/09` §1 ("Leitura de
loss pela tendência — início ~1.0 é normal; **val-loss subindo = parar ou
adicionar dados**") e para os gates go/no-go por degrau do ADR-017:

- `ValLossTracker`: registra `{step, train_loss, val_loss, timestamp}` por
  época/step, com validação determinística dos pontos e timestamps UTC
  injetáveis (reprodutível em teste).
- `analyze_curve`: tendência (`decreasing`/`plateau`/`increasing`) por
  regressão linear de mínimos quadrados sobre a **cauda** da curva (regra do
  protocolo: decisão pela cauda, não pelo valor absoluto), `overfit_gap`
  (val − train) e veredito `continue`/`stop_overfitting`/`add_data`.
- `record_training_run`: registra o run via `experiments.log.new_run`
  (provenance obrigatória: siga_commit, sigateste_commit, dataset_version,
  needle_version/depth, artifact_hash) e grava `experiments/runs/<id>.json`
  com curva + veredito nas `metrics`.
- `build_tracking_report`: relatório comparável entre LoRAs em
  `experiments/reports/val_loss_tracking.json`.

Só stdlib (determinístico primeiro); nenhuma dependência nova; treino real
e engines externas ficam fora do escopo — este módulo não treina nada.
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from experiments.log import new_run

ROOT = Path(__file__).resolve().parent.parent

VERDICT_CONTINUE = "continue"
VERDICT_STOP_OVERFITTING = "stop_overfitting"
VERDICT_ADD_DATA = "add_data"

TREND_DECREASING = "decreasing"
TREND_PLATEAU = "plateau"
TREND_INCREASING = "increasing"

DEFAULT_TAIL_POINTS = 5
DEFAULT_SLOPE_TOLERANCE = 1e-3
DEFAULT_GAP_THRESHOLD = 0.10


class CurveError(ValueError):
    """Curva insuficiente ou malformada para análise determinística."""


def _utc_iso(clock: Callable[[], float] | None) -> str:
    now = time.time() if clock is None else clock()
    return datetime.fromtimestamp(now, tz=timezone.utc).isoformat(timespec="seconds")


def _validate_losses(step: int, train_loss: float, val_loss: float) -> None:
    if isinstance(step, bool) or not isinstance(step, int) or step < 0:
        raise CurveError(f"step deve ser inteiro >= 0, recebido {step!r}")
    for name, value in (("train_loss", train_loss), ("val_loss", val_loss)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CurveError(f"{name} deve ser numérico, recebido {value!r}")
        if not math.isfinite(float(value)):
            raise CurveError(f"{name} deve ser finito, recebido {value!r}")
    if val_loss < 0:
        raise CurveError(f"val_loss deve ser >= 0 (loss), recebido {val_loss!r}")


class ValLossTracker:
    """Acumula a curva de loss por época/step de um treino de LoRA."""

    def __init__(
        self,
        *,
        model_name: str,
        dataset_size: int,
        depth: int,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not model_name or not isinstance(model_name, str):
            raise CurveError("model_name deve ser string não vazia")
        if isinstance(dataset_size, bool) or not isinstance(dataset_size, int) or dataset_size < 1:
            raise CurveError(f"dataset_size deve ser inteiro >= 1, recebido {dataset_size!r}")
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 1:
            raise CurveError(f"depth deve ser inteiro >= 1, recebido {depth!r}")
        self.model_name = model_name
        self.dataset_size = dataset_size
        self.depth = depth
        self._clock = clock
        self.points: list[dict[str, Any]] = []

    def log(self, step: int, train_loss: float, val_loss: float) -> dict[str, Any]:
        """Registra um ponto `{step, train_loss, val_loss, timestamp}` validado."""
        _validate_losses(step, train_loss, val_loss)
        point = {
            "step": step,
            "train_loss": float(train_loss),
            "val_loss": float(val_loss),
            "timestamp": _utc_iso(self._clock),
        }
        if self.points and step <= self.points[-1]["step"]:
            raise CurveError(
                f"step deve ser estritamente crescente: {step} <= {self.points[-1]['step']}"
            )
        self.points.append(point)
        return dict(point)

    def val_curve(self) -> list[float]:
        """Série de val-loss na ordem registrada (entrada de `analyze_curve`)."""
        return [p["val_loss"] for p in self.points]

    def train_curve(self) -> list[float]:
        """Série de train-loss na ordem registrada."""
        return [p["train_loss"] for p in self.points]


def _tail_slope(series: list[float], tail_points: int) -> float:
    """Inclinação da regressão linear (mínimos quadrados) sobre os últimos `tail_points`.

    x = índice dentro da cauda (0..n-1); a inclinação é por passo de época.
    """
    tail = series[-tail_points:]
    n = len(tail)
    mean_x = (n - 1) / 2.0
    mean_y = sum(tail) / n
    num = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(tail))
    den = sum((i - mean_x) ** 2 for i in range(n))
    return num / den


def _classify_trend(slope: float, tolerance: float) -> str:
    if slope < -tolerance:
        return TREND_DECREASING
    if slope > tolerance:
        return TREND_INCREASING
    return TREND_PLATEAU


def analyze_curve(
    val_loss: list[float],
    train_loss: list[float] | None = None,
    *,
    tail_points: int = DEFAULT_TAIL_POINTS,
    slope_tolerance: float = DEFAULT_SLOPE_TOLERANCE,
    gap_threshold: float = DEFAULT_GAP_THRESHOLD,
) -> dict[str, Any]:
    """Analisa a curva de val-loss e devolve trend, gap e veredito go/no-go.

    - **trend**: regressão linear sobre a cauda (últimos `tail_points` pontos;
      usa a curva inteira se for menor). Regra de `docs/09`: o início ~1.0 é
      normal — a decisão vem da cauda.
    - **overfit_gap**: média de (val − train) na cauda (exige `train_loss` da
      mesma dimensão).
    - **verdict**:
      - `stop_overfitting`: val-loss subindo na cauda (slope > tolerance);
      - `add_data`: platô de val (|slope| <= tolerance) com gap acima de
        `gap_threshold` (memorização sem generalizar — docs/09: "adicionar
        dados");
      - `continue`: caso restante (queda saudável ou platô com gap sob controle).
    """
    if not isinstance(val_loss, list) or len(val_loss) < 2:
        raise CurveError("val_loss deve ser uma lista com >= 2 pontos")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) for v in val_loss):
        raise CurveError("val_loss deve conter apenas números finitos")
    if any(v < 0 for v in val_loss):
        raise CurveError("val_loss deve ser >= 0 em todos os pontos")
    if train_loss is not None:
        if not isinstance(train_loss, list) or len(train_loss) != len(val_loss):
            raise CurveError("train_loss deve ter a mesma dimensão de val_loss")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) for v in train_loss):
            raise CurveError("train_loss deve conter apenas números finitos")
    if tail_points < 2:
        raise CurveError("tail_points deve ser >= 2")
    if slope_tolerance < 0 or gap_threshold < 0:
        raise CurveError("slope_tolerance e gap_threshold devem ser >= 0")

    effective_tail = min(tail_points, len(val_loss))
    slope = _tail_slope(val_loss, effective_tail)
    trend = _classify_trend(slope, slope_tolerance)

    overfit_gap = None
    if train_loss is not None:
        tail_pairs = list(zip(train_loss[-effective_tail:], val_loss[-effective_tail:]))
        overfit_gap = sum(v - t for t, v in tail_pairs) / len(tail_pairs)

    if trend == TREND_INCREASING:
        verdict = VERDICT_STOP_OVERFITTING
    elif overfit_gap is not None and trend == TREND_PLATEAU and overfit_gap > gap_threshold:
        verdict = VERDICT_ADD_DATA
    else:
        verdict = VERDICT_CONTINUE

    return {
        "trend": trend,
        "tail_slope_per_step": round(slope, 6),
        "tail_points_used": effective_tail,
        "overfit_gap": round(overfit_gap, 6) if overfit_gap is not None else None,
        "gap_threshold": gap_threshold,
        "verdict": verdict,
        "first_val_loss": val_loss[0],
        "last_val_loss": val_loss[-1],
        "min_val_loss": min(val_loss),
    }


def record_training_run(
    tracker: ValLossTracker,
    *,
    analysis: dict[str, Any] | None = None,
    dataset_version: str,
    tool_version: str = "1.0.0",
    index_version: str = "1.0.0",
    bench_version: str = "1.0.0",
    needle_version: str | None = "2.0-45M",
    artifact_hash: str | None = None,
    siga_root: str | Path | None = None,
    work_root: str | Path | None = None,
    notes: str = "",
    runs_dir: str | Path | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Registra o run de treino com provenance completa (experiments.log).

    A curva e o veredito entram nas `metrics` (schema permite objeto livre);
    o arquivo `experiments/runs/<experiment_id>.json` é gravado e validado
    contra `experiments/schema.json`. `analysis` ausente é calculada aqui.
    """
    if not tracker.points:
        raise CurveError("tracker sem pontos: registre a curva antes de gravar o run")
    analysis = analysis or analyze_curve(tracker.val_curve(), tracker.train_curve())
    record = new_run(
        config={
            "kind": "val_loss_tracking",
            "model_name": tracker.model_name,
            "dataset_size": tracker.dataset_size,
            "depth": tracker.depth,
        },
        dataset_version=dataset_version,
        tool_version=tool_version,
        index_version=index_version,
        bench_version=bench_version,
        metrics={
            "model_name": tracker.model_name,
            "dataset_size": tracker.dataset_size,
            "depth": tracker.depth,
            "curve": tracker.points,
            "analysis": analysis,
            "final_val_loss": tracker.val_curve()[-1],
            "verdict": analysis["verdict"],
        },
        needle_version=needle_version,
        needle_depth=tracker.depth,
        artifact_hash=artifact_hash,
        notes=notes,
        now=now,
        siga_root=siga_root,
        work_root=work_root,
    )
    target_dir = Path(runs_dir) if runs_dir is not None else ROOT / "experiments/runs"
    target_dir.mkdir(parents=True, exist_ok=True)
    out = target_dir / f"{record['experiment_id']}.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    record["run_file"] = str(out)
    return record


def build_tracking_report(
    run_paths: list[str | Path],
    *,
    reports_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Agrega runs de treino em relatório comparável entre LoRAs.

    Lê cada run (JSON já gravado), extrai `{experiment_id, date, model,
    dataset_size, depth, verdict, final_val_loss, trend, overfit_gap}` e
    grava `experiments/reports/val_loss_tracking.json`. Sem runs, o
    relatório nasce vazio e válido (histórico começa no primeiro treino).
    """
    entries: list[dict[str, Any]] = []
    for path in run_paths:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        metrics = raw.get("metrics", {})
        config = raw.get("config", {})
        analysis = metrics.get("analysis", {})
        entries.append(
            {
                "experiment_id": raw.get("experiment_id"),
                "date": raw.get("date"),
                # F15 grava a identidade do modelo nas metrics; runs futuros
                # podem carregar `config` — ambos são aceitos aqui.
                "model_name": metrics.get("model_name") or config.get("model_name"),
                "dataset_size": metrics.get("dataset_size") or config.get("dataset_size"),
                "depth": metrics.get("depth") or config.get("depth"),
                "siga_commit": raw.get("siga_commit"),
                "sigateste_commit": raw.get("sigateste_commit"),
                "verdict": metrics.get("verdict"),
                "final_val_loss": metrics.get("final_val_loss"),
                "trend": analysis.get("trend"),
                "overfit_gap": analysis.get("overfit_gap"),
            }
        )
    entries.sort(key=lambda e: (e.get("date") or "", e.get("experiment_id") or ""))
    report = {
        "description": "Histórico de val-loss dos treinos de LoRA (F15, ADR-025; comparável entre runs).",
        "runs": entries,
        "total_runs": len(entries),
    }
    target_dir = Path(reports_dir) if reports_dir is not None else ROOT / "experiments/reports"
    target_dir.mkdir(parents=True, exist_ok=True)
    out = target_dir / "val_loss_tracking.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report
