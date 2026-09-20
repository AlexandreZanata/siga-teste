"""Gold agentivo → formato de treino Needle + readiness (H06, docs/19).

Converte o gold do H03 para o formato exato do `needle finetune`
({query, tools, answers[{name, arguments}], reasoning, system}, padrão
P07/`training/export_needle.py`), com split temporal por `holdout_date`
e guarda anti-contaminação (só tasks do artefato congelado; dado
bench-derived nunca avalia o mesmo bench). Prepara o treino — não
treina: sem torch/engine local, pesos ficam pendentes (readiness).
Só stdlib, determinístico.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.mcp_suite_score import load_tasks
from experiments.log import new_run

ROOT = Path(__file__).resolve().parent.parent
GOLD_DEFAULT = ROOT / "eval/mcp_suite/gold/opencode-musespark-20260920.gold.jsonl"
OUT_DEFAULT = ROOT / "datasets/mcp_gold"
SPLIT_CUTOFF = "2020-01-01"
SYSTEM_FACTS = "date: 2026-09-20, locale: pt-BR, repo: SIGA, environment: siga-needle-expert"


def gold_to_needle(record: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    """Um registro gold → um registro de treino (reasoning factual, sem prosa)."""
    method = (record.get("tools") or [""])[0]
    verification = record.get("verification", {})
    answers = record.get("answers", {})
    n_files = len(answers.get("files", []))
    return {
        "query": record.get("query", ""),
        "tools": record.get("tools", []),
        "answers": [{"name": method, "arguments": task.get("args", {})}],
        "reasoning": (
            f"{method} cited {n_files} file(s); "
            f"verifier={verification.get('verdict')} recall={verification.get('recall_at_k')}"
        ),
        "system": SYSTEM_FACTS,
        "source_holdout_id": record.get("source_holdout_id"),
        "difficulty": record.get("difficulty"),
    }


def export_gold(
    gold_records: list[dict[str, Any]],
    tasks: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Converte + separa por data (train < 2020 <= valid); task fora → erro."""
    train: list[dict[str, Any]] = []
    valid: list[dict[str, Any]] = []
    for rec in gold_records:
        base = rec.get("id", "").split(":")[0]
        task = tasks.get(base)
        if task is None:
            raise ValueError(f"gold fora do artefato congelado: {rec.get('id')!r}")
        needle = gold_to_needle(rec, task)
        needle["holdout_date"] = task.get("holdout_date", "")
        (train if needle["holdout_date"] < SPLIT_CUTOFF else valid).append(needle)
    def _sort_key(r: dict[str, Any]) -> tuple[str, str]:
        return (r["query"], r["tools"][0] if r["tools"] else "")

    return {"train": sorted(train, key=_sort_key), "valid": sorted(valid, key=_sort_key)}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def save_splits(splits: dict[str, list[dict[str, Any]]], out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    full = splits["train"] + splits["valid"]
    payloads = {
        "needle_train": splits["train"],
        "needle_val": splits["valid"],
        "needle_full": full,
    }
    hashes = {}
    for name, rows in payloads.items():
        text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        (out_dir / f"{name}.jsonl").write_text(text, encoding="utf-8")
        hashes[name] = _sha(text)
    manifest = {
        "export_version": "v1.0",
        "source": "eval/mcp_suite/gold (H03, suite EVAL-MCP)",
        "format": "cactus-needle-v2",
        "split_cutoff": SPLIT_CUTOFF,
        "train_records": len(splits["train"]),
        "val_records": len(splits["valid"]),
        "total_records": len(full),
        "hashes": hashes,
        "bench_derived": True,
        "note": "bench-derived: treinar aqui e avaliar no mesmo bench é contaminação; avaliar em holdout fresco.",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return manifest


def readiness(manifest: dict[str, Any]) -> dict[str, Any]:
    """Pronto p/ treino? Dados sim; engine não — registrado sem rodeio."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401

        engine = True
    except ImportError:
        engine = False
    return {
        "data_ready": manifest["total_records"] > 0,
        "engine_available": engine,
        "ready": manifest["total_records"] > 0 and engine,
        "blocker": None if engine else "sem torch/transformers local — `needle finetune` pendente; dado pronto e versionado.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=GOLD_DEFAULT)
    parser.add_argument("--out-dir", type=Path, default=OUT_DEFAULT)
    parser.add_argument("--no-save", action="store_true")
    opts = parser.parse_args()
    tasks = load_tasks()
    gold_records = [
        json.loads(line) for line in opts.gold.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    splits = export_gold(gold_records, tasks)
    print(f"gold={len(gold_records)} train={len(splits['train'])} valid={len(splits['valid'])}")
    if opts.no_save:
        return 0
    manifest = save_splits(splits, opts.out_dir)
    ready = readiness(manifest)
    print(f"ready={ready['ready']} blocker={ready['blocker']}")
    report = {
        "suite": "EVAL-MCP/H06",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest": manifest,
        "readiness": ready,
    }
    reports_dir = ROOT / "experiments/reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    record = new_run(
        config={"kind": "h06_readiness", "source": str(opts.gold.relative_to(ROOT))},
        dataset_version="v1.0",
        tool_version="1.0.0",
        index_version="tree-sitter-java-0.23",
        bench_version="v1.0",
        metrics={"n_train": manifest["train_records"], "n_val": manifest["val_records"], "ready": ready["ready"]},
        notes="H06: gold agentivo em formato de treino + readiness (docs/19).",
        siga_root=ROOT.parent,
        work_root=ROOT,
    )
    runs_dir = ROOT / "experiments/runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{record['experiment_id']}.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    report["experiment_id"] = record["experiment_id"]
    (reports_dir / "h06_readiness.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print("report: experiments/reports/h06_readiness.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
