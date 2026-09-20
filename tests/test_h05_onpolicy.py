"""H05: on-policy + auditoria + veredito (docs/19). Hermético, offline."""

from __future__ import annotations

import subprocess

from evaluation.h05_onpolicy import apply_policy, audit
from evaluation.mcp_suite_score import load_tasks, score_run


def _repo(tmp_path):
    (tmp_path / "zebra.java").write_text("public class ZebraStripe {\n void run() {}\n}\n", encoding="utf-8")
    (tmp_path / "other.java").write_text("public class Other {}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    return tmp_path


def _task(files):
    return {
        "kind": "locate",
        "method": "siga.locate",
        "args": {"query": "ZebraStripe run", "limit": 10},
        "query": "ZebraStripe run",
        "execution_commit": "c" * 40,
        "source_holdout_id": "h-1",
        "ground_truth": {"files": files, "commits": []},
    }


def _row(tid, braco, arquivos):
    return {
        "task_id": tid, "braco": braco, "resposta": "", "arquivos": arquivos,
        "simbolos": [], "commits": [], "tokens_proxy": 0, "latency_ms": 1, "chamadas_mcp": [],
    }


def test_policy_recupera_fail_com_tool(tmp_path):
    repo = _repo(tmp_path)
    tasks = {"t1": _task(["zebra.java"])}
    rows = [_row("t1", "B", ["other.java"])]
    assert score_run(tasks, rows[0])["verdict"] == "fail"
    # policy roda no repo real do teste via monkeypatch do resolver de repo
    import evaluation.h05_onpolicy as h05
    orig = h05._siga
    h05._siga = lambda: None
    try:
        out = apply_policy(tasks, rows, repo)
    finally:
        h05._siga = orig
    assert len(out) == 1 and out[0]["braco"] == "C"
    assert score_run(tasks, out[0])["task_success"] is True


def test_policy_rejeita_task_fora_do_congelado(tmp_path):
    try:
        apply_policy({"t1": _task(["zebra.java"])}, [_row("fantasma", "B", [])], tmp_path)
    except ValueError:
        return
    raise AssertionError("deveria rejeitar task desconhecida")


def test_auditoria_passa_no_repo_real():
    tasks = load_tasks()
    rep = audit(tasks)
    assert rep["pass"] is True, rep
    assert rep["n_gold"] == 29
