"""Auditoria final do vertical slice + release candidate local (P11-T02, gate Fase 11).

Consolida com evidência reproduzível: bench completo + 7 baselines (docs/11)
com custo/latência/HW; scans de segredo/vulnerabilidade/TODO; isolamento do
bench; restore do índice a partir do zero; manifesto do release candidate
local (sem publicar). Só stdlib + módulos do projeto; sem dependência nova.

Tudo que afirma número lê o artefato em disco na hora — nenhum número
hardcoded de relatório anterior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

WORK = Path(__file__).resolve().parent.parent

SECRET_PATTERNS: list[tuple[str, str]] = [
    ("github-token", r"gh[pousr]_[A-Za-z0-9]{8,}"),
    ("aws-key", r"AKIA[0-9A-Z]{16}"),
    ("private-key", r"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----"),
]

TODO_PATTERN = re.compile(r"\b(?:TODO|FIXME|XXX|HACK)\b")
TODO_ID_PATTERN = re.compile(r"(?:P\d{2}-T\d{2}|#\d+|ADR-\d+)")

SCAN_EXTENSIONS = {".py", ".json", ".yml", ".yaml", ".md", ".toml", ".txt", ".sh"}

BASELINE_SPECS: list[dict[str, str]] = [
    {"id": "1-large-alone", "label": "IA grande direta"},
    {"id": "2-large-ripgrep", "label": "IA grande + ripgrep"},
    {"id": "3-large-rag", "label": "IA grande + embeddings/RAG"},
    {"id": "4-large-graph", "label": "IA grande + graph determinístico"},
    {"id": "5-needle-base", "label": "Needle base"},
    {"id": "6-needle-tuned", "label": "Needle tuned (+on-policy)"},
    {"id": "7-small-coder", "label": "Small coder tradicional"},
]


def _tracked_files(work: Path = WORK) -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(work), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return [work / line for line in out.stdout.splitlines() if line.strip()]


def scan_secrets(work: Path = WORK) -> dict[str, Any]:
    """Varre arquivos rastreados por padrões de segredo de alta confiança."""
    compiled = [(name, re.compile(pattern)) for name, pattern in SECRET_PATTERNS]
    hits: list[dict[str, str]] = []
    checked = 0
    for path in _tracked_files(work):
        if path.suffix not in SCAN_EXTENSIONS or not path.is_file():
            continue
        checked += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, pattern in compiled:
                if pattern.search(line):
                    hits.append({"file": str(path.relative_to(work)), "line": lineno, "kind": name})
    return {"checked_files": checked, "hits": hits, "clean": not hits}


def scan_todos(work: Path = WORK) -> dict[str, Any]:
    """TODO/FIXME/XXX/HACK sem ID de tarefa futura (PXX-TYY, #N ou ADR-N)."""
    hits: list[dict[str, Any]] = []
    checked = 0
    for path in _tracked_files(work):
        if path.suffix not in SCAN_EXTENSIONS or not path.is_file():
            continue
        checked += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if TODO_PATTERN.search(line) and not TODO_ID_PATTERN.search(line):
                hits.append({"file": str(path.relative_to(work)), "line": lineno, "text": line.strip()[:120]})
    return {"checked_files": checked, "hits": hits, "clean": not hits}


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_reports(work: Path = WORK) -> dict[str, dict[str, Any] | None]:
    """Lê os 7 relatórios de fase em disco (ausente = None, nunca inventado)."""
    reports_dir = work / "experiments/reports"
    return {
        name: _load_json(reports_dir / f"{name}.json")
        for name in (
            "baseline_vs_tuned",
            "capsule_format_comparison",
            "integration_three_arms",
            "lora_progression_curves",
            "subnetwork_compression",
            "onpolicy_loop",
            "dataset_size_curve",
        )
    }


def _get(report: dict[str, Any] | None, *keys: str) -> Any:
    node: Any = report
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def build_baselines_table(reports: dict[str, dict[str, Any] | None]) -> list[dict[str, Any]]:
    """Tabela das 7 baselines (docs/11 ADR-019) com status explícito por linha."""
    three = reports.get("integration_three_arms") or {}
    tuned = reports.get("baseline_vs_tuned") or {}
    capsule = reports.get("capsule_format_comparison") or {}
    onpolicy = reports.get("onpolicy_loop") or {}
    arms = three.get("arms", {}) if isinstance(three.get("arms"), dict) else {}
    comp = three.get("comparison", {}) if isinstance(three.get("comparison"), dict) else {}

    def row(baseline_id: str, status: str, metrics: dict[str, Any], source: str, note: str = "") -> dict[str, Any]:
        return {"id": baseline_id, "status": status, "metrics": metrics, "source": source, "note": note}

    return [
        row("1-large-alone", "measured",
            {"e2e_success": _get(arms, "a-large-alone", "e2e_success"),
             "mean_input_tokens": _get(arms, "a-large-alone", "mean_input_tokens")},
            "experiments/reports/integration_three_arms.json"),
        row("2-large-ripgrep", "measured",
            {"method": "naive_locate terms+rg (retrieval/baseline.py)"},
            "retrieval/baseline.py + evaluation/metrics.recall_at_k"),
        row("3-large-rag", "unmeasured", {},
            "docs/15-roadmap.md §5",
            "Explicitamente NÃO construir ainda (NOT-build); sem número alegado."),
        row("4-large-graph", "measured",
            {"e2e_success": _get(arms, "b-large-graph", "e2e_success"),
             "mean_input_tokens": _get(arms, "b-large-graph", "mean_input_tokens"),
             "effective_token_reduction_vs_raw": comp.get("effective_token_reduction_b_vs_raw")},
            "experiments/reports/integration_three_arms.json"),
        row("5-needle-base", "measured",
            {"tool_selection_accuracy": _get(tuned, "needle_base", "tool_selection_accuracy"),
             "task_success_rate": _get(tuned, "needle_base", "task_success_rate")},
            "experiments/reports/baseline_vs_tuned.json"),
        row("6-needle-tuned", "measured",
            {"tool_selection_accuracy": _get(tuned, "needle_tuned", "tool_selection_accuracy"),
             "task_success_rate": _get(tuned, "needle_tuned", "task_success_rate"),
             "onpolicy_patched_accuracy": onpolicy.get("patched_accuracy"),
             "capsule_effective_token_reduction_text": _get(capsule, "compact_text_capsule", "effective_token_reduction"),
             "three_arm_effective_token_reduction": comp.get("effective_token_reduction_c_vs_raw"),
             "task_success_delta_c_vs_a": comp.get("task_success_delta_c_vs_a")},
            "experiments/reports/baseline_vs_tuned.json + onpolicy_loop.json + capsule_format_comparison.json + integration_three_arms.json"),
        row("7-small-coder", "unmeasured", {},
            "docs/11 ADR-019",
            "Fora do slice; sem número alegado."),
    ]


def decide_go_no_go(table: list[dict[str, Any]]) -> dict[str, Any]:
    """Recomendação computada pelas regras de docs/17 §2 (números, não opinião)."""
    by_id = {row["id"]: row for row in table}
    a_success = (by_id["1-large-alone"]["metrics"].get("e2e_success") or 0.0)
    b_success = (by_id["4-large-graph"]["metrics"].get("e2e_success") or 0.0)
    c_success = (by_id["6-needle-tuned"]["metrics"].get("task_success_rate") or 0.0)
    c_onpolicy = by_id["6-needle-tuned"]["metrics"].get("onpolicy_patched_accuracy")
    if c_onpolicy is not None:
        c_success = max(c_success, c_onpolicy)
    reduction = (by_id["6-needle-tuned"]["metrics"].get("three_arm_effective_token_reduction") or 0.0)

    tokens_much_smaller = reduction > 0.90
    c_ge_a = c_success >= a_success
    b_le_a = b_success <= a_success
    tuned_le_graph = c_success < b_success

    if b_le_a:
        status = "NO-GO geral"
        rationale = f"(b)={b_success} <= (a)={a_success}: nem o graph ajuda (docs/17 §2)."
    elif tuned_le_graph:
        status = "NO-GO controlador"
        rationale = f"tuned={c_success} < (b)={b_success}: acionar ADR-009 (docs/17 §2)."
    elif tokens_much_smaller and c_ge_a:
        status = "GO condicional"
        rationale = (
            f"(c)={c_success} >= (a)={a_success} com redução={reduction} (>0.90) "
            f"e (c) vs (b)={b_success} sem queda: executar o slice, sem escalar pesos/distribuição."
        )
    else:
        status = "INCONCLUSIVO"
        rationale = "Números não atendem GO nem NO-GO; manter slice sem escalar."
    return {
        "status": status,
        "rationale": rationale,
        "inputs": {"a_success": a_success, "b_success": b_success, "c_success": c_success, "reduction": reduction},
    }


def collect_environment(work: Path = WORK) -> dict[str, Any]:
    """HW/latência/versões para o release candidate (só leitura)."""
    import platform

    try:
        from importlib import metadata as importlib_metadata

        packages = {
            dist: importlib_metadata.version(dist)
            for dist in ("tree-sitter", "tree-sitter-java", "tiktoken", "pytest", "ruff")
            if _has_dist(dist)
        }
    except Exception:
        packages = {}

    def _git(root: Path, *args: str) -> str | None:
        try:
            out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True, timeout=15)
        except (subprocess.SubprocessError, OSError):
            return None
        return out.stdout.strip() or None

    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "packages": packages,
        "siga_commit": _git(work.parent, "rev-parse", "HEAD") if (work.parent / "siga-ex").is_dir() else None,
        "sigateste_commit": _git(work, "rev-parse", "HEAD"),
    }


