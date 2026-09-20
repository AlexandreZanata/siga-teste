"""H01: failure mining sobre runs sintéticos (docs/19 §3). Só stdlib, offline."""

from __future__ import annotations

from evaluation.h01_failures import MODES, classify, mine


def _task(kind="locate", files=None, commits=None):
    return {
        "kind": kind,
        "method": "siga.locate",
        "args": {},
        "ground_truth": {"files": files or [], "commits": commits or []},
    }


def _score(verdict="fail", commit_hit=None):
    return {"verdict": verdict, "commit_hit": commit_hit, "recall_at_k": 0.0, "n_answered_files": 0}


def _run(task_id, arquivos=None, simbolos=None, commits=None, braco="B"):
    return {
        "task_id": task_id,
        "braco": braco,
        "resposta": "",
        "arquivos": arquivos or [],
        "simbolos": simbolos or [],
        "commits": commits or [],
        "tokens_proxy": 0,
        "latency_ms": 1,
        "chamadas_mcp": [],
    }


def test_modos_sao_estaveis_e_ordenados():
    assert MODES == (
        "no_files_cited",
        "out_of_head",
        "history_commit_miss",
        "wrong_module",
        "partial_miss",
    )


def test_no_files_cited_tem_prioridade(tmp_path):
    task = _task(files=["siga-ex/a.java"])
    primary, modes = classify(task, _run("t", arquivos=[]), _score(), tmp_path)
    assert primary == "no_files_cited"


def test_out_of_head_quando_citado_nao_existe(tmp_path):
    (tmp_path / "siga-ex").mkdir()
    (tmp_path / "siga-ex" / "a.java").write_text("x", encoding="utf-8")
    task = _task(files=["siga-ex/a.java"])
    run = _run("t", arquivos=["siga-ex/a.java", "siga-ex/sumiu.java"])
    primary, _ = classify(task, run, _score(), tmp_path)
    assert primary == "out_of_head"


def test_wrong_module_sem_intersecao_de_shard(tmp_path):
    (tmp_path / "sigaex").mkdir()
    (tmp_path / "sigaex" / "b.jsp").write_text("x", encoding="utf-8")
    task = _task(files=["siga-ex/a.java"])
    run = _run("t", arquivos=["sigaex/b.jsp"])
    primary, _ = classify(task, run, _score(), tmp_path)
    assert primary == "wrong_module"


def test_history_commit_miss(tmp_path):
    (tmp_path / "siga-ex").mkdir()
    (tmp_path / "siga-ex" / "a.java").write_text("x", encoding="utf-8")
    task = _task(kind="history", files=[], commits=[{"sha": "abc123"}])
    run = _run("t", arquivos=["siga-ex/a.java"])
    primary, _ = classify(task, run, _score(commit_hit=0.0), tmp_path)
    assert primary == "history_commit_miss"


def test_mine_soma_fails_e_exige_gt_congelado():
    tasks = {"t1": _task(files=["siga-ex/a.java"]), "t2": _task(files=["siga-ex/b.java"])}
    rows = [_run("t1", arquivos=[]), _run("t2", arquivos=["sigaex/z.jsp"], braco="A")]
    report = mine(tasks, rows)
    assert report["by_arm"]["B"]["n_fail"] == 1
    assert report["by_arm"]["A"]["n_fail"] == 1
    assert sum(report["by_arm"]["B"]["mode_counts"].values()) == 1
    assert report["by_arm"]["B"]["fails"][0]["primary_mode"] == "no_files_cited"
    assert report["priorities"], "mining sem prioridades é inútil"
