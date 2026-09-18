"""Tracking reproduzível (P01-T02): schema válido + mesmo hash p/ mesmos inputs."""

from __future__ import annotations

import json

import pytest

from experiments import log


def _inputs(now: str = "2026-09-18T00:00:00Z") -> dict:
    return {
        "config": {"tool": "siga_locate", "depth": 2},
        "dataset_version": "d0",
        "tool_version": "t0",
        "index_version": "i0",
        "bench_version": "b0",
        "metrics": {"recall_at_1": 0.5},
        "latency": {"p50_ms": 12.5, "p95_ms": None},
        "now": now,
    }


def test_schema_loads_and_covers_required_fields():
    schema = json.loads(log.SCHEMA_PATH.read_text(encoding="utf-8"))
    for field in (
        "experiment_id",
        "siga_commit",
        "sigateste_commit",
        "needle_version",
        "needle_depth",
        "artifact_hash",
        "dataset_version",
        "tool_version",
        "index_version",
        "bench_version",
        "metrics",
        "hardware",
        "latency",
    ):
        assert field in schema["required"]
        assert field in schema["properties"]


def test_same_inputs_same_config_hash():
    first = log.new_run(**_inputs())
    second = log.new_run(**_inputs())
    log.validate_record(first)
    log.validate_record(second)
    assert log.config_hash(_inputs()["config"]) == log.config_hash(_inputs()["config"])
    assert first == second


def test_missing_required_field_fails():
    record = log.new_run(**_inputs())
    del record["bench_version"]
    with pytest.raises(ValueError):
        log.validate_record(record)


def test_save_load_roundtrip(tmp_path):
    record = log.new_run(**_inputs())
    path = log.save(record, tmp_path / "run.json")
    assert log.load(path) == record