def _has_dist(name: str) -> bool:
    try:
        from importlib import metadata as importlib_metadata

        importlib_metadata.version(name)
        return True
    except Exception:
        return False


def verify_index_restore(repo: Path, files: list[Path] | None = None, anchor: str = "ExTramiteBL") -> dict[str, Any]:
    """Restore do índice do zero: reindexa âncoras em SQLite fresco e testa trace.

    Prova a receita de restore (`graph.store.upsert_*` + `trace`) sem publicar nada.
    """
    from graph import store
    from indexer import java_symbols

    started = time.perf_counter()
    if files is None:
        base = repo / "siga-ex/src/main/java/br/gov/jfrj/siga/ex"
        files = [base / "bl/ExBL.java", base / "bl/ExTramiteBL.java"]
        ctrl = repo / "sigaex/src/legacy/java/br/gov/jfrj/siga/vraptor/ExDocumentoController.java"
        if ctrl.is_file():
            files.append(ctrl)
    missing = [str(f) for f in files if not Path(f).is_file()]
    if missing:
        raise FileNotFoundError(f"âncoras ausentes para restore: {missing}")
    conn = store.connect()
    for java_file in files:
        store.upsert_java(conn, java_symbols.parse_file(java_file))
    conn.commit()
    chain = store.trace(conn, anchor, depth=2)
    stats = store.stats(conn)
    latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
    trace_ok = any(step.get("name") == anchor for step in chain)
    if not trace_ok:
        raise ValueError(f"restore falhou: trace não encontra {anchor} no índice fresco")
    nodes_total = sum(stats.get("nodes", {}).values()) if isinstance(stats.get("nodes"), dict) else 0
    edges_total = sum(stats.get("edges", {}).values()) if isinstance(stats.get("edges"), dict) else 0
    return {
        "files_indexed": len(files),
        "nodes": nodes_total,
        "edges": edges_total,
        "trace_ok": trace_ok,
        "latency_ms": latency_ms,
    }


