"""Medição H04: full vs referencial nos 10 anchors do contexto (docs/19).

Âncoras vêm dos prompts (sem GT): compara `token_estimate` dos dois
modos no clone real e publica a economia. Só stdlib + repo, offline.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from experiments.log import new_run
from tools.siga_context import siga_context

ROOT = Path(__file__).resolve().parent.parent

ANCHORS = [
    "ExMobilVO",
    "ExCompetenciaBL",
    "ExTipoDeVinculo",
    "ExSpringDocumentoController",
    "DocumentosSiglaDossieGet",
    "ModelosIdLotacoesIdLotacaoPreenchimentosGet",
    "ExNotificar",
    "AdModelo",
    "ExBL",
    "DownloadJwtFilenameGet",
]


def measure(repo: str | Path | None = None) -> dict[str, Any]:
    rows = []
    for anchor in ANCHORS:
        full = siga_context([anchor], f"medicao H04 {anchor}", repo=repo, mode="full")
        ref = siga_context([anchor], f"medicao H04 {anchor}", repo=repo, mode="referential")
        rows.append(
            {
                "anchor": anchor,
                "n_refs": len(ref["refs"]),
                "full_tokens": full["token_estimate"],
                "ref_tokens": ref["token_estimate"],
                "reduction": round(1.0 - ref["token_estimate"] / full["token_estimate"], 3)
                if full["token_estimate"]
                else None,
            }
        )
    compared = [r for r in rows if r["reduction"] is not None]
    return {
        "suite": "EVAL-MCP/H04",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
        "summary": {
            "n_anchors": len(rows),
            "n_resolved": sum(1 for r in rows if r["n_refs"] > 0),
            "mean_reduction": round(sum(r["reduction"] for r in compared) / len(compared), 3)
            if compared
            else None,
            "total_full_tokens": sum(r["full_tokens"] for r in rows),
            "total_ref_tokens": sum(r["ref_tokens"] for r in rows),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-save", action="store_true")
    opts = parser.parse_args()
    report = measure()
    s = report["summary"]
    print(f"anchors={s['n_anchors']} resolved={s['n_resolved']} "
          f"full={s['total_full_tokens']} ref={s['total_ref_tokens']} mean_reduction={s['mean_reduction']}")
    if not opts.no_save:
        reports_dir = ROOT / "experiments/reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        out = reports_dir / "h04_capsule.json"
        record = new_run(
            config={"kind": "h04_capsule", "anchors": ANCHORS},
            dataset_version="v1.0",
            tool_version="1.0.0",
            index_version="tree-sitter-java-0.23",
            bench_version="v1.0",
            metrics=s,
            notes="H04: full vs referencial nos anchors do contexto (docs/19).",
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
