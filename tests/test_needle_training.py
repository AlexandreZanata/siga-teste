"""Testes para o exportador do Needle e benchmark Base vs Tuned (P07-T01, docs/09 §1).

Validações:
- Conformidade do formato exportado com as regras do Cactus Needle
- Exportação reproduzível com hashes SHA-256 idênticos
- Isolamento absoluto (zero contaminação de SHAs do benchmark nos dados exportados)
- Comparação Needle Base vs Tuned no holdout (321 tarefas)
- Ganho positivo de acurácia e sucesso de tarefa no modelo Tuned
- Geração de relatório formal em experiments/reports/baseline_vs_tuned.json
"""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.harness import bench_shas, check_no_leakage, load_manifest
from evaluation.needlerun import (
    NeedleBaseModel,
    NeedleTunedModel,
    compare_base_vs_tuned,
    run_needle_evaluation,
)
from training.export_needle import (
    canonical_to_needle_record,
    compute_file_sha256,
    export_canonical_to_needle,
)

ROOT = Path(__file__).resolve().parent.parent


def test_canonical_to_needle_record_format():
    # 1. Registro com ferramenta
    rec_tool = {
        "id": "gold-001",
        "task_type": "locate",
        "query": "Localizar o controller ExDocumentoController",
        "tools": ["siga_locate"],
        "answers": [{"name": "siga_locate", "arguments": {"query": "ExDocumentoController", "kind": "controller"}}],
        "reasoning": "ExDocumentoController -> query, kind=controller",
    }
    needle_tool = canonical_to_needle_record(rec_tool)
    assert needle_tool["query"] == rec_tool["query"]
    assert len(needle_tool["answers"]) == 1
    assert needle_tool["answers"][0]["name"] == "siga_locate"
    assert needle_tool["answers"][0]["arguments"]["kind"] == "controller"
    assert needle_tool["reasoning"] == rec_tool["reasoning"]
    assert "system" in needle_tool

    # 2. Registro off-topic (deve ter answers: [])
    rec_off = {
        "id": "gold-050",
        "task_type": "off-topic",
        "query": "Como preparar um café expresso?",
        "tools": [],
        "answers": [],
        "reasoning": "café -> fora do escopo do SIGA",
        "final": "OFF_TOPIC",
    }
    needle_off = canonical_to_needle_record(rec_off)
    assert needle_off["query"] == rec_off["query"]
    assert needle_off["answers"] == []
    assert len(needle_off["tools"]) == 5  # Catálogo das 5 ferramentas visíveis
    assert "system" in needle_off


def test_export_needle_reproducibility_and_anti_leakage(tmp_path: Path):
    export_dir = tmp_path / "needle_export"
    meta1 = export_canonical_to_needle(output_dir=export_dir)

    assert meta1["total_records"] == 500
    assert meta1["train_records"] == 350
    assert meta1["val_records"] == 150

    train_file = export_dir / "needle_train.jsonl"
    val_file = export_dir / "needle_val.jsonl"
    full_file = export_dir / "needle_full.jsonl"
    manifest_file = export_dir / "manifest.json"

    assert train_file.is_file()
    assert val_file.is_file()
    assert full_file.is_file()
    assert manifest_file.is_file()

    # Validação dos hashes SHA-256
    assert compute_file_sha256(train_file) == meta1["hashes"]["needle_train"]
    assert compute_file_sha256(val_file) == meta1["hashes"]["needle_val"]
    assert compute_file_sha256(full_file) == meta1["hashes"]["needle_full"]

    # Reprodutibilidade estrita: segundo export deve gerar hashes idênticos
    export_dir2 = tmp_path / "needle_export2"
    meta2 = export_canonical_to_needle(output_dir=export_dir2)
    assert meta1["hashes"] == meta2["hashes"], "Exportação deve ser determinística e reproduzível"

    # Anti-leakage: nenhum SHA do benchmark presente nos arquivos exportados
    manifest = load_manifest(ROOT / "datasets/benchmark/manifest.json")
    check_no_leakage(bench_shas(manifest), tmp_path)


def test_needlerun_base_vs_tuned_comparison():
    # Executa a comparação no holdout congelado (sem gerar run tracking duplicado no teste)
    res = compare_base_vs_tuned(log_run=False)

    assert res["benchmark"] == "SIGA-Bench Holdout"
    assert res["total_holdout_samples"] == 321
    assert res["code_tasks_count"] == 311
    assert res["off_topic_tasks_count"] == 10

    base = res["needle_base"]
    tuned = res["needle_tuned"]
    deltas = res["deltas"]

    # Tuned deve superar Base em acurácia de ferramentas e taxa de sucesso
    assert tuned["tool_selection_accuracy"] >= base["tool_selection_accuracy"]
    assert tuned["no_tool_accuracy"] == 1.0
    assert tuned["no_tool_accuracy"] >= base["no_tool_accuracy"]
    assert tuned["task_success_rate"] >= base["task_success_rate"]
    assert deltas["task_success_delta"] >= 0.0

    # Latência P50 deve ser ultrarrápida (< 5ms)
    assert tuned["latency_p50_ms"] < 5.0

    # Relatório gravado em experiments/reports/
    rep_file = ROOT / "experiments/reports/baseline_vs_tuned.json"
    assert rep_file.is_file()
    saved = json.loads(rep_file.read_text(encoding="utf-8"))
    assert saved["needle_tuned"]["task_success_rate"] == tuned["task_success_rate"]


def test_needlerun_models_direct_evaluation():
    sample_tasks = [
        {"id": "t1", "query": "Localizar ExDocumento", "task_type": "locate", "expected_tools": ["siga_locate"]},
        {"id": "t2", "query": "Receita de bolo de cenoura", "task_type": "off-topic", "expected_tools": []},
    ]

    base = NeedleBaseModel()
    tuned = NeedleTunedModel()

    m_base = run_needle_evaluation(base, sample_tasks)
    m_tuned = run_needle_evaluation(tuned, sample_tasks)

    assert m_tuned["no_tool_accuracy"] == 1.0
    assert m_tuned["task_success_rate"] == 1.0
    # O modelo base tenta chamar tool no bolo de cenoura, errando a decisão chamar-vs-[]
    assert m_base["no_tool_accuracy"] < m_tuned["no_tool_accuracy"]
