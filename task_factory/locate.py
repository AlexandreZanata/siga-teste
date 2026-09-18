"""Gerador de tarefas da categoria locate (P06-T01, docs/08 §2).

Gera tarefas para localização de arquivos, símbolos, controllers,
entidades, JSPs, migrações e testes sobre o ecossistema SIGA.
"""

from __future__ import annotations

from typing import Any

LOCATE_TEMPLATES: list[dict[str, Any]] = [
    {
        "kind": "controller",
        "target": "ExDocumentoController",
        "query": "Localizar o controller responsável pelo ciclo de vida de documentos",
        "expected_file": "ExDocumentoController.java",
    },
    {
        "kind": "symbol",
        "target": "ExTramiteBL",
        "query": "Onde está implementada a regra de negócio para cálculo de trâmites pendentes?",
        "expected_file": "ExTramiteBL.java",
    },
    {
        "kind": "file",
        "target": "ExDocumento.java",
        "query": "Localizar o arquivo principal da entidade ExDocumento",
        "expected_file": "ExDocumento.java",
    },
    {
        "kind": "entity",
        "target": "ExMobil",
        "query": "Encontrar a entidade JPA que representa o móbil de um documento",
        "expected_file": "ExMobil.java",
    },
    {
        "kind": "jsp",
        "target": "exibe.jsp",
        "query": "Qual JSP é responsável por renderizar a exibição principal de um documento?",
        "expected_file": "exibe.jsp",
    },
    {
        "kind": "migration",
        "target": "siga.ex_documento",
        "query": "Buscar a migração SQL que cria ou altera a tabela siga.ex_documento",
        "expected_file": "SIGA_UTF8_V104__Documento_com_Principal.sql",
    },
    {
        "kind": "test",
        "target": "ExTramiteBLTest",
        "query": "Onde estão os testes automatizados da lógica de trâmite de documentos?",
        "expected_file": "ExTramiteBLTest.java",
    },
    {
        "kind": "controller",
        "target": "ExMovimentacaoController",
        "query": "Localizar controller de movimentação de expedientes",
        "expected_file": "ExMovimentacaoController.java",
    },
    {
        "kind": "entity",
        "target": "ExModelo",
        "query": "Localizar a entidade de modelo de documento",
        "expected_file": "ExModelo.java",
    },
    {
        "kind": "jsp",
        "target": "marcar.jsp",
        "query": "Localizar o JSP de marcação de documento",
        "expected_file": "marcar.jsp",
    },
]


def generate_locate_tasks(prefix: str = "task-locate") -> list[dict[str, Any]]:
    """Gera lista canônica de tarefas da categoria locate."""
    tasks = []
    for idx, tpl in enumerate(LOCATE_TEMPLATES, 1):
        tasks.append(
            {
                "id": f"{prefix}-{idx:03d}",
                "category": "locate",
                "kind": tpl["kind"],
                "target": tpl["target"],
                "query": tpl["query"],
                "expected_file": tpl["expected_file"],
                "difficulty": "easy",
            }
        )
    return tasks
