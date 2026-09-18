"""Métricas puras do bench (P04-T02): fixtures, sem clone, sem rede."""

from __future__ import annotations

import pytest

from evaluation import metrics


def test_recall_at_k():
    ranked = ["a", "b", "c", "d", "e", "f"]
    assert metrics.recall_at_k(ranked, {"a", "c"}, 5) == 1.0
    assert metrics.recall_at_k(ranked, {"a", "f"}, 5) == 0.5
    assert metrics.recall_at_k(ranked, {"a", "f"}, 1) == 0.5
    assert metrics.recall_at_k(ranked, set(), 5) == 1.0


def test_tool_and_sequence_and_args():
    assert metrics.tool_selection_accuracy(["a", "b", "c"], ["a", "x", "c"]) == pytest.approx(2 / 3)
    assert metrics.sequence_success(["a", "b"], ["a", "b"]) == 1.0
    assert metrics.sequence_success(["a"], ["a", "b"]) == 0.0
    assert metrics.argument_exact_match({"q": "x"}, {"q": "x"}) == 1.0
    assert metrics.argument_exact_match({"q": "x"}, {"q": "y"}) == 0.0
    assert metrics.invalid_tool_call_rate([{"name": "a"}, {"name": "zzz"}, {}], {"a"}) == pytest.approx(2 / 3)
    assert metrics.invalid_tool_call_rate([], {"a"}) == 0.0
    assert metrics.no_tool_accuracy([True, False], [True, True]) == 0.5


def test_hallucination_and_trace():
    assert metrics.hallucination_rate(["a", "zzz"], {"a"}) == 0.5
    assert metrics.hallucination_rate([], {"a"}) == 0.0
    assert metrics.trace_accuracy(["a", "b", "c"], ["a", "c"]) == 1.0
    assert metrics.trace_accuracy(["c", "a"], ["a", "c"]) == 0.5
    assert metrics.trace_accuracy(["a"], []) == 1.0


def test_cost_latency_e2e_and_summarize():
    assert metrics.mean_tool_calls([1, 2, 3]) == 2.0
    assert metrics.mean_tool_calls([]) == 0.0
    lat = metrics.latency_p50_p95([10.0, 20.0, 30.0, 40.0])
    assert lat == {"p50_ms": 25.0, "p95_ms": 40.0}
    with pytest.raises(ValueError):
        metrics.latency_p50_p95([])
    assert metrics.count_tokens("a b  c") == 3
    assert metrics.cost_usd(1000, 500, 0.01, 0.03) == pytest.approx(0.025)
    assert metrics.e2e_success([True, False, True]) == pytest.approx(2 / 3)
    summary = metrics.summarize([{"r": 1.0, "ok": True}, {"r": 0.5, "ok": False}])
    assert summary == {"r": 0.75}
    assert metrics.summarize([]) == {}
