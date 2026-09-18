"""Seletor semântico e avaliador das 5 tools (P05-T02, ADR-013/014 em docs/06).

Implementa:
- Registro dos contratos das 5 tools semânticas
- Seleção determinística por intenção/gatilhos regex (grounding-safe)
- Avaliação de tool selection accuracy e invalid call rate em amostras
"""

from __future__ import annotations

import re
from typing import Any

SIGA_TOOLS: dict[str, dict[str, Any]] = {
    "siga_locate": {
        "description": "Localiza arquivos, símbolos e componentes de uma funcionalidade no repositório.",
        "parameters": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Span da tarefa descrevendo a funcionalidade a localizar.",
                },
                "kind": {
                    "type": ["string", "null"],
                    "enum": [
                        "file",
                        "symbol",
                        "controller",
                        "entity",
                        "jsp",
                        "migration",
                        "test",
                        None,
                    ],
                    "description": "Tipo opcional de componente a filtrar.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 10,
                },
            },
            "additionalProperties": False,
        },
    },
    "siga_trace": {
        "description": "Traça o fluxo de execução endpoint→controller→negócio(BL)→entidade→persistência→view.",
        "parameters": {
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Símbolo real de passo anterior a ser rastreado.",
                },
                "depth": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 3,
                    "default": 2,
                    "description": "Profundidade do grafo (1 a 3 hops).",
                },
            },
            "additionalProperties": False,
        },
    },
    "siga_impact": {
        "description": "Calcula os efeitos e impacto estático de modificar arquivo/classe/método.",
        "parameters": {
            "type": "object",
            "required": ["target"],
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Símbolo ou caminho real a inspecionar.",
                },
                "hops": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1,
                    "description": "Raio de propagação de impacto.",
                },
            },
            "additionalProperties": False,
        },
    },
    "siga_history": {
        "description": "Busca histórico Git, commits, diffs e co-alterações (CHANGED_WITH).",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": ["string", "null"],
                    "description": "Símbolo ou arquivo alvo.",
                },
                "query": {
                    "type": ["string", "null"],
                    "description": "Texto para buscar nas mensagens de commit.",
                },
                "since": {
                    "type": ["string", "null"],
                    "description": "Data limite inicial.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 10,
                },
            },
            "additionalProperties": False,
        },
    },
    "siga_context": {
        "description": "Produz a cápsula de contexto mínima para a IA grande a partir de símbolos validados.",
        "parameters": {
            "type": "object",
            "required": ["symbols", "task"],
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de símbolos âncora reais.",
                },
                "task": {
                    "type": "string",
                    "description": "Descrição verbatim da tarefa.",
                },
            },
            "additionalProperties": False,
        },
    },
}

# Gatilhos regex de intenção para classificação
_INTENT_TRIGGERS: list[tuple[str, re.Pattern[str]]] = [
    (
        "siga_context",
        re.compile(
            r"\b(c[áa]psula\w*|contexto\w*|empacot\w*|prompt|resumo\s+final|context\s+capsule)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "siga_history",
        re.compile(
            r"\b(hist[óo]rico\w*|commits?|diffs?|co-?altera\w*|changed_with|antig[oa]s?|passad[oa]s?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "siga_impact",
        re.compile(
            r"\b(impacto\w*|efeitos?|quem\s+chama|callers?|callees?|afetad\w*|modifica\w*|quebra\w*|depend[êe]ncia\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "siga_trace",
        re.compile(
            r"\b(fluxo\w*|tra[çc]a\w*|cadeia\w*|endpoint\w*|execu[çc][ãa]o|caminho\w*|trace|flow)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "siga_locate",
        re.compile(
            r"\b(localiz\w*|onde\s+fica|encontr\w*|busca\w*|qual\s+arquivo|candidat\w*|pesquis\w*)\b",
            re.IGNORECASE,
        ),
    ),
]


def select_tool(intent: str) -> tuple[str, dict[str, Any]]:
    """Classifica a intenção do usuário para uma das 5 tools semânticas com argumentos iniciais."""
    clean = intent.strip()
    for tool_name, pattern in _INTENT_TRIGGERS:
        if pattern.search(clean):
            # Extrai argumentos básicos grounded no texto
            args: dict[str, Any] = {}
            if tool_name == "siga_locate":
                args = {"query": clean}
            elif tool_name in ("siga_trace", "siga_impact"):
                # Procura possíveis nomes CamelCase de símbolo no texto
                symbols = re.findall(r"\b[A-Z][a-zA-Z0-9_]+\b", clean)
                target = symbols[0] if symbols else clean
                if tool_name == "siga_trace":
                    args = {"symbol": target, "depth": 2}
                else:
                    args = {"target": target, "hops": 1}
            elif tool_name == "siga_history":
                symbols = re.findall(r"\b[A-Z][a-zA-Z0-9_]+\b", clean)
                if symbols:
                    args = {"target": symbols[0]}
                else:
                    args = {"query": clean}
            elif tool_name == "siga_context":
                symbols = re.findall(r"\b[A-Z][a-zA-Z0-9_]+\b", clean)
                args = {"symbols": symbols, "task": clean}
            return tool_name, args

    # Default seguro quando não há gatilho específico: siga_locate
    return "siga_locate", {"query": clean}


def evaluate_tool_selection(samples: list[dict[str, str]]) -> dict[str, float]:
    """Mede a acurácia de seleção das tools sobre uma amostra de casos rotulados.

    Cada amostra contém: {'intent': str, 'expected_tool': str}.
    """
    if not samples:
        return {"total": 0.0, "accuracy": 0.0}

    correct = 0
    for s in samples:
        selected_tool, _ = select_tool(s["intent"])
        if selected_tool == s["expected_tool"]:
            correct += 1

    return {
        "total": float(len(samples)),
        "correct": float(correct),
        "accuracy": round(correct / len(samples), 4),
    }


def evaluate_invalid_call_rate(calls: list[dict[str, Any]]) -> dict[str, float]:
    """Mede a taxa de chamadas inválidas contra os contratos das tools.

    Cada item contém: {'tool': str, 'args': dict}.
    """
    if not calls:
        return {"total": 0.0, "invalid_count": 0.0, "invalid_call_rate": 0.0}

    invalid_count = 0
    for call in calls:
        tool_name = call.get("tool")
        args = call.get("args")
        if tool_name not in SIGA_TOOLS or not isinstance(args, dict):
            invalid_count += 1
            continue

        schema = SIGA_TOOLS[tool_name]["parameters"]
        # Valida campos obrigatórios
        required = schema.get("required", [])
        if any(r not in args for r in required):
            invalid_count += 1
            continue

        # Valida tipos básicos
        props = schema.get("properties", {})
        has_type_error = False
        for k, v in args.items():
            if k not in props:
                has_type_error = True
                break
            prop_type = props[k].get("type")
            if prop_type == "string" and not isinstance(v, str):
                has_type_error = True
                break
            elif prop_type == "integer" and (
                not isinstance(v, int) or isinstance(v, bool)
            ):
                has_type_error = True
                break
            elif prop_type == "array" and not isinstance(v, list):
                has_type_error = True
                break
            elif isinstance(prop_type, list) and not any(
                (t == "string" and isinstance(v, str))
                or (t == "null" and v is None)
                for t in prop_type
            ):
                has_type_error = True
                break

        if has_type_error:
            invalid_count += 1

    return {
        "total": float(len(calls)),
        "invalid_count": float(invalid_count),
        "invalid_call_rate": round(invalid_count / len(calls), 4),
    }
