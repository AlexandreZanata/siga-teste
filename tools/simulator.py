"""Simulador determinístico de ferramentas e trajetórias (P05-T03, docs/06 e docs/07).

Executa as 5 tools semânticas reais e registra a cadeia canônica:
OBSERVATION -> ACTION -> ARGS -> RESULT -> FINAL

Garante:
- Execução determinística ponta a ponta
- Validação estrita de grounding (args extraídos da query ou passos anteriores)
- Suporte a trajetórias curtas e casos off-topic (answers: [])
- Provenance completa em formato JSONL
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from tools.siga_context import siga_context
from tools.siga_history import siga_history
from tools.siga_impact import siga_impact
from tools.siga_locate import siga_locate
from tools.siga_trace import siga_trace

GOLD_PATH = Path(__file__).resolve().parent / "gold_trajectories.jsonl"


def _resolve_repo(repo: str | Path | None) -> Path:
    if repo is not None:
        return Path(repo).resolve()
    parent = Path(__file__).resolve().parent.parent.parent
    if (parent / "siga-ex").is_dir():
        return parent
    return Path(__file__).resolve().parent.parent


def validate_grounding(
    args: dict[str, Any],
    query: str,
    prior_results: list[Any] | None = None,
) -> bool:
    """Verifica se os argumentos da tool estão embasados na query ou em resultados prévios."""
    context_text = query.lower()
    if prior_results:
        context_text += " " + json.dumps(prior_results, default=str).lower()

    for key, value in args.items():
        if key in ("depth", "hops", "limit", "since"):
            continue
        if isinstance(value, str):
            clean_val = value.strip().lower().replace(".java", "").replace(".jsp", "")
            # Permitido se o valor (ou radical) estiver na query ou em resultados anteriores
            # ou for um enum conhecido
            if clean_val in ("file", "symbol", "controller", "entity", "jsp", "migration", "test"):
                continue
            if clean_val not in context_text:
                # Se não estiver no texto literal, verifica se algum token coincide
                tokens = [t for t in clean_val.split("_") if len(t) >= 3]
                if not any(t in context_text for t in tokens):
                    return False
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip().lower() not in context_text:
                    return False
    return True


class Simulator:
    """Simulador de execução determinística de tools sobre repositório e grafo."""

    def __init__(
        self,
        repo: str | Path | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        self.repo = _resolve_repo(repo)
        self.conn = conn

    def execute_action(self, action: str, args: dict[str, Any]) -> Any:
        """Executa a ferramenta semântica indicada com os argumentos fornecidos."""
        clean_args = dict(args)

        if action == "siga_locate":
            return siga_locate(**clean_args, repo=self.repo, conn=self.conn)
        elif action == "siga_trace":
            return siga_trace(**clean_args, repo=self.repo, conn=self.conn)
        elif action == "siga_impact":
            return siga_impact(**clean_args, repo=self.repo, conn=self.conn)
        elif action == "siga_history":
            return siga_history(**clean_args, repo=self.repo, conn=self.conn)
        elif action == "siga_context":
            return siga_context(**clean_args, repo=self.repo, conn=self.conn)
        elif action in ("none", "final", "off_topic"):
            return None
        else:
            raise ValueError(f"Ação desconhecida: {action!r}")

    def run_trajectory(self, trajectory: dict[str, Any]) -> dict[str, Any]:
        """Executa uma trajetória completa e registra OBSERVATION->ACTION->ARGS->RESULT->FINAL."""
        traj_id = trajectory.get("id", "traj-unknown")
        query = trajectory.get("query", "")
        reasoning = trajectory.get("reasoning", "")
        task_type = trajectory.get("task_type", "general")
        raw_steps = trajectory.get("steps", [])

        # Casos off-topic (sem chamadas de tool)
        if task_type == "off-topic" or not raw_steps or trajectory.get("tools") == []:
            return {
                "id": traj_id,
                "query": query,
                "reasoning": reasoning,
                "task_type": task_type,
                "success": True,
                "grounded": True,
                "steps": [
                    {
                        "observation": query,
                        "action": "none",
                        "args": {},
                        "result": None,
                    }
                ],
                "final": trajectory.get("final", "OFF_TOPIC"),
            }

        executed_steps: list[dict[str, Any]] = []
        prior_results: list[Any] = []
        current_observation = query
        all_grounded = True

        for idx, step in enumerate(raw_steps):
            action = step.get("action", "")
            args = step.get("args", {})

            is_grounded = validate_grounding(args, query, prior_results)
            if not is_grounded:
                all_grounded = False

            try:
                result = self.execute_action(action, args)
            except Exception as e:
                return {
                    "id": traj_id,
                    "query": query,
                    "reasoning": reasoning,
                    "task_type": task_type,
                    "success": False,
                    "grounded": all_grounded,
                    "error": str(e),
                    "steps": executed_steps,
                    "final": "ERROR",
                }

            step_record = {
                "step": idx + 1,
                "observation": current_observation,
                "action": action,
                "args": args,
                "result": result,
            }
            executed_steps.append(step_record)
            prior_results.append(result)

            # Próxima observação é um resumo do resultado anterior
            if isinstance(result, list):
                current_observation = f"Found {len(result)} items: {result[:2]}"
            elif isinstance(result, dict):
                current_observation = f"Result keys: {list(result.keys())}"

        final_outcome = trajectory.get("final")
        if not final_outcome and executed_steps:
            last_res = executed_steps[-1]["result"]
            if isinstance(last_res, dict) and "capsule_text" in last_res:
                final_outcome = "CAPSULE_GENERATED"
            elif isinstance(last_res, list) and last_res:
                final_outcome = f"FOUND: {last_res[0].get('target') or last_res[0]}"
            else:
                final_outcome = "COMPLETED"

        return {
            "id": traj_id,
            "query": query,
            "reasoning": reasoning,
            "task_type": task_type,
            "success": True,
            "grounded": all_grounded,
            "steps": executed_steps,
            "final": final_outcome,
        }

    def run_all(self, trajectories: list[dict[str, Any]]) -> dict[str, Any]:
        """Executa lote de trajetórias e retorna métricas de conclusão e tempo."""
        start_time = time.perf_counter()
        successes = 0
        total_steps = 0
        failed_ids: list[str] = []

        for traj in trajectories:
            res = self.run_trajectory(traj)
            if res.get("success"):
                successes += 1
                total_steps += len(res.get("steps", []))
            else:
                failed_ids.append(traj.get("id", "unknown"))

        duration = time.perf_counter() - start_time
        total = len(trajectories)

        return {
            "total": total,
            "success": successes,
            "failed": total - successes,
            "failed_ids": failed_ids,
            "success_rate": round(successes / total, 4) if total else 0.0,
            "total_steps": total_steps,
            "duration_s": round(duration, 3),
        }


def load_trajectories(path: str | Path) -> list[dict[str, Any]]:
    """Carrega trajetórias a partir de um arquivo JSONL."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")

    trajectories: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            trajectories.append(json.loads(line))
    return trajectories


def save_trajectories(path: str | Path, trajectories: list[dict[str, Any]]) -> None:
    """Salva lista de trajetórias em formato JSONL ordenado."""
    p = Path(path)
    lines = [json.dumps(t, ensure_ascii=False) for t in trajectories]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
