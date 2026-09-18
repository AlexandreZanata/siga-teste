"""F06: expansão 2k do dataset gold com error analysis (docs/15-roadmap.md §6; ADR-017 em docs/09).

O degrau 500 -> 2k da fábrica de dados reutiliza o pipeline verificado do P06
(3 teachers -> executor -> verificador determinístico -> shortest-correct) sobre
variações determinísticas e grounded das 500 tarefas base, publica o ponto na
curva com error analysis escrita (critério obrigatório do ADR-017) e provenance.
Não altera o gold_500 existente e não re-treina modelo (curvas de treino são P07).
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess

from task_factory.catalog import build_task_catalog
from task_factory.expansion import (
    BASELINE_SIZE,
    EXPANSION_TARGET,
    build_expansion_catalog,
    generate_expansion_variations,
    run_expansion_2k,
)

ROOT = Path(__file__).resolve().parent.parent

SAMPLE_JAVA = """package br.gov.exemplo;

public class ServicoExemploController {
    public void processar() {}
}
"""

MINI_TASKS = [
    {
        "id": "task-mini-0001",
        "category": "locate",
        "subcategory": "controller",
        "target": "ServicoExemploController",
        "query": "Localizar o controller ServicoExemploController responsável pelo fluxo web",
        "expected_tools": ["siga_locate"],
        "args": {"query": "ServicoExemploController", "kind": "controller"},
        "difficulty": "easy",
    },
    {
        "id": "task-mini-0002",
        "category": "hard_negative",
        "subcategory": "off-topic",
        "query": "Qual o melhor framework de frontend para 2027?",
        "expected_tools": [],
        "expected_action": "refusal",
        "reasoning": "Pergunta fora do domínio do repositório SIGA.",
        "final": "OFF_TOPIC",
        "difficulty": "easy",
    },
    {
        "id": "task-mini-0003",
        "category": "hard_negative",
        "subcategory": "ambiguous-incomplete",
        "query": "Corrija o bug do sistema",
        "expected_tools": [],
        "expected_action": "clarification_needed",
        "reasoning": "Informação insuficiente para acionar qualquer ferramenta.",
        "final": "CLARIFICATION_NEEDED",
        "difficulty": "easy",
    },
]


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
    _git("commit", "-m", "feat: initial commit for expansion test", cwd=repo)

    from graph import store
    from indexer import java_symbols

    conn = store.connect()
    for jf in repo.rglob("*.java"):
        store.upsert_java(conn, java_symbols.parse_file(jf))
    conn.commit()
    return repo, conn


def test_expansion_variations_deterministic_unique_and_non_mutating():
    base = build_task_catalog()
    assert len(base) == BASELINE_SIZE

    v1 = generate_expansion_variations(base, per_task=3, seed=17)
    v2 = generate_expansion_variations(base, per_task=3, seed=17)
    assert v1 == v2, "variações devem ser determinísticas"
    assert len(v1) == EXPANSION_TARGET - BASELINE_SIZE

    base_snapshot = json.dumps(base, ensure_ascii=False)
    _ = generate_expansion_variations(base, per_task=3, seed=99)
    assert json.dumps(base, ensure_ascii=False) == base_snapshot, "base não pode ser mutada"

    var_queries = [t["query"] for t in v1]
    assert len(var_queries) == len(set(var_queries)), "variações devem ter queries únicas entre si"
    assert not (set(var_queries) & {q for q in (t["query"] for t in base)}), "variações não podem colidir com a base"

    base_ids = {b["id"] for b in base}
    base_by_id = {b["id"]: b for b in base}
    for t in v1:
        assert t["id"] not in base_ids
        assert t["category"] in {"locate", "trace", "impact", "history", "hard_negative"}
        assert t["difficulty"] in {"easy", "medium", "hard"}
        root_id = t["id"].rsplit("-x", 1)[0]
        assert t["query"] != base_by_id[root_id]["query"], "cada variante altera a query da base"
        if t["category"] == "hard_negative" and t["subcategory"] in {"off-topic", "ambiguous-incomplete"}:
            assert t["expected_tools"] == []

    trace_vars = [t for t in v1 if t["category"] == "trace"]
    assert {t["args"]["depth"] for t in trace_vars} == {1, 2, 3}
    history_vars = [t for t in v1 if t["category"] == "history"]
    assert {t["args"]["limit"] for t in history_vars} >= {3, 4}
    for t in (t for t in v1 if t["category"] == "locate"):
        root_id = t["id"].rsplit("-x", 1)[0]
        assert t["args"] == base_by_id[root_id]["args"]

    catalog = build_expansion_catalog(base, per_task=3, seed=17)
    assert len(catalog) == EXPANSION_TARGET


def test_expansion_pipeline_verifies_and_publishes_with_error_analysis(tmp_path):
    repo, conn = _setup_fixture(tmp_path)
    tasks = build_expansion_catalog(MINI_TASKS, per_task=3, seed=7)
    assert len(tasks) == 12

    result = run_expansion_2k(
        tasks=tasks,
        repo_path=repo,
        conn=conn,
        output_root=tmp_path / "ds",
        log_run=False,
        save_report=False,
    )
    assert result["total_generated"] == 12
    assert result["total_verified"] == 12
    assert result["total_rejected"] == 0
    assert result["acceptance_rate"] == 1.0

    gold_file = tmp_path / "ds/verified/gold_2000.jsonl"
    assert gold_file.is_file()
    lines = gold_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 12
    rec = json.loads(lines[0])
    assert rec["id"] == "gold-2k-0001"
    assert rec["repo_commit"]
    assert rec["split"] in {"train", "valid"}
    assert rec["verification"]["passed"] is True
    assert rec["generator_version"]
    assert rec["license"] == "AGPLv3"

    report = result
    assert report["adr"] == "ADR-017"
    assert report["expansion_status"] == "measured"
    assert report["total_generated"] == 12

    ea = report["error_analysis"]
    assert isinstance(ea["failure_modes"], list) and ea["failure_modes"]
    assert ea["root_cause"]
    assert ea["scale_decision"]
    assert ea["category_failures"] == {}
    assert ea["residual_risk_modes"]

    m = report["metrics_2k"]
    assert m["total_records"] == 12
    assert m["no_tool_accuracy"] == 1.0
    assert m["hallucination_rate"] == 0.0
    assert m["anti_leakage_passed"] is True
    assert report["anti_leakage_verified"] is True


def test_expansion_rejects_unverifiable_task_with_category_failure(tmp_path):
    repo, conn = _setup_fixture(tmp_path)
    bad = [
        dict(
            MINI_TASKS[0],
            id="task-mini-bad",
            target="ClasseInexistenteController",
            args={"query": "ClasseInexistenteController", "kind": "controller"},
        )
    ]
    tasks = build_expansion_catalog(bad, per_task=2, seed=1)
    assert len(tasks) == 3

    result = run_expansion_2k(
        tasks=tasks,
        repo_path=repo,
        conn=conn,
        output_root=tmp_path / "ds",
        log_run=False,
        save_report=False,
    )
    assert result["total_generated"] == 3
    assert result["total_verified"] == 0
    assert result["total_rejected"] == 3

    rejected_file = tmp_path / "ds/rejected/rejected_expansion_2k.jsonl"
    assert len(rejected_file.read_text(encoding="utf-8").splitlines()) == 3

    assert result["error_analysis"]["category_failures"] == {"locate": 3}
