"""Teacher agentivo: runs verificados viram gold (H03, docs/19 §4).

Converte runs manuais da suite EVAL-MCP (braço B) em trajetórias gold
para pós-treino, com verificação determinística pelo scorer — o agente
é o teacher, o verifier é o ground truth (consenso LLM nunca é).

Formato por registro (MASTER_PLAN): id, repo_commit, task_type, query,
tools, trajectory (OBSERVATION→ACTION→TOOL ARGS→RESULT→FINAL), answers,
verification, teacher, source, source_holdout_id, difficulty, score.

Guarda anti-leakage: gold derivado do bench NUNCA avalia o mesmo bench;
cada registro carrega `source_holdout_id` para auditoria de splits.
Só stdlib, determinístico.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.mcp_suite_score import load_tasks, score_run
from experiments.log import new_run

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "eval/mcp_suite/runs"
GOLD_DIR = ROOT / "eval/mcp_suite/gold"


def _a_verdict(tasks: dict[str, dict[str, Any]], by_task_arm: dict, task_id: str) -> str:
    row = by_task_arm.get((task_id, "A"))
    if row is None:
        return "unknown"
    if row["verdict"] == "exact":
        return "easy"
    if row["verdict"] == "partial":
        return "medium"
    return "hard"


def build_record(
    task: dict[str, Any],
    run: dict[str, Any],
    score: dict[str, Any],
    difficulty: str,
    teacher: str,
    source: str,
) -> dict[str, Any]:
    method = task.get("method", "")
    trajectory = [
        {"step": "OBSERVATION", "content": task.get("query", "")},
        {"step": "ACTION", "content": f"call {method}"},
        {"step": "TOOL ARGS", "content": json.dumps(task.get("args", {}), ensure_ascii=False)},
        {
            "step": "RESULT",
            "content": json.dumps(
                {"files": run.get("arquivos", []), "symbols": run.get("simbolos", [])},
                ensure_ascii=False,
            ),
        },
        {
            "step": "FINAL",
            "content": json.dumps(
                {"files": run.get("arquivos", []), "symbols": run.get("simbolos", [])},
                ensure_ascii=False,
            ),
        },
    ]
    return {
        "id": f"{run.get('task_id')}:{teacher}",
        "repo_commit": task.get("execution_commit"),
        "task_type": task.get("kind"),
        "query": task.get("query"),
        "tools": [method],
        "trajectory": trajectory,
        "answers": {"files": run.get("arquivos", []), "symbols": run.get("simbolos", [])},
        "verification": {
            "verdict": score.get("verdict"),
            "recall_at_k": score.get("recall_at_k"),
            "precision": score.get("precision"),
        },
        "teacher": teacher,
        "source": source,
        "source_holdout_id": task.get("source_holdout_id"),
        "difficulty": difficulty,
        "score": score.get("recall_at_k"),
    }


def runs_to_gold(
    tasks: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
    teacher: str,
    source: str,
) -> dict[str, Any]:
    """Só exact/partial do braço B viram gold; fails vão p/ near-miss."""
    scored = {}
    for row in rows:
        tid = row.get("task_id", "")
        if tid not in tasks:
            raise ValueError(f"task_id fora do artefato congelado: {tid!r}")
        scored[(tid, row.get("braco"))] = score_run(tasks, row)
    gold: list[dict[str, Any]] = []
    near_miss: list[str] = []
    for row in rows:
        if row.get("braco") != "B":
            continue
        score = scored[(row.get("task_id"), "B")]
        if score.get("verdict") not in ("exact", "partial"):
            near_miss.append(row.get("task_id", ""))
            continue
        task = tasks[row["task_id"]]
        gold.append(
            build_record(task, row, score, _a_verdict(tasks, scored, row["task_id"]), teacher, source)
        )
    gold.sort(key=lambda g: g["id"])
    return {
        "gold": gold,
        "near_miss": sorted(near_miss),
        "stats": {
            "n_b_rows": sum(1 for r in rows if r.get("braco") == "B"),
            "n_gold": len(gold),
            "n_near_miss": len(near_miss),
            "difficulty": {d: sum(1 for g in gold if g["difficulty"] == d) for d in ("easy", "medium", "hard", "unknown")},
        },
    }


def save_gold(gold: list[dict[str, Any]], out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for rec in gold:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, help="arquivo de run único (JSONL)")
    parser.add_argument("--runs-dir", type=Path, help="diretório com runs (default: eval/mcp_suite/runs)")
    parser.add_argument("--teacher", default="agent-ide", help="rótulo do teacher (ex.: modelo-ide-data)")
    parser.add_argument("--out", type=Path, help="saída gold (default: eval/mcp_suite/gold/<stem>.gold.jsonl)")
    parser.add_argument("--no-save", action="store_true", help="não grava gold/summary (só stdout)")
    opts = parser.parse_args()
    tasks = load_tasks()
    if opts.runs:
        run_files = [opts.runs]
    else:
        run_dir = opts.runs_dir or RUNS_DIR
        run_files = sorted(run_dir.glob("*.jsonl"))
        if not run_files:
            raise SystemExit(f"nenhum run em {run_dir}")
    for path in run_files:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        result = runs_to_gold(tasks, rows, opts.teacher, path.name)
        stats = result["stats"]
        print(f"[{path.name}] gold={stats['n_gold']}/{stats['n_b_rows']} near-miss={stats['n_near_miss']} {stats['difficulty']}")
        if opts.no_save:
            continue
        out = opts.out or (GOLD_DIR / f"{path.stem}.gold.jsonl")
        save_gold(result["gold"], out)
        summary = {
            "suite": "EVAL-MCP/H03",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tasks_artifact": "eval/mcp_suite/tasks.jsonl",
            "run_file": path.name,
            "teacher": opts.teacher,
            "gold_file": str(out.relative_to(ROOT)),
            "stats": stats,
            "near_miss": result["near_miss"],
        }
        reports_dir = ROOT / "experiments/reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "h03_gold.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        record = new_run(
            config={"kind": "h03_gold", "run_file": path.name, "teacher": opts.teacher},
            dataset_version="v1.0",
            tool_version="1.0.0",
            index_version="tree-sitter-java-0.23",
            bench_version="v1.0",
            metrics={"n_gold": stats["n_gold"], "n_near_miss": stats["n_near_miss"]},
            notes="H03: teacher agentivo — runs verificados viram gold (docs/19).",
            siga_root=ROOT.parent,
            work_root=ROOT,
        )
        runs_dir = ROOT / "experiments/runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / f"{record['experiment_id']}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"gold: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
