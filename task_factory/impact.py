"""Gerador de tarefas da categoria impact (P06-T01, docs/08 §2).

Gera tarefas para avaliar os impactos de modificar um componente:
callers, callees, testes unitários afetados e dependências.
"""

from __future__ import annotations

from typing import Any

IMPACT_TEMPLATES: list[dict[str, Any]] = [
    {
        "target": "ExDocumento",
        "hops": 1,
        "query": "Quais são os efeitos e componentes afetados se alterarmos a entidade ExDocumento?",
        "focus": "entity_callers",
    },
    {
        "target": "ExTramiteBL",
        "hops": 1,
        "query": "Quem chama ExTramiteBL e quais testes cobrem esse componente de trâmite?",
        "focus": "bl_callers_and_tests",
    },
    {
        "target": "ExDocumentoController",
        "hops": 1,
        "query": "Qual o impacto estático e métodos invocados por ExDocumentoController?",
        "focus": "controller_callees",
    },
    {
        "target": "ExMobil",
        "hops": 1,
        "query": "Quais classes dependem da estrutura de vias e numeração de ExMobil?",
        "focus": "model_dependencies",
    },
    {
        "target": "ExClassificacao",
        "hops": 1,
        "query": "Identificar todos os pontos do sistema que referenciam ExClassificacao",
        "focus": "classification_impact",
    },
    {
        "target": "ExMovimentacaoController",
        "hops": 1,
        "query": "Quais arquivos e formulários serão impactados ao modificar ExMovimentacaoController?",
        "focus": "movimentacao_impact",
    },
]


def generate_impact_tasks(prefix: str = "task-impact") -> list[dict[str, Any]]:
    """Gera lista canônica de tarefas da categoria impact."""
    tasks = []
    for idx, tpl in enumerate(IMPACT_TEMPLATES, 1):
        tasks.append(
            {
                "id": f"{prefix}-{idx:03d}",
                "category": "impact",
                "target": tpl["target"],
                "hops": tpl["hops"],
                "query": tpl["query"],
                "focus": tpl["focus"],
                "difficulty": "medium",
            }
        )
    return tasks
