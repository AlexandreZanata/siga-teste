"""H03: fallback de termos + teacher agentivo (docs/19). Só stdlib, offline."""

from __future__ import annotations

import subprocess

import pytest

from retrieval.baseline import broadened_terms, expanded_terms
from task_factory.runs_to_gold import runs_to_gold
from tools.siga_locate import siga_locate


def _repo(tmp_path):
    (tmp_path / "cfg.java").write_text("public class Cfg {\n int LimiteDiasConfig = 1;\n}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    return tmp_path


def test_broadened_superset_com_camel_e_sem_digito():
    base = expanded_terms("LimiteDias relatorio2")
    broad = broadened_terms("LimiteDias relatorio2")
    assert set(base) <= set(broad)
    assert "limite" in broad and "dias" in broad and "relatorio" in broad


def test_fallback_acha_case_diferente_antes_do_vazio(tmp_path):
    root = _repo(tmp_path)
    hits = siga_locate("LimiteDiasConfig zqqqx", repo=root, limit=5)
    assert hits, "fallback case-insensitive deveria achar cfg.java"
    assert any("cfg.java" in (h.get("file") or "") for h in hits)
    assert siga_locate("zqqqx wwwwvvvv", repo=root, limit=5) == []


def _task(kind="locate", files=None):
    return {
        "kind": kind,
        "method": "siga.locate",
        "args": {"query": "q"},
        "query": "q",
        "execution_commit": "c" * 40,
        "source_holdout_id": "h-1",
        "ground_truth": {"files": files or [], "commits": []},
    }


def _row(tid, braco, arquivos):
    return {
        "task_id": tid,
        "braco": braco,
        "resposta": "",
        "arquivos": arquivos,
        "simbolos": [],
        "commits": [],
        "tokens_proxy": 0,
        "latency_ms": 1,
        "chamadas_mcp": [],
    }


def test_runs_to_gold_so_verificado_e_dificuldade_do_braco_a():
    tasks = {
        "t1": _task(files=["a.java"]),
        "t2": _task(files=["a.java", "b.java"]),
        "t3": _task(files=["a.java"]),
    }
    rows = [
        _row("t1", "B", ["a.java"]),
        _row("t1", "A", ["a.java"]),
        _row("t2", "B", ["a.java", "z.java"]),
        _row("t2", "A", []),
        _row("t3", "B", []),
    ]
    result = runs_to_gold(tasks, rows, "teacher-x", "run.jsonl")
    assert result["stats"]["n_gold"] == 2
    assert result["near_miss"] == ["t3"]
    by_id = {g["id"]: g for g in result["gold"]}
    assert by_id["t1:teacher-x"]["difficulty"] == "easy"
    assert by_id["t2:teacher-x"]["difficulty"] == "hard"
    traj = by_id["t1:teacher-x"]["trajectory"]
    assert [s["step"] for s in traj] == ["OBSERVATION", "ACTION", "TOOL ARGS", "RESULT", "FINAL"]
    assert by_id["t1:teacher-x"]["source_holdout_id"] == "h-1"
    assert by_id["t1:teacher-x"]["verification"]["verdict"] == "exact"


def test_runs_to_gold_rejeita_task_fora_do_congelado():
    with pytest.raises(ValueError):
        runs_to_gold({"t1": _task(files=["a.java"])}, [_row("fantasma", "B", ["a.java"])], "t", "r")
