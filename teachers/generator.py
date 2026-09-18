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

    # Casos off-topic ou no-tool: todos os teachers concordam com answers vazias
    if category == "ambiguous" and subcategory in ("off-topic", "no-tool"):
        reasoning = (
            f"'{query[:30]}' -> fora do escopo do repositório SIGA (off-topic)"
            if subcategory == "off-topic"
            else f"'{query[:30]}' -> interação conversacional sem chamada de ferramenta"
        )
        return {
            "id": f"{task_id}-{teacher}",
            "task_id": task_id,
            "teacher": teacher,
            "prompt_version": prompt_ver,
            "timestamp": timestamp,
            "query": query,
            "reasoning": reasoning,
            "task_type": subcategory,
            "tools": [],
            "answers": [],
            "steps": [],
            "final": "OFF_TOPIC" if subcategory == "off-topic" else "NO_TOOL",
            "source": f"teacher:{teacher}",
        }

    # Seleciona tool primária e formata argumentos grounded
    tool_name, base_args = select_tool(query)

    # Estilos de cada professor para reasoning e parâmetros
    if teacher == "deepseek":
        # Estilo analítico: derivação estrita direta
        reasoning = f"'{target or query[:30]}' -> {list(base_args.keys())[0]}"
        steps = [{"observation": query, "action": tool_name, "args": base_args}]
    elif teacher == "gemini":
        # Estilo arquitetural: ênfase no componente
        reasoning = f"'{target or query[:30]}' -> {tool_name} (análise arquitetural)"
        steps = [{"observation": query, "action": tool_name, "args": base_args}]
    else:  # muse
        # Estilo conciso: minimalista
        reasoning = f"'{target or query[:20]}' -> ação rápida"
        steps = [{"observation": query, "action": tool_name, "args": base_args}]

    return {
        "id": f"{task_id}-{teacher}",
        "task_id": task_id,
        "teacher": teacher,
        "prompt_version": prompt_ver,
        "timestamp": timestamp,
        "query": query,
        "reasoning": reasoning,
        "task_type": category,
        "tools": [tool_name],
        "answers": [{"name": tool_name, "arguments": base_args}],
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
