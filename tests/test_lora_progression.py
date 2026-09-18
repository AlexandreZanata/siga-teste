"""Testes da progressão LoRA e curvas dataset size vs depth (P07-T02, ADR-017 em docs/09).

Validações:
- Presença dos 5 degraus de dataset (100 -> 500 -> 2k -> 5k -> 10k)
- Análise de erros escrita e fundamentada para cada degrau
- Matriz de profundidade (subnetworks 2..20) com escalonamento de latência
- Identificação e congelamento da melhor configuração com experiment_id
- Prova numérica do ganho de fine-tuning (exit gate da Fase 07)
- Conformidade do relatório JSON e ausência de contaminação de holdout
"""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.harness import bench_shas, check_no_leakage, load_manifest
from experiments.log import validate_record
from training.lora_progression import (
    DATASET_SIZES,
    DEPTHS,
    ERROR_ANALYSES,
    publish_lora_curves,
    run_dataset_progression,
    run_depth_progression,
    select_best_configuration,
)

ROOT = Path(__file__).resolve().parent.parent


def test_error_analysis_coverage_for_all_steps():
    assert DATASET_SIZES == [100, 500, 2000, 5000, 10000]
    for size in DATASET_SIZES:
        assert size in ERROR_ANALYSES, f"Análise de erros ausente para degrau N={size}"
        analysis = ERROR_ANALYSES[size]
        assert "failure_modes" in analysis and len(analysis["failure_modes"]) > 0
        assert "root_cause" in analysis and len(analysis["root_cause"]) > 20
        assert "scale_justification" in analysis and len(analysis["scale_justification"]) > 20
        assert "val_loss_trend" in analysis and len(analysis["val_loss_trend"]) > 10


def test_dataset_progression_accuracy_and_plateau():
    # Executa a progressão sobre o holdout
    results = run_dataset_progression()
    assert len(results) == 5

    # Acurácia deve ser estritamente crescente ou igual ao longo da escala
    accuracies = [r["tool_selection_accuracy"] for r in results]
    assert accuracies[0] >= 0.85  # N=100
    assert accuracies[1] >= 0.96  # N=500
    assert accuracies[2] >= 0.97  # N=2000
    assert accuracies[3] >= 0.98  # N=5000
    assert accuracies[4] >= 0.98  # N=10000

    # Diminishing returns: o ganho de 5k para 10k é menor que o ganho de 100 para 500
    gain_early = accuracies[1] - accuracies[0]
    gain_late = accuracies[4] - accuracies[3]
    assert gain_early > gain_late, "Deve haver retornos decrescentes (diminishing returns) no topo da escala"

    # Zero alucinações em todos os modelos tunados
    for r in results:
        assert r["hallucination_rate"] == 0.0
        assert r["no_tool_accuracy"] >= 0.97


def test_depth_progression_latency_and_capacity():
    depth_results = run_depth_progression(dataset_size=5000)
    assert len(depth_results) == len(DEPTHS)

    # Sub-redes profundas (>= 12) devem ter acurácia alta (>= 98%)
    deep_accs = [r["tool_selection_accuracy"] for r in depth_results if r["depth"] >= 12]
    assert all(acc >= 0.98 for acc in deep_accs)

    # Sub-rede mínima viável de 12 camadas atinge mais de 98% de acurácia
    d12 = next(r for r in depth_results if r["depth"] == 12)
    assert d12["tool_selection_accuracy"] >= 0.98

    # Latência deve ser ultrarrápida em todas as profundidades (< 5ms)
    for r in depth_results:
        assert r["latency_p50_ms"] < 5.0


def test_selection_and_freezing_of_best_configuration():
    prog_res = run_dataset_progression()
    depth_res = run_depth_progression(dataset_size=5000)

    best = select_best_configuration(prog_res, depth_res)

    assert best["dataset_size"] in (2000, 5000, 10000)
    assert best["depth"] in (12, 16, 20)
    assert best["tool_selection_accuracy"] >= 0.98
    assert best["no_tool_accuracy"] == 1.0
    assert best["hallucination_rate"] == 0.0
    assert "tradeoff_rationale" in best


def test_publish_lora_curves_and_gain_proof(tmp_path: Path):
    # Executa a geração e publicação sem logar duplicatas se log_run=False
    report = publish_lora_curves(log_run=False)

    assert report["benchmark"] == "SIGA-Bench Holdout"
    assert len(report["dataset_progression"]) == 5
    assert len(report["depth_progression"]) == 6
    assert len(report["grid_matrix"]) == 30  # 5 sizes x 6 depths

    # Gate de saída da Fase 07: ganho do fine-tune provado numericamente
    gain_eval = report["fine_tune_gain_evaluation"]
    assert gain_eval["fine_tune_gain_status"] == "PROVED"
    assert gain_eval["tool_accuracy_gain"] > 0.03  # Mais de +3% de ganho vs base
    assert gain_eval["no_tool_accuracy_gain"] > 0.0

    # Validação do arquivo publicado em experiments/reports/lora_progression_curves.json
    rep_file = ROOT / "experiments/reports/lora_progression_curves.json"
    assert rep_file.is_file()
    saved = json.loads(rep_file.read_text(encoding="utf-8"))
    assert saved["benchmark"] == "SIGA-Bench Holdout"

    # Validação de registros em experiments/runs contra o schema
    runs = list((ROOT / "experiments/runs").glob("*.json"))
    assert len(runs) > 0
    for rf in runs:
        rec = json.loads(rf.read_text(encoding="utf-8"))
        validate_record(rec)

    # Anti-leakage: nenhum SHA do benchmark nos relatórios
    manifest = load_manifest(ROOT / "datasets/benchmark/manifest.json")
    check_no_leakage(bench_shas(manifest), ROOT / "experiments/reports")
