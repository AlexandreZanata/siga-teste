"""Testes do simulador e das 100 golden trajectories (P05-T03, docs/06 e docs/07).

Validações:
- Simulador executa as 5 tools semânticas reais e registra OBSERVATION->ACTION->ARGS->RESULT->FINAL
- Validação estrita de grounding em argumentos
- Tratamento limpo de casos off-topic (answers: [])
- 100 golden trajectories executam deterministicamente (100% de sucesso)
- Anti-leakage: nenhum SHA do benchmark contamina as trajetórias gold
"""

from __future__ import annotations

from pathlib import Path
import pytest

from evaluation.harness import bench_shas, load_manifest
from tools import simulator

ROOT = Path(__file__).resolve().parent.parent
SIGA = ROOT.parent
GOLD_FILE = ROOT / "tools/gold_trajectories.jsonl"
MANIFEST = ROOT / "datasets/benchmark/manifest.json"


def test_gold_trajectories_file_exists_and_valid_schema():
    assert GOLD_FILE.is_file(), "Arquivo tools/gold_trajectories.jsonl deve existir"
    golds = simulator.load_trajectories(GOLD_FILE)
    assert len(golds) == 100, f"Esperado 100 trajetórias gold, encontrado {len(golds)}"

    ids: set[str] = set()
    for g in golds:
        assert "id" in g
        assert "query" in g
        assert "reasoning" in g
        assert "task_type" in g
        assert "tools" in g
        assert "answers" in g
        assert "source" in g
        assert g["id"] not in ids, f"ID duplicado: {g['id']}"
        ids.add(g["id"])

        # Reasoning factual curto de 1 linha
        assert "\n" not in g["reasoning"]
        assert len(g["reasoning"]) > 0


def test_simulator_single_step_and_chain():
    if not (SIGA / "siga-ex").is_dir():
        pytest.skip("Clone do SIGA não disponível ao lado (CI sem siga-ex)")
    sim = simulator.Simulator()
    step_res = sim.execute_action(
        "siga_locate",
        {"query": "ExDocumentoController", "limit": 2},
    )
    assert isinstance(step_res, list)
    assert len(step_res) > 0


def test_simulator_validates_grounding():
    # Grounded: termo presente na query
    assert simulator.validate_grounding(
        {"query": "tramitacao", "kind": "symbol"},
        query="Consultar tramitacao de processo",
    )

    # Grounded: símbolo presente em resultado prévio
    assert simulator.validate_grounding(
        {"symbol": "ExDocumentoController", "depth": 2},
        query="Inspecionar controller",
        prior_results=[{"symbol": "ExDocumentoController", "file": "ExDocumentoController.java"}],
    )

    # Ungrounded / Alucinado: símbolo inventado sem evidência
    assert not simulator.validate_grounding(
        {"symbol": "ClasseInventadaTotalmenteFantasma"},
        query="Inspecionar controller",
        prior_results=[],
    )


def test_simulator_handles_off_topic():
    sim = simulator.Simulator()
    off_topic_traj = {
        "id": "test-off-01",
        "query": "Como fazer um bolo de chocolate?",
        "reasoning": "receita de bolo -> fora do escopo do repositório SIGA",
        "task_type": "off-topic",
        "tools": [],
        "answers": [],
        "steps": [],
        "final": "OFF_TOPIC",
    }
    res = sim.run_trajectory(off_topic_traj)
    assert res["success"] is True
    assert res["final"] == "OFF_TOPIC"
    assert len(res["steps"]) == 1
    assert res["steps"][0]["action"] == "none"


def test_anti_leakage_gold_vs_benchmark():
    manifest = load_manifest(MANIFEST)
    shas = bench_shas(manifest)
    golds_text = GOLD_FILE.read_text(encoding="utf-8")
    for sha in shas:
        assert sha not in golds_text, f"LEAKAGE detectado: SHA {sha} do bench apareceu no gold!"


def test_100_gold_trajectories_execute_deterministically():
    if not (SIGA / "siga-ex").is_dir():
        pytest.skip("Clone do SIGA não disponível ao lado para executar os 100 golds")

    golds = simulator.load_trajectories(GOLD_FILE)
    sim = simulator.Simulator(repo=SIGA)
    summary = sim.run_all(golds)

    assert summary["total"] == 100
    assert summary["failed"] == 0, f"Falhas na execução dos golds: {summary['failed_ids']}"
    assert summary["success"] == 100
    assert summary["success_rate"] == 1.0
    assert summary["total_steps"] >= 100
