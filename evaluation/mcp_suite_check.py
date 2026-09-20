"""Checker cego da suite EVAL-MCP (G01, docs/18 §4).

O avaliador humano cola a RESPOSTA do agente no checker; ele compara
**cegamente** contra o `tasks.jsonl` congelado — o mesmo arquivo do dia
do benchmark, nunca regenerado. Determinístico, só stdlib:

- `parse_response`: extrai `FILE:`/`SYMBOL:`/`COMMIT:` do formato fixo dos
  prompts (tolerante a prosa fora do bloco; em bloco ### RESPOSTA, só ele vale);
- `evaluate_response`: recall@k do GT (`evaluation.metrics.recall_at_k`),
  hallucination rate (`evaluation.metrics.hallucination_rate`) e
  `out_of_repo_rate` (paths que não existem no commit do bench) — paths
  normalizados (relativos, sem prefixo `../`, `/` do SO);
- `build_report`: report comparável entre modelos/IDEs em
  `experiments/reports/mcp_suite_check.json` + run em `experiments/runs/`
  via `experiments.log` com **provenance completa** (siga_head_commit,
  tasks artifact, bench_commit, modelo/IDE informados pelo operador).

Uso: `python -m evaluation.mcp_suite_check --task 001 --response resposta.md
--model <nome> --ide <nome>` (ou `--all-answers DIR/` com arquivos
`NNN-nome-do-modelo.md`). Nunca escreve fora de `siga-teste`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluation.metrics import hallucination_rate, recall_at_k  # noqa: E402
from experiments.log import new_run  # noqa: E402

TASKS = ROOT / "eval/mcp_suite/tasks.jsonl"

_FILE_RE = re.compile(r"^\s*FILE:\s*(.+?)\s*$", re.MULTILINE)
_SYMBOL_RE = re.compile(r"^\s*SYMBOL:\s*(.+?)\s*$", re.MULTILINE)
_COMMIT_RE = re.compile(r"^\s*COMMIT:\s*([0-9a-f]{7,40})\s*$", re.MULTILINE)
_BLOCK_RE = re.compile(r"###\s*RESPOSTA\s*\n(.*?)(?:\n###\s|\Z)", re.DOTALL | re.IGNORECASE)


def _norm(path: str) -> str:
    """Normaliza um caminho citado pelo agente para comparar com o GT."""
    p = path.strip().strip("`'\"")
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    if re.fullmatch(r"[0-9a-f]{7,40}", p):
        return p
    if re.search(r"[0-9a-f]{40}", p):  # git show formats: hash:path
        p = p.split(":")[-1]
    if p.startswith("../"):
        p = p[3:]
    while p.startswith("/"):
        p = p[1:]
    p = re.sub(r"#.*$", "", p)
    p = re.sub(r"\s+.*$", "", p)  # trailing commentary
    return p.strip()


def parse_response(text: str) -> dict[str, Any]:
    """Extrai files/symbols/commits do formato fixo. Bloco ### RESPOSTA tem precedência."""
    block = _BLOCK_RE.search(text)
    scope = block.group(1) if block else text
    files: list[str] = []
    for m in _FILE_RE.finditer(scope):
        n = _norm(m.group(1))
        if n and n not in files:
            files.append(n)
    symbols: list[str] = []
    for m in _SYMBOL_RE.finditer(scope):
        s = m.group(1).strip().strip("`'\"")
        if s and s not in symbols:
            symbols.append(s)
    commits: list[str] = []
    for m in _COMMIT_RE.finditer(scope):
        c = m.group(1)
        if c not in commits:
            commits.append(c)
    return {"files": files, "symbols": symbols, "commits": commits}


def _gt_for(task: dict[str, Any]) -> list[str]:
    gt = task["ground_truth"]
    return gt.get("files", [])


def _gt_commits(task: dict[str, Any]) -> list[str]:
    return [c["sha"] for c in task["ground_truth"].get("commits", []) if c.get("sha")]


def _in_repo(path: str, root: Path) -> bool:
    p = (root / path).resolve()
    try:
        p.relative_to(root.resolve())
    except ValueError:
        return False
    return p.is_file()


