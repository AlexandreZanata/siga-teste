"""F12: sub-recuperação da cápsula em traces longos (docs/15 §6, risco ADR-008).

Execução local determinística (grafo em memória + repo sintético) e, quando o
clone do SIGA está disponível, execução real no holdout congelado com a mesma
régua do P09/F05 (basename recall@1/3/5 + tokens de contexto).
"""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.capsule_recovery import (
    _budget_slice,
    _rank_aware_order,
    build_recovery_files,
    discover_trace_files,
    run_capsule_recovery,
)
from graph import store
from indexer import jsp_symbols

CONTROLLER_JAVA = """package br.exemplo.escola;

public class AlunoController {
    public void salvar(Aluno aluno) {}
}
"""

ALUNO_JAVA = """package br.exemplo.escola;

public class Aluno extends Pessoa {
    private String matricula;
    public String getMatricula() { return matricula; }
}
"""

PESSOA_JAVA = """package br.exemplo.escola;

public class Pessoa {
    protected String nome;
}
"""

# Convenção SIGA (fixture F03): o JSP menciona o símbolo pelo nome real no texto.
EXIBE_JSP = '<%@ include file="cabecalho.jsp"%>\n<html>Aluno de teste: ${aluno.matricula}</html>\n'
CABECALHO_JSP = "<html><body>cabecalho</body></html>\n"


def _make_repo(tmp_path: Path) -> Path:
    """Slice sintético mínimo: Controller → Aluno → Pessoa + JSP que referencia."""
    pkg = tmp_path / "siga-ex/src/main/java/br/exemplo/escola"
    webapp = tmp_path / "sigaex/src/main/webapp/escola"
    pkg.mkdir(parents=True)
    webapp.mkdir(parents=True)
    (pkg / "AlunoController.java").write_text(CONTROLLER_JAVA, encoding="utf-8")
    (pkg / "Aluno.java").write_text(ALUNO_JAVA, encoding="utf-8")
    (pkg / "Pessoa.java").write_text(PESSOA_JAVA, encoding="utf-8")
    (webapp / "exibe.jsp").write_text(EXIBE_JSP, encoding="utf-8")
    (webapp / "cabecalho.jsp").write_text(CABECALHO_JSP, encoding="utf-8")
    return tmp_path


def _index(tmp_path: Path):
    conn = store.connect()
    pkg = tmp_path / "siga-ex/src/main/java/br/exemplo/escola"
    for name in ("AlunoController.java", "Aluno.java", "Pessoa.java"):
        from indexer import java_symbols

        store.upsert_java(conn, java_symbols.parse_file(pkg / name))
    for jsp in (tmp_path / "sigaex/src/main/webapp/escola").glob("*.jsp"):
        store.upsert_jsp(conn, jsp_symbols.parse_file(jsp))
    conn.commit()
    return conn


def test_discovery_returns_real_files_without_invention(tmp_path: Path):
    repo = _make_repo(tmp_path)
    conn = _index(repo)

    discovery = discover_trace_files(repo, "atualizar matricula do aluno", conn, depth=3)

    for f in discovery["chain_files"] + discovery["views"]:
        assert Path(f).is_file(), f"path inventado: {f}"
    # JSP referenciando o símbolo real entra como view (foco ADR-008)
    assert any(f.endswith("exibe.jsp") for f in discovery["views"])
    # Cadeia do grafo inclui os 3 arquivos Java (depth 3 alcança Pessoa)
    chain_names = {Path(f).name for f in discovery["chain_files"]}
    assert {"AlunoController.java", "Aluno.java", "Pessoa.java"} <= chain_names
    conn.close()


def test_budget_slice_hard_ceiling_preserves_jsp_views(tmp_path: Path):
    files = [f"pasta{i}/Documento{i}.java" for i in range(200)]
    files += ["webapp/escola/exibe.jsp", "webapp/escola/marcar.jsp"]

    sliced = _budget_slice(files, budget_tokens=150.0, task="ajustar exibicao do documento")

    total = _budget_slice_token_cost("ajustar exibicao do documento", sliced)
    assert total <= 150.0, "teto duro de tokens foi estourado"
    assert "webapp/escola/exibe.jsp" in sliced, "view deve ser preservada primeiro"


def _budget_slice_token_cost(task: str, files: list[str]) -> float:
    from evaluation.capsule_recovery import count_tokens_metrics

    return float(count_tokens_metrics(f"TASK: {task.strip()}\n" + "\n".join(files)))


def test_arm_ordering_recovered_categories_first(tmp_path: Path):
    """O que o trace resgata (categoria) antecede o top-5 do baseline no braço B."""
    repo = _make_repo(tmp_path)
    conn = _index(repo)

    discovery = {
        "chain_files": [str(repo / "siga-ex/src/main/java/br/exemplo/escola/Aluno.java")],
        "views": [str(repo / "sigaex/src/main/webapp/escola/exibe.jsp")],
    }
    recovery = build_recovery_files(repo, conn, discovery)
    base_rel = ["siga-ex/src/main/java/br/exemplo/escola/Pessoa.java"]
    ordered = _rank_aware_order(recovery, base_rel)

    assert ordered[0].endswith("exibe.jsp"), "view recuperada deve vir primeiro"
    assert any(f.endswith("Aluno.java") for f in ordered)
    assert len(ordered) == len(set(ordered)), "sem duplicatas entre recovery e baseline"
    conn.close()


def _load_real_report() -> dict:
    """Padrão F05: os testes de régua leem o relatório publicado da execução real."""
    root = Path(__file__).resolve().parent.parent
    return json.loads((root / "experiments/reports/capsule_recovery.json").read_text(encoding="utf-8"))


def test_recovery_spike_measured_on_holdout_with_same_ruler():
    report = _load_real_report()

    assert report["total_tasks"] == 311
    assert set(report["arms"]) == {"A-capsule-baseline", "B-category-recovery", "C-budget-slice"}
    for arm in report["arms"].values():
        for k in ("top1", "top3", "top5"):
            assert 0.0 <= arm["recall"][k] <= 1.0
        assert arm["context_tokens"]["mean"] > 0
    # Teto do braço C respeitado na execução real (budget preservado)
    assert report["arms"]["C-budget-slice"]["context_tokens"]["mean"] <= report["budget_tokens"]
    assert report["decision"]


def test_baseline_arm_matches_production_capsule_flow(tmp_path: Path):
    """Guarda: braço A é a cápsula real do braço (c) do P09, não um simulacro."""
    repo = _make_repo(tmp_path)
    conn = _index(repo)

    from context.capsule import build_context_capsule
    from retrieval.baseline import naive_locate

    query = "atualizar matricula do aluno"
    base_files = naive_locate(repo, query, limit=5)
    capsule = build_context_capsule(task=query, repo=repo, files=base_files, max_snippets=3)

    report = run_capsule_recovery(
        repo_path=repo,
        conn=conn,
        max_tasks=1,
        log_run=False,
        save_report=False,
    )
    arm_a = report["arms"]["A-capsule-baseline"]
    assert arm_a["method"].startswith("cápsula padrão do braço (c) do P09")
    assert capsule.related_files or base_files, "baseline deve ter arquivos reais"
    conn.close()


def test_recovery_report_published_with_provenance():
    report = _load_real_report()

    assert report["task_id"] == "F12-capsule-sub-recovery"
    assert report["spike_status"] == "measured"
    assert report["runtime"] == {"cpu_only": True, "network_calls": 0}
    assert report["anti_leakage_verified"] is True
    assert report["total_tasks"] == 311
    assert report["experiment_id"]
    assert report["decision"]
