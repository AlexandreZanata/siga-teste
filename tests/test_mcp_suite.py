"""Testes da suite EVAL-MCP (G01): freeze, checker cego e integridade do artefato.

O artefato congelado (`eval/mcp_suite/tasks.jsonl` + `prompts/`) é commitado:
os testes validam a estrutura, ausência de vazamento de GT e a matemática do
checker sobre fixtures sintéticas — sem exigir o clone do SIGA (roda no CI).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.mcp_suite_check import (  # noqa: E402
    _norm,
    build_report,
    evaluate_response,
    parse_response,
)
from scripts.freeze_mcp_suite import (  # noqa: E402
    COUNTS,
    PROMPTS_DIR,
    TASKS_OUT,
    check_artifacts,
    derived_candidates,
    ground_truth,
    render_prompt,
)

FIXTURE = {
    "seq": 1,
    "id": "mcp-locate-001",
    "method": "siga.locate",
    "kind": "locate",
    "args": {"query": "q", "limit": 10},
    "ground_truth": {"files": ["a/b/C.java", "d/E.jsp"]},
}


def _load_suite() -> list[dict]:
    doc = json.loads(TASKS_OUT.read_text(encoding="utf-8"))
    return doc["tasks"]


# ---------------------------------------------------------------- freeze puro


def test_derived_candidates_order_and_args(tmp_path):
    for f in ("x/A.java", "x/B.jsp"):
        p = tmp_path / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    ht = {
        "query": "q",
        "ground_truth_files": ["x/A.java", "x/missing.java", "x/B.jsp"],
    }
    cands = derived_candidates("trace", ht, tmp_path)
    assert [c["args"]["symbol"] for c in cands] == ["A"]
    cands = derived_candidates("impact", ht, tmp_path)
    assert [c["args"]["target"] for c in cands] == ["x/A.java", "x/B.jsp"]
    assert cands[0]["args"]["hops"] == 1
    cands = derived_candidates("history", ht, tmp_path)
    assert cands[0]["args"]["limit"] == 10 and cands[0]["args"]["target"] == "x/A.java"


def test_ground_truth_excludes_target_for_impact_and_history(tmp_path):
    for f in ("a/T.java", "b/U.java"):
        p = tmp_path / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    result = {"files": ["a/T.java", "b/U.java"], "commits": []}
    gt = ground_truth("impact", result, tmp_path, target="a/T.java")
    assert gt["files"] == ["b/U.java"]
    hist = {
        "files": [],
        "commits": [
            {"sha": "a" * 40, "date": "2026-01-01", "subject": "s", "files": ["a/T.java", "b/U.java"]},
            {"sha": "b" * 40, "date": "2026-01-02", "subject": "t", "files": ["a/T.java"]},
        ],
    }
    gt = ground_truth("history", hist, tmp_path, target="a/T.java")
    assert gt["files"] == ["b/U.java"]
    assert [c["sha"] for c in gt["commits"]] == ["a" * 40, "b" * 40]
    gt = ground_truth("locate", {"files": ["a/T.java"]}, tmp_path)
    assert gt == {"files": ["a/T.java"]}


FIXTURE = {
    "seq": 1,
    "id": "mcp-locate-001",
    "method": "siga.locate",
    "kind": "locate",
    "args": {"query": "q", "limit": 10},
    "ground_truth": {"files": ["a/b/C.java", "d/E.jsp"]},
}


def test_render_prompt_has_id_and_format_but_no_gt():
    task = {"id": "mcp-locate-099", "seq": 99, "method": "siga.locate", "kind": "locate", "query": "enunciado real", "args": {"query": "q"}, "ground_truth": {"files": ["sigilo/NaoVazarei.java"]}}
    text = render_prompt(task)
    assert task["id"] in text
    assert "FILE:" in text and "RESPOSTA" in text
    assert "sigilo/NaoVazarei.java" not in text
    assert "SYMBOL:" in text


# ---------------------------------------------------- artefato congelado real


def test_artifact_structure_and_counts():
    problems = check_artifacts()
    assert problems == [], problems
    tasks = _load_suite()
    kinds = {k: sum(1 for t in tasks if t["kind"] == k) for k in COUNTS}
    assert kinds == {"locate": 20, "trace": 10, "impact": 10, "history": 10, "context": 10}
    for i, t in enumerate(tasks, 1):
        assert t["seq"] == i
        assert (PROMPTS_DIR / f"{i:03d}.md").is_file()


def test_prompts_never_leak_ground_truth():
    for t in _load_suite():
        text = (PROMPTS_DIR / f"{t['seq']:03d}.md").read_text(encoding="utf-8")
        for f in t["ground_truth"].get("files", []):
            assert f not in text, f"prompt {t['seq']:03d} vaza {f}"
        for c in t["ground_truth"].get("commits", []):
            assert c["sha"] not in text, f"prompt {t['seq']:03d} vaza commit"


def test_artifact_provenance_present():
    doc = json.loads(TASKS_OUT.read_text(encoding="utf-8"))
    prov = doc["provenance"]
    for key in ("siga_head_commit", "selection_rule", "gt_source", "generated_at", "excluded_candidates"):
        assert key in prov, key
    assert len(prov["siga_head_commit"]) == 40


# ------------------------------------------------------------------- checker


def test_norm_variants():
    assert _norm("  a/b/C.java  ") == "a/b/C.java"
    assert _norm("`a/b/C.java`") == "a/b/C.java"
    assert _norm("./a/b/C.java") == "a/b/C.java"
    assert _norm("../siga/a/b/C.java") == "siga/a/b/C.java"
    assert _norm("a/b/C.java (ver também X)") == "a/b/C.java"
    assert _norm("a/b/C.java#L10") == "a/b/C.java"
    assert _norm(f"{'a' * 40}:a/b/C.java") == "a/b/C.java"
    assert _norm("A\\B\\C.java") == "A/B/C.java"


def test_parse_response_block_and_fallback():
    answer = "Prosa qualquer com a/b/C.java no meio (ignorada).\n### RESPOSTA\nFILE: a/b/C.java\nSYMBOL: C\nCOMMIT: " + "a" * 40
    parsed = parse_response(answer)
    assert parsed["files"] == ["a/b/C.java"]
    assert parsed["symbols"] == ["C"]
    assert parsed["commits"] == ["a" * 40]
    parsed = parse_response("FILE: x/Y.java\nFILE: x/Y.java")
    assert parsed["files"] == ["x/Y.java"]


def test_evaluate_response_metrics(tmp_path):
    (tmp_path / "a/b").mkdir(parents=True)
    (tmp_path / "a/b/C.java").write_text("x", encoding="utf-8")
    (tmp_path / "d").mkdir()
    (tmp_path / "d/E.jsp").write_text("x", encoding="utf-8")
    answer = "### RESPOSTA\nFILE: a/b/C.java\nFILE: inventado/NaoExiste.java\nSYMBOL: C\n"
    r = evaluate_response(FIXTURE, answer, tmp_path)
    assert r["recall_at_k"] == 0.5
    assert r["hallucination_rate"] == 0.5
    assert r["out_of_repo_files"] == ["inventado/NaoExiste.java"]
    assert r["task_id"] == FIXTURE["id"]


def test_evaluate_response_history_commit_recall():
    task = {
        "seq": 41,
        "id": "mcp-history-001",
        "method": "siga.history",
        "kind": "history",
        "args": {"target": "x.java"},
        "ground_truth": {"files": [], "commits": [{"sha": "a" * 40, "date": None, "subject": "s"}]},
    }
    answer = f"### RESPOSTA\nCOMMIT: {'a' * 12}\nCOMMIT: {'f' * 12}\n"
    r = evaluate_response(task, answer, Path("."))
    assert r["recall_at_k"] is None  # sem GT de arquivos
    assert r["hallucination_rate"] == 0.0  # sem FILE citado, sem halluc (lista vazia)
    assert r["commit_recall"] == 1.0  # o único sha do GT foi citado (cobertura do GT)


def test_build_report_summary():
    per_task = [
        {"recall_at_k": 1.0, "hallucination_rate": 0.0, "out_of_repo_files": []},
        {"recall_at_k": 0.5, "hallucination_rate": 0.5, "out_of_repo_files": ["x"]},
    ]
    report = build_report(per_task, {"model": "m", "ide": "i", "bench_commit": "abc"}, "def")
    assert report["summary"]["n_tasks"] == 2
    assert report["summary"]["mean_recall_at_k"] == 0.75
    assert report["summary"]["mean_hallucination_rate"] == 0.25
    assert report["summary"]["tasks_with_out_of_repo"] == 1
    assert report["siga_head_commit"] == "def"
    assert report["model"] == "m"


def test_suite_counts_documented_in_counts_const():
    assert COUNTS == {"locate": 20, "trace": 10, "impact": 10, "history": 10, "context": 10}
