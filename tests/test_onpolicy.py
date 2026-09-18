"""Loop on-policy com failure mining (P11-T01, docs/09 ADR-017).

Validações:
- Mining encontra as falhas léxicas conhecidas com regiões observáveis.
- Active learning rateia o orçamento pelas regiões com mais falhas.
- Correção teacher só é aceita após execução real + verifier determinístico.
- Registros-alvo carregam provenance total (repo_commit, teacher, prompt,
  timestamp, verifier, licença).
- Patch de região dá ganho nas falhas-alvo sem regressão no holdout.
- Bench nunca entra no train: ids `onpolicy-*`, split `onpolicy`, prefixo
  `datasets/onpolicy/`, zero SHA do bench nos registros.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from evaluation.harness import bench_shas, find_leakage, load_manifest
from evaluation.needlerun import NeedleTunedModel
from experiments.log import validate_record
from tools.simulator import Simulator
from training.lora_progression import load_holdout_tasks
from training.onpolicy import (
    ONPOLICY_PREFIX,
    PatchedStudent,
    _leakage_texts,
    accuracy,
    correct_failure,
    expected_tool,
    learn_patch,
    mine_failures,
    region_of,
    run_onpolicy_loop,
    select_target_regions,
)
ROOT = Path(__file__).resolve().parent.parent

EXPECTED_REGIONS = {
    "commit-localization+siga_context",
    "commit-localization+siga_impact",
    "commit-localization+siga_trace",
}


def _student() -> NeedleTunedModel:
    return NeedleTunedModel(name="needle-tuned-5000-d12", dataset_size=5000, depth=12)


def _seed_repo(root: Path) -> Path:
    (root / "ServicoExemplo.java").write_text(
        "package br.gov.exemplo;\npublic class ServicoExemplo {\n    public void executar() {}\n}\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "seed"],
        check=True,
    )
    return root


def test_expected_tool_and_region_contract():
    assert expected_tool({"task_type": "commit-localization"}) == "siga_locate"
    assert expected_tool({"task_type": "off-topic"}) == "none"
    assert expected_tool({"task_type": "locate", "expected_tools": ["siga_trace"]}) == "siga_trace"
    region = region_of({"task_type": "commit-localization", "query": "fluxo de desentranhamento"})
    assert region == "commit-localization+siga_trace"


def test_mine_failures_finds_known_lexical_regions():
    tasks = load_holdout_tasks()
    failures = mine_failures(tasks, _student())
    assert len(failures) == 5
    assert {f["region"] for f in failures} == EXPECTED_REGIONS
    assert accuracy(_student(), tasks) == 0.9844
    for failure in failures:
        assert failure["expected"] == "siga_locate"
        assert failure["predicted"] != "siga_locate"


def test_active_learning_budget_allocation():
    tasks = load_holdout_tasks()
    failures = mine_failures(tasks, _student())
    allocation = select_target_regions(failures, 8)
    assert set(allocation) == EXPECTED_REGIONS
    assert sum(allocation.values()) <= 8
    assert allocation["commit-localization+siga_impact"] >= allocation["commit-localization+siga_trace"]
    with pytest.raises(ValueError):
        select_target_regions(failures, 0)


def test_correct_failure_provenance_and_verification(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    tasks = load_holdout_tasks()
    failures = mine_failures(tasks, _student())
    record = correct_failure(
        failures[0], repo=repo, repo_commit="abc123", loop_id="loop-01", simulator=Simulator(repo=repo)
    )
    assert record is not None
    for key in ("repo_commit", "teacher", "teachers_consulted", "prompt_version", "timestamp", "license", "source", "failure_region", "loop_id", "verification", "trajectory", "answers"):
        assert key in record, f"provenance ausente: {key}"
    assert record["id"].startswith(f"{ONPOLICY_PREFIX}-")
    assert record["split"] == "onpolicy"
    assert record["verification"]["passed"] is True
    assert record["tools"] == ["siga_locate"]


def test_patch_gain_without_holdout_regression(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    sim = Simulator(repo=repo)
    tasks = load_holdout_tasks()
    base = _student()
    failures = mine_failures(tasks, base)
    records = [
        rec
        for rec in (correct_failure(f, repo=repo, repo_commit="abc", loop_id="loop-01", simulator=sim) for f in failures)
        if rec is not None
    ]
    assert len(records) == len(failures)
    patch = learn_patch(records)
    assert set(patch) == EXPECTED_REGIONS
    assert all(tool == "siga_locate" for tool in patch.values())
    patched = PatchedStudent(base, patch)
    assert accuracy(patched, tasks) == 1.0
    assert accuracy(patched, tasks) >= accuracy(base, tasks)
    assert mine_failures(tasks, patched) == []


def test_never_reintroduces_bench(tmp_path: Path):
    _seed_repo(tmp_path)
    bench_root = tmp_path / "work"
    (bench_root / "datasets/benchmark").mkdir(parents=True)
    shutil.copy(ROOT / "datasets/benchmark/holdout.jsonl", bench_root / "datasets/benchmark/holdout.jsonl")
    shutil.copy(ROOT / "datasets/benchmark/manifest.json", bench_root / "datasets/benchmark/manifest.json")

    report = run_onpolicy_loop(
        holdout_path=bench_root / "datasets/benchmark/holdout.jsonl",
        repo_path=tmp_path,
        budget=8,
        loop_id="loop-01",
        log_run=False,
        save=True,
        work_root=bench_root,
    )
    assert report["no_regression"] is True
    assert report["target_gain"] == 1.0
    assert report["holdout_delta"] >= 0.0
    assert report["anti_leakage_verified"] is True

    target_file = bench_root / report["target_file"]
    assert target_file.is_file()
    records = [json.loads(line) for line in target_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(records) == report["target_records"] > 0
    manifest = load_manifest(bench_root / "datasets/benchmark/manifest.json")
    assert find_leakage(bench_shas(manifest), _leakage_texts(records)) == set()
    for record in records:
        assert record["id"].startswith(f"{ONPOLICY_PREFIX}-")
        assert record["split"] == "onpolicy"

    for split in ("raw", "canonical", "verified"):
        assert not (bench_root / "datasets" / split).exists(), f"split de treino tocado: {split}"


def test_experiment_tracking_valid(tmp_path: Path):
    _seed_repo(tmp_path)
    bench_root = tmp_path / "work"
    (bench_root / "datasets/benchmark").mkdir(parents=True)
    shutil.copy(ROOT / "datasets/benchmark/holdout.jsonl", bench_root / "datasets/benchmark/holdout.jsonl")
    shutil.copy(ROOT / "datasets/benchmark/manifest.json", bench_root / "datasets/benchmark/manifest.json")

    report = run_onpolicy_loop(
        holdout_path=bench_root / "datasets/benchmark/holdout.jsonl",
        repo_path=tmp_path,
        budget=2,
        loop_id="loop-02",
        log_run=True,
        save=True,
        work_root=bench_root,
    )
    assert "experiment_id" in report
    run_file = bench_root / "experiments/runs" / f"{report['experiment_id']}.json"
    validate_record(json.loads(run_file.read_text(encoding="utf-8")))
