"""Testes do harness de scoring da suite EVAL-MCP (G02).

Lógica pura sobre fixtures sintéticas — sem rede, sem clone. Cobre:
veredito por tarefa (files, history-por-commits, símbolo âncora), abort em
run de tarefa desconhecida, agregados por braço, `effective_token_reduction`
e a regra do docs/11 §1 (redução de tokens com queda de success = fracasso).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.mcp_suite_score import (  # noqa: E402
    aggregate,
    compare_arms,
    effective_token_reduction,
    load_tasks,
    score_run,
    score_run_file,
    tokens_proxy,
)

A_SHA = "a" * 40
B_SHA = "b" * 40
C_SHA = "c" * 40

TASKS = {
    "mcp-locate-001": {
        "id": "mcp-locate-001",
        "kind": "locate",
        "method": "siga.locate",
        "args": {"query": "q"},
        "ground_truth": {"files": ["a/b/C.java", "d/E.jsp"]},
    },
    "mcp-trace-001": {
        "id": "mcp-trace-001",
        "kind": "trace",
        "method": "siga.trace",
        "args": {"symbol": "ExMobil", "depth": 2},
        "ground_truth": {"files": ["x/ExMobil.java"], "anchor": "ExMobil"},
    },
    "mcp-history-001": {
        "id": "mcp-history-001",
        "kind": "history",
        "method": "siga.history",
        "args": {"target": "x.java"},
        "ground_truth": {"commits": [{"sha": A_SHA, "date": None, "subject": "s"},
                                     {"sha": B_SHA, "date": None, "subject": "t"}],
                         "files": []},
    },
}


# ------------------------------------------------------------------ veredito


def test_exact_when_all_gt_and_nothing_else():
    run = {"task_id": "mcp-locate-001", "braco": "A", "arquivos": ["a/b/C.java", "d/E.jsp"]}
    s = score_run(TASKS, run)
    assert s["verdict"] == "exact" and s["task_success"] is True
    assert s["recall_at_k"] == 1.0 and s["precision"] == 1.0 and s["hallucination_rate"] == 0.0


def test_partial_when_half_gt_hit():
    run = {"task_id": "mcp-locate-001", "braco": "A", "arquivos": ["a/b/C.java"]}
    s = score_run(TASKS, run)
    assert s["verdict"] == "partial" and s["task_success"] is True
    assert s["recall_at_k"] == 0.5 and s["precision"] == 1.0


def test_fail_when_precision_below_threshold():
    run = {"task_id": "mcp-locate-001", "braco": "A", "arquivos": ["a/b/C.java", "z/X.java", "z/Y.java"]}
    s = score_run(TASKS, run)
    assert s["verdict"] == "fail" and s["task_success"] is False
    assert s["recall_at_k"] == 0.5 and s["precision"] < 0.5


def test_history_scored_by_commit_coverage():
    run = {"task_id": "mcp-history-001", "braco": "B", "commits": [A_SHA[:12]]}
    s = score_run(TASKS, run)
    assert s["task_success"] is True  # 1 de 2 = 0.5 ≥ threshold (regra uniforme)
    assert s["verdict"] == "partial"
    assert s["recall_at_k"] == 0.5 and s["precision"] is None
    run2 = {"task_id": "mcp-history-001", "braco": "B", "commits": [A_SHA[:12], B_SHA[:12]]}
    s2 = score_run(TASKS, run2)
    assert s2["verdict"] == "exact" and s2["task_success"] is True


def test_history_cited_unknown_commit_is_hallucination():
    run = {"task_id": "mcp-history-001", "braco": "A", "commits": [A_SHA[:12], C_SHA[:12]]}
    s = score_run(TASKS, run)
    assert s["hallucination_rate"] == 0.5


def test_symbol_anchor_hit_for_trace_and_context():
    run = {"task_id": "mcp-trace-001", "braco": "B", "arquivos": ["x/ExMobil.java"], "simbolos": ["ExMobil"]}
    s = score_run(TASKS, run)
    assert s["symbol_hit"] is True and s["verdict"] == "exact"
    run2 = {"task_id": "mcp-trace-001", "braco": "B", "arquivos": ["x/ExMobil.java"]}
    assert score_run(TASKS, run2)["symbol_hit"] is False


def test_unknown_task_aborts_no_false_success():
    with pytest.raises(SystemExit, match="tarefa inexistente"):
        score_run(TASKS, {"task_id": "mcp-locate-999", "arquivos": []})


# ------------------------------------------------------------------ agregados


def test_aggregate_counts_and_success():
    scores = [
        score_run(TASKS, {"task_id": "mcp-locate-001", "braco": "A", "arquivos": ["a/b/C.java", "d/E.jsp"], "latency_ms": 10, "tokens_proxy": 100}),
        score_run(TASKS, {"task_id": "mcp-trace-001", "braco": "A", "arquivos": ["x/ExMobil.java"], "latency_ms": 30, "tokens_proxy": 50}),
        score_run(TASKS, {"task_id": "mcp-history-001", "braco": "A", "commits": [A_SHA[:12], B_SHA[:12]], "latency_ms": 20, "tokens_proxy": 70}),
    ]
    agg = aggregate(scores)
    assert agg["n_tasks"] == 3 and agg["n_exact"] == 3
    assert agg["task_success"] == 1.0
    assert agg["tokens_proxy_total"] == 220
    assert agg["latency"]["p50_ms"] == 20.0


def test_effective_token_reduction_and_none_case():
    assert effective_token_reduction(1000, 400) == 0.6
    assert effective_token_reduction(0, 400) is None


def _agg(success: float, tokens: int) -> dict:
    n = 10
    return {"n_tasks": n, "task_success": success, "tokens_proxy_total": tokens}


def test_compare_arms_docs11_rule_failure_on_regression():
    # redução de tokens com queda de success = fracasso, sem exceção
    cmp_ = compare_arms(_agg(0.9, 1000), _agg(0.7, 400))
    assert cmp_["comparable"] is True
    assert cmp_["task_success_delta"] == -0.2
    assert cmp_["effective_token_reduction"] == 0.6
    assert cmp_["verdict"] == "failure_token_reduction_with_regression"


def test_compare_arms_mcp_helps_and_tie():
    assert compare_arms(_agg(0.8, 1000), _agg(0.9, 400))["verdict"] == "mcp_helps"
    assert compare_arms(_agg(0.8, 1000), _agg(0.8, 800))["verdict"] == "tie"
    assert compare_arms(_agg(0.8, 1000), _agg(0.8, 1000))["effective_token_reduction"] == 0.0


def test_compare_arms_not_comparable_below_min_tasks():
    small = {"n_tasks": 4, "task_success": 1.0, "tokens_proxy_total": 10}
    cmp_ = compare_arms(small, small)
    assert cmp_["comparable"] is False and "mínimo" in cmp_["reason"]


# ---------------------------------------------------------- arquivo de run


def test_score_run_file_roundtrip(tmp_path):
    lines = [
        {"task_id": "mcp-locate-001", "braco": "A", "arquivos": ["a/b/C.java"], "tokens_proxy": 100, "latency_ms": 10, "chamadas_mcp": []},
        {"task_id": "mcp-locate-001", "braco": "B", "arquivos": ["a/b/C.java", "d/E.jsp"], "tokens_proxy": 40, "latency_ms": 8, "chamadas_mcp": [{"method": "siga.locate"}]},
        {"task_id": "mcp-trace-001", "braco": "B", "arquivos": ["x/ExMobil.java"], "simbolos": ["ExMobil"], "tokens_proxy": 30, "latency_ms": 12, "chamadas_mcp": [{"method": "siga.trace"}]},
    ]
    f = tmp_path / "probe-ide-20260920.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    report = score_run_file(f, TASKS)
    assert report["n_lines"] == 3
    assert report["aggregate"]["A"]["n_tasks"] == 1
    assert report["aggregate"]["B"]["n_tasks"] == 2
    assert report["aggregate"]["B"]["mean_mcp_calls"] == 1.0
    # A/B só é comparado com o mínimo por braço — aqui B tem 2 < MIN_TASKS
    assert report["comparison"]["comparable"] is False


def test_score_run_file_skips_blank_lines(tmp_path):
    f = tmp_path / "r.jsonl"
    f.write_text(json.dumps({"task_id": "mcp-trace-001", "braco": "A", "arquivos": ["x/ExMobil.java"]}) + "\n\n", encoding="utf-8")
    report = score_run_file(f, TASKS)
    assert report["n_lines"] == 1


def test_load_tasks_real_artifact_shapes():
    tasks = load_tasks()
    assert len(tasks) == 60
    kinds = {t["kind"] for t in tasks.values()}
    assert kinds == {"locate", "trace", "impact", "history", "context"}


# --------------------------------------------- métricas do docs/10 §2 (G02)


def test_tool_selection_and_argument_exact_arm_b_only():
    run = {
        "task_id": "mcp-locate-001",
        "braco": "B",
        "arquivos": ["a/b/C.java"],
        "chamadas_mcp": [{"method": "siga.locate", "args": {"query": "q"}}],
    }
    s = score_run(TASKS, run)
    assert s["tool_selection_correct"] is True
    assert s["argument_exact"] is True  # args == task.args congelado
    run_a = {"task_id": "mcp-locate-001", "braco": "A", "arquivos": ["a/b/C.java"]}
    s_a = score_run(TASKS, run_a)
    assert s_a["tool_selection_correct"] is None and s_a["argument_exact"] is None
    run_wrong = {
        "task_id": "mcp-locate-001",
        "braco": "B",
        "arquivos": [],
        "chamadas_mcp": [{"method": "siga.trace", "args": {}}],
    }
    s_w = score_run(TASKS, run_wrong)
    assert s_w["tool_selection_correct"] is False and s_w["argument_exact"] is None


def test_recall_at_k_profile_docs10():
    run = {"task_id": "mcp-locate-001", "braco": "A", "arquivos": ["a/b/C.java"]}
    s = score_run(TASKS, run)
    assert s["recall_at_1"] == 0.5  # 1º arquivo citado está no GT
    assert s["recall_at_3"] == 0.5 and s["recall_at_5"] == 0.5
    assert s["symbol_recall_at_1"] is None  # locate não tem âncora de símbolo


def test_symbol_recall_profile_for_trace():
    run = {"task_id": "mcp-trace-001", "braco": "B", "arquivos": ["x/ExMobil.java"], "simbolos": ["Outra", "ExMobil"]}
    s = score_run(TASKS, run)
    assert s["symbol_recall_at_1"] == 0.0 and s["symbol_recall_at_3"] == 1.0


def test_tokens_proxy_matches_metrics_count_tokens():
    from evaluation.metrics import count_tokens

    text = "duas palavras aqui"
    assert tokens_proxy(text) == count_tokens(text)
    assert tokens_proxy("") == 0


def test_aggregate_includes_docs10_metrics():
    scores = [
        score_run(TASKS, {"task_id": "mcp-locate-001", "braco": "B", "arquivos": ["a/b/C.java"],
                          "chamadas_mcp": [{"method": "siga.locate", "args": {"query": "q"}}]}),
        score_run(TASKS, {"task_id": "mcp-trace-001", "braco": "B", "arquivos": ["x/ExMobil.java"],
                          "simbolos": ["ExMobil"], "chamadas_mcp": [{"method": "siga.trace", "args": {"symbol": "ExMobil", "depth": 2}}]}),
    ]
    agg = aggregate(scores)
    assert agg["tool_selection_accuracy"] == 1.0
    assert agg["argument_exact_rate"] == 1.0
    assert agg["mean_recall_at_1"] == 0.75
    assert agg["mean_symbol_recall_at_1"] == 1.0  # locate=None excluído; trace cita ExMobil em 1º


def test_aggregate_ignores_arm_a_in_tool_metrics():
    scores = [
        score_run(TASKS, {"task_id": "mcp-locate-001", "braco": "A", "arquivos": ["a/b/C.java"]}),
        score_run(TASKS, {"task_id": "mcp-locate-001", "braco": "B", "arquivos": ["a/b/C.java"],
                          "chamadas_mcp": [{"method": "siga.locate", "args": {"query": "q"}}]}),
    ]
    agg = aggregate(scores)
    assert agg["tool_selection_accuracy"] == 1.0  # só o B entra na média
