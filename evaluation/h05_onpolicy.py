"""On-policy final + auditoria de contaminação + veredito GO (H05, docs/19).

Reaplica as tools melhoradas (H01–H04) sobre os INPUTS dos fails da ref1
— nunca o GT — e mede o delta com o scorer. Audita que o gold do H03
só referencia o bench congelado e que o bench segue intocado. Fecha com
o veredito GO/NO-GO da meta 0.99. Offline, determinístico, só stdlib.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.mcp_suite_score import (
    aggregate,
    compare_arms,
    load_tasks,
    score_run,
    tokens_proxy,
)
from experiments.log import new_run
from tools.siga_history import siga_history as history_fn
from tools.siga_impact import siga_impact as impact_fn
from tools.siga_locate import siga_locate as locate_fn

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "eval/mcp_suite/runs"
REF1 = RUNS_DIR / "opencode-musespark-20260920.jsonl"
GO_RECALL5 = 0.99
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


def _stems(files: list[str]) -> list[str]:
    return [Path(f).stem for f in files if f.endswith(".java")]


def _row(task_id: str, files: list[str], symbols: list[str], commits: list[str], latency: float, calls: list) -> dict[str, Any]:
    lines = ["### RESPOSTA", ""]
    lines += [f"FILE: {f}" for f in files]
    lines += [f"SYMBOL: {s}" for s in symbols]
    lines += [f"COMMIT: {c}" for c in commits]
    resposta = "\n".join(lines) + "\n"
    return {
        "task_id": task_id,
        "braco": "C",
        "resposta": resposta,
        "arquivos": files,
        "simbolos": symbols,
        "commits": commits,
        "tokens_proxy": tokens_proxy(resposta),
        "latency_ms": round(latency, 3),
        "chamadas_mcp": calls,
    }


def apply_policy(tasks: dict[str, dict[str, Any]], rows: list[dict[str, Any]], siga: Path) -> list[dict[str, Any]]:
    """Reexecuta a policy atual nos fails do braço B (inputs do task, sem GT)."""
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("braco") != "B":
            continue
        task = tasks.get(row.get("task_id", ""))
        if task is None:
            raise ValueError(f"task_id fora do congelado: {row.get('task_id')!r}")
        if score_run(tasks, row).get("verdict") != "fail":
            continue
        kind = task.get("kind")
        args = task.get("args", {}) or {}
        t0 = time.perf_counter()
        files: list[str] = []
        symbols: list[str] = []
        commits: list[str] = []
        calls: list = []
        if kind == "locate":
            calls = [{"method": "siga.locate", "args": args}]
            hits = locate_fn(
                args.get("query", ""), kind=args.get("kind"), repo=siga, limit=10
            )
            files = [_rel(siga, h["file"]) for h in hits[:TOP_FILES] if h.get("file")]
            symbols = _stems(files)
        elif kind == "impact":
            calls = [{"method": "siga.impact", "args": args}]
            res = impact_fn(args.get("target", ""), hops=int(args.get("hops", 1)), repo=siga)
            files = [_rel(siga, f) for f in (res.get("affected_files") or [])[:TOP_FILES]]
            symbols = _stems(files)
        elif kind == "history":
            calls = [{"method": "siga.history", "args": args}]
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
            symbols = _stems(files)
            commits = [c["sha"] for c in res.get("commits", []) if c.get("sha")]
        else:
            continue
        out.append(_row(row["task_id"], files, symbols, commits, (time.perf_counter() - t0) * 1000.0, calls))
    return out


def audit(tasks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Gold ⊆ bench congelado; bench intocado; gold carrega holdout id."""
    holdout_ids: set[str] = set()
    bench_path = ROOT / "datasets/benchmark/holdout.jsonl"
    if bench_path.is_file():
        for line in bench_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                holdout_ids.add(json.loads(line).get("id", ""))
    gold_path = ROOT / "eval/mcp_suite/gold/opencode-musespark-20260920.gold.jsonl"
    gold_ids: set[str] = set()
    bad: list[str] = []
    if gold_path.is_file():
        for line in gold_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            gold_ids.add(rec.get("id", ""))
            hid = rec.get("source_holdout_id", "")
            if hid not in holdout_ids:
                bad.append(rec.get("id", ""))
            base = rec.get("id", "").split(":")[0]
            if base not in tasks:
                bad.append(rec.get("id", "") + ":task-unknown")
    bench_clean = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--short", "--", "datasets/benchmark"],
        capture_output=True, text=True, check=True, timeout=60,
    ).stdout.strip() == ""
    return {
        "gold_file": str(gold_path.relative_to(ROOT)) if gold_path.is_file() else None,
        "n_gold": len(gold_ids),
        "gold_outside_bench": sorted(bad),
        "bench_tree_clean": bench_clean,
        "pass": not bad and bench_clean,
    }


