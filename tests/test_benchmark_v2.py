"""Testes de conformidade e anti-leakage do Benchmark v2 (P13-T02)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.harness import check_no_leakage

ROOT = Path(__file__).resolve().parent.parent
BENCH_DIR = ROOT / "datasets/benchmark_v2"


def test_benchmark_v2_manifest_and_splits() -> None:
    manifest_path = BENCH_DIR / "manifest.json"
    assert manifest_path.is_file(), "manifest.json do v2 deve existir"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["version"] == 2
    assert manifest["t1"] < manifest["t2"]

    splits = manifest["splits"]
    train_shas = set(splits["train"])
    valid_shas = set(splits["valid"])
    test_shas = set(splits["test"])

    # Disjunção total
    assert train_shas.isdisjoint(valid_shas)
    assert train_shas.isdisjoint(test_shas)
    assert valid_shas.isdisjoint(test_shas)

    # Contagens conforme o contrato do P13
    assert 200 <= len(test_shas) <= 500
    assert len(train_shas) == 200
    assert len(valid_shas) == 200


def test_benchmark_v2_hashes_integrity() -> None:
    manifest_path = BENCH_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for filename, expected_hash in manifest["files"].items():
        file_path = BENCH_DIR / filename
        assert file_path.is_file(), f"Arquivo {filename} deve existir"
        actual_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        assert actual_hash == expected_hash, f"Hash divergente para {filename}"


def test_benchmark_v2_zero_leakage() -> None:
    manifest_path = BENCH_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    test_shas = set(manifest["splits"]["test"])
    check_no_leakage(test_shas, ROOT)
