"""20 exemplos do holdout ponta a ponta (P04-T02, sem LLM).

Pipeline determinístico: query (mensagem do commit) → search_text no slice
→ File Recall@1/@5 contra ground_truth_files. Publica os números;
sem threshold mágico (baselines da P06/Fase 11 comparam aqui).
"""

from __future__ import annotations

import json
from pathlib import Path

from evaluation import metrics
from retrieval.baseline import naive_locate

ROOT = Path(__file__).resolve().parent.parent.parent
SIGA = ROOT.parent
HOLDOUT = ROOT / "datasets/benchmark/holdout.jsonl"
N_RUN = 20


def _load_tasks() -> list[dict]:
    tasks = [json.loads(line) for line in HOLDOUT.read_text(encoding="utf-8").splitlines()]
    return sorted(tasks, key=lambda t: t["id"])[:N_RUN]


def test_holdout_runs_end_to_end():
    tasks = _load_tasks()
    assert len(tasks) == N_RUN
    recalls_1: list[float] = []
    recalls_5: list[float] = []
    for task in tasks:
        ranked_abs = naive_locate(SIGA, task["query"], limit=5)
        ranked = [str(Path(f).relative_to(SIGA)) for f in ranked_abs]
        assert all((SIGA / f).is_file() for f in ranked)
        expected = set(task["ground_truth_files"])
        recalls_1.append(metrics.recall_at_k(ranked, expected, 1))
        recalls_5.append(metrics.recall_at_k(ranked, expected, 5))
    r1 = sum(recalls_1) / len(recalls_1)
    r5 = sum(recalls_5) / len(recalls_5)
    print(f"\nholdout determinístico (20 ex): File Recall@1={r1:.2f} Recall@5={r5:.2f}")
    assert 0.0 <= r1 <= r5 <= 1.0
