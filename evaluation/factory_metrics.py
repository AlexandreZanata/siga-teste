"""Métricas da fábrica de dados e curva dataset-size (P06-T02, docs/07 §4 e docs/09 §1).

Mede:
- no-tool accuracy: precisão em tarefas sem ferramenta (off-topic, insuficientes)
- hallucination rate: proporção de alvos/símbolos alucinados nos dados
- distribuição por professor e categoria
- curva dataset-size (100 -> 500) com logging estruturado em experiments/
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from evaluation.harness import bench_shas, load_manifest
from experiments.log import new_run
from verifier import checker

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "datasets/benchmark/manifest.json"


def compute_gold_metrics(
    records: list[dict[str, Any]],
    repo_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Calcula métricas de qualidade, no-tool accuracy e hallucination sobre registros gold."""
    if repo_path is None:
        parent = ROOT.parent
        repo_path = parent if (parent / "siga-ex").is_dir() else ROOT

    total = len(records)
    if total == 0:
        return {"total": 0, "no_tool_accuracy": 0.0, "hallucination_rate": 0.0}

    no_tool_candidates = 0
    no_tool_correct = 0

    tool_records = 0
    hallucinated_records = 0

    teacher_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    split_counts: dict[str, int] = {}
    step_counts: list[int] = []

    no_tool_types = {
        "off-topic",
        "no-tool",
        "ambiguous-incomplete",
        "insufficient",
        "refusal",
        "clarification_needed",
    }

    for rec in records:
        cat = rec.get("task_type") or rec.get("category", "unknown")
        subcat = rec.get("subcategory", "")
        teacher = rec.get("teacher", "unknown")
        split = rec.get("split", "unknown")
        tools = rec.get("tools", [])
        steps = rec.get("trajectory", []) or rec.get("steps", [])

        teacher_counts[teacher] = teacher_counts.get(teacher, 0) + 1
        category_counts[cat] = category_counts.get(cat, 0) + 1
        split_counts[split] = split_counts.get(split, 0) + 1
        step_counts.append(len(steps))

        # Avaliação de no-tool
        is_no_tool_expected = (
            cat in no_tool_types
            or subcat in no_tool_types
            or "off-topic" in str(rec.get("reasoning", ""))
            or rec.get("final") in ("OFF_TOPIC", "CLARIFICATION_NEEDED", "NO_TOOL")
        )
        if is_no_tool_expected:
            no_tool_candidates += 1
            if len(tools) == 0 and len(rec.get("answers", [])) == 0:
                no_tool_correct += 1

        # Avaliação de hallucination em chamadas de tools
        if len(tools) > 0:
            tool_records += 1
            has_hallucination = False
            for step in steps:
                args = step.get("args", {})
                target = args.get("target") or args.get("symbol") or args.get("path")
                if target and isinstance(target, str):
                    clean = target.replace(".java", "").replace(".jsp", "").replace(".sql", "")
                    if clean not in ("file", "symbol", "controller", "entity", "jsp", "migration", "test"):
                        # Checa se existe no grafo ou repo
                        exists_in_graph = checker.check_symbol(conn, clean) if conn else True
                        exists_in_repo = checker.check_grep(repo_path, clean)
                        if not exists_in_graph and not exists_in_repo:
                            has_hallucination = True
                            break
            if has_hallucination:
                hallucinated_records += 1

    no_tool_accuracy = (
        round(no_tool_correct / no_tool_candidates, 4) if no_tool_candidates > 0 else 1.0
    )
    hallucination_rate = (
        round(hallucinated_records / tool_records, 4) if tool_records > 0 else 0.0
    )

    # Verificação anti-leakage contra benchmark
    manifest = load_manifest(MANIFEST_PATH)
    shas = bench_shas(manifest)
    leaked = any(
        sha in json.dumps(rec, ensure_ascii=False)
        for rec in records
        for sha in shas
    )

    return {
        "total_records": total,
        "no_tool_accuracy": no_tool_accuracy,
        "no_tool_candidates": no_tool_candidates,
        "no_tool_correct": no_tool_correct,
        "hallucination_rate": hallucination_rate,
        "tool_records": tool_records,
        "anti_leakage_passed": not leaked,
        "avg_steps": round(sum(step_counts) / len(step_counts), 2) if step_counts else 0.0,
        "teacher_distribution": teacher_counts,
        "category_distribution": category_counts,
        "split_distribution": split_counts,
    }


def record_dataset_size_curve(
    gold_100: list[dict[str, Any]],
    gold_500: list[dict[str, Any]],
    repo_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Calcula métricas dos pontos N=100 e N=500 e grava registro em experiments/."""
    m100 = compute_gold_metrics(gold_100, repo_path=repo_path, conn=conn)
    m500 = compute_gold_metrics(gold_500, repo_path=repo_path, conn=conn)

    curve_data = {
        "curve": "dataset_size_progression",
        "points": [
            {"n": 100, "metrics": m100},
            {"n": 500, "metrics": m500},
        ],
        "delta": {
            "scale_factor": 5.0,
            "no_tool_accuracy_preserved": m500["no_tool_accuracy"] >= m100["no_tool_accuracy"],
            "zero_hallucination_maintained": m500["hallucination_rate"] == 0.0,
            "categories_expanded": len(m500["category_distribution"]) >= len(m100["category_distribution"]),
        },
    }

    # Registra no experiment tracking do projeto
    exp_record = new_run(
        config={"dataset_curve": [100, 500], "factory_strategy": "multi_teacher_shortest_correct"},
        dataset_version="v1.0",
        tool_version="1.0.0",
        index_version="1.0.0",
        bench_version="1.0.0",
        metrics={
            "n100_no_tool_acc": m100["no_tool_accuracy"],
            "n500_no_tool_acc": m500["no_tool_accuracy"],
            "n100_hallucination_rate": m100["hallucination_rate"],
            "n500_hallucination_rate": m500["hallucination_rate"],
            "n500_total": m500["total_records"],
        },
        notes="P06-T02: Curva dataset-size iniciada (100 -> 500 gold records) com multi-teacher selection.",
        siga_root=repo_path,
        work_root=ROOT,
    )

    reports_dir = ROOT / "experiments/reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / "dataset_size_curve.json"
    report_file.write_text(json.dumps(curve_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    runs_dir = ROOT / "experiments/runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_file = runs_dir / f"{exp_record['experiment_id']}.json"
    run_file.write_text(json.dumps(exp_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return curve_data
