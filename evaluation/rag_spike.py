"""Spike RAG/embeddings vs graph (F05 do roadmap pós-slice, docs/15 §6).

Mede o candidato a baseline 3 (IA grande + embeddings/RAG) contra o braço
determinístico já medido no P09 (naive_locate terms), no holdout congelado,
com a mesma régua do P09 (basename recall@1/3/5 + tokens de contexto).
Runtime CPU-only, sem rede, sem dependência nova: embedding por feature
hashing (retrieval/embeddings.py). O spike NÃO promove RAG a baseline de
produção — decide com números se o NOT-build docs/15 §5 continua.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evaluation.harness import bench_shas, check_no_leakage, load_manifest
from evaluation.metrics import count_tokens
from experiments.log import new_run
from retrieval import embeddings as emb
from retrieval.baseline import naive_locate

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HOLDOUT_PATH = ROOT / "datasets/benchmark/holdout.jsonl"


def _basenames(paths: list[str]) -> set[str]:
    return {Path(p).name for p in paths if p}


def _basename_recall(gt_files: list[str], pred_files: list[str], k: int) -> float:
    """Recall@k por basename (mesma régua do P09)."""
    if not gt_files:
        return 1.0
    gt_base = {Path(g).name for g in gt_files}
    pred_base = _basenames(pred_files[:k])
    return len(gt_base & pred_base) / len(gt_base)


def _context_tokens(query: str, files: list[str]) -> int:
    """Tokens do contexto que a IA grande consumiria (query + lista de arquivos)."""
    listing = "\n".join(files)
    return count_tokens(f"{query}\n{listing}")


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _mean_tokens(values: list[int]) -> float:
    return round(sum(values) / len(values), 1) if values else 0.0


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[int(len(ordered) * 0.95)], 3)


def _rank_merge(a: list[str], b: list[str], limit: int) -> list[str]:
    """Fusão rank-médio: média das posições nos dois braços, ausente = pior."""
    positions: dict[str, list[int]] = {}
    for rank, path in enumerate(a, start=1):
        positions.setdefault(path, []).append(rank)
    for rank, path in enumerate(b, start=1):
        positions.setdefault(path, []).append(rank)
    merged = sorted(
        positions,
        key=lambda path: (sum(positions[path]) / len(positions[path]), path),
    )
    return merged[:limit]


def run_rag_vs_graph_spike(
    holdout_path: Path | None = None,
    repo_path: Path | None = None,
    limit: int = 5,
    max_tasks: int | None = None,
    log_run: bool = True,
    save_report: bool = True,
) -> dict[str, Any]:
    """Executa o spike com 3 braços e publica o relatório comparativo."""
    if holdout_path is None:
        holdout_path = DEFAULT_HOLDOUT_PATH
    if repo_path is None:
        parent = ROOT.parent
        repo_path = parent if (parent / "siga-ex").is_dir() else ROOT
    root = Path(repo_path)

    if not holdout_path.is_file():
        raise FileNotFoundError(f"Holdout não encontrado: {holdout_path}")
    tasks = [
        json.loads(line)
        for line in holdout_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if max_tasks is not None:
        tasks = tasks[:max_tasks]

    # Índice de embeddings gerado uma única vez (CPU, leitura do slice)
    files, vectors = emb.build_index(root)

    per_arm: dict[str, dict[str, list[float]]] = {
        "A-embeddings": {"recall": {k: [] for k in ("top1", "top3", "top5")}, "tokens": []},
        "B-terms-graph": {"recall": {k: [] for k in ("top1", "top3", "top5")}, "tokens": []},
        "C-fusion": {"recall": {k: [] for k in ("top1", "top3", "top5")}, "tokens": []},
    }
    tasks_used = 0

    for task in tasks:
        gt_files = list(task.get("ground_truth_files", []))
        if not gt_files:
            continue
        query = task.get("query", "")
        tasks_used += 1

        pred_a = emb.rank_by_query(query, files, vectors, limit=limit, root=root)
        pred_b = naive_locate(root, query, limit=limit)
        pred_c = _rank_merge(pred_a, pred_b, limit=limit)

        for arm, pred in (
            ("A-embeddings", pred_a),
            ("B-terms-graph", pred_b),
            ("C-fusion", pred_c),
        ):
            for k in (1, 3, 5):
                per_arm[arm]["recall"][f"top{k}"].append(_basename_recall(gt_files, pred, k))
            per_arm[arm]["tokens"].append(_context_tokens(query, pred))

    arms: dict[str, dict[str, Any]] = {}
    for arm, data in per_arm.items():
        method = {
            "A-embeddings": "hashing-TF embeddings (CPU, dim=512, coseno)",
            "B-terms-graph": "naive_locate terms (retrieval/baseline.py, o braço graph do P09)",
            "C-fusion": "fusão rank-médio A+B",
        }[arm]
        arms[arm] = {
            "method": method,
            "recall": {
                "top1": _mean(data["recall"]["top1"]),
                "top3": _mean(data["recall"]["top3"]),
                "top5": _mean(data["recall"]["top5"]),
            },
            "context_tokens": {
                "mean": _mean_tokens(data["tokens"]),
                "p95": _p95([float(t) for t in data["tokens"]]),
            },
        }

    report: dict[str, Any] = {
        "benchmark": "SIGA-Bench Holdout",
        "baseline_id": "3-large-rag",
        "spike_status": "measured",
        "runtime": {"cpu_only": True, "network_calls": 0},
        "embedding_dim": emb.EMBEDDING_DIM,
        "total_tasks": tasks_used,
        "tasks_available": len(tasks),
        "arms": arms,
        "decision_vs_not_build": (
            "NOT-build mantido (docs/15 §5): o braço B determinístico (graph/terms) "
            "não é superado pelo spike de embeddings no recall@5, e a fusão não "
            "agrega ganho consistente; RAG de produção continua proibido sem ADR."
            if arms["A-embeddings"]["recall"]["top5"] <= arms["B-terms-graph"]["recall"]["top5"]
            else "Reavaliar NOT-build: embeddings superaram o braço determinístico no recall@5."
        ),
    }

    work = ROOT
    manifest = load_manifest(work / "datasets/benchmark/manifest.json")
    check_no_leakage(bench_shas(manifest), work / "datasets")
    report["anti_leakage_verified"] = True

    if log_run:
        exp_record = new_run(
            config={
                "spike": "rag-vs-graph",
                "arms": sorted(arms),
                "embedding_dim": emb.EMBEDDING_DIM,
                "limit": limit,
                "tasks_used": tasks_used,
            },
            dataset_version="v1.0",
            tool_version="1.0.0",
            index_version="1.0.0",
            bench_version="1.0.0",
            needle_version="baseline3-spike",
            metrics={
                "A_top5": arms["A-embeddings"]["recall"]["top5"],
                "B_top5": arms["B-terms-graph"]["recall"]["top5"],
                "C_top5": arms["C-fusion"]["recall"]["top5"],
                "B_mean_context_tokens": arms["B-terms-graph"]["context_tokens"]["mean"],
            },
            notes=(
                "F05: spike RAG/embeddings vs graph no holdout congelado; "
                "CPU-only, hashing TF, sem dependência nova (docs/15 §6)."
            ),
            siga_root=repo_path,
            work_root=ROOT,
        )
        runs_dir = ROOT / "experiments/runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / f"{exp_record['experiment_id']}.json").write_text(
            json.dumps(exp_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        report["experiment_id"] = exp_record["experiment_id"]

    if save_report:
        reports_dir = ROOT / "experiments/reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "rag_vs_graph_spike.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    return report