def evaluate_response(task: dict[str, Any], answer: str, repo_root: Path) -> dict[str, Any]:
    parsed = parse_response(answer)
    gt = _gt_for(task)
    k = len(gt) if gt else len(parsed["files"])
    recall = recall_at_k(parsed["files"], set(gt), k) if gt else None
    halluc = hallucination_rate(parsed["files"], set(gt))
    out_of_repo = [f for f in parsed["files"] if not _in_repo(f, repo_root)]
    commits_gt = _gt_commits(task)
    commit_recall = None
    if commits_gt:
        short = {c[:12] for c in commits_gt}
        hit = sum(1 for c in parsed["commits"] if any(c[:12] == g[:12] for g in short))
        commit_recall = round(hit / len(commits_gt), 3)
    return {
        "task_id": task["id"],
        "seq": task["seq"],
        "method": task["method"],
        "kind": task["kind"],
        "gt_files": gt,
        "answered_files": parsed["files"],
        "answered_symbols": parsed["symbols"],
        "answered_commits": parsed["commits"],
        "recall_at_k": recall,
        "hallucination_rate": halluc,
        "out_of_repo_files": out_of_repo,
        "commit_recall": commit_recall,
    }


def load_tasks() -> dict[int, dict[str, Any]]:
    doc = json.loads(TASKS.read_text(encoding="utf-8"))
    return {t["seq"]: t for t in doc["tasks"]}


def build_report(per_task: list[dict[str, Any]], meta: dict[str, Any], siga_head: str) -> dict[str, Any]:
    recalls = [r["recall_at_k"] for r in per_task if r["recall_at_k"] is not None]
    hallucs = [r["hallucination_rate"] for r in per_task]
    oors = [r["out_of_repo_files"] for r in per_task]
    report = {
        "suite": "EVAL-MCP",
        "model": meta.get("model", "unspecified"),
        "ide": meta.get("ide", "unspecified"),
        "operated_at": datetime.now(timezone.utc).isoformat(),
        "tasks_artifact": "eval/mcp_suite/tasks.jsonl",
        "siga_head_commit": siga_head,
        "bench_commit": meta.get("bench_commit", siga_head),
        "per_task": per_task,
        "summary": {
            "n_tasks": len(per_task),
            "mean_recall_at_k": round(sum(recalls) / len(recalls), 3) if recalls else None,
            "mean_hallucination_rate": round(sum(hallucs) / len(hallucs), 3) if hallucs else None,
            "tasks_with_out_of_repo": sum(1 for o in oors if o),
        },
    }
    return report


def save_report(report: dict[str, Any], siga_head: str) -> Path:

    reports_dir = ROOT / "experiments/reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / "mcp_suite_check.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    metrics = {
        "model": report["model"],
        "ide": report["ide"],
        "n_tasks": report["summary"]["n_tasks"],
        "mean_recall_at_k": report["summary"]["mean_recall_at_k"],
        "mean_hallucination_rate": report["summary"]["mean_hallucination_rate"],
        "tasks_with_out_of_repo": report["summary"]["tasks_with_out_of_repo"],
    }
    new_run(
        kind="mcp_suite_check",
        config={"tasks_artifact": "eval/mcp_suite/tasks.jsonl", "siga_head_commit": siga_head},
        metrics=metrics,
        artifacts=[str(out.relative_to(ROOT))],
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", help="seq ou id da tarefa (ex.: 001)")
    parser.add_argument("--response", type=Path, help="arquivo com a resposta colada do agente")
    parser.add_argument("--all-answers", type=Path, help="dir com respostas NNN-<modelo>.md")
    parser.add_argument("--model", default="unspecified")
    parser.add_argument("--ide", default="unspecified")
    parser.add_argument("--report", type=Path, help="escreve o report agregado neste caminho")
    parser.add_argument("--no-save", action="store_true", help="não grava report/run (só stdout)")
    opts = parser.parse_args()
    tasks = load_tasks()
    repo_root = ROOT.parent if (ROOT.parent / "siga-ex").is_dir() else ROOT

    import subprocess

    siga_head = (
        subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"], capture_output=True, text=True)
        .stdout.strip()
        or "unknown"
    )

    per_task: list[dict[str, Any]] = []
    if opts.all_answers:
        for f in sorted(opts.all_answers.glob("*.md")):
            seq = int(f.name[:3])
            per_task.append(evaluate_response(tasks[seq], f.read_text(encoding="utf-8"), repo_root))
    elif opts.task and opts.response:
        seq = int(opts.task[:3])
        per_task.append(evaluate_response(tasks[seq], opts.response.read_text(encoding="utf-8"), repo_root))
    else:
        parser.error("use --task+--response ou --all-answers")
    report = build_report(per_task, {"model": opts.model, "ide": opts.ide, "bench_commit": siga_head}, siga_head)
    for r in per_task:
        print(json.dumps(r, ensure_ascii=False))
    if not opts.no_save:
        path = save_report(report, siga_head) if opts.report is None else None
        if path is not None:
            print(f"report: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
