"""Testes da multi-teacher factory e do verificador determinístico (P06-T01, docs/08).

Validações:
- Cobertura de todas as categorias na task_factory (locate, trace, impact, history, ambiguous, mutation)
- Prompts versionados carregam para os 3 teachers (DeepSeek, Gemini, Muse)
- Verificador determinístico cobre AST, symbol, grep, Git, diff, Maven, testes e anti-leakage
- Regra central: Resposta só entra em verified/ se o verificador determinístico passar;
  consenso LLM nunca é ground truth.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
import subprocess

from graph import store
from indexer import java_symbols
from task_factory import (
    generate_all_categories,
    generate_ambiguous_tasks,
    generate_history_tasks,
    generate_impact_tasks,
    generate_locate_tasks,
    generate_mutation_tasks,
    generate_trace_tasks,
)
from teachers import (
    generate_candidate_for_teacher,
    generate_multi_teacher_candidates,
    load_teacher_prompt,
)
from verifier import (
    check_anti_leakage,
    check_ast,
    check_diff,
    check_git,
    check_grep,
    check_maven,
    check_symbol,
    check_tests,
    promote_to_verified,
    verify_candidate,
)

SAMPLE_JAVA = """package br.gov.exemplo;

public class ServicoExemplo {
    public void executarOperacao() {}
}
"""

SAMPLE_TEST_JAVA = """package br.gov.exemplo;