def score_file(tasks: dict[str, dict[str, Any]], path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    scores = [score_run(tasks, r) for r in rows]
    by_arm = {arm: [s for s in scores if s["braco"] == arm] for arm in ("A", "B", "C")}
    return scores, {arm: aggregate(items) for arm, items in by_arm.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref1", type=Path, default=REF1)
    parser.add_argument("--ref2", type=Path, default=RUNS_DIR / "buffy-freebuff-20260920.jsonl")
    parser.add_argument("--no-save", action="store_true")
    opts = parser.parse_args()
    tasks = load_tasks()
    siga = _siga()

    _, agg_ref1 = score_file(tasks, opts.ref1)
    ref1_scores = [score_run(tasks, r) for r in
                   (json.loads(line) for line in opts.ref1.read_text(encoding="utf-8").splitlines() if line.strip())]
    policy_rows: list[dict[str, Any]] = []
    policy_skipped = siga is None
    if not policy_skipped:
        ref1_rows = [json.loads(line) for line in opts.ref1.read_text(encoding="utf-8").splitlines() if line.strip()]
        policy_rows = apply_policy(tasks, ref1_rows, siga)
    c_scores = [score_run(tasks, r) for r in policy_rows]
    agg_c = aggregate(c_scores)
    c_ids = {r["task_id"] for r in policy_rows}
    b_sub = aggregate([s for s in ref1_scores if s["task_id"] in c_ids and s["braco"] == "B"])
    vs_subset = compare_arms(b_sub, agg_c) if agg_c.get("n_tasks") else None

    ref2_info: dict[str, Any] = {"present": opts.ref2.is_file()}
    agg_ref2b: dict[str, Any] = {"n_tasks": 0}
    if opts.ref2.is_file():
        digest = hashlib.sha256(opts.ref2.read_bytes()).hexdigest()[:16]
        _, agg_ref2 = score_file(tasks, opts.ref2)
        agg_ref2b = agg_ref2.get("B", {"n_tasks": 0})
        ref2_info.update({"sha16": digest, "agg_b": agg_ref2b})

    audit_rep = audit(tasks)
    rec5_c = (agg_c.get("mean_recall_at_5") or 0.0) if agg_c.get("n_tasks") else 0.0
    rec5_b = (agg_ref1.get("B", {}).get("mean_recall_at_5") or 0.0)
    verdict = "GO" if min(rec5_c, rec5_b) >= GO_RECALL5 and audit_rep["pass"] else "NO-GO"
    report = {
        "suite": "EVAL-MCP/H05",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "skipped": policy_skipped,
            "n_policy_rows": len(policy_rows),
            "agg_c": agg_c,
            "b_subset_same_tasks": b_sub,
            "vs_b_subset": vs_subset,
            "vs_ref1b_all": compare_arms(agg_ref1.get("B", {}), agg_c) if agg_c.get("n_tasks") else None,
        },
        "ref1b": agg_ref1.get("B", {}),
        "ref2": ref2_info,
        "audit": audit_rep,
        "go_target": {"recall_at_5": GO_RECALL5},
        "verdict": verdict,
    }
    print(f"[C policy] n={agg_c.get('n_tasks')} success={agg_c.get('task_success')} recall@5={agg_c.get('mean_recall_at_5')}")
    print(f"[B ref1] success={agg_ref1.get('B', {}).get('task_success')} recall@5={rec5_b}")
    if agg_ref2b.get("n_tasks"):
        print(f"[B ref2] success={agg_ref2b.get('task_success')} recall@5={agg_ref2b.get('mean_recall_at_5')}")
    print(f"audit_pass={audit_rep['pass']} verdict={verdict}")
    if not opts.no_save:
        reports_dir = ROOT / "experiments/reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        out = reports_dir / "h05_onpolicy.json"
        record = new_run(
            config={"kind": "h05_onpolicy"},
            dataset_version="v1.0",
            tool_version="1.0.0",
            index_version="tree-sitter-java-0.23",
            bench_version="v1.0",
            metrics={"verdict": verdict, "c_success": agg_c.get("task_success"), "c_recall5": rec5_c},
            notes="H05: on-policy final + auditoria + veredito GO (docs/19).",
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
