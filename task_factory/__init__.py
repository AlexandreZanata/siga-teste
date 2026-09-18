"""Módulo task_factory (P06-T01, docs/08 §2).

Fábrica de geração de tarefas canônicas por categoria:
- locate: arquivos, símbolos, controllers, entidades, jsp, migrações, testes
- trace: fluxos e cadeias arquiteturais de execução
- impact: análise de callers, callees, dependências e testes
- history: histórico Git, diffs e co-alterações (CHANGED_WITH)
- ambiguous: ambíguas, off-topic, no-tool, insuficientes
- mutation: mutações de código (condição, validação, import, annotation, SQL, JSP)
"""

from typing import Any

from task_factory.ambiguous import generate_ambiguous_tasks
from task_factory.history import generate_history_tasks
from task_factory.impact import generate_impact_tasks
from task_factory.locate import generate_locate_tasks
from task_factory.mutation import generate_mutation_tasks
from task_factory.trace import generate_trace_tasks


def generate_all_categories() -> dict[str, list[dict[str, Any]]]:
    """Gera o catálogo de tarefas categorizadas."""
    return {
        "locate": generate_locate_tasks(),
        "trace": generate_trace_tasks(),
        "impact": generate_impact_tasks(),
        "history": generate_history_tasks(),
        "ambiguous": generate_ambiguous_tasks(),
        "mutation": generate_mutation_tasks(),
    }


__all__ = [
    "generate_all_categories",
    "generate_locate_tasks",
    "generate_trace_tasks",
    "generate_impact_tasks",
    "generate_history_tasks",
    "generate_ambiguous_tasks",
    "generate_mutation_tasks",
]
