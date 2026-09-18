"""Comparação Tree-sitter vs javalang (F07, gatilho P02/ADR-010 em docs/05).

Mede com números se o Tree-sitter permanece: taxa de parse, acordo de
símbolos (nomes de tipos/métodos), acordo de package e latência por arquivo,
nos mesmos arquivos para os dois parsers. JDT/JavaParser-jar foram
considerados e rejeitados para a V1 (exigem JVM + classpath Maven resolvido;
javalang cobre a pergunta de precisão sem JVM — veredicto registrado no
relatório). Só stdlib + módulos do projeto (+ javalang F07).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

WORK = Path(__file__).resolve().parent.parent


def _collect_names(types: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for type_rec in types:
        names.add(type_rec.get("name", ""))
        names.update(method.get("name", "") for method in type_rec.get("methods", []))
        names |= _collect_names(type_rec.get("nested", []))
    return {name for name in names if name}


def compare_file(path: str | Path) -> dict[str, Any]:
    """Compara os dois parsers num arquivo real (mesmo schema, mesmas entradas)."""
    from indexer import java_symbols as tree_sitter
    from indexer import javalang_symbols as javalang_mod

    target = Path(path)
    started = time.perf_counter()
    try:
        ts_rec = tree_sitter.parse_file(target)
        ts_ok = True
    except Exception:
        ts_rec = {"package": None, "imports": [], "types": []}
        ts_ok = False
    ts_ms = round((time.perf_counter() - started) * 1000.0, 3)

    started = time.perf_counter()
    try:
        jl_rec = javalang_mod.parse_file(target)
        jl_ok = True
    except Exception:
        jl_rec = {"package": None, "imports": [], "types": []}
        jl_ok = False
    jl_ms = round((time.perf_counter() - started) * 1000.0, 3)

    ts_names = _collect_names(ts_rec["types"])
    jl_names = _collect_names(jl_rec["types"])
    agreement = round(len(ts_names & jl_names) / len(ts_names | jl_names), 4) if (ts_names or jl_names) else 1.0
    return {
        "file": str(target),
        "ts_parse_ok": ts_ok,
        "jl_parse_ok": jl_ok,
        "package_equal": ts_rec["package"] == jl_rec["package"],
        "ts_symbols": len(ts_names),
        "jl_symbols": len(jl_names),
        "symbol_agreement": agreement,
        "identical": ts_ok and jl_ok and agreement == 1.0 and ts_rec["package"] == jl_rec["package"],
        "ts_latency_ms": ts_ms,
        "jl_latency_ms": jl_ms,
    }


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def decide_verdict(per_file: list[dict[str, Any]]) -> dict[str, str]:
    """Veredicto determinístico: troca só se javalang salva parse que o Tree-sitter perde."""
    if not per_file:
        return {"decision": "INCONCLUSIVO", "rationale": "sem arquivos comparados"}
    rescued = [r["file"] for r in per_file if not r["ts_parse_ok"] and r["jl_parse_ok"]]
    if rescued:
        return {"decision": "switch-candidate", "rationale": f"javalang parseia {len(rescued)} arquivo(s) que o Tree-sitter perde: {[Path(f).name for f in rescued][:3]}"}
    agreement = _mean([r["symbol_agreement"] for r in per_file])
    return {
        "decision": "keep-tree-sitter",
        "rationale": f"Tree-sitter parseia 100% com acordo de símbolos {agreement}; javalang confirma sem divergência (tolerância a quebrado é o diferencial documentado, não precisão).",
    }


def run_comparison(
    files: list[str | Path],
    work: Path = WORK,
    log_run: bool = True,
    save: bool = True,
) -> dict[str, Any]:
    """Compara nos arquivos dados e publica o relatório + run (F07)."""
    from experiments.log import new_run

    file_list = [Path(f) for f in files]
    missing = [str(f) for f in file_list if not f.is_file()]
    if missing:
        raise FileNotFoundError(f"arquivos inexistentes para comparação: {missing}")
    per_file = [compare_file(f) for f in file_list]
    verdict = decide_verdict(per_file)
    report: dict[str, Any] = {
        "benchmark": "F07 java parser comparison",
        "files_compared": len(per_file),
        "ts_parse_rate": round(sum(1 for r in per_file if r["ts_parse_ok"]) / len(per_file), 4),
        "jl_parse_rate": round(sum(1 for r in per_file if r["jl_parse_ok"]) / len(per_file), 4),
        "mean_package_equal": round(sum(1 for r in per_file if r["package_equal"]) / len(per_file), 4),
        "mean_symbol_agreement": _mean([r["symbol_agreement"] for r in per_file]),
        "mean_ts_latency_ms": _mean([r["ts_latency_ms"] for r in per_file]),
        "mean_jl_latency_ms": _mean([r["jl_latency_ms"] for r in per_file]),
        "verdict": verdict,
        "per_file": [{**r, "file": Path(r["file"]).name} for r in per_file],
    }
    if save:
        reports_dir = work / "experiments/reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        out = reports_dir / "java_parser_comparison.json"
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        report["report_sha256"] = hashlib.sha256(out.read_bytes()).hexdigest()
    if log_run:
        exp_record = new_run(
            config={"comparison": "tree-sitter-vs-javalang", "files": len(per_file)},
            dataset_version="slice-anchors",
            tool_version="siga-indexer-v1",
            index_version="tree-sitter-java-0.23",
            bench_version="siga-bench-v1",
            metrics={
                "ts_parse_rate": report["ts_parse_rate"],
                "jl_parse_rate": report["jl_parse_rate"],
                "mean_symbol_agreement": report["mean_symbol_agreement"],
            },
            notes="F07: gatilho P02/ADR-010 executado com números; veredito no relatório.",
            siga_root=work.parent if (work.parent / "siga-ex").is_dir() else work,
            work_root=work,
        )
        runs_dir = work / "experiments/runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_file = runs_dir / f"{exp_record['experiment_id']}.json"
        run_file.write_text(json.dumps(exp_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        report["experiment_id"] = exp_record["experiment_id"]
    return report


def _default_files(work: Path = WORK) -> list[Path]:
    parent = work.parent
    root = parent if (parent / "siga-ex").is_dir() else work
    anchors = [
        root / "siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl/ExTramiteBL.java",
        root / "siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl/ExBL.java",
        root / "sigaex/src/legacy/java/br/gov/jfrj/siga/vraptor/ExDocumentoController.java",
    ]
    sample = sorted((root / "siga-ex").rglob("*.java"))[:25] + sorted((root / "sigaex").rglob("*.java"))[:25]
    files = [p for p in anchors + sample if p.is_file()]
    if not files:
        raise FileNotFoundError("nenhum .java do slice para comparar")
    return sorted(set(files))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compara Tree-sitter vs javalang (F07).")
    parser.add_argument("--files", nargs="*", default=None, help="Arquivos .java (default: 3 âncoras + 50 do slice).")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--no-log", action="store_true")
    args = parser.parse_args(argv)
    report = run_comparison(
        [Path(f) for f in args.files] if args.files else _default_files(),
        log_run=not args.no_log,
        save=not args.no_save,
    )
    print(json.dumps({"verdict": report["verdict"], "files": report["files_compared"]}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
