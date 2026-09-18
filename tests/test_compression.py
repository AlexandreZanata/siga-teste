"""Testes para compressão por subnetworks e descoberta do menor modelo viável (P08-T01, docs/08).

Validações:
- Cobertura completa do fatiamento progressivo: 20 -> 18 -> ... -> 2
- Modelagem precisa de tamanho (MB) e RAM (MB) em 4-bit e 2-bit
- Avaliação empírica no holdout com latência P50/P95 e retenção de acurácia
- Identificação da sub-rede mínima viável que preserva o alvo de routing (>= 98%)
- Geração da tabela formal de compressão e congelamento do modelo alvo
- Verificação anti-leakage e validação de schema de tracking
"""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.harness import bench_shas, check_no_leakage, load_manifest
from experiments.log import validate_record
from training.compress import (
    STEP_DEPTHS,
    calculate_footprint,
    evaluate_subnetwork_progression,
    find_smallest_viable_subnetwork,
    publish_compression_report,
)

ROOT = Path(__file__).resolve().parent.parent


def test_step_depths_and_footprint_calculation():
    assert STEP_DEPTHS == [20, 18, 16, 14, 12, 10, 8, 6, 4, 2]

    # Modelos mais profundos devem ocupar mais espaço e consumir mais RAM
    fp20_4bit = calculate_footprint(20, "4-bit")
    fp12_4bit = calculate_footprint(12, "4-bit")
    fp2_4bit = calculate_footprint(2, "4-bit")

    assert fp20_4bit["model_size_mb"] == 28.0
    assert fp20_4bit["peak_ram_mb"] == 43.0
    assert fp12_4bit["model_size_mb"] == 19.2
    assert fp12_4bit["peak_ram_mb"] == 28.6
    assert fp2_4bit["model_size_mb"] == 8.2
    assert fp2_4bit["peak_ram_mb"] == 10.6

    # Monotonicidade estrita
    assert fp20_4bit["model_size_mb"] > fp12_4bit["model_size_mb"] > fp2_4bit["model_size_mb"]
    assert fp20_4bit["peak_ram_mb"] > fp12_4bit["peak_ram_mb"] > fp2_4bit["peak_ram_mb"]

    # 2-bit deve ser significativamente mais compacto que 4-bit
    fp20_2bit = calculate_footprint(20, "2-bit")
    assert fp20_2bit["model_size_mb"] < fp20_4bit["model_size_mb"]
    assert fp20_2bit["peak_ram_mb"] < fp20_4bit["peak_ram_mb"]


def test_subnetwork_progression_evaluation():
    # Avalia a progressão de 10 passos sobre o holdout
    results = evaluate_subnetwork_progression(dataset_size=5000)
    assert len(results) == 10

    # Todas as configurações devem manter zero alucinações e recusa perfeita (100% no-tool)
    for r in results:
        assert r["hallucination_rate"] == 0.0
        assert r["no_tool_accuracy"] == 1.0
        assert r["latency_p50_ms"] < 5.0

    # Profundidades altas (>= 12) mantêm acurácia excelente (>= 98%)
    for r in results:
        if r["depth"] >= 12:
            assert r["tool_selection_accuracy"] >= 0.98
            assert r["accuracy_retention_pct"] >= 99.0

    # Profundidades ultra-baixas têm degradação esperada mas controlada
    r2 = next(r for r in results if r["depth"] == 2)
    assert r2["tool_selection_accuracy"] < 0.95
    assert r2["ram_reduction_pct"] > 60.0  # Economia massiva de RAM (>60%)


def test_find_smallest_viable_subnetwork():
    results = evaluate_subnetwork_progression(dataset_size=5000)
    smallest = find_smallest_viable_subnetwork(results, target_accuracy=0.98)

    # Menor viável que atinge >= 98% deve ser 10 ou 12 camadas
    assert smallest["depth"] in (10, 12)
    assert smallest["tool_selection_accuracy"] >= 0.98
    assert smallest["no_tool_accuracy"] == 1.0
    assert smallest["hallucination_rate"] == 0.0
    assert smallest["accuracy_target_met"] is True
    assert smallest["peak_ram_mb"] < 30.0
    assert smallest["ram_reduction_pct"] > 30.0  # Mais de 30% de economia de RAM


def test_publish_compression_report_and_gate_assessment():
    # Executa a geração e publicação sem logar duplicatas durante o teste
    report = publish_compression_report(log_run=False, target_accuracy=0.98)

    assert report["benchmark"] == "SIGA-Bench Holdout"
    assert len(report["tested_depths"]) == 10
    assert len(report["table_4bit_subnetworks"]) == 10
    assert len(report["table_2bit_subnetworks"]) == 10

    gate = report["exit_gate_assessment"]
    assert gate["status"] == "PASSED"
    assert gate["smallest_viable_depth"] in (10, 12)
    assert gate["accuracy_preserved"] >= 0.98

    # Validação do arquivo salvo em experiments/reports/subnetwork_compression.json
    rep_file = ROOT / "experiments/reports/subnetwork_compression.json"
    assert rep_file.is_file()
    saved = json.loads(rep_file.read_text(encoding="utf-8"))
    assert saved["benchmark"] == "SIGA-Bench Holdout"

    # Validação de records em experiments/runs contra o schema
    runs = list((ROOT / "experiments/runs").glob("*.json"))
    assert len(runs) > 0
    for rf in runs:
        rec = json.loads(rf.read_text(encoding="utf-8"))
        validate_record(rec)

    # Anti-leakage: nenhum SHA do benchmark nos relatórios
    manifest = load_manifest(ROOT / "datasets/benchmark/manifest.json")
    check_no_leakage(bench_shas(manifest), ROOT / "experiments/reports")
