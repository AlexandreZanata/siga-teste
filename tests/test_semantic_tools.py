"""Testes das 5 tools semânticas (P05-T02, ADR-013/014 em docs/06).

- Validação mínima do fluxo `locate→trace→context` sem inventar path/símbolo.
- Tool selection accuracy medida em amostra de intenções.
- Invalid call rate medido contra os contratos das tools.
- Testes de `siga_impact` e `siga_history`.
- Execução determinística em repo sintético e no clone real se disponível.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
import subprocess

import pytest

from graph import store
from indexer import java_symbols, sql_tables
from tools import (
    siga_context,
    siga_history,
    siga_impact,
    siga_locate,
    siga_trace,
)
from tools.selector import (
    evaluate_invalid_call_rate,
    evaluate_tool_selection,
)

ROOT = Path(__file__).resolve().parent.parent
SIGA = ROOT.parent

CONTROLLER_JAVA = """package br.gov.exemplo;

public class ServicoExemploController {
    private ServicoExemploBL bl;

    public void processar() {
        bl.executar("acao");
    }
}
"""

BL_JAVA = """package br.gov.exemplo;

public class ServicoExemploBL {
    private ServicoExemploEntity entity;

    public void executar(String acao) {
        validar(acao);
    }

    private void validar(String a) {}
}
"""

ENTITY_JAVA = """package br.gov.exemplo;

public class ServicoExemploEntity {
    private Long id;
}
"""

TEST_JAVA = """package br.gov.exemplo;

