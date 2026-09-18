"""Módulo de seleção da trajetória mais curta e correta (P06-T02, docs/08).

Implementa o pipeline:
TASK -> 3 teachers -> múltiplas trajetórias -> execução real -> score -> trajetória curta correta -> gold
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any

from teachers.generator import generate_multi_teacher_candidates
from tools.simulator import Simulator
from verifier.pipeline import verify_candidate

VERIFIER_VERSION = "1.0.0"
GENERATOR_VERSION = "1.0.0"
DEFAULT_LICENSE = "AGPLv3"


def score_candidate(
    candidate: dict[str, Any],
    execution_result: dict[str, Any],
    verification_report: dict[str, Any],
) -> float:
    """Calcula pontuação de qualidade e concisão para a trajetória candidata.

    Critérios:
    - Verificação determinística reprovada -> score 0.0
    - Falha de execução no simulador -> score 0.0
    - Falha de grounding -> score 0.0
    - Trajetória correta aprovada -> base 1.0 + bônus de concisão (menor número de passos)
    """
    if not verification_report.get("passed", False):
        return 0.0

    if not execution_result.get("success", False):
        return 0.0

    if not execution_result.get("grounded", False):
        return 0.0

    steps = candidate.get("steps", [])
    step_count = len(steps)
    reasoning_len = len(candidate.get("reasoning", ""))

    # Bônus inversamente proporcional ao número de passos e ao tamanho do reasoning
    conciseness_bonus = 1.0 / (1.0 + step_count) + 0.01 / (1.0 + reasoning_len)
    return round(1.0 + conciseness_bonus, 4)


def select_shortest_correct(
    task: dict[str, Any],
    candidates: list[dict[str, Any]] | None = None,
    simulator: Simulator | None = None,
    repo: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Seleciona a trajetória mais curta e correta entre os candidatos dos professores.

    Retorna (vencedor, lista_de_relatórios_de_avaliação).
    """
    if simulator is None:
        simulator = Simulator(repo=repo, conn=conn)
    if repo is None:
        repo = simulator.repo

    if candidates is None:
        candidates = generate_multi_teacher_candidates(task)

    evaluated_candidates = []

    for cand in candidates:
        # 1. Execução real no simulador
        exec_res = simulator.run_trajectory(cand)

        # 2. Verificação determinística multi-fonte
        ver_rep = verify_candidate(cand, repo=repo, conn=conn)

        # 3. Cálculo do score
        score = score_candidate(cand, exec_res, ver_rep)

        evaluated = {
            "candidate": cand,
            "execution": exec_res,
            "verification": ver_rep,
            "score": score,
            "passed": ver_rep.get("passed", False) and exec_res.get("success", False),
            "step_count": len(cand.get("steps", [])),
            "reasoning_len": len(cand.get("reasoning", "")),
        }
        evaluated_candidates.append(evaluated)

    # Filtra apenas aprovados determinísticos
    valid = [e for e in evaluated_candidates if e["passed"]]
    if not valid:
        return None, evaluated_candidates

    # Ordena para seleção:
    # 1. Maior score (que já prioriza concisão de passos)
    # 2. Menor número de passos (step_count)
    # 3. Menor tamanho de reasoning
    # 4. Desempate determinístico por id do candidato
    valid.sort(
        key=lambda e: (
            -e["score"],
            e["step_count"],
            e["reasoning_len"],
            e["candidate"]["id"],
        )
    )

    winner = valid[0]
    return winner, evaluated_candidates


def build_canonical_gold_record(
    task: dict[str, Any],
    winning_eval: dict[str, Any],
    gold_id: str,
    repo_commit: str,
    split: str,
) -> dict[str, Any]:
    """Constrói o registro gold canônico conforme schema e regras do docs/07 §2."""
    cand = winning_eval["candidate"]
    exec_res = winning_eval["execution"]
    ver_rep = winning_eval["verification"]

    now = datetime.now(timezone.utc).isoformat()

    # Formata a trajetória executada
    raw_steps = exec_res.get("steps", [])
    trajectory: list[dict[str, Any]] = []
    for s in raw_steps:
        trajectory.append(
            {
                "observation": s.get("observation", ""),
                "action": s.get("action", ""),
                "args": s.get("args", {}),
                "result": s.get("result"),
            }
        )

    return {
        "id": gold_id,
        "repo_commit": repo_commit,
        "split": split,
        "temporal_window": split,
        "task_type": task.get("category", "general"),
        "subcategory": task.get("subcategory", ""),
        "query": task.get("query", ""),
        "tools": cand.get("tools", []),
        "trajectory": trajectory,
        "answers": cand.get("answers", []),
        "reasoning": cand.get("reasoning", ""),
        "verification": {
            "verifier_version": ver_rep.get("verifier_version", VERIFIER_VERSION),
            "passed": ver_rep.get("passed", True),
            "timestamp": ver_rep.get("timestamp", now),
            "checks": ver_rep.get("checks", []),
        },
        "teacher": cand.get("teacher", "ensemble"),
        "source": "teacher-verified",
        "difficulty": task.get("difficulty", "medium"),
        "score": winning_eval.get("score", 1.0),
        "prompt_version": cand.get("prompt_version", "v1.0"),
        "timestamp": now,
        "generator_version": GENERATOR_VERSION,
        "license": DEFAULT_LICENSE,
    }


def process_task_to_gold(
    task: dict[str, Any],
    gold_id: str,
    repo_commit: str,
    split: str,
    simulator: Simulator | None = None,
    repo: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Executa o pipeline completo para uma única tarefa."""
    winner, _ = select_shortest_correct(
        task=task,
        simulator=simulator,
        repo=repo,
        conn=conn,
    )
    if winner is None:
        return None

    return build_canonical_gold_record(
        task=task,
        winning_eval=winner,
        gold_id=gold_id,
        repo_commit=repo_commit,
        split=split,
    )
