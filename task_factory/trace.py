"""Gerador de tarefas da categoria trace (P06-T01, docs/08 §2).

Gera tarefas para traçar fluxos arquiteturais de execução:
endpoint -> controller -> regra de negócio (BL) -> entidade -> tabela/migração -> view.
"""

from __future__ import annotations

from typing import Any

TRACE_TEMPLATES: list[dict[str, Any]] = [
    {
        "symbol": "ExDocumentoController",
        "depth": 2,
        "query": "Traçar o fluxo completo a partir de ExDocumentoController até as entidades e tabelas",
        "expected_stages": ["controller", "bl", "entity", "persistence"],
    },
    {
        "symbol": "ExTramiteBL",
        "depth": 2,
        "query": "Traçar as dependências e o fluxo de execução de ExTramiteBL",
        "expected_stages": ["bl", "entity"],
    },
    {
        "symbol": "ExMobilController",
        "depth": 2,
        "query": "Mapear a cadeia de execução do controlador de vias e móbil ExMobilController",
        "expected_stages": ["controller", "bl", "entity"],
    },
    {
        "symbol": "ExMovimentacaoController",
        "depth": 2,
        "query": "Rastrear fluxo de movimentação de documentos a partir de ExMovimentacaoController",
        "expected_stages": ["controller", "bl", "entity", "persistence"],
    },
    {
        "symbol": "ExModeloController",
        "depth": 2,
        "query": "Traçar fluxo de gerenciamento de templates e modelos em ExModeloController",
        "expected_stages": ["controller", "entity", "view"],
    },
    {
        "symbol": "ExClassificacaoController",
        "depth": 2,
        "query": "Traçar a cadeia do plano de classificação documental via ExClassificacaoController",
        "expected_stages": ["controller", "bl", "entity"],
    },
    {
        "symbol": "ExArquivoBL",
        "depth": 2,
        "query": "Traçar o fluxo de arquivamento e custódia de documentos via ExArquivoBL",
        "expected_stages": ["bl", "entity", "persistence"],
    },
    {
        "symbol": "ExEmailBL",
        "depth": 2,
        "query": "Traçar o fluxo de notificação e envio de correio eletrônico a partir de ExEmailBL",
        "expected_stages": ["bl", "entity"],
    },
]


def generate_trace_tasks(prefix: str = "task-trace") -> list[dict[str, Any]]:
    """Gera lista canônica de tarefas da categoria trace."""
    tasks = []
    for idx, tpl in enumerate(TRACE_TEMPLATES, 1):
        tasks.append(
            {
                "id": f"{prefix}-{idx:03d}",
                "category": "trace",
                "symbol": tpl["symbol"],
                "depth": tpl["depth"],
                "query": tpl["query"],
                "expected_stages": tpl["expected_stages"],
                "difficulty": "medium",
            }
        )
    return tasks
