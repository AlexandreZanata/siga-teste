"""Failure mining da ref1 EVAL-MCP + prioridades H01 (docs/19 §3/§4).

Lê o GT congelado (`tasks.jsonl`) e os runs manuais, classifica cada
`fail` do braço B em modos acionáveis e publica prioridades para os
degraus H02+. Análise offline, só stdlib, determinística.

Modos (primário = primeira regra que dispara, nesta ordem):
  `no_files_cited` — resposta sem nenhum FILE;
  `out_of_head` — ao menos 1 citado não existe no HEAD do bench;
  `history_commit_miss` — history sem cobertura do commit do GT;
  `wrong_module` — citados e GT sem nenhum módulo (shard) em comum;
  `partial_miss` — algum sinal, mas abaixo do limiar de success.

Sem clone do SIGA ao lado, o check de HEAD é pulado explicitamente
(`head_check_skipped=true`) — nunca sucesso falso.
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
from tools.module_shards import module_of

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "eval/mcp_suite/runs"

MODES = (
    "no_files_cited",
    "out_of_head",
    "history_commit_miss",
    "wrong_module",
    "partial_miss",
)


def _siga_root() -> Path | None:
    parent = ROOT.parent
    if (parent / "siga-ex").is_dir():
        return parent
    return None


def _gt_files(task: dict[str, Any]) -> list[str]:
    gt = task.get("ground_truth") or {}
    return list(gt.get("files") or [])


def _gt_commits(task: dict[str, Any]) -> list[str]:
    gt = task.get("ground_truth") or {}
    return list(gt.get("commits") or [])


def _modules(paths: list[str]) -> set[str]:
    mods: set[str] = set()
    for p in paths:
        try:
            mods.add(module_of(p))
        except ValueError:
            continue
    return mods


def classify(
    task: dict[str, Any],
    run: dict[str, Any],
    score: dict[str, Any],
    siga: Path | None,
) -> tuple[str, list[str]]:
    """(modo primário, todos os modos) para um fail; '' quando não é fail."""
    if score.get("verdict") != "fail":
        return "", []
    files = list(run.get("arquivos") or [])
    modes: list[str] = []
    if not files:
        modes.append("no_files_cited")
    if siga is not None:
        if any(not (siga / f).is_file() for f in files):
            modes.append("out_of_head")
    if (task.get("kind") == "history" or task.get("method") == "siga.history") and not score.get("commit_hit"):
        modes.append("history_commit_miss")
    gt_files = _gt_files(task)
    if files and gt_files and not (_modules(files) & _modules(gt_files)):
        modes.append("wrong_module")
    if not modes:
        modes.append("partial_miss")
    return modes[0], modes


def mine(tasks: dict[str, dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    siga = _siga_root()
    by_arm: dict[str, dict[str, Any]] = {}
    missed_files: dict[str, int] = {}
    gt_module_fails: dict[str, int] = {}
    for arm in ("A", "B"):
        arm_rows = [r for r in rows if r.get("braco") == arm]
        fails: list[dict[str, Any]] = []
        for run in arm_rows:
            task = tasks.get(run.get("task_id", ""))
            if task is None:
                raise ValueError(f"task_id fora do artefato congelado: {run.get('task_id')!r}")
            score = score_run(tasks, run)
            primary, modes = classify(task, run, score, siga)
            if not primary:
                continue
            for gf in _gt_files(task):
                missed_files[gf] = missed_files.get(gf, 0) + 1
                try:
                    mod = module_of(gf)
                except ValueError:
                    continue
                gt_module_fails[mod] = gt_module_fails.get(mod, 0) + 1
            fails.append(
                {
                    "task_id": run.get("task_id"),
                    "kind": task.get("kind"),
                    "primary_mode": primary,
                    "modes": modes,
                    "recall_at_k": score.get("recall_at_k"),
                    "n_answered_files": score.get("n_answered_files"),
                }
            )
        mode_counts: dict[str, int] = {m: 0 for m in MODES}
        for f in fails:
            mode_counts[f["primary_mode"]] += 1
        by_arm[arm] = {
            "n_tasks": len(arm_rows),
            "n_fail": len(fails),
            "mode_counts": mode_counts,
            "fails": sorted(fails, key=lambda f: f["task_id"]),
        }
    priorities = [
        "wrong_module → filtro por shard no locate (H01) + juiz por módulo (H02)",
        "out_of_head → validador existe-no-HEAD no envelope MCP (H02)",
        "history_commit_miss → siga_history sobre git log --follow com resolução p/ HEAD (H02)",
        "no_files_cited → fallback: ampliar termos antes de declarar vazio (H03)",
        "partial_miss → teacher agentivo sobre estes casos (H03)",
    ]
    return {
        "head_check_skipped": siga is None,
        "by_arm": by_arm,
        "gt_module_fails": dict(sorted(gt_module_fails.items(), key=lambda kv: (-kv[1], kv[0]))),
        "top_missed_files": sorted(missed_files.items(), key=lambda kv: (-kv[1], kv[0]))[:10],
        "priorities": priorities,
    }


def run_mining(run_files: list[Path], tasks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in run_files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    report = {
        "suite": "EVAL-MCP/H01",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tasks_artifact": "eval/mcp_suite/tasks.jsonl",
        "run_files": [str(p.relative_to(ROOT)) if p.is_absolute() else str(p) for p in run_files],
        "mining": mine(tasks, rows),
    }
    return report


def save_report(report: dict[str, Any]) -> Path:
    reports_dir = ROOT / "experiments/reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / "h01_failures.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    record = new_run(
        config={"kind": "h01_failures", "tasks_artifact": report["tasks_artifact"], "runs": report["run_files"]},
        dataset_version="v1.0",
        tool_version="1.0.0",
        index_version="tree-sitter-java-0.23",
        bench_version="v1.0",
        metrics={
            "b_fail": report["mining"]["by_arm"].get("B", {}).get("n_fail"),
            "b_modes": report["mining"]["by_arm"].get("B", {}).get("mode_counts"),
        },
        notes="H01: failure mining da ref1 EVAL-MCP (docs/19).",
        siga_root=ROOT.parent,
        work_root=ROOT,
    )
    runs_dir = ROOT / "experiments/runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_file = runs_dir / f"{record['experiment_id']}.json"
    run_file.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report["experiment_id"] = record["experiment_id"]
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, help="arquivo de run único (JSONL)")
    parser.add_argument("--runs-dir", type=Path, help="diretório com runs (default: eval/mcp_suite/runs)")
    parser.add_argument("--no-save", action="store_true", help="não grava report/run (só stdout)")
    opts = parser.parse_args()
    tasks = load_tasks()
    if opts.runs:
        run_files = [opts.runs]
    else:
        run_dir = opts.runs_dir or RUNS_DIR
        run_files = sorted(run_dir.glob("*.jsonl"))
        if not run_files:
            raise SystemExit(f"nenhum run em {run_dir}")
    report = run_mining(run_files, tasks)
    mining = report["mining"]
    for arm in ("A", "B"):
        info = mining["by_arm"].get(arm, {})
        print(f"[braço {arm}] fail={info.get('n_fail')}/{info.get('n_tasks')} modes={info.get('mode_counts')}")
    print(f"head_check_skipped={mining['head_check_skipped']}")
    if not opts.no_save:
        out = save_report(report)
        print(f"report: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