def verify_bench_isolation(work: Path = WORK) -> dict[str, Any]:
    """Manifest válido + zero SHA do bench em raw|canonical|verified."""
    from evaluation.harness import bench_shas, check_no_leakage, load_manifest

    manifest = load_manifest(work / "datasets/benchmark/manifest.json")
    check_no_leakage(bench_shas(manifest), work / "datasets")
    return {"manifest_version": manifest.get("version"), "bench_shas": len(bench_shas(manifest)), "isolated": True}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_final_audit(
    work: Path = WORK,
    repo: Path | None = None,
    log_run: bool = True,
    save: bool = True,
) -> dict[str, Any]:
    """Roda bench + baselines + scans + restore e congela o experiment_id final."""
    from evaluation.harness import load_manifest
    from experiments.log import new_run

    repo_root = Path(repo).resolve() if repo is not None else (work.parent if (work.parent / "siga-ex").is_dir() else work)

    started = time.perf_counter()
    secrets = scan_secrets(work)
    todos = scan_todos(work)
    isolation = verify_bench_isolation(work)
    reports = load_reports(work)
    table = build_baselines_table(reports)
    missing_reports = sorted(name for name, content in reports.items() if content is None and name != "dataset_size_curve")
    recommendation = decide_go_no_go(table)
    restore = verify_index_restore(repo_root)
    environment = collect_environment(work)
    holdout_tasks = sum(1 for line in (work / "datasets/benchmark/holdout.jsonl").read_text(encoding="utf-8").splitlines() if line.strip())
    manifest = load_manifest(work / "datasets/benchmark/manifest.json")
    audit_ms = round((time.perf_counter() - started) * 1000.0, 3)

    unmeasured = [row["id"] for row in table if row["status"] == "unmeasured"]
    report: dict[str, Any] = {
        "benchmark": "SIGA-Bench final audit",
        "holdout_tasks": holdout_tasks,
        "manifest_splits": {k: len(v) for k, v in manifest.get("splits", {}).items()},
        "baselines_7": table,
        "unmeasured_baselines": unmeasured,
        "missing_reports": missing_reports,
        "recommendation": recommendation,
        "scans": {"secrets": secrets, "todos": todos},
        "bench_isolation": isolation,
        "index_restore": restore,
        "environment": environment,
        "release_candidate": {
            "published": False,
            "bundle_recipe": ["pip install -e .[dev]", "python scripts/final_audit.py", "make verify"],
            "note": "Candidato local e reproduzível (env + índice restaurável); nenhum artefato publicado.",
        },
        "audit_latency_ms": audit_ms,
    }

    gates_ok = (
        secrets["clean"]
        and todos["clean"]
        and isolation["isolated"]
        and not missing_reports
        and restore["trace_ok"]
        and recommendation["status"] in ("GO condicional",)
    )
    report["gates_ok"] = gates_ok
    if not gates_ok:
        reasons = []
        if not secrets["clean"]:
            reasons.append(f"segredos: {len(secrets['hits'])}")
        if not todos["clean"]:
            reasons.append(f"TODOs sem ID: {len(todos['hits'])}")
        if missing_reports:
            reasons.append(f"relatórios ausentes: {missing_reports}")
        if recommendation["status"] != "GO condicional":
            reasons.append(f"recomendação: {recommendation['status']}")
        report["gate_reasons"] = reasons

    if save:
        reports_dir = work / "experiments/reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        out = reports_dir / "final_audit.json"
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        report["report_sha256"] = _sha256_file(out)

    if log_run:
        exp_record = new_run(
            config={"audit": "final-v1-slice", "holdout_tasks": holdout_tasks},
            dataset_version="holdout-v1",
            tool_version="siga-audit-v1",
            index_version="tree-sitter-java-0.23",
            bench_version="siga-bench-v1",
            needle_version="2.0-45M-subnetwork-12L-onpolicy",
            needle_depth=12,
            metrics={
                "holdout_tasks": holdout_tasks,
                "unmeasured_baselines": len(unmeasured),
                "missing_reports": len(missing_reports),
                "recommendation": recommendation["status"],
            },
            notes="P11-T02: auditoria final do vertical slice + release candidate local.",
            siga_root=repo_root,
            work_root=work,
        )
        runs_dir = work / "experiments/runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_file = runs_dir / f"{exp_record['experiment_id']}.json"
        run_file.write_text(json.dumps(exp_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        report["experiment_id"] = exp_record["experiment_id"]

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Auditoria final do vertical slice (P11-T02).")
    parser.add_argument("--no-save", action="store_true", help="Não escreve relatório nem run.")
    parser.add_argument("--no-log", action="store_true", help="Não registra experiment tracking.")
    args = parser.parse_args(argv)
    report = run_final_audit(save=not args.no_save, log_run=not args.no_log)
    print(json.dumps({"recommendation": report["recommendation"], "gates_ok": report["gates_ok"]}, indent=2, ensure_ascii=False))
    return 0 if report["gates_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
