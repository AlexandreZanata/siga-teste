"""Testes para hard negatives e seleção da trajetória mais curta e correta (P06-T02).

Validações:
- Cobertura de todas as 6 subcategorias de hard negatives
- Pipeline TASK -> 3 teachers -> execução real -> score -> trajetória curta correta
- Preferência pela trajetória mais curta entre alternativas corretas
- Rejeição de candidatos com alucinação ou falha de execução
- Contrato do dataset gold de 500 exemplos (provenance completa e splits temporais)
- Medição de no-tool accuracy (1.0) e hallucination rate (0.0)
- Curva dataset-size iniciada (100 -> 500)
- Zero leakage contra benchmark
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess

from evaluation.factory_metrics import compute_gold_metrics
from evaluation.harness import bench_shas, check_no_leakage, load_manifest
from graph import store
from indexer import java_symbols
from task_factory.hard_negatives import (
    generate_hard_negative_tasks,
    generate_off_topic_tasks,
)
from teachers.selection import select_shortest_correct
from tools.simulator import Simulator

ROOT = Path(__file__).resolve().parent.parent

SAMPLE_JAVA = """package br.gov.exemplo;

public class ServicoExemploController {
    public void processar() {}
}
"""


def _git(*args: str, cwd: Path) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@e", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return out.stdout.strip()


def _setup_fixture(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)

    pkg_dir = repo / "sigaex/src/main/java/br/gov/exemplo"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "ServicoExemploController.java").write_text(SAMPLE_JAVA, encoding="utf-8")

    _git("add", ".", cwd=repo)
    _git("commit", "-m", "feat: initial commit for selection test", cwd=repo)

    conn = store.connect()
    for jf in repo.rglob("*.java"):
        store.upsert_java(conn, java_symbols.parse_file(jf))
    conn.commit()
    return repo, conn


def test_hard_negatives_generation_all_categories():
    tasks = generate_hard_negative_tasks()
    subcats = {t["subcategory"] for t in tasks}
    expected = {
        "off-topic",
        "similar-tool",
        "similar-args",
        "homonym",
        "neighboring-module",
        "ambiguous-incomplete",
    }
    assert expected <= subcats

    # 1. Off-topic: tools vazias e refusal
    off_topics = [t for t in tasks if t["subcategory"] == "off-topic"]
    assert len(off_topics) >= 10
    assert all(t["expected_tools"] == [] for t in off_topics)
    assert all(t["expected_action"] == "refusal" for t in off_topics)
    assert all(t.get("final") == "OFF_TOPIC" for t in off_topics)

    # 2. Ambiguous-incomplete: tools vazias e clarification_needed
    incompletes = [t for t in tasks if t["subcategory"] == "ambiguous-incomplete"]
    assert len(incompletes) >= 5
    assert all(t["expected_tools"] == [] for t in incompletes)
    assert all(t["expected_action"] == "clarification_needed" for t in incompletes)

    # 3. Similar-tool: expectativa explícita de ferramenta
    sim_tools = [t for t in tasks if t["subcategory"] == "similar-tool"]
    assert len(sim_tools) >= 5
    assert all(len(t["expected_tools"]) > 0 for t in sim_tools)

    # Gerador parametrizável de off-topic
    off_generated = generate_off_topic_tasks(count=25)
    assert len(off_generated) == 25
    assert all(t["subcategory"] == "off-topic" for t in off_generated)


def test_shortest_correct_selection_prefers_concise(tmp_path: Path):
    repo, conn = _setup_fixture(tmp_path)
    sim = Simulator(repo=repo, conn=conn)

    task = {
        "id": "task-test-sel",
        "category": "locate",
        "target": "ServicoExemploController",
        "query": "Localizar ServicoExemploController",
        "expected_tools": ["siga_locate"],
        "args": {"query": "ServicoExemploController", "kind": "controller"},
    }

    # Candidato 1: Curto (1 passo correto)
    cand_short = {
        "id": "cand-short-deepseek",
        "task_id": "task-test-sel",
        "teacher": "deepseek",
        "prompt_version": "v1.0",
        "query": task["query"],
        "reasoning": "ServicoExemploController -> locate",
        "task_type": "locate",
        "tools": ["siga_locate"],
        "answers": [{"name": "siga_locate", "arguments": task["args"]}],
        "steps": [{"observation": task["query"], "action": "siga_locate", "args": task["args"]}],
        "final": "LOCATED",
    }

    # Candidato 2: Longo (2 passos com redundância válida)
    cand_long = {
        "id": "cand-long-gemini",
        "task_id": "task-test-sel",
        "teacher": "gemini",
        "prompt_version": "v1.0",
        "query": task["query"],
        "reasoning": "ServicoExemploController -> locate preliminar e locate refinado",
        "task_type": "locate",
        "tools": ["siga_locate", "siga_locate"],
        "answers": [{"name": "siga_locate", "arguments": task["args"]}],
        "steps": [
            {"observation": task["query"], "action": "siga_locate", "args": {"query": "ServicoExemploController"}},
            {"observation": "ok", "action": "siga_locate", "args": task["args"]},
        ],
        "final": "LOCATED",
    }

    # Candidato 3: Alucinado (alvo inexistente -> deve falhar na verificação)
    cand_hallucinated = {
        "id": "cand-hallucinated-muse",
        "task_id": "task-test-sel",
        "teacher": "muse",
        "prompt_version": "v1.0",
        "query": task["query"],
        "reasoning": "ServicoFantasmaTotalmenteInexistente -> locate",
        "task_type": "locate",
        "tools": ["siga_locate"],
        "answers": [{"name": "siga_locate", "arguments": {"query": "ServicoFantasmaTotalmenteInexistente"}}],
        "steps": [
            {
                "observation": task["query"],
                "action": "siga_locate",
                "args": {"query": "ServicoFantasmaTotalmenteInexistente", "target": "ServicoFantasmaTotalmenteInexistente"},
            }
        ],
        "final": "LOCATED",
    }

    winner, evals = select_shortest_correct(
        task=task,
        candidates=[cand_long, cand_short, cand_hallucinated],
        simulator=sim,
        repo=repo,
        conn=conn,
    )

    assert winner is not None
    # Deve selecionar o candidato mais curto!
    assert winner["candidate"]["id"] == "cand-short-deepseek"
    assert winner["step_count"] == 1
    assert winner["score"] > 1.4

    # Verifica que o candidato alucinado foi reprovado com score 0
    hallucinated_eval = next(e for e in evals if e["candidate"]["id"] == "cand-hallucinated-muse")
    assert hallucinated_eval["passed"] is False
    assert hallucinated_eval["score"] == 0.0


def test_shortest_correct_selection_off_topic(tmp_path: Path):
    repo, conn = _setup_fixture(tmp_path)
    sim = Simulator(repo=repo, conn=conn)

    off_task = {
        "id": "task-off-01",
        "category": "hard_negative",
        "subcategory": "off-topic",
        "query": "Como plantar violetas?",
        "expected_tools": [],
        "expected_action": "refusal",
    }

    winner, evals = select_shortest_correct(
        task=off_task,
        simulator=sim,
        repo=repo,
        conn=conn,
    )

    assert winner is not None
    assert winner["candidate"]["tools"] == []
    assert winner["candidate"]["answers"] == []
    assert winner["candidate"]["steps"] == []
    assert winner["candidate"]["final"] == "OFF_TOPIC"
    assert winner["passed"] is True


def test_gold_500_dataset_and_provenance():
    canonical_path = ROOT / "datasets/canonical/v1/canonical.jsonl"
    report_path = ROOT / "datasets/canonical/v1/report.json"
    gold_path = ROOT / "datasets/verified/gold_500.jsonl"

    assert canonical_path.is_file(), "Arquivo canonical.jsonl deve existir"
    assert report_path.is_file(), "Arquivo report.json deve existir"

    target_file = gold_path if gold_path.is_file() else canonical_path
    records = [json.loads(line) for line in target_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(records) >= 500, f"Deve conter pelo menos 500 registros gold, encontrado {len(records)}"

    required_fields = {
        "id",
        "repo_commit",
        "split",
        "temporal_window",
        "task_type",
        "query",
        "tools",
        "trajectory",
        "answers",
        "reasoning",
        "verification",
        "teacher",
        "source",
        "difficulty",
        "score",
        "prompt_version",
        "timestamp",
        "generator_version",
        "license",
    }

    train_count = 0
    valid_count = 0

    for rec in records:
        missing = required_fields - set(rec.keys())
        assert not missing, f"Registro {rec.get('id')} sem campos obrigatórios: {missing}"

        assert rec["split"] in ("train", "valid")
        if rec["split"] == "train":
            train_count += 1
        else:
            valid_count += 1

        assert rec["verification"]["passed"] is True
        assert len(rec["repo_commit"]) == 40
        assert rec["license"] == "AGPLv3"

    # Splits temporais devem ter distribuição balanceada
    assert train_count >= 300, f"Esperado >= 300 em train, encontrado {train_count}"
    assert valid_count >= 100, f"Esperado >= 100 em valid, encontrado {valid_count}"

    # Métricas de no-tool e hallucination
    metrics = compute_gold_metrics(records)
    assert metrics["no_tool_accuracy"] == 1.0, f"no_tool_accuracy deve ser 1.0, obtido {metrics['no_tool_accuracy']}"
    assert metrics["hallucination_rate"] == 0.0, f"hallucination_rate deve ser 0.0, obtido {metrics['hallucination_rate']}"

    # Anti-leakage: zero SHAs do benchmark
    manifest = load_manifest(ROOT / "datasets/benchmark/manifest.json")
    check_no_leakage(bench_shas(manifest), ROOT / "datasets")


def test_dataset_size_curve_file_exists():
    curve_file = ROOT / "experiments/reports/dataset_size_curve.json"
    assert curve_file.is_file(), "Relatório dataset_size_curve.json deve existir"

    data = json.loads(curve_file.read_text(encoding="utf-8"))
    assert data["curve"] == "dataset_size_progression"
    points = data["points"]
    assert len(points) == 2
    assert points[0]["n"] == 100
    assert points[1]["n"] == 500
    assert points[1]["metrics"]["total_records"] == 500
    assert points[1]["metrics"]["no_tool_accuracy"] == 1.0
    assert points[1]["metrics"]["hallucination_rate"] == 0.0
