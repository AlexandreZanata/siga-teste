"""Gerador de tarefas da categoria history e co-change (P06-T01, docs/08 §2).

Gera tarefas para inspeção de histórico Git, diffs reais e identificação
de componentes que costumam mudar juntos (parceiros CHANGED_WITH).
"""

from __future__ import annotations

from typing import Any

HISTORY_TEMPLATES: list[dict[str, Any]] = [
    {
        "target": "ExDocumento.java",
        "query": "Consultar o histórico recente de modificações e commits do arquivo ExDocumento.java",
        "focus": "file_commits",
    },
    {
        "target": "ExTramiteBL.java",
        "query": "Quais arquivos foram alterados conjuntamente (co-alteração) com ExTramiteBL.java?",
        "focus": "cochange_partners",
    },
    {
        "target": "ExDocumentoController.java",
        "query": "Inspecionar o último diff aplicado em ExDocumentoController.java",
        "focus": "recent_diff",
    },
    {
        "target": None,
        "query_term": "assinar",
        "query": "Buscar histórico de commits relacionados à funcionalidade de assinar documentos",
        "focus": "grep_commits",
    },
    {
        "target": "ExMobil.java",
        "query": "Verificar histórico e parceiros de co-alteração de ExMobil.java",
        "focus": "cochange_partners",
    },
    {
        "target": None,
        "query_term": "tramite",
        "query": "Buscar commits que mencionam trâmite no repositório",
        "focus": "grep_commits",
    },
]


def generate_history_tasks(prefix: str = "task-history") -> list[dict[str, Any]]:
    """Gera lista canônica de tarefas da categoria history."""
    tasks = []
    for idx, tpl in enumerate(HISTORY_TEMPLATES, 1):
        tasks.append(
            {
                "id": f"{prefix}-{idx:03d}",
                "category": "history",
                "target": tpl["target"],
                "query_term": tpl.get("query_term"),
                "query": tpl["query"],
                "focus": tpl["focus"],
                "difficulty": "easy",
            }
        )
    return tasks
