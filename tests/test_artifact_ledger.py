"""Testes herméticos do ledger de artefatos reais do Needle (P13-T04).

Nenhum teste carrega engine, pesos, GPU ou treina: o carregamento é substituído
por um runner injetado e o relatório é exercitado sobre fixtures temporárias.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from training import artifact_ledger as ledger_mod


def _write(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return ledger_mod.sha256_file(path)


def _fixture_spec(tmp_path: Path) -> tuple[list[dict], dict[str, Path]]:
    files = {
        "smoke_dataset": tmp_path / "data/smoke/train-100.jsonl",
        "smoke_export": tmp_path / "data/smoke/tuned-20L.cact",
        "candidate_dataset": tmp_path / "datasets/needle_export/needle_train.jsonl",
        "candidate_adapter": tmp_path / "data/candidate/adapter.safetensors",
        "candidate_20l": tmp_path / "data/candidate/tuned-20L.cact",
        "candidate_12l": tmp_path / "data/candidate/tuned-12L.cact",
    }
    payloads = {
        "smoke_dataset": b'{"query": "smoke"}\n',
        "smoke_export": b"smoke-cact",
        "candidate_dataset": b'{"query": "candidate"}\n',
        "candidate_adapter": b"candidate-adapter",
        "candidate_20l": b"candidate-20L",
        "candidate_12l": b"candidate-12L",
    }
    hashes = {name: _write(path, payloads[name]) for name, path in files.items()}
    spec = [
        {
            "role": "dataset",
            "classification": "smoke",
            "path": "data/smoke/train-100.jsonl",
            "expected_sha256": hashes["smoke_dataset"],
            "records": 100,
        },
        {
            "role": "export",
            "classification": "smoke",
            "path": "data/smoke/tuned-20L.cact",
            "expected_sha256": hashes["smoke_export"],
            "layers": 20,
        },
        {
            "role": "dataset",
            "classification": "candidate",
            "path": "datasets/needle_export/needle_train.jsonl",
            "expected_sha256": hashes["candidate_dataset"],
            "records": 350,
            "trained_from": "legacy",
        },
        {
            "role": "adapter",
            "classification": "candidate",
            "path": "data/candidate/adapter.safetensors",
            "expected_sha256": hashes["candidate_adapter"],
        },
        {
            "role": "export",
            "classification": "candidate",
            "path": "data/candidate/tuned-20L.cact",
            "expected_sha256": hashes["candidate_20l"],
            "layers": 20,
        },
        {
            "role": "export",
            "classification": "candidate",
            "path": "data/candidate/tuned-12L.cact",
            "expected_sha256": hashes["candidate_12l"],
            "layers": 12,
        },
    ]
    return spec, files


def _train_summary(tmp_path: Path) -> Path:
    summary = {
        "task": "P13-T04",
        "dataset": {
            "path": "data/needle-real/v1/train-100.jsonl",
            "sha256": "d" * 64,
        },
        "checkpoint_sha256": "c" * 64,
        "config": {"epochs": 1, "max_len": 256, "lora_rank": 16},
        "batch_search": {
            "attempts": [
                {"batch_size": 1, "status": "ok", "elapsed_s": 75.0, "peak_vram_mib": 7646},
                {"batch_size": 2, "status": "ok", "elapsed_s": 74.0, "peak_vram_mib": 7646},
                {"batch_size": 4, "status": "oom", "elapsed_s": 108.0, "peak_vram_mib": 7652},
            ],
            "best_batch_size": 2,
        },
    }
    path = tmp_path / "train_summary.json"
    path.write_text(json.dumps(summary), encoding="utf-8")
    return path


def test_build_ledger_verifies_and_classifies(tmp_path):
    spec, _ = _fixture_spec(tmp_path)
    ledger = ledger_mod.build_ledger(root=tmp_path, spec=spec, train_summary=_train_summary(tmp_path))

    assert ledger["all_verified"] is True
    assert ledger["missing"] == []
    assert ledger["counts"] == {"smoke": 2, "candidate": 4}
    assert ledger["classifications"]["candidate"] == [
        "datasets/needle_export/needle_train.jsonl",
        "data/candidate/adapter.safetensors",
        "data/candidate/tuned-20L.cact",
        "data/candidate/tuned-12L.cact",
    ]
    assert all(entry["present"] and entry["verified"] for entry in ledger["artifacts"])


def test_build_ledger_detects_mismatch_and_missing(tmp_path):
    spec, files = _fixture_spec(tmp_path)
    spec[0]["expected_sha256"] = "0" * 64  # hash divergente
    files["candidate_12l"].unlink()  # artefato ausente
    ledger = ledger_mod.build_ledger(root=tmp_path, spec=spec, train_summary=_train_summary(tmp_path))

    assert ledger["all_verified"] is False
    assert ledger["missing"] == ["data/candidate/tuned-12L.cact"]
    status = {entry["path"]: entry for entry in ledger["artifacts"]}
    assert status["data/smoke/train-100.jsonl"]["verified"] is False
    assert status["data/candidate/tuned-12L.cact"]["present"] is False


def test_cache_key_is_deterministic_and_field_sensitive():
    base = ledger_mod.cache_key("a" * 64, 256, 16, "W4STE_A8")
    assert base == ledger_mod.cache_key("a" * 64, 256, 16, "W4STE_A8")
    assert "max_len=256" in base and "rank=16" in base and "scheme=W4STE_A8" in base
    variants = {
        ledger_mod.cache_key("b" * 64, 256, 16, "W4STE_A8"),
        ledger_mod.cache_key("a" * 64, 512, 16, "W4STE_A8"),
        ledger_mod.cache_key("a" * 64, 256, 32, "W4STE_A8"),
        ledger_mod.cache_key("a" * 64, 256, 16, "W8A8"),
    }
    assert base not in variants
    assert len(variants) == 4


def test_read_batch_evidence_returns_safe_batch_and_cache_key(tmp_path):
    evidence = ledger_mod.read_batch_evidence(_train_summary(tmp_path))
    assert evidence["best_batch_size"] == 2
    assert evidence["cache_key"].startswith("checkpoint=" + "c" * 64)
    assert "rank=16" in evidence["cache_key"]
    assert evidence["config"]["max_len"] == 256


def test_read_batch_evidence_fails_closed(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"batch_search": {"attempts": [], "best_batch_size": None}}))
    with pytest.raises(ValueError):
        ledger_mod.read_batch_evidence(path)
    path.write_text(
        json.dumps(
            {
                "batch_search": {
                    "attempts": [{"batch_size": 4, "status": "oom"}],
                    "best_batch_size": 4,
                }
            }
        )
    )
    with pytest.raises(ValueError):
        ledger_mod.read_batch_evidence(path)


def test_structural_check_loads_candidate_exports_offline(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    spec, _ = _fixture_spec(tmp_path)
    ledger = ledger_mod.build_ledger(root=tmp_path, spec=spec, train_summary=_train_summary(tmp_path))
    seen: list[dict] = []

    def runner(artifact, stage, seed, timeout_s, budget_s, checkpoint):
        seen.append(
            {
                "path": artifact["path"],
                "stage": stage,
                "seed": seed,
                "checkpoint": checkpoint,
                "offline": os.environ.get("HF_HUB_OFFLINE"),
            }
        )
        return {"loaded": True, "status": "completed", "metrics": {"latency_ms": {"p50": 1.0}}}

    result = ledger_mod.structural_check(
        ledger, checkpoint_dir=tmp_path / "runs", runner=runner
    )

    assert result["all_loaded"] is True
    assert [item["path"] for item in seen] == [
        "data/candidate/tuned-20L.cact",
        "data/candidate/tuned-12L.cact",
    ]
    assert all(item["offline"] == "1" for item in seen)
    assert all(item["stage"] == 4 and item["seed"] == 0 for item in seen)
    assert os.environ.get("HF_HUB_OFFLINE") is None  # restaurado após o carregamento


def test_structural_check_records_failure_honestly(tmp_path):
    spec, _ = _fixture_spec(tmp_path)
    ledger = ledger_mod.build_ledger(root=tmp_path, spec=spec, train_summary=_train_summary(tmp_path))

    def runner(artifact, stage, seed, timeout_s, budget_s, checkpoint):
        if artifact["layers"] == 12:
            raise RuntimeError("envelope inválido")
        return {"loaded": True, "status": "completed", "metrics": {}}

    result = ledger_mod.structural_check(ledger, checkpoint_dir=tmp_path / "runs", runner=runner)
    assert result["all_loaded"] is False
    failed = [item for item in result["artifacts"] if not item["loaded"]]
    assert failed and "RuntimeError" in failed[0]["error"]


def test_build_report_relativizes_absolute_batch_dataset(tmp_path):
    spec, _ = _fixture_spec(tmp_path)
    summary = _train_summary(tmp_path)
    data = json.loads(summary.read_text(encoding="utf-8"))
    data["dataset"]["path"] = str(tmp_path / "data/needle-real/v1/train-100.jsonl")
    summary.write_text(json.dumps(data), encoding="utf-8")
    ledger = ledger_mod.build_ledger(root=tmp_path, spec=spec, train_summary=summary)
    structural = {
        "stage": 4,
        "seed": 0,
        "offline_enforced": True,
        "artifacts": [
            {"path": "data/candidate/tuned-20L.cact", "layers": 20, "loaded": True,
             "checkpoint": str(tmp_path / "runs/c.partial.jsonl")}
        ],
        "all_loaded": True,
    }
    report = ledger_mod.build_report(ledger, structural, root=tmp_path)
    assert report["task"] == "P13-T04"
    assert report["all_verified"] is True
    assert report["offline"] is True
    assert report["batch"]["dataset"] == "data/needle-real/v1/train-100.jsonl"
    assert all("trained_from" not in entry for entry in report["artifacts"])
    assert "source" not in report["batch"]
    assert report["structural"]["artifacts"][0]["checkpoint"] == "runs/c.partial.jsonl"
