"""Testes da revalidação do GO com edição real (F20, ADR-030 em DECISIONS.md).

- `select_edit_targets`/`build_simple_patch`: alvos determinísticos e patch
  mínimo JSP-safe (o juiz F11 rejeita `<%`);
- `run_editing_task`/`run_editing_e2e_arm`: e2e locate→context→patch→apply→judge
  em fixture (CI) e clone real (dev); clone real permanece intocado;
- `decide_extended`: veredito GO/NO-GO determinístico (critérios docs/17 +
  gate de edição) e comparação com o ADR-023;
- `run_revalidation`: artefatos com provenance e veredito estável contra os
  relatórios versionados.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from experiments.log import validate_record
from evaluation.go_revalidation import (
    MIN_EDIT_VALID_RATE,
    MIN_TASKS_EDIT,
    RevalidationError,
    build_simple_patch,
    decide_extended,
    load_localization_reference,
    run_editing_e2e_arm,
    run_editing_task,
    run_revalidation,
    select_edit_targets,
)

ROOT = Path(__file__).resolve().parent.parent
SIGA = ROOT.parent
# Espelha os alvos reais do slice: JSP HTML puro, sem `<%` (o juiz F11
# congelado rejeita qualquer `<%` como scriptlet).
JSP = "<!DOCTYPE html>\n<html><body>pagina de teste</body></html>\n"


def _siga_available() -> bool:
    return (SIGA / "sigaex").is_dir()


def _seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "sigaex").mkdir(parents=True)
    for i in range(1, 7):
        (repo / "sigaex" / f"pagina{i}.jsp").write_text(JSP, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "seed"],
        check=True,
    )
    return repo


def test_select_edit_targets_deterministic_and_readable(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    targets = select_edit_targets(repo, limit=10)
    assert [t.name for t in targets] == [f"pagina{i}.jsp" for i in range(1, 7)]
    # Não-decodificável é excluído (alvo inválido), mantendo determinismo.
    (repo / "sigaex" / "binario.jsp").write_bytes(b"\xff\xfe\x00bin")
    targets2 = select_edit_targets(repo, limit=10)
    assert all(t.name != "binario.jsp" for t in targets2)
    # JSP com `<%` é excluído: o juiz F11 congelado sempre rejeita scriptlet.
    (repo / "sigaex" / "aa-scriptlet.jsp").write_text("<%@ page %>\nhtml\n", encoding="utf-8")
    targets3 = select_edit_targets(repo, limit=10)
    assert all(t.name != "aa-scriptlet.jsp" for t in targets3)
    # Caso descoberto na revalidação real (definirMarcador.jsp): original com
    # `javascript:` também é excluído — o texto revisado herdaria o padrão e o
    # juiz rejeitaria; todo o contrato `_UNSAFE_JSP` define a superfície, não
    # só `<%`.
    (repo / "sigaex" / "aa-javascript.jsp").write_text(
        '<button onclick="javascript: document.f.submit()">ok</button>\n', encoding="utf-8"
    )
    targets4 = select_edit_targets(repo, limit=10)
    assert all(t.name != "aa-javascript.jsp" for t in targets4)


def test_build_simple_patch_is_jsp_safe_and_minimal(tmp_path: Path):
    patch = build_simple_patch("sigaex/pagina1.jsp", JSP)
    assert "<%--" not in patch and patch.count("<%") == JSP.count("<%")  # não introduz scriptlet
    workspace = tmp_path / "ws"
    (workspace / "sigaex").mkdir(parents=True)
    (workspace / "sigaex" / "pagina1.jsp").write_text(JSP, encoding="utf-8")
    from evaluation.editing import apply_unified_patch

    result = apply_unified_patch(workspace, patch)
    assert result["changed_lines"] > 0 and result["before_sha256"] != result["after_sha256"]
    revised = (workspace / "sigaex" / "pagina1.jsp").read_text(encoding="utf-8")
    assert revised == "<!-- revisao e2e F20: alvo de auditoria de edicao real -->\n" + JSP
    from evaluation.rewrite_judge import judge_rewrite

    verdict = judge_rewrite("sigaex/pagina1.jsp", JSP, revised)
    assert verdict["verdict"] == "PASS", verdict


def test_run_editing_task_e2e_on_fixture(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    with_source = repo / "sigaex" / "pagina1.jsp"
    before = with_source.read_bytes()
    task = run_editing_task(repo, tmp_path / "ws", with_source, "revisar pagina1")
    assert task["patch_applied"] is True
    assert task["judge_verdict"] == "PASS"
    assert task["out_of_scope_edit"] is False
    assert with_source.read_bytes() == before  # clone real intocado


def test_run_editing_e2e_arm_fixture_full_cycle(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    arm = run_editing_e2e_arm(repo, limit=6)
    assert arm["total_tasks"] == 6
    assert arm["judge_pass"] == 6
    assert arm["judge_pass_rate"] == 1.0
    assert arm["out_of_scope_edits"] == 0
    for i in range(1, 7):
        assert (repo / "sigaex" / f"pagina{i}.jsp").read_text(encoding="utf-8") == JSP


def test_run_editing_e2e_arm_requires_minimum_tasks(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "sigaex").mkdir(parents=True)
    (repo / "sigaex" / "unico.jsp").write_text(JSP, encoding="utf-8")
    with pytest.raises(RevalidationError, match="insuficientes"):
        run_editing_e2e_arm(repo, limit=10)


def test_decide_extended_go_and_no_go_paths():
    localization = load_localization_reference()
    good_editing = {
        "total_tasks": 6,
        "judge_pass": 6,
        "judge_pass_rate": 1.0,
        "out_of_scope_edits": 0,
        "latency_p50_ms": 5.0,
    }
    decision = decide_extended(localization, good_editing)
    assert decision["verdict"] == "GO"
    assert decision["original_criteria"]["pass"] is True
    assert decision["editing_gate"]["pass"] is True
    assert "fecha a ressalva" in decision["delta_vs_adr023"]

    weak_editing = {
        "total_tasks": 6,
        "judge_pass": 2,
        "judge_pass_rate": 2 / 6,
        "out_of_scope_edits": 0,
        "latency_p50_ms": 5.0,
    }
    assert decide_extended(localization, weak_editing)["verdict"] == "NO-GO"
    assert decide_extended(localization, weak_editing)["editing_gate"]["observed_valid_rate"] < MIN_EDIT_VALID_RATE

    few_tasks = {**good_editing, "total_tasks": MIN_TASKS_EDIT - 1, "judge_pass": MIN_TASKS_EDIT - 1, "judge_pass_rate": 1.0}
    assert decide_extended(localization, few_tasks)["verdict"] == "NO-GO"

    strayed = {**good_editing, "out_of_scope_edits": 1}
    assert decide_extended(localization, strayed)["verdict"] == "NO-GO"


def test_load_localization_reference_contract():
    localization = load_localization_reference()
    comparison = localization["comparison"]
    assert comparison["task_success_delta_c_vs_a"] > 0
    assert comparison["effective_token_reduction_c_vs_raw"] > 0.90
    assert comparison["task_success_delta_c_vs_b"] > 0
    assert localization["source"] == "integration_three_arms.json"


def test_run_revalidation_real_clone_and_report(tmp_path: Path):
    if _siga_available():
        repo = SIGA
    else:
        repo = _seed_repo(tmp_path / "clone")
    report = run_revalidation(repo, edit_limit=6, save_report=False, log_run=False)
    assert report["clone_untouched_verified"] is True
    assert report["decision"]["verdict"] == "GO"
    assert report["editing_e2e"]["judge_pass_rate"] >= MIN_EDIT_VALID_RATE
    if _siga_available():
        status = subprocess.run(
            ["git", "-C", str(SIGA), "status", "--short"], capture_output=True, text=True, check=True
        )
        modified = [line for line in status.stdout.splitlines() if not line.startswith("??")]
        assert modified == [], f"clone real do SIGA foi modificado pela auditoria! {modified}"


def test_run_revalidation_persists_valid_run(tmp_path: Path):
    if _siga_available():
        repo = SIGA
    else:
        repo = _seed_repo(tmp_path / "clone")
    report = run_revalidation(repo, edit_limit=6, save_report=False, log_run=True, now="2026-09-19T16:00:00+00:00")
    run_path = ROOT / "experiments/runs" / f"{report['experiment_id']}.json"
    assert run_path.is_file()
    on_disk = json.loads(run_path.read_text(encoding="utf-8"))
    validate_record(on_disk)
    assert on_disk["metrics"]["verdict"] == "GO"
    run_path.unlink()  # run e2e de teste não polui o histórico versionado
