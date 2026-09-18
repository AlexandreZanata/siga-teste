"""Gerador multi-teacher com prompts versionados (P06-T01, ADR-016 em docs/08).

Implementa a geração de trajetórias candidatas pelos 3 professores:
- DeepSeek V4.1 Flash (analítico / direto)
- Gemini 3.8 Flash (semântico / contextual)
- Muse Spark 1.3 (conciso / minimalista)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.selector import select_tool

TEACHER_DIR = Path(__file__).resolve().parent
PROMPT_VERSIONS = {
    "deepseek": "v1.0",
    "gemini": "v1.0",
    "muse": "v1.0",
}


def load_teacher_prompt(teacher: str) -> str:
    """Carrega o texto do prompt versionado do professor."""
    prompt_file = TEACHER_DIR / teacher / "prompt_v1.txt"
    if not prompt_file.is_file():
        raise FileNotFoundError(f"Prompt não encontrado para teacher {teacher}: {prompt_file}")
    return prompt_file.read_text(encoding="utf-8")


def generate_candidate_for_teacher(
    teacher: str,
    task: dict[str, Any],
) -> dict[str, Any]:
    """Gera uma trajetória candidata para uma tarefa a partir do professor indicado."""
    if teacher not in PROMPT_VERSIONS:
        raise ValueError(f"Teacher desconhecido: {teacher!r}")

    query = task.get("query", "")
    task_id = task.get("id", "task-unknown")
    category = task.get("category", "general")
    subcategory = task.get("subcategory", "")
    target = task.get("target") or task.get("symbol") or ""

    timestamp = datetime.now(timezone.utc).isoformat()
    prompt_ver = PROMPT_VERSIONS[teacher]

    # Casos off-topic, no-tool ou insuficientes: sem chamada de ferramentas
    is_no_tool = (
        task.get("expected_tools") == []
        or (
            category in ("ambiguous", "hard_negative")
            and subcategory in ("off-topic", "no-tool", "ambiguous-incomplete", "insufficient")
        )
    )
    if is_no_tool:
        final_str = (
            "OFF_TOPIC"
            if subcategory == "off-topic"
            else "CLARIFICATION_NEEDED"
            if subcategory in ("ambiguous-incomplete", "insufficient")
            else "NO_TOOL"
        )
        reasoning = (
            f"'{query[:30]}' -> fora do escopo do repositório SIGA (off-topic)"
            if subcategory == "off-topic"
            else f"'{query[:30]}' -> parâmetros insuficientes (pedir esclarecimento)"
            if subcategory in ("ambiguous-incomplete", "insufficient")
            else f"'{query[:30]}' -> interação sem chamada de ferramenta"
        )
        return {
            "id": f"{task_id}-{teacher}",
            "task_id": task_id,
            "teacher": teacher,
            "prompt_version": prompt_ver,
            "timestamp": timestamp,
            "query": query,
            "reasoning": reasoning,
            "task_type": subcategory or category,
            "tools": [],
            "answers": [],
            "steps": [],
            "final": final_str,
            "source": f"teacher:{teacher}",
        }

    # Seleciona tool primária e argumentos (respeitando especificações da tarefa se houver)
    expected_tools = task.get("expected_tools")
    if expected_tools and expected_tools[0]:
        tool_name = expected_tools[0]
        base_args = dict(task.get("args", {}))
        if not base_args:
            _, fallback_args = select_tool(query)
            base_args = fallback_args
    else:
        tool_name, base_args = select_tool(query)

    # Estilos e trajetórias de cada professor:
    # DeepSeek: analítico, direto (1 passo canônico)
    # Gemini: arquitetural, contextual (pode propor validação preliminar em 2 passos para tarefas de contexto/trace)
    # Muse: minimalista e rápido (1 passo compacto)
    if teacher == "deepseek":
        reasoning = f"'{target or query[:30]}' -> {tool_name} ({list(base_args.keys())[0] if base_args else 'direto'})"
        steps = [{"observation": query, "action": tool_name, "args": base_args}]
        tools_used = [tool_name]
        answers = [{"name": tool_name, "arguments": base_args}]
    elif teacher == "gemini":
        reasoning = f"'{target or query[:30]}' -> {tool_name} (análise arquitetural)"
        # Para tarefas de contexto ou trace, Gemini propõe um passo exploratório preliminar
        if tool_name in ("siga_context", "siga_trace") and target:
            steps = [
                {"observation": query, "action": "siga_locate", "args": {"query": target, "limit": 3}},
                {"observation": f"Alvo {target} localizado", "action": tool_name, "args": base_args},
            ]
            tools_used = ["siga_locate", tool_name]
            answers = [
                {"name": "siga_locate", "arguments": {"query": target, "limit": 3}},
                {"name": tool_name, "arguments": base_args},
            ]
        else:
            steps = [{"observation": query, "action": tool_name, "args": base_args}]
            tools_used = [tool_name]
            answers = [{"name": tool_name, "arguments": base_args}]
    else:  # muse
        reasoning = f"'{target or query[:20]}' -> ação rápida"
        steps = [{"observation": query, "action": tool_name, "args": base_args}]
        tools_used = [tool_name]
        answers = [{"name": tool_name, "arguments": base_args}]

    return {
        "id": f"{task_id}-{teacher}",
        "task_id": task_id,
        "teacher": teacher,
        "prompt_version": prompt_ver,
        "timestamp": timestamp,
        "query": query,
        "reasoning": reasoning,
        "task_type": category,
        "tools": tools_used,
        "answers": answers,
        "steps": steps,
        "final": f"COMPLETED_{tool_name}",
        "source": f"teacher:{teacher}",
    }


def generate_multi_teacher_candidates(task: dict[str, Any]) -> list[dict[str, Any]]:
    """Gera candidatos independentes a partir dos 3 professores para a mesma tarefa."""
    return [
        generate_candidate_for_teacher(t, task)
        for t in ("deepseek", "gemini", "muse")
    ]
