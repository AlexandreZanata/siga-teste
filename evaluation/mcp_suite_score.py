"""Harness de scoring da suite EVAL-MCP (G02, docs/18 §3/§5).

Veredito determinístico offline sobre os runs manuais registrados em
`eval/mcp_suite/runs/<modelo>-<ide>-<data>.jsonl` (formato do PROTOCOL.md):
cada linha `{task_id, braco, resposta, arquivos, simbolos, commits,
tokens_proxy, latency_ms, chamadas_mcp}`.

Veredito por tarefa, do mais para o menos exigente:
- `exact`   — todos os arquivos do GT citados e nenhum arquivo fora do GT
  (recall = precision = 1);
- `partial` — recall@k ≥ 0.5 (k = |GT|) e precision ≥ 0.5;
- `fail`    — caso contrário.
`task_success = partial ou melhor`. Em `history` o GT congelado é a lista de
commits: acerto = cobertura dos commits do GT citados (12 hex); arquivos
citados não são a superfície. Símbolo âncora (trace/context) gera
`symbol_hit` quando citado.

Regra do docs/11 §1: `effective_token_reduction = 1 - tok_B/tok_A` sempre
acompanhado de `task_success_delta` — redução de tokens com queda de success
= fracasso, sem exceção. Determinístico, só stdlib; os runs referenciam
apenas tarefas do artefato congelado `tasks.jsonl` (run desconhecido aborta,
nunca sucesso falso).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluation.metrics import (  # noqa: E402
    count_tokens,
    hallucination_rate,
    latency_p50_p95,
    recall_at_k,
)
from experiments.log import new_run  # noqa: E402

TASKS = ROOT / "eval/mcp_suite/tasks.jsonl"
RUNS_DIR = ROOT / "eval/mcp_suite/runs"
SUCCESS_THRESHOLD = 0.5
MIN_TASKS = 5

TEST_OVERRIDE_PATH: Path | None = None


def load_tasks(path: Path | None = None) -> dict[str, dict[str, Any]]:
    p = path or TEST_OVERRIDE_PATH or TASKS
    doc = json.loads(p.read_text(encoding="utf-8"))
    return {t["id"]: t for t in doc["tasks"]}


def tokens_proxy(text: str) -> int:
    """Proxy whitespace de tokens (docs/18 §3 — mesmo de evaluation.metrics)."""
    return count_tokens(text)


def commit_coverage(gt_commits: list[str], cited: list[str]) -> float:
    """Fração dos commits do GT citados (comparação por 12 hex)."""
    short_gt = {c[:12] for c in gt_commits}
    short_cited = {c[:12] for c in cited}
    return len(short_gt & short_cited) / len(short_gt)


def score_run(tasks: dict[str, dict[str, Any]], run: dict[str, Any]) -> dict[str, Any]:
    """Veredito por tarefa a partir de um run do braço A ou B."""
    task_id = run.get("task_id")
    if task_id not in tasks:
        raise SystemExit(f"run referencia tarefa inexistente no artefato congelado: {task_id!r}")
    task = tasks[task_id]
    gt = task["ground_truth"]
    gt_files: list[str] = gt.get("files", [])
    gt_commits: list[str] = [c["sha"] for c in gt.get("commits", [])]
    files = [str(f) for f in run.get("arquivos", [])]
    symbols = [str(s) for s in run.get("simbolos", [])]
    cited_commits = [str(c) for c in run.get("commits", [])]

    commit_hit: float | None = None
    symbol_hit: bool | None = None
    if gt_files:
        recall = recall_at_k(files, set(gt_files), k=len(gt_files))
        precision = len(set(files) & set(gt_files)) / len(files) if files else 0.0
        halluc = hallucination_rate(files, set(gt_files))
    else:
        # history: GT por commits — arquivos citados não são a superfície.
        recall = commit_coverage(gt_commits, cited_commits) if gt_commits else 0.0
        precision = None
        cited_short = [c[:12] for c in cited_commits]
        halluc = hallucination_rate(cited_short, {c[:12] for c in gt_commits}) if cited_short else 0.0
        commit_hit = recall

    anchor = gt.get("anchor")
    anchor_is_symbol = bool(anchor and "/" not in anchor)
    symbol_hit: bool | None = None
    if anchor_is_symbol and task["kind"] in ("trace", "context"):
        symbol_hit = anchor in symbols

    # Recall@1/3/5 (docs/10 §2) sobre a superfície do GT congelado.
    recalls = {f"recall_at_{k}": round(recall_at_k(files, set(gt_files), k), 3) for k in (1, 3, 5)} if gt_files else {f"recall_at_{k}": None for k in (1, 3, 5)}
    if anchor_is_symbol:
        symbol_recalls = {f"symbol_recall_at_{k}": round(recall_at_k(symbols, {anchor}, k), 3) for k in (1, 3, 5)}
    else:
        symbol_recalls = {f"symbol_recall_at_{k}": None for k in (1, 3, 5)}

    # Tool Selection Accuracy e Argument Exact Match (só fazem sentido no braço B).
    calls = run.get("chamadas_mcp") or []
    call_methods = [c.get("method") if isinstance(c, dict) else str(c) for c in calls]
    tool_selection_correct: bool | None = None
    argument_exact: bool | None = None
    expected_method = task.get("method")
    if run.get("braco") == "B" and calls:
        tool_selection_correct = expected_method in call_methods
        matching = [c for c in calls if isinstance(c, dict) and c.get("method") == expected_method]
        if matching:
            argument_exact = matching[0].get("args", {}) == task.get("args", {})

    if recall >= SUCCESS_THRESHOLD and (precision is None or precision >= SUCCESS_THRESHOLD):
        verdict = "exact" if recall >= 0.999 and (precision is None or precision >= 0.999) else "partial"
    else:
        verdict = "fail"

    return {
        "task_id": task_id,
        "kind": task["kind"],
        "braco": run.get("braco", "?"),
        "verdict": verdict,
        "task_success": verdict in ("exact", "partial"),
        "recall_at_k": round(recall, 3),
        "precision": None if precision is None else round(precision, 3),
        "hallucination_rate": round(halluc, 3),
        "commit_hit": None if commit_hit is None else round(commit_hit, 3),
        "symbol_hit": symbol_hit,
        **recalls,
        **symbol_recalls,
        "tool_selection_correct": tool_selection_correct,
        "argument_exact": argument_exact,
        "n_answered_files": len(files),
        "n_answered_symbols": len(symbols),
        "n_mcp_calls": len(run.get("chamadas_mcp") or []),
        "latency_ms": run.get("latency_ms"),
        "tokens_proxy": run.get("tokens_proxy", 0),
    }


def _mean(vals: list[Any]) -> float | None:
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def aggregate(scores: list[dict[str, Any]]) -> dict[str, Any]:
    if not scores:
        return {"n_tasks": 0}
    recalls = [s["recall_at_k"] for s in scores if s["recall_at_k"] is not None]
    latencies = [s["latency_ms"] for s in scores if isinstance(s["latency_ms"], (int, float))]
    return {
        "n_tasks": len(scores),
        "n_exact": sum(1 for s in scores if s["verdict"] == "exact"),
        "n_partial": sum(1 for s in scores if s["verdict"] == "partial"),
        "n_fail": sum(1 for s in scores if s["verdict"] == "fail"),
        "task_success": round(sum(1 for s in scores if s["task_success"]) / len(scores), 3),
        "mean_recall_at_k": round(sum(recalls) / len(recalls), 3) if recalls else None,
        "mean_recall_at_1": _mean([s.get("recall_at_1") for s in scores]),
        "mean_recall_at_3": _mean([s.get("recall_at_3") for s in scores]),
        "mean_recall_at_5": _mean([s.get("recall_at_5") for s in scores]),
        "mean_symbol_recall_at_1": _mean([s.get("symbol_recall_at_1") for s in scores]),
        "mean_hallucination_rate": round(sum(s["hallucination_rate"] for s in scores) / len(scores), 3),
        "tool_selection_accuracy": _mean(
            [1.0 if s["tool_selection_correct"] else 0.0 for s in scores if s.get("tool_selection_correct") is not None]
        ),
        "argument_exact_rate": _mean(
            [1.0 if s["argument_exact"] else 0.0 for s in scores if s.get("argument_exact") is not None]
        ),
        "tokens_proxy_total": sum(s["tokens_proxy"] or 0 for s in scores),
        "latency": latency_p50_p95(latencies) if len(latencies) >= 2 else None,
        "mean_mcp_calls": round(sum(s["n_mcp_calls"] for s in scores) / len(scores), 3),
    }


def effective_token_reduction(tok_a: int, tok_b: int) -> float | None:
    """docs/11: 1 - tok_B/tok_A; None quando o braço A não tem base."""
    if not tok_a:
        return None
    return round(1.0 - tok_b / tok_a, 3)


def compare_arms(agg_a: dict[str, Any], agg_b: dict[str, Any]) -> dict[str, Any]:
    """A vs B com a regra do docs/11: redução de tokens sem success = fracasso."""
    if agg_a.get("n_tasks", 0) < MIN_TASKS or agg_b.get("n_tasks", 0) < MIN_TASKS:
        return {"comparable": False, "reason": f"mínimo de {MIN_TASKS} tarefas por braço"}
    delta = round(agg_b["task_success"] - agg_a["task_success"], 3)
    reduction = effective_token_reduction(agg_a["tokens_proxy_total"], agg_b["tokens_proxy_total"])
    if reduction is not None and reduction > 0 and delta < 0:
        verdict = "failure_token_reduction_with_regression"
    elif delta > 0:
        verdict = "mcp_helps"
    elif delta < 0:
        verdict = "mcp_hurts"
    else:
        verdict = "tie"
    return {
        "comparable": True,
        "task_success_delta": delta,
        "effective_token_reduction": reduction,
        "verdict": verdict,
    }


def score_run_file(path: Path, tasks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    scores: list[dict[str, Any]] = []
    n_lines = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        n_lines += 1
        scores.append(score_run(tasks, json.loads(line)))
    by_arm = {arm: [s for s in scores if s["braco"] == arm] for arm in ("A", "B")}
    aggregate_by_arm = {arm: aggregate(items) for arm, items in by_arm.items()}
    comparison = None
    if aggregate_by_arm["A"]["n_tasks"] and aggregate_by_arm["B"]["n_tasks"]:
        comparison = compare_arms(aggregate_by_arm["A"], aggregate_by_arm["B"])
    return {
        "file": str(path),
        "n_lines": n_lines,
        "scores": scores,
        "aggregate": aggregate_by_arm,
        "comparison": comparison,
    }


def save_report(report: dict[str, Any]) -> Path:
    reports_dir = ROOT / "experiments/reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / "mcp_suite_score.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    summary = report["summary"]
    new_run(
        kind="mcp_suite_score",
        config={
            "tasks_artifact": "eval/mcp_suite/tasks.jsonl",
            "runs": [r["file"] for r in report["runs"]],
        },
        metrics=summary,
        artifacts=[str(out.relative_to(ROOT))],
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, help="arquivo de run único (JSONL)")
    parser.add_argument("--runs-dir", type=Path, help="diretório com runs (default: eval/mcp_suite/runs)")
    parser.add_argument("--report", type=Path, help="caminho alternativo do report agregado")
    parser.add_argument("--no-save", action="store_true", help="não grava report/run (só stdout)")
    opts = parser.parse_args()
    tasks = load_tasks()
    if opts.runs:
        run_files = [opts.runs]
    else:
        run_dir = opts.runs_dir or RUNS_DIR
        run_files = sorted(run_dir.glob("*.jsonl"))
        if not run_files:
            raise SystemExit(f"nenhum run em {run_dir} (use --runs ou registre runs no formato do PROTOCOL.md)")
    entries = [score_run_file(f, tasks) for f in run_files]
    arms = {"A": 0, "B": 0}
    for e in entries:
        for arm in arms:
            arms[arm] += e["aggregate"][arm].get("n_tasks", 0)
    report = {
        "suite": "EVAL-MCP",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tasks_artifact": "eval/mcp_suite/tasks.jsonl",
        "success_threshold": SUCCESS_THRESHOLD,
        "runs": entries,
        "summary": {
            "n_run_files": len(entries),
            "n_tasks_scored": sum(e["n_lines"] for e in entries),
            "n_tasks_arm_A": arms["A"],
            "n_tasks_arm_B": arms["B"],
            "comparisons": [e["comparison"] for e in entries if e["comparison"]],
        },
    }
    for e in entries:
        for arm in ("A", "B"):
            agg = e["aggregate"][arm]
            if agg.get("n_tasks"):
                print(f"[{Path(e['file']).name} braço {arm}] success={agg['task_success']} "
                      f"exact={agg['n_exact']} partial={agg['n_partial']} fail={agg['n_fail']} "
                      f"recall~{agg['mean_recall_at_k']} tokens={agg['tokens_proxy_total']}")
        if e["comparison"]:
            print(f"  A vs B: {json.dumps(e['comparison'], ensure_ascii=False)}")
    if not opts.no_save:
        out = save_report(report)
        print(f"report: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
