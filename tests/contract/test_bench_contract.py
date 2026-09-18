"""Contrato do bench (P04-T01, ADR-018 em docs/10).

- Manifest real: schema, T1<T2, SHAs existem no clone e caem na janela certa.
- Anti-leakage: fixture autocontida (limpo passa, contaminado levanta) +
  varredura real de datasets/{raw,canonical,verified} (vazios hoje).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from evaluation.harness import (
    bench_shas,
    check_no_leakage,
    commit_task,
    load_manifest,
    temporal_split,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parent.parent.parent
SIGA = ROOT.parent
MANIFEST = ROOT / "datasets/benchmark/manifest.json"


def _sha_date(sha: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(SIGA), "show", "--no-patch", "--format=%ad", "--date=short", sha],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return out.stdout.strip()


def test_manifest_valid_and_temporal():
    manifest = load_manifest(MANIFEST)
    assert manifest["branch"] == "desenvolvimento"
    total = 0
    for split, low, high in (("train", None, manifest["t1"]), ("valid", manifest["t1"], manifest["t2"]), ("test", manifest["t2"], None)):
        for sha in manifest["splits"][split]:
            date = _sha_date(sha)
            if low is not None:
                assert date >= low, f"{sha[:12]} fora da janela {split}"
            if high is not None:
                assert date < high, f"{sha[:12]} fora da janela {split}"
            commit_task(SIGA, sha)  # tarefa derivável: mensagem→arquivos, parent N-1
            total += 1
    assert total >= 9


def test_temporal_split_rejects_inverted_cuts():
    with pytest.raises(ValueError):
        temporal_split([], "2024-01-01", "2020-01-01")


def test_no_leakage_fixture(tmp_path: Path):
    bench = {"a" * 40, "b" * 40}
    clean = tmp_path / "raw"
    clean.mkdir()
    (clean / "d.jsonl").write_text('{"repo_commit": "' + "c" * 40 + '"}\n')
    check_no_leakage(bench, tmp_path)  # limpo passa
    (clean / "d.jsonl").write_text('{"repo_commit": "' + "a" * 40 + '"}\n')
    with pytest.raises(ValueError, match="LEAKAGE"):
        check_no_leakage(bench, tmp_path)


def test_no_leakage_real_datasets():
    manifest = load_manifest(MANIFEST)
    check_no_leakage(bench_shas(manifest), ROOT / "datasets")


def test_validate_manifest_rejects_duplicates():
    manifest = load_manifest(MANIFEST)
    manifest["splits"]["valid"] = manifest["splits"]["train"][:1]
    with pytest.raises(ValueError, match="repetido"):
        validate_manifest(manifest)
