"""Testes do val-loss tracking (F15, ADR-025 em docs/09).

- `ValLossTracker`: pontos validados (step crescente, losses finitos),
  timestamps UTC injetáveis.
- `analyze_curve`: trend pela cauda (regressão de mínimos quadrados),
  overfit_gap e veredito determinístico (continue/stop_overfitting/add_data),
  com as regras de docs/09 §1 (início ~1.0 é normal; decisão pela cauda).
- `record_training_run`: run válido pelo `experiments/schema.json` com
  provenance completa (siga_commit, sigateste_commit) e curva nas metrics.
- `build_tracking_report`: histórico comparável, ordenado por data.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from experiments.log import validate_record
from training.val_loss import (
    CurveError,
    ROOT,
    ValLossTracker,
    analyze_curve,
    build_tracking_report,
    record_training_run,
)

SIGA = ROOT.parent


def _siga_clone_available() -> bool:
    """Clone do SIGA ao lado (CI não tem — provenance carrega null e o schema aceita)."""
    return (SIGA / "siga-ex").is_dir()


class FakeClock:
    """Relógio injetável: 1s por chamada, determinístico."""

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


def _tracker(points: list[tuple[int, float, float]]) -> ValLossTracker:
    tracker = ValLossTracker(model_name="needle-tuned-5000-d12", dataset_size=5000, depth=12, clock=FakeClock())
    for step, train, val in points:
        tracker.log(step, train, val)
    return tracker


def test_tracker_logs_validated_points_with_utc_timestamps():
    tracker = _tracker([(0, 0.92, 1.02), (1, 0.60, 0.71), (2, 0.45, 0.52)])
    assert len(tracker.points) == 3
    first = tracker.points[0]
    assert set(first) == {"step", "train_loss", "val_loss", "timestamp"}
    assert first["timestamp"].endswith("+00:00")
    assert tracker.val_curve() == [1.02, 0.71, 0.52]
    assert tracker.train_curve() == [0.92, 0.60, 0.45]


def test_tracker_rejects_non_increasing_steps_and_invalid_losses():
    tracker = ValLossTracker(model_name="m", dataset_size=100, depth=12)
    tracker.log(0, 0.9, 1.0)
    with pytest.raises(CurveError, match="estritamente crescente"):
        tracker.log(0, 0.8, 0.9)
    with pytest.raises(CurveError):
        tracker.log(-1, 0.8, 0.9)
    with pytest.raises(CurveError, match="finito"):
        tracker.log(1, float("nan"), 0.9)
    with pytest.raises(CurveError, match="finito"):
        tracker.log(1, 0.8, math.inf)
    with pytest.raises(CurveError, match=">= 0"):
        tracker.log(1, 0.8, -0.1)
    with pytest.raises(CurveError):
        tracker.log(True, 0.8, 0.9)


def test_analyze_curve_decreasing_continues():
    analysis = analyze_curve([1.02, 0.71, 0.55, 0.50, 0.47, 0.45], [0.92, 0.60, 0.48, 0.44, 0.42, 0.41])
    assert analysis["trend"] == "decreasing"
    assert analysis["verdict"] == "continue"
    assert analysis["tail_points_used"] == 5
    assert analysis["overfit_gap"] is not None and analysis["overfit_gap"] >= 0
    assert analysis["min_val_loss"] == 0.45


def test_analyze_curve_increasing_val_stops_overfitting():
    # Overfitting sustentado: val sobe por 4 épocas após o mínimo (padrão do
    # degrau 10k do P07, 0.27 -> 0.31, aqui estendido) — pego com a janela padrão.
    analysis = analyze_curve([0.45, 0.33, 0.29, 0.27, 0.28, 0.30, 0.32, 0.34])
    assert analysis["trend"] == "increasing"
    assert analysis["verdict"] == "stop_overfitting"
    assert analysis["tail_slope_per_step"] > 0
    # U-curto (só 2 épocas de subida): a janela padrão de 5 ainda enxerga a
    # queda anterior; o chamador aperta a janela para detectar a virada cedo.
    short_u = analyze_curve([0.45, 0.33, 0.29, 0.27, 0.29, 0.31], tail_points=3)
    assert short_u["trend"] == "increasing"
    assert short_u["verdict"] == "stop_overfitting"


def test_analyze_curve_plateau_with_high_gap_adds_data():
    flat_val = [0.30] * 6
    assert analyze_curve(flat_val, [0.05] * 6)["verdict"] == "add_data"
    assert analyze_curve(flat_val, [0.05] * 6)["overfit_gap"] == pytest.approx(0.25)
    # Platô com gap sob controle segue de pé (protocolo: só gap alto pede dados).
    assert analyze_curve(flat_val, [0.28] * 6)["verdict"] == "continue"
    # Sem train_loss não há gap: platô saudável é continue.
    assert analyze_curve(flat_val)["verdict"] == "continue"


def test_analyze_curve_early_high_start_is_normal():
    # Início ~1.0 é normal (docs/09): queda forte no fim decide continue.
    analysis = analyze_curve([1.02, 0.90, 0.80, 0.72, 0.66, 0.61])
    assert analysis["verdict"] == "continue"


def test_analyze_curve_validates_malformed_inputs():
    with pytest.raises(CurveError, match=">= 2"):
        analyze_curve([0.5])
    with pytest.raises(CurveError, match="finitos"):
        analyze_curve([0.5, float("nan")])
    with pytest.raises(CurveError, match=">= 0"):
        analyze_curve([0.5, -0.2])
    with pytest.raises(CurveError, match="mesma dimensão"):
        analyze_curve([0.5, 0.4], [0.6])
    with pytest.raises(CurveError, match="tail_points"):
        analyze_curve([0.5, 0.4], tail_points=1)
    with pytest.raises(CurveError, match="gap_threshold"):
        analyze_curve([0.5, 0.4], gap_threshold=-1)


def test_record_training_run_validates_against_schema(tmp_path: Path):
    tracker = _tracker([(0, 0.92, 1.02), (1, 0.60, 0.71), (2, 0.45, 0.52), (3, 0.41, 0.47), (4, 0.39, 0.44)])
    record = record_training_run(
        tracker,
        dataset_version="v1.0",
        needle_version="2.0-45M",
        artifact_hash="abc123",
        siga_root=SIGA,
        work_root=ROOT,
        runs_dir=tmp_path / "runs",
        now="2026-09-19T12:00:00+00:00",
        notes="F15: run sintético de teste",
    )
    validate_record(record)  # provenance completa + schema
    if _siga_clone_available():
        assert record["siga_commit"] and record["sigateste_commit"]
    else:
        assert record["siga_commit"] is None  # CI sem clone: null explícito no schema
        assert record["sigateste_commit"] is not None
    assert record["metrics"]["verdict"] == "continue"
    assert record["metrics"]["analysis"]["trend"] == "decreasing"
    assert len(record["metrics"]["curve"]) == 5
    run_file = Path(record["run_file"])
    assert run_file.is_file()
    on_disk = json.loads(run_file.read_text(encoding="utf-8"))
    assert on_disk["experiment_id"] == record["experiment_id"]
    assert "run_file" not in on_disk  # segredo de caminho não vaza para o run persistido


def test_record_training_run_requires_points(tmp_path: Path):
    empty = ValLossTracker(model_name="m", dataset_size=100, depth=12)
    with pytest.raises(CurveError, match="sem pontos"):
        record_training_run(empty, dataset_version="v1.0", runs_dir=tmp_path)


def test_build_tracking_report_aggregates_sorted_history(tmp_path: Path):
    run_a = record_training_run(
        _tracker([(0, 0.9, 1.0), (1, 0.5, 0.6), (2, 0.4, 0.5)]),
        dataset_version="v1.0",
        siga_root=SIGA,
        work_root=ROOT,
        runs_dir=tmp_path,
        now="2026-09-19T10:00:00+00:00",
    )
    run_b = record_training_run(
        # Val sobe sustentado após o mínimo: tail5 = [0.50, 0.45, 0.47, 0.50, 0.53]
        # tem inclinação positiva líquida → stop_overfitting.
        _tracker([(0, 0.85, 0.90), (1, 0.55, 0.50), (2, 0.50, 0.45), (3, 0.50, 0.47), (4, 0.51, 0.50), (5, 0.53, 0.53)]),
        dataset_version="v1.0",
        siga_root=SIGA,
        work_root=ROOT,
        runs_dir=tmp_path,
        now="2026-09-19T11:00:00+00:00",
    )
    report = build_tracking_report([run_b["run_file"], run_a["run_file"]], reports_dir=tmp_path / "reports")
    assert report["total_runs"] == 2
    ids = [entry["experiment_id"] for entry in report["runs"]]
    assert ids == [run_a["experiment_id"], run_b["experiment_id"]]
    verdicts = [entry["verdict"] for entry in report["runs"]]
    assert verdicts == ["continue", "stop_overfitting"]
    for entry in report["runs"]:
        assert entry["model_name"] == "needle-tuned-5000-d12"
        if _siga_clone_available():
            assert entry["siga_commit"] and entry["sigateste_commit"]
    persisted = json.loads((tmp_path / "reports" / "val_loss_tracking.json").read_text(encoding="utf-8"))
    assert persisted["total_runs"] == 2


def test_build_tracking_report_empty_history_is_valid(tmp_path: Path):
    report = build_tracking_report([], reports_dir=tmp_path / "reports")
    assert report == {
        "description": report["description"],
        "runs": [],
        "total_runs": 0,
    }
