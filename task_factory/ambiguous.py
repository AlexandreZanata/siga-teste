"""Gerador de tarefas ambíguas, off-topic, no-tool e insuficientes (P06-T01, docs/08 §2).

Casos de teste negativos essenciais para treinar o Needle a recusar
ou pedir desambiguação em vez de chamar ferramentas indiscriminadamente.
"""

from __future__ import annotations

from typing import Any

AMBIGUOUS_TEMPLATES: list[dict[str, Any]] = [
    # Ambíguas (homônimos ou múltiplos alvos no SIGA)
    {
        "subcategory": "ambiguous",
        "query": "Alterar a lógica do modelo",
        "ambiguity": "ExModelo (entidade) vs ExModeloController vs ExModeloBL",
        "expected_action": "disambiguation_needed",
    },
    {
        "subcategory": "ambiguous",
        "query": "Consultar classificação",
        "ambiguity": "ExClassificacao (entidade) vs ExClassificacaoController",
        "expected_action": "disambiguation_needed",
    },
    # Off-topic (perguntas fora do escopo do SIGA -> answers: [])
    {
        "subcategory": "off-topic",
        "query": "Qual é a previsão do tempo para amanhã?",
        "expected_action": "refusal",
        "expected_tools": [],
    },
    {
        "subcategory": "off-topic",
        "query": "Como preparar um bolo de fubá fofinho?",
        "expected_action": "refusal",
        "expected_tools": [],
    },
    {
        "subcategory": "off-topic",
        "query": "Qual a distância em quilômetros da Terra ao Sol?",
        "expected_action": "refusal",
        "expected_tools": [],
    },
    # No-tool (não exige execução de ferramentas)
    {
        "subcategory": "no-tool",
        "query": "Olá, bom dia! Você está pronto para ajudar?",
        "expected_action": "direct_reply",
        "expected_tools": [],
    },
    {
        "subcategory": "no-tool",
        "query": "O que significa a sigla SIGA no contexto deste sistema?",
        "expected_action": "direct_reply",
        "expected_tools": [],
    },
    # Insuficiente (descrição vaga demais para agir)
    {
        "subcategory": "insufficient",
        "query": "Corrigir o erro no método",
        "expected_action": "ask_details",
        "expected_tools": [],
    },
    {
        "subcategory": "insufficient",
        "query": "Ajustar o botão na tela",
        "expected_action": "ask_details",
        "expected_tools": [],
    },
]


def generate_ambiguous_tasks(prefix: str = "task-ambig") -> list[dict[str, Any]]:
    """Gera lista canônica de tarefas ambíguas, off-topic, no-tool e insuficientes."""
    tasks = []
    for idx, tpl in enumerate(AMBIGUOUS_TEMPLATES, 1):
        tasks.append(
            {
                "id": f"{prefix}-{idx:03d}",
                "category": "ambiguous",
                "subcategory": tpl["subcategory"],
                "query": tpl["query"],
                "expected_action": tpl["expected_action"],
                "expected_tools": tpl.get("expected_tools", []),
                "difficulty": "easy",
            }
        )
    return tasks
