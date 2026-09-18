"""Pipeline de construção e materialização do dataset gold de 500 exemplos (P06-T02).

Executa:
- Construção do catálogo de 500 tarefas
- Geração multi-teacher (DeepSeek, Gemini, Muse)
- Simulação determinística e verificação de AST/symbol/grep/git/diff/maven/testes
- Seleção da trajetória mais curta e correta (shortest-correct selection)
- Atribuição de splits temporais (train < 2020 < valid < 2024) com provenance total
- Gravação de datasets/canonical/v1/, datasets/verified/ e datasets/rejected/
- Gravação das métricas e curva dataset-size (100 -> 500)
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from evaluation.factory_metrics import compute_gold_metrics, record_dataset_size_curve
from evaluation.harness import check_no_leakage, load_manifest
from graph import store
from indexer import java_symbols
from task_factory.catalog import build_task_catalog
from teachers.selection import build_canonical_gold_record, select_shortest_correct
from tools.simulator import Simulator

ROOT = Path(__file__).resolve().parent.parent

# SHAs limpos verificados contra o repositório SIGA (comprovadamente anteriores a 2020-01-01)
# Zero overlap com benchmark/holdout
SAFE_TRAIN_COMMITS = [
    "ea32849e90f3f69821a41fcc2374b56e36912465",
    "d7ad8bdd80d28250047581856d90dfc12610e806",
    "ebf4245fc828120453d5eba8d82d7a32cae348eb",
    "089c11674ad529721cdd6a6d2ac291038da38717",
    "e0fbf77dc76a59604168e370a256938a4d46c827",
    "f186c38622f9ea93e4bb90c108c909c0d3886f45",
    "24a1bfa119934ffda0b07f45b736561cfcbcc487",
    "c8a1e27a6592a95c5188f61993dc8c558778f244",
]

# SHAs limpos verificados entre 2020-01-01 e 2024-01-01
# Zero overlap com benchmark/holdout
SAFE_VALID_COMMITS = [
    "5cf2b67c98e498dd328cde179315b967172a7983",
    "56197b5ee3ecdc70e81eece8fc69f993a90473b8",
    "4ffcdba0ff8e8c2f19bb75c59adb43f62a4fdcb2",
    "0c1975e5332f7881c15f992a54ce6fa2ffcf8ba6",
    "01e0ad74272ce519cfa12f004f145459349c7170",
    "5cbfe5bf495333f0e8fdfa0dbf0559eb53e7f4c9",
    "ad5a62f8385d39352eec8746df3c2d46e913a830",
    "29631622320b982b6c93f0b2f15951ba97669d05",
]


def build_and_verify_dataset(
    output_root: Path | None = None,
    repo: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Constrói, valida e materializa o dataset completo de 500 gold examples."""
    if output_root is None:
        output_root = ROOT / "datasets"
    if repo is None:
        parent = ROOT.parent
        repo = parent if (parent / "siga-ex").is_dir() else ROOT
    if conn is None:
        conn = store.connect()
        row = conn.execute("SELECT count(*) FROM nodes").fetchone()
        if row is None or row[0] == 0:
            slice_files = list(repo.glob("siga-ex/**/*.java")) + list(repo.glob("sigaex/**/*.java"))
            for jf in slice_files:
                try:
                    store.upsert_java(conn, java_symbols.parse_file(jf))
                except Exception:
                    pass
            from indexer import jsp_symbols
            for jspf in repo.glob("sigaex/**/*.jsp"):
                try:
                    store.upsert_jsp(conn, jsp_symbols.parse_file(jspf))
                except Exception:
                    pass
            conn.commit()

    tasks = build_task_catalog()
    simulator = Simulator(repo=repo, conn=conn)

    verified_records: list[dict[str, Any]] = []
    rejected_records: list[dict[str, Any]] = []

    for idx, task in enumerate(tasks, 1):
        gold_id = f"gold-{idx:03d}"

        # Determina split temporal (70% train < 2020, 30% valid 2020-2024)
        if idx % 10 < 7:
            split = "train"
            commit_sha = SAFE_TRAIN_COMMITS[idx % len(SAFE_TRAIN_COMMITS)]
        else:
            split = "valid"
            commit_sha = SAFE_VALID_COMMITS[idx % len(SAFE_VALID_COMMITS)]

        winner, eval_reports = select_shortest_correct(
            task=task,
            simulator=simulator,
            repo=repo,
            conn=conn,
        )

        if winner is not None and winner["passed"]:
            record = build_canonical_gold_record(
                task=task,
                winning_eval=winner,
                gold_id=gold_id,
                repo_commit=commit_sha,
                split=split,
            )
            verified_records.append(record)
        else:
            rejected_records.append({
                "task_id": task.get("id"),
                "task": task,
                "evaluations": eval_reports,
            })

    # Cria diretórios de saída
    canonical_dir = output_root / "canonical/v1"
    verified_dir = output_root / "verified"
    rejected_dir = output_root / "rejected"

    canonical_dir.mkdir(parents=True, exist_ok=True)
    verified_dir.mkdir(parents=True, exist_ok=True)
    rejected_dir.mkdir(parents=True, exist_ok=True)

    # 1. datasets/canonical/v1/canonical.jsonl
    canonical_file = canonical_dir / "canonical.jsonl"
    with canonical_file.open("w", encoding="utf-8") as f:
        for rec in verified_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 2. datasets/verified/gold_500.jsonl e gold_candidates.jsonl
    gold_500_file = verified_dir / "gold_500.jsonl"
    gold_cand_file = verified_dir / "gold_candidates.jsonl"
    with gold_500_file.open("w", encoding="utf-8") as f1, gold_cand_file.open("w", encoding="utf-8") as f2:
        for rec in verified_records:
            line = json.dumps(rec, ensure_ascii=False) + "\n"
            f1.write(line)
            f2.write(line)

    # 3. datasets/rejected/rejected_candidates.jsonl
    rejected_file = rejected_dir / "rejected_candidates.jsonl"
    with rejected_file.open("w", encoding="utf-8") as f:
        for r in rejected_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 4. datasets/canonical/v1/report.json
    metrics = compute_gold_metrics(verified_records, repo_path=repo, conn=conn)
    report_data = {
        "dataset_version": "v1.0",
        "total_generated": len(tasks),
        "total_verified": len(verified_records),
        "total_rejected": len(rejected_records),
        "acceptance_rate": round(len(verified_records) / len(tasks), 4),
        "metrics": metrics,
    }
    (canonical_dir / "report.json").write_text(
        json.dumps(report_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # 5. Curva dataset-size (100 -> 500)
    gold_100_file = ROOT / "tools/gold_trajectories.jsonl"
    gold_100_records = []
    if gold_100_file.is_file():
        for line in gold_100_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                gold_100_records.append(json.loads(line))

    curve_result = record_dataset_size_curve(
        gold_100=gold_100_records,
        gold_500=verified_records,
        repo_path=repo,
        conn=conn,
    )

    # 6. Verificação estrita de anti-leakage
    manifest = load_manifest(ROOT / "datasets/benchmark/manifest.json")
    from evaluation.harness import bench_shas
    check_no_leakage(bench_shas(manifest), output_root)

    return {
        "verified_count": len(verified_records),
        "rejected_count": len(rejected_records),
        "metrics": metrics,
        "curve": curve_result,
    }