public class ServicoExemploTest {
    public void testExecutarOperacao() {
        new ServicoExemplo().executarOperacao();
    }
}
"""

SAMPLE_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>br.gov.exemplo</groupId>
  <artifactId>exemplo-parent</artifactId>
  <version>1.0</version>
  <packaging>pom</packaging>
  <modules>
    <module>modulo-a</module>
  </modules>
</project>
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

    pkg_dir = repo / "modulo-a/src/main/java/br/gov/exemplo"
    pkg_dir.mkdir(parents=True)
    test_dir = repo / "modulo-a/src/test/java/br/gov/exemplo"
    test_dir.mkdir(parents=True)

    (pkg_dir / "ServicoExemplo.java").write_text(SAMPLE_JAVA, encoding="utf-8")
    (test_dir / "ServicoExemploTest.java").write_text(SAMPLE_TEST_JAVA, encoding="utf-8")
    (repo / "pom.xml").write_text(SAMPLE_POM, encoding="utf-8")

    _git("add", ".", cwd=repo)
    _git("commit", "-m", "feat: initial commit for verifier", cwd=repo)

    conn = store.connect()
    for jf in repo.rglob("*.java"):
        store.upsert_java(conn, java_symbols.parse_file(jf))
    conn.commit()
    return repo, conn


def test_task_factory_generates_all_categories():
    categories = generate_all_categories()
    expected = {"locate", "trace", "impact", "history", "ambiguous", "mutation"}
    assert set(categories.keys()) == expected

    # 1. locate
    locates = generate_locate_tasks()
    kinds = {t["kind"] for t in locates}
    assert {"file", "symbol", "controller", "entity", "jsp", "migration", "test"} <= kinds

    # 2. trace
    traces = generate_trace_tasks()
    assert len(traces) >= 5
    assert all("expected_stages" in t for t in traces)

    # 3. impact
    impacts = generate_impact_tasks()
    assert len(impacts) >= 5
    assert all("target" in t for t in impacts)

    # 4. history
    histories = generate_history_tasks()
    assert len(histories) >= 5

    # 5. ambiguous (ambiguous, off-topic, no-tool, insufficient)
    ambigs = generate_ambiguous_tasks()
    subcats = {t["subcategory"] for t in ambigs}
    assert {"ambiguous", "off-topic", "no-tool", "insufficient"} <= subcats

    # 6. mutation
    mutations = generate_mutation_tasks()
    mtypes = {t["mutation_type"] for t in mutations}
    assert {
        "inverted_condition",
        "removed_validation",
        "swapped_annotation",
        "swapped_import",
        "broken_sql_migration",
        "broken_jsp_endpoint",
    } <= mtypes


def test_teachers_versioned_prompts_and_candidates():
    # Carregamento de prompts versionados
    for t in ("deepseek", "gemini", "muse"):
        prompt = load_teacher_prompt(t)
        assert len(prompt) > 50
        assert "SIGA" in prompt or "siga_" in prompt

    # Geração de candidatos multi-teacher
    task = {
        "id": "task-test-01",
        "query": "Localizar controller de documento",
        "category": "locate",
        "target": "ExDocumentoController",
    }
    candidates = generate_multi_teacher_candidates(task)
    assert len(candidates) == 3
    teachers = {c["teacher"] for c in candidates}
    assert teachers == {"deepseek", "gemini", "muse"}

    for c in candidates:
        assert c["prompt_version"] == "v1.0"
        assert c["task_id"] == "task-test-01"
        assert len(c["tools"]) == 1
        assert len(c["answers"]) == 1
        assert len(c["steps"]) == 1

    # Off-topic: todos retornam answers vazias
    off_task = {
        "id": "task-off-01",
        "query": "Como cozinhar arroz?",
        "category": "ambiguous",
        "subcategory": "off-topic",
    }
    off_cand = generate_candidate_for_teacher("deepseek", off_task)
    assert off_cand["tools"] == []
    assert off_cand["answers"] == []
    assert off_cand["steps"] == []
    assert off_cand["final"] == "OFF_TOPIC"


def test_verifier_deterministic_checks(tmp_path: Path):
    repo, conn = _setup_fixture(tmp_path)
    commit_sha = _git("rev-parse", "HEAD", cwd=repo)
    java_file = "modulo-a/src/main/java/br/gov/exemplo/ServicoExemplo.java"
    test_file = "modulo-a/src/test/java/br/gov/exemplo/ServicoExemploTest.java"

    # AST check
    assert check_ast(repo, java_file, "ServicoExemplo")
    assert check_ast(repo, java_file, "executarOperacao")
    assert not check_ast(repo, java_file, "MetodoInventadoAlucinado")

    # Symbol check no grafo
    assert check_symbol(conn, "ServicoExemplo")
    assert not check_symbol(conn, "SimboloInexistenteNoGrafo")

    # Grep check
    assert check_grep(repo, "executarOperacao")
    assert not check_grep(repo, "TextoTotalmenteInexistenteXYZ123")

    # Git check
    assert check_git(repo, commit_sha)
    assert check_git(repo, commit_sha, file_rel="ServicoExemplo.java")
    assert not check_git(repo, "0" * 40)

    # Diff check
    assert check_diff(repo, commit_sha, "ServicoExemplo")
    assert not check_diff(repo, commit_sha, "LinhaDeCodigoInventada")

    # Maven check
    assert check_maven(repo, "modulo-a")
    assert not check_maven(repo, "modulo-inexistente")

    # Test check
    assert check_tests(repo, test_file, "ServicoExemplo")
    assert not check_tests(repo, test_file, "ClasseNaoMencionadaNoTeste")

    # Anti-leakage
    assert check_anti_leakage('{"query": "teste normal"}')
    assert not check_anti_leakage('{"repo_commit": "48610bd6504692ad3f2e99ef318beb84e2668fd6"}')


def test_promotion_to_verified_only_on_deterministic_pass(tmp_path: Path):
    repo, conn = _setup_fixture(tmp_path)
    datasets_dir = tmp_path / "datasets"

    # 1. Candidato válido com símbolo real
    valid_candidate = {
        "id": "cand-valid-01",
        "task_id": "task-01",
        "query": "Localizar ServicoExemplo",
        "task_type": "locate",
        "steps": [
            {
                "action": "siga_locate",
                "args": {"query": "ServicoExemplo", "target": "ServicoExemplo"},
            }
        ],
    }
    report_valid = verify_candidate(valid_candidate, repo=repo, conn=conn)
    assert report_valid["passed"] is True
    dest_valid = promote_to_verified(valid_candidate, report_valid, datasets_dir)
    assert "verified" in str(dest_valid)
    assert dest_valid.is_file()

    # 2. Candidato inválido com símbolo ALUCINADO (mesmo se professores concordassem)
    hallucinated_candidate = {
        "id": "cand-hallucinated-02",
        "task_id": "task-02",
        "query": "Localizar ServicoFantasma",
        "task_type": "locate",
        "steps": [
            {
                "action": "siga_locate",
                "args": {"query": "ServicoFantasma", "target": "ServicoFantasmaTotalmenteInexistente"},
            }
        ],
    }
    report_invalid = verify_candidate(hallucinated_candidate, repo=repo, conn=conn)
    assert report_invalid["passed"] is False
    assert len(report_invalid["errors"]) > 0

    dest_invalid = promote_to_verified(hallucinated_candidate, report_invalid, datasets_dir)
    assert "rejected" in str(dest_invalid)
    assert dest_invalid.is_file()

    # Confirma que o candidato alucinado NUNCA foi promovido para verified/
    verified_file = datasets_dir / "verified/gold_candidates.jsonl"
    verified_content = verified_file.read_text(encoding="utf-8")
    assert "cand-valid-01" in verified_content
    assert "cand-hallucinated-02" not in verified_content
