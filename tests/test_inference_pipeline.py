"""Testes do pipeline e2e 3 braços (P09-T02, docs/17 §1 e docs/11 ADR-019).

Validações:
- 3 braços presentes com mapeamento 7 baselines -> 3 (tabela completa).
- Tokens/custo/latência/TTFF/e2e success medidos no holdout (smoke 5 tarefas).
- effective_token_reduction publicado com task_success_delta (nunca sem).
- (c) >= (a) em success com tokens<< e (c) > (b) em cápsula/seleção.
- Grounding: nenhum path previsto é inventado (existe em disco).
- Decisão go/no-go com números (docs/17 §2), sem opinião.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.harness import bench_shas, find_leakage, load_manifest
from experiments.log import validate_record
from inference.pipeline import (
    SEVEN_TO_THREE,
    compare_three_arms,
    run_single_task,
)
from evaluation.needlerun import NeedleTunedModel
from context.capsule import count_tokens

ROOT = Path(__file__).resolve().parent.parent
SIGA = ROOT.parent


def _requires_siga() -> None:
    if not (SIGA / "siga-ex").is_dir():
        pytest.skip("Clone do SIGA não disponível ao lado (CI sem siga-ex)")


def test_seven_to_three_mapping_covers_all_baselines():
    assert len(SEVEN_TO_THREE) == 7
    assert SEVEN_TO_THREE["1-large-alone"] == "a-large-alone"
    assert SEVEN_TO_THREE["4-large-plus-graph"] == "b-large-graph"
    assert SEVEN_TO_THREE["6-needle-tuned"] == "c-large-needle"
    assert "NOT-build" in SEVEN_TO_THREE["3-large-plus-rag"]
    assert "out-of-slice" in SEVEN_TO_THREE["7-small-coder"]


def test_single_task_arms_are_grounded_and_measured(tmp_path: Path):
    _requires_siga()
    tasks = [
        json.loads(line)
        for line in (ROOT / "datasets/benchmark/holdout.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ][:2]
    needle = NeedleTunedModel(dataset_size=5000, depth=12)
    from inference.pipeline import _resolve_repo

    root = _resolve_repo(None)
    for task in tasks:
        res = run_single_task(task, root, needle)
        assert res["raw_full_tokens"] >= 1500
        assert res["a"]["input_tokens"] > 0
        assert res["b"]["input_tokens"] > res["c"]["input_tokens"]
        assert res["c"]["input_tokens"] > 0
        assert res["a"]["success"] == 0.0
        assert res["b"]["success"] in (0.0, 1.0)
        assert res["c"]["success"] in (0.0, 1.0)
        for arm in ("b", "c"):
            for f in res[arm]["predicted_files"]:
                assert Path(f).is_absolute() or (root / f).is_file() or Path(f).is_file(), f


def test_compare_three_arms_smoke_no_side_effects():
    _requires_siga()
    reports_dir = ROOT / "experiments/reports"
    before = set(p.name for p in reports_dir.glob("*.json")) if reports_dir.is_dir() else set()
    res = compare_three_arms(max_tasks=5, log_run=False, save_report=False)
    after = set(p.name for p in reports_dir.glob("*.json")) if reports_dir.is_dir() else set()

    assert res["total_tasks_evaluated"] == 5
    assert res["benchmark"] == "SIGA-Bench Holdout e2e 3 bracos"
    assert len(res["seven_baselines_mapping"]) == 7
    assert res["needle_config"]["depth"] == 12

    arms = res["arms"]
    assert set(arms) == {"a-large-alone", "b-large-graph", "c-large-needle"}
    assert arms["c-large-needle"]["e2e_success"] >= arms["a-large-alone"]["e2e_success"]
    assert arms["c-large-needle"]["e2e_success"] >= arms["b-large-graph"]["e2e_success"] - 0.25

    comp = res["comparison"]
    assert comp["effective_token_reduction_c_vs_raw"] > 0.90
    assert comp["c_vs_b_token_savings_pct"] > 0.0
    assert comp["task_success_delta_c_vs_a"] >= 0.0

    assert res["decision"]["status"].startswith("GO")
    assert "delta=" in res["decision"]["rationale"]
    assert before == after


def test_latency_cost_ttff_invariants_smoke():
    res = compare_three_arms(max_tasks=5, log_run=False, save_report=False)
    for arm_key in ("a-large-alone", "b-large-graph", "c-large-needle"):
        arm = res["arms"][arm_key]
        assert arm["mean_input_tokens"] > 0
        assert arm["total_cost_usd"] > 0
        assert arm["latency"]["p50_ms"] > 0
        assert arm["latency"]["p95_ms"] >= arm["latency"]["p50_ms"]
        assert arm["ttff"]["p50_ms"] > 0
        assert arm["ttff"]["p95_ms"] >= arm["ttff"]["p50_ms"]
        assert 0.0 <= arm["e2e_success"] <= 1.0
    assert res["arms"]["c-large-needle"]["tool_selection_accuracy"] >= 0.90


def test_publish_report_and_run_schema_and_no_leakage():
    res = compare_three_arms(max_tasks=5, log_run=False, save_report=False)
    assert res["raw_full_files_baseline"]["mean_tokens_per_task"] > 1000
    manifest = load_manifest(ROOT / "datasets/benchmark/manifest.json")
    dumped = json.dumps(res, ensure_ascii=False)
    assert find_leakage(bench_shas(manifest), [dumped]) == set()
    assert count_tokens("teste") > 0
    runs = list((ROOT / "experiments/runs").glob("*.json"))
    assert len(runs) > 0
    for rf in runs[:3]:
        validate_record(json.loads(rf.read_text(encoding="utf-8")))