public class ServicoExemploBLTest {
    public void testExecutar() {
        new ServicoExemploBL().executar("teste");
    }
}
"""

MIGR_SQL = """CREATE TABLE exemplo.servico (
    id NUMBER PRIMARY KEY,
    nome VARCHAR2(100)
);
"""


def _git(*args: str, cwd: Path) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=tester", "-c", "user.email=tester@siga.test", *args],
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

    pkg_dir = repo / "src/main/java/br/gov/exemplo"
    pkg_dir.mkdir(parents=True)
    test_dir = repo / "src/test/java/br/gov/exemplo"
    test_dir.mkdir(parents=True)
    mig_dir = repo / "src/main/resources/db/migration"
    mig_dir.mkdir(parents=True)

    (pkg_dir / "ServicoExemploController.java").write_text(CONTROLLER_JAVA, encoding="utf-8")
    (pkg_dir / "ServicoExemploBL.java").write_text(BL_JAVA, encoding="utf-8")
    (pkg_dir / "ServicoExemploEntity.java").write_text(ENTITY_JAVA, encoding="utf-8")
    (test_dir / "ServicoExemploBLTest.java").write_text(TEST_JAVA, encoding="utf-8")
    (mig_dir / "V001__servico.sql").write_text(MIGR_SQL, encoding="utf-8")

    _git("add", ".", cwd=repo)
    _git("commit", "-m", "feat: initial commit", cwd=repo)

    conn = store.connect()
    for jf in repo.rglob("*.java"):
        store.upsert_java(conn, java_symbols.parse_file(jf))
    for sf in repo.rglob("*.sql"):
        store.upsert_migration(conn, sql_tables.parse_migration(sf))
    conn.commit()
    return repo, conn


def test_fluxo_locate_trace_context_sem_inventar_path_ou_simbolo(tmp_path: Path):
    repo, conn = _setup_fixture(tmp_path)

    # 1. Passo 1: siga_locate
    query = "ServicoExemplo"
    candidates = siga_locate(query=query, repo=repo, conn=conn, limit=5)
    assert candidates, "siga_locate deve retornar candidatos"

    # Nenhum path retornado pode ser inventado
    for cand in candidates:
        if cand.get("file"):
            assert Path(cand["file"]).is_file(), f"path inventado no locate: {cand['file']}"
        if cand.get("symbol"):
            # Símbolo existe no grafo
            sym_row = conn.execute(
                "SELECT id FROM nodes WHERE name = ?", (cand["symbol"],)
            ).fetchone()
            assert sym_row is not None, f"símbolo inventado no locate: {cand['symbol']}"

    top_candidate = candidates[0]
    top_symbol = top_candidate.get("symbol") or "ServicoExemploBL"

    # 2. Passo 2: siga_trace a partir do símbolo localizado
    trace_res = siga_trace(symbol=top_symbol, depth=2, repo=repo, conn=conn)
    assert trace_res["symbol"] == top_symbol
    assert trace_res["chain"], "trace deve encontrar nós na vizinhança"

    # Todos os arquivos encontrados no trace existem
    for f in trace_res["files"]:
        assert Path(f).is_file(), f"path inventado no trace: {f}"

    # Todos os nós do trace existem no grafo
    for node in trace_res["chain"]:
        node_row = conn.execute(
            "SELECT id FROM nodes WHERE id = ?", (node["id"],)
        ).fetchone()
        assert node_row is not None, f"nó inventado no trace: {node}"

    # 3. Passo 3: siga_context empacota os símbolos validados
    symbols_to_capsule = [top_symbol, "ServicoExemploController"]
    task_desc = "Implementar validação extra no ServicoExemplo"
    capsule = siga_context(
        symbols=symbols_to_capsule,
        task=task_desc,
        repo=repo,
        conn=conn,
    )
    assert capsule["task"] == task_desc
    assert set(capsule["symbols"]) == set(symbols_to_capsule)
    assert capsule["files"], "cápsula deve referenciar arquivos reais"
    for f in capsule["files"]:
        assert Path(f).is_file(), f"path inventado na cápsula: {f}"
    assert "ServicoExemploBL" in capsule["capsule_text"]
    assert capsule["token_estimate"] > 0


def test_siga_impact_callers_callees_tests(tmp_path: Path):
    repo, conn = _setup_fixture(tmp_path)
    target = "ServicoExemploBL"
    impact = siga_impact(target=target, repo=repo, conn=conn)

    assert impact["symbol"] == target
    assert any("ServicoExemploBLTest.java" in t for t in impact["related_tests"])
    assert any("ServicoExemploController.java" in c["file"] for c in impact["callers"])
    assert "validar" in impact["callees"]
    for f in impact["affected_files"]:
        assert Path(f).is_file(), f"arquivo afetado inexistente: {f}"


def test_siga_history_commits_diff_cochanges(tmp_path: Path):
    repo, conn = _setup_fixture(tmp_path)
    # Por target
    hist = siga_history(target="ServicoExemploBL.java", repo=repo, conn=conn)
    assert len(hist["commits"]) == 1
    assert hist["recent_diff"] is not None
    assert "ServicoExemploBL" in hist["recent_diff"]["diff"]

    # Por query
    hist_q = siga_history(query="initial", repo=repo, conn=conn)
    assert len(hist_q["commits"]) == 1


def test_tool_selection_accuracy_em_amostra():
    sample_dataset = [
        {"intent": "Onde fica o arquivo de tramitação de documentos?", "expected_tool": "siga_locate"},
        {"intent": "Encontrar a classe ExDocumentoController no repositório", "expected_tool": "siga_locate"},
        {"intent": "Pesquisar candidatos para a tela de marcação de documento", "expected_tool": "siga_locate"},
        {"intent": "Localizar controller de movimentação", "expected_tool": "siga_locate"},
        {"intent": "Traçar o fluxo de execução de ExDocumentoController", "expected_tool": "siga_trace"},
        {"intent": "Qual é a cadeia de execução do endpoint até o banco?", "expected_tool": "siga_trace"},
        {"intent": "Trace do fluxo de negócio de ExTramiteBL", "expected_tool": "siga_trace"},
        {"intent": "Caminho de chamada e dependências de ExMobilSelecao", "expected_tool": "siga_trace"},
        {"intent": "Quais os efeitos e quem chama ExTramiteBL?", "expected_tool": "siga_impact"},
        {"intent": "Qual o impacto de alterar a tabela siga.ex_documento?", "expected_tool": "siga_impact"},
        {"intent": "Quais arquivos serão afetados ao modificar ServicoExemplo?", "expected_tool": "siga_impact"},
        {"intent": "Análise de callers e dependências de ExDocumento", "expected_tool": "siga_impact"},
        {"intent": "Ver histórico de commits do arquivo ExDocumento.java", "expected_tool": "siga_history"},
        {"intent": "Quais foram as últimas alterações e diffs do commit?", "expected_tool": "siga_history"},
        {"intent": "Arquivos alterados juntos (co-alteração) com ExTramiteBL", "expected_tool": "siga_history"},
        {"intent": "Buscar diffs antigos de movimentação", "expected_tool": "siga_history"},
        {"intent": "Gerar cápsula de contexto para a IA grande", "expected_tool": "siga_context"},
        {"intent": "Empacotar o resumo final da tarefa com os símbolos selecionados", "expected_tool": "siga_context"},
        {"intent": "Construir context capsule para enviar no prompt do LLM", "expected_tool": "siga_context"},
        {"intent": "Contexto compacto da tarefa com ExDocumento", "expected_tool": "siga_context"},
    ]

    metrics = evaluate_tool_selection(sample_dataset)
    assert metrics["total"] == 20.0
    assert metrics["accuracy"] >= 0.95, f"Acurácia abaixo de 95%: {metrics}"


def test_invalid_call_rate_medido():
    calls = [
        {"tool": "siga_locate", "args": {"query": "documento"}},  # válido
        {"tool": "siga_trace", "args": {"symbol": "ExDocumento", "depth": 2}},  # válido
        {"tool": "siga_impact", "args": {"target": "ExDocumento"}},  # válido
        {"tool": "siga_history", "args": {"target": "ExDocumento.java"}},  # válido
        {"tool": "siga_context", "args": {"symbols": ["ExDocumento"], "task": "tarefa"}},  # válido
        {"tool": "siga_locate", "args": {}},  # inválido: falta query
        {"tool": "siga_trace", "args": {"symbol": 123}},  # inválido: symbol int
        {"tool": "siga_impact", "args": {"target": "Ex", "hops": "dois"}},  # inválido: hops str
        {"tool": "siga_context", "args": {"symbols": "não_é_lista", "task": "t"}},  # inválido
        {"tool": "tool_desconhecida", "args": {}},  # inválido: ferramenta inexistente
    ]

    metrics = evaluate_invalid_call_rate(calls)
    assert metrics["total"] == 10.0
    assert metrics["invalid_count"] == 5.0
    assert metrics["invalid_call_rate"] == 0.50


def test_real_slice_flow_if_available():
    if not (SIGA / "siga-ex").is_dir():
        pytest.skip("Clone do SIGA não disponível ao lado")

    # 1. Locate
    candidates = siga_locate("calcular tramites pendentes", repo=SIGA, limit=5)
    assert candidates, "deve localizar candidatos no SIGA"
    for c in candidates:
        if c.get("file"):
            assert Path(c["file"]).is_file(), f"arquivo inexistente: {c['file']}"

    # 2. Trace
    trace_res = siga_trace("ExTramiteBL", depth=1, repo=SIGA)
    assert trace_res["symbol"] == "ExTramiteBL"
    for f in trace_res["files"]:
        assert Path(f).is_file()

    # 3. Context
    capsule = siga_context(
        symbols=["ExTramiteBL"],
        task="Ajustar cálculo de trâmites pendentes",
        repo=SIGA,
    )
    assert "ExTramiteBL" in capsule["capsule_text"]
    for f in capsule["files"]:
        assert Path(f).is_file()
