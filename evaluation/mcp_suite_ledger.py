"""Planilha-livro de runs da suite EVAL-MCP (G04, docs/18 §5).

Mantém `eval/mcp_suite/replication.csv` — o índice de replicação multi-
modelo/IDE — sincronizado deterministicamente com os runs reais
(`eval/mcp_suite/runs/<modelo>-<ide>-<data>.jsonl`):

- `ledger_row` deriva as métricas da linha do próprio run via
  `score_run_file` (mesmo veredito do scorer G02 — nunca redigido à mão);
- `update_ledger` é **idempotente**: a chave `(modelo, ide, braco, run_file)`
  substitui a linha anterior; linhas ficam em ordem determinística;
- CSV com cabeçalho canônico fixo (`HEADER`); arquivo inexistente é criado
  com o cabeçalho; header divergente aborta (nunca corrompe a planilha).

CLI: `python -m evaluation.mcp_suite_ledger --runs <arquivo.jsonl>
--modelo X --ide Y [--data AAAAMMDD] [--notas "..."] [--csv caminho]`.
Determinístico, só stdlib; run fora do artefato congelado aborta no scorer.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluation.mcp_suite_score import score_run_file  # noqa: E402

LEDGER = ROOT / "eval/mcp_suite/replication.csv"

HEADER = [
    "modelo",
    "ide",
    "braco",
    "data",
    "run_file",
    "n_tasks",
    "n_exact",
    "n_partial",
    "n_fail",
    "task_success",
    "mean_recall_at_k",
    "mean_hallucination_rate",
    "tokens_proxy_total",
    "p50_ms",
    "p95_ms",
    "mean_mcp_calls",
    "generated_at",
    "notas",
]
KEY = ("modelo", "ide", "braco", "run_file")


def read_ledger(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != HEADER:
            raise SystemExit(f"cabeçalho inesperado em {path}: {reader.fieldnames}")
        return list(reader)


def write_ledger(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)


def _date_from(path: Path, explicit: str | None) -> str:
    if explicit:
        if not re.fullmatch(r"\d{8}", explicit):
            raise SystemExit(f"--data deve ser AAAAMMDD: {explicit!r}")
        return explicit
    m = re.search(r"-(\d{8})\.jsonl$", path.name)
    return m.group(1) if m else ""


def ledger_row(
    run_path: Path,
    tasks_path: Path,
    modelo: str,
    ide: str,
    data: str | None = None,
    notas: str = "",
    now: str | None = None,
) -> list[dict[str, str]]:
    """Uma linha por braço presente no run, com métricas derivadas do scorer."""
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    by_id = {t["id"]: t for t in tasks["tasks"]}
    report = score_run_file(run_path, by_id)
    stamp = now or datetime.now(timezone.utc).isoformat()
    day = _date_from(run_path, data)
    rows: list[dict[str, str]] = []
    for arm in ("A", "B"):
        agg = report["aggregate"][arm]
        if not agg.get("n_tasks"):
            continue
        latency = agg.get("latency") or {}
        rows.append(
            {
                "modelo": modelo,
                "ide": ide,
                "braco": arm,
                "data": day,
                "run_file": str(run_path),
                "n_tasks": str(agg["n_tasks"]),
                "n_exact": str(agg["n_exact"]),
                "n_partial": str(agg["n_partial"]),
                "n_fail": str(agg["n_fail"]),
                "task_success": str(agg["task_success"]),
                "mean_recall_at_k": "" if agg["mean_recall_at_k"] is None else str(agg["mean_recall_at_k"]),
                "mean_hallucination_rate": str(agg["mean_hallucination_rate"]),
                "tokens_proxy_total": str(agg["tokens_proxy_total"]),
                "p50_ms": "" if not latency else str(latency["p50_ms"]),
                "p95_ms": "" if not latency else str(latency["p95_ms"]),
                "mean_mcp_calls": str(agg["mean_mcp_calls"]),
                "generated_at": stamp,
                "notas": notas,
            }
        )
    if not rows:
        raise SystemExit(f"run sem nenhuma linha de braço pontuável: {run_path}")
    return rows


def update_ledger(existing: list[dict[str, str]], new_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Substitui pela KEY e ordena deterministicamente (modelo, ide, braco, run_file, data)."""
    merged = {(r["modelo"], r["ide"], r["braco"], r["run_file"]): r for r in existing}
    for row in new_rows:
        merged[(row["modelo"], row["ide"], row["braco"], row["run_file"])] = row
    return sorted(merged.values(), key=lambda r: (r["modelo"], r["ide"], r["braco"], r["run_file"], r["data"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True, help="arquivo de run (JSONL) a lançar na planilha")
    parser.add_argument("--modelo", required=True)
    parser.add_argument("--ide", required=True)
    parser.add_argument("--data", help="AAAAMMDD (default: sufixo do nome do arquivo)")
    parser.add_argument("--notas", default="")
    parser.add_argument("--csv", type=Path, default=LEDGER, help="planilha (default: eval/mcp_suite/replication.csv)")
    parser.add_argument("--tasks", type=Path, default=ROOT / "eval/mcp_suite/tasks.jsonl")
    parser.add_argument("--dry-run", action="store_true", help="mostra as linhas e não grava")
    opts = parser.parse_args()
    if not opts.runs.is_file():
        raise SystemExit(f"run inexistente: {opts.runs}")
    new_rows = ledger_row(
        opts.runs,
        opts.tasks,
        modelo=opts.modelo,
        ide=opts.ide,
        data=opts.data,
        notas=opts.notas,
    )
    existing = read_ledger(opts.csv)
    merged = update_ledger(existing, new_rows)
    for row in new_rows:
        print(json.dumps(row, ensure_ascii=False))
    if opts.dry_run:
        print("dry-run: nada gravado")
        return 0
    write_ledger(opts.csv, merged)
    print(f"planilha: {opts.csv} ({len(merged)} linhas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
