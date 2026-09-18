"""Auditoria final do slice + release local (P11-T02, gate Fase 11).

Validações:
- Scanners de segredo/TODO: limpo aqui, sujo em fixture plantada.
- Tabela das 7 baselines sempre com status explícito (medido/não medido).
- Recomendação go/no-go computada (GO, NO-GO geral, NO-GO controlador).
- Auditoria ponta a ponta em fixture isolada: gates_ok, relatório válido,
  experiment tracking válido, release candidate local sem publicar.
- Restore do índice a partir do zero em repo sintético.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from evaluation.harness import load_manifest
from experiments.log import validate_record
from scripts.final_audit import (
    build_baselines_table,
    decide_go_no_go,
    load_reports,
    run_final_audit,
    scan_secrets,
    scan_todos,
    verify_index_restore,
)

ROOT = Path(__file__).resolve().parent.parent


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, timeout=60)


def _seed_repo(root: Path, payload: str = "ok") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "ServicoExemplo.java").write_text(
        "package br.gov.exemplo;\npublic class ServicoExemplo {\n    public void executar() {}\n}\n",
        encoding="utf-8",
    )
    (root / "nota.txt").write_text(payload, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "seed")
    return root


def test_scanners_clean_here_and_dirty_on_planted_fixture(tmp_path: Path):
    assert scan_secrets(ROOT)["clean"] is True
    assert scan_todos(ROOT)["clean"] is True

    repo = _seed_repo(tmp_path / "dirty", payload="token ghp_ABCDEFGHIJKLMNOP123456\nTODO refatorar tudo\n")
    secrets = scan_secrets(repo)
    assert secrets["clean"] is False
    assert {hit["kind"] for hit in secrets["hits"]} == {"github-token"}
    todos = scan_todos(repo)
    assert todos["clean"] is False
    assert len(todos["hits"]) == 1


def test_baselines_table_always_explicit():
    reports = load_reports(ROOT)
    table = build_baselines_table(reports)
    assert [row["id"] for row in table] == [f"{n}-{s}" for n, s in
        [("1", "large-alone"), ("2", "large-ripgrep"), ("3", "large-rag"), ("4", "large-graph"),
         ("5", "needle-base"), ("6", "needle-tuned"), ("7", "small-coder")]]
    by_id = {row["id"]: row for row in table}
    assert by_id["3-large-rag"]["status"] == "unmeasured"
    assert by_id["7-small-coder"]["status"] == "unmeasured"
    assert by_id["6-needle-tuned"]["status"] == "measured"
    assert by_id["6-needle-tuned"]["metrics"]["task_success_delta_c_vs_a"] >= 0.0


def test_decide_go_no_go_branches():
    def table_with(a: float, b: float, c: float, reduction: float) -> list[dict]:
        def row(i: str, metrics: dict) -> dict:
            return {"id": i, "status": "measured", "metrics": metrics, "source": "t", "note": ""}
        return [
            row("1-large-alone", {"e2e_success": a}),
            row("2-large-ripgrep", {}),
            row("3-large-rag", {}),
            row("4-large-graph", {"e2e_success": b}),
            row("5-needle-base", {}),
            row("6-needle-tuned", {"task_success_rate": c, "three_arm_effective_token_reduction": reduction}),
            row("7-small-coder", {}),
        ]

    assert decide_go_no_go(table_with(0.0, 0.38, 1.0, 0.99))["status"] == "GO condicional"
    assert decide_go_no_go(table_with(0.5, 0.4, 1.0, 0.99))["status"] == "NO-GO geral"
    assert decide_go_no_go(table_with(0.0, 0.9, 0.5, 0.99))["status"] == "NO-GO controlador"
    assert decide_go_no_go(table_with(0.0, 0.38, 0.5, 0.50))["status"] == "INCONCLUSIVO"


def test_index_restore_from_scratch(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    result = verify_index_restore(repo, files=[repo / "ServicoExemplo.java"], anchor="ServicoExemplo")
    assert result["trace_ok"] is True
    assert result["files_indexed"] == 1
    assert result["nodes"] >= 1


def test_final_audit_end_to_end_in_isolated_fixture(tmp_path: Path):
    work = tmp_path / "work"
    (work / "datasets/benchmark").mkdir(parents=True)
    (work / "experiments/reports").mkdir(parents=True)
    shutil.copy(ROOT / "datasets/benchmark/holdout.jsonl", work / "datasets/benchmark/holdout.jsonl")
    shutil.copy(ROOT / "datasets/benchmark/manifest.json", work / "datasets/benchmark/manifest.json")
    for src in (ROOT / "experiments/reports").glob("*.json"):
        shutil.copy(src, work / "experiments/reports" / src.name)
    _git(work, "init", "-q")
    _git(work, "add", ".")
    _git(work, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "fixture")
    repo = _seed_repo(tmp_path / "repo")
    (repo / "ServicoExemplo.java").write_text(
        "package br.gov.exemplo;\npublic class ServicoExemplo {\n    public void executar() {}\n}\n",
        encoding="utf-8",
    )

    import scripts.final_audit as audit

    real_restore = audit.verify_index_restore
    audit.verify_index_restore = lambda r, files=None: real_restore(
        tmp_path / "repo", files=[tmp_path / "repo" / "ServicoExemplo.java"], anchor="ServicoExemplo"
    )
    try:
        report = run_final_audit(work=work, repo=tmp_path / "repo", log_run=True, save=True)
    finally:
        audit.verify_index_restore = real_restore

    assert report["gates_ok"] is True
    assert report["recommendation"]["status"] == "GO condicional"
    assert report["bench_isolation"]["isolated"] is True
    assert report["release_candidate"]["published"] is False
    assert "experiment_id" in report
    assert "report_sha256" in report

    saved = json.loads((work / "experiments/reports/final_audit.json").read_text(encoding="utf-8"))
    assert saved["recommendation"]["status"] == "GO condicional"
    run_file = work / "experiments/runs" / f"{report['experiment_id']}.json"
    validate_record(json.loads(run_file.read_text(encoding="utf-8")))
    manifest = load_manifest(work / "datasets/benchmark/manifest.json")
    assert manifest["version"] == 1
