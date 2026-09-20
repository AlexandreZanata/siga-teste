"""Auditoria de dessincronização GT×tools pós-F21 (F23, diag ref2-v2).

Após o F21 as tools mudaram (trace expande, history intersecta) mas o GT
foi congelado no G01 com o comportamento antigo. Este módulo mede, por
tarefa e sem responder nada (só reexecuta as tools nos INPUTS), se o
output atual CONTÉM o GT (GT stale-incompleto), diverge dele (miss real)
ou coincide — para decidir com evidência se o re-freeze procede.
Offline, determinístico, só stdlib.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.mcp_suite_score import commit_coverage, load_tasks
from experiments.log import new_run
from tools.siga_history import siga_history as history_fn
from tools.siga_impact import siga_impact as impact_fn
from tools.siga_locate import siga_locate as locate_fn

ROOT = Path(__file__).resolve().parent.parent
TOP_FILES = 5


def _siga() -> Path | None:
    parent = ROOT.parent
    return parent if (parent / "siga-ex").is_dir() else None


def _rel(siga: Path, path: str) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            return str(p.resolve().relative_to(siga.resolve()))
        except ValueError:
            return path
    return path


def current_output(task: dict[str, Any], siga: Path) -> dict[str, list[str]]:
    """Output atual das tools para os inputs do task (sem GT)."""
    kind = task.get("kind")
    args = task.get("args", {}) or {}
    files: list[str] = []
    commits: list[str] = []
    if kind == "locate":
        hits = locate_fn(args.get("query", ""), kind=args.get("kind"), repo=siga, limit=10)
        files = [_rel(siga, h["file"]) for h in hits[:TOP_FILES] if h.get("file")]
    elif kind == "impact":
        res = impact_fn(args.get("target", ""), hops=int(args.get("hops", 1)), repo=siga)
        files = [_rel(siga, f) for f in (res.get("affected_files") or [])[:TOP_FILES]]
    elif kind == "history":
        res = history_fn(
            target=args.get("target"), query=args.get("query"),
            limit=int(args.get("limit", 10)), repo=siga,
        )
        seen: list[str] = []
        for c in res.get("commits", []):
            for e in c.get("files_at_head", []):
                if e.get("exists") and e["path"] not in seen:
                    seen.append(e["path"])
        files = seen[:TOP_FILES]
        commits = [c["sha"] for c in res.get("commits", []) if c.get("sha")]
    elif kind == "trace":
        from tools.siga_trace import siga_trace as trace_fn

        res = trace_fn(args.get("symbol", ""), depth=int(args.get("depth", 2)), repo=siga)
        files = [_rel(siga, f) for f in (res.get("files") or [])[:TOP_FILES]]
    elif kind == "context":
        from tools.siga_context import siga_context as context_fn

        res = context_fn(args.get("symbols", []), args.get("task", ""), repo=siga, mode="referential")
        files = [r["path"] for r in (res.get("refs") or [])[:TOP_FILES]]
    return {"files": files, "commits": commits}


def classify(task: dict[str, Any], cur: dict[str, list[str]]) -> str:
    """EXACT | SUPERSET_STALE | PARTIAL | DISJOINT (history: por commits)."""
    gt = task.get("ground_truth", {}) or {}
    if task.get("kind") == "history":
        gt_commits = [c["sha"] if isinstance(c, dict) else c for c in gt.get("commits", [])]
        if not gt_commits:
            return "PARTIAL"
        cov = commit_coverage(gt_commits, cur["commits"])
        if cov >= 0.999:
            return "EXACT" if len(cur["commits"]) <= len(gt_commits) + 2 else "SUPERSET_STALE"
        return "PARTIAL" if cov > 0 else "DISJOINT"
    gt_files = set(gt.get("files", []))
    cur_files = set(cur["files"])
    if not gt_files:
        return "PARTIAL"
    if gt_files == cur_files or (gt_files <= cur_files and len(cur_files) == len(gt_files)):
        return "EXACT"
    if gt_files <= cur_files:
        return "SUPERSET_STALE"
    if gt_files & cur_files:
        return "PARTIAL"
    return "DISJOINT"


def audit(tasks: dict[str, dict[str, Any]], siga: Path) -> dict[str, Any]:
    rows = []
    for tid in sorted(tasks):
        task = tasks[tid]
        t0 = time.perf_counter()
        cur = current_output(task, siga)
        rows.append(
            {
                "task_id": tid,
                "kind": task.get("kind"),
                "status": classify(task, cur),
                "n_gt_files": len((task.get("ground_truth", {}) or {}).get("files", [])),
                "n_cur_files": len(cur["files"]),
                "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
            }
        )
    by_kind: dict[str, dict[str, int]] = {}
    for r in rows:
        bucket = by_kind.setdefault(r["kind"], {})
        bucket[r["status"]] = bucket.get(r["status"], 0) + 1
    stale = sum(1 for r in rows if r["status"] == "SUPERSET_STALE")
    return {
        "n_tasks": len(rows),
        "by_kind": by_kind,
        "n_superset_stale": stale,
        "recommendation": "RE-FREEZE" if stale >= 5 else "KEEP",
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-save", action="store_true")
    opts = parser.parse_args()
    siga = _siga()
    if siga is None:
        print("sem clone do SIGA ao lado — auditoria pulada explicitamente")
        return 0
    tasks = load_tasks()
    report = {
        "suite": "EVAL-MCP/F23",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tasks_artifact": "eval/mcp_suite/tasks.jsonl",
        "audit": audit(tasks, siga),
    }
    a = report["audit"]
    print(f"tasks={a['n_tasks']} stale={a['n_superset_stale']} rec={a['recommendation']}")
    for kind, counts in sorted(a["by_kind"].items()):
        print(f"  {kind}: {counts}")
    if not opts.no_save:
        reports_dir = ROOT / "experiments/reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        out = reports_dir / "gt_desync.json"
        record = new_run(
            config={"kind": "gt_desync"},
            dataset_version="v1.0",
            tool_version="1.0.0",
            index_version="tree-sitter-java-0.23",
            bench_version="v1.0",
            metrics={"n_superset_stale": a["n_superset_stale"], "recommendation": a["recommendation"]},
            notes="F23: auditoria de dessincronização GT×tools pós-F21 (sem re-freeze).",
            siga_root=ROOT.parent,
            work_root=ROOT,
        )
        runs_dir = ROOT / "experiments/runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / f"{record['experiment_id']}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        report["experiment_id"] = record["experiment_id"]
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"report: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
