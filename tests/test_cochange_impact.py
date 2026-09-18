"""Co-change sem chamada direta (F08; lacunas P03-T02 `1a47b862`/`fecfd9ce`).

- `before_sha` restringe parceiros ao histórico estritamente anterior
  (prever o commit a partir dele mesmo seria leakage).
- `impact_recall_with_cochange` fecha o gap quando o par já co-ocorreu
  antes; quando a 1ª co-ocorrência É o commit avaliado, o recall fica 0
  (irredutível sem leakage — documentado, não escondido).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from indexer import git_history
from retrieval.callgraph import impact_recall, impact_recall_with_cochange, static_impact

ROOT = Path(__file__).resolve().parent.parent
SIGA = ROOT.parent


def _requires_siga() -> None:
    if not (SIGA / "siga-ex").is_dir():
        import pytest

        pytest.skip("Clone do SIGA não disponível ao lado (CI sem siga-ex)")


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@e", *args],
        check=True,
        capture_output=True,
        timeout=60,
    )


def _seed_two_commit_repo(root: Path) -> dict[str, str]:
    (root / "siga-ex").mkdir(parents=True)
    (root / "siga-ex/AAA.java").write_text("package x;\npublic class AAA {\n    public void executar() {}\n}\n", encoding="utf-8")
    (root / "siga-ex/BBB.java").write_text("package x;\npublic class BBB {\n    public void rodar() {}\n}\n", encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "c1 aaa+bbb")
    (root / "siga-ex/BBB.java").write_text("package x;\npublic class BBB {\n    public void rodar() {}\n    public void extra() {}\n}\n", encoding="utf-8")
    (root / "siga-ex/AAA.java").write_text("package x;\npublic class AAA {\n    public void executar() {}\n    public void outro() {}\n}\n", encoding="utf-8")
    _git(root, "commit", "-qam", "c2 aaa+bbb")
    log = subprocess.run(
        ["git", "-C", str(root), "log", "--format=%H"], capture_output=True, text=True, check=True, timeout=60
    ).stdout.split()
    return {"c2": log[0], "c1": log[1]}


def test_cochange_partners_before_sha_excludes_commit(tmp_path: Path):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "A.txt").write_text("a", encoding="utf-8")
    (tmp_path / "B.txt").write_text("b", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "c1")
    (tmp_path / "C.txt").write_text("c", encoding="utf-8")
    (tmp_path / "A.txt").write_text("a2", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "c2")
    shas = subprocess.run(
        ["git", "-C", str(tmp_path), "log", "--format=%H"], capture_output=True, text=True, check=True, timeout=60
    ).stdout.split()
    full = {p["path"] for p in git_history.cochange_partners(tmp_path, "A.txt")}
    assert full == {"B.txt", "C.txt"}
    before = {p["path"] for p in git_history.cochange_partners(tmp_path, "A.txt", before_sha=shas[0])}
    assert before == {"B.txt"}, "histórico deve excluir o próprio commit avaliado"


def test_with_cochange_closes_gap_without_call_edge(tmp_path: Path):
    shas = _seed_two_commit_repo(tmp_path)
    static = impact_recall(tmp_path, shas["c2"])
    assert static["skipped"] is False
    assert static["recall"] == 0.0
    with_co = impact_recall_with_cochange(tmp_path, shas["c2"])
    assert with_co["recall_static"] == 0.0
    assert with_co["recall"] == 1.0
    assert any(p.endswith("BBB.java") for p in with_co["cochange"])
    impact = static_impact(tmp_path, tmp_path / "siga-ex/AAA.java", with_cochange=True, before_sha=shas["c2"])
    assert any(p.endswith("BBB.java") for p in impact["cochange"])
    impact_off = static_impact(tmp_path, tmp_path / "siga-ex/AAA.java")
    assert impact_off["cochange"] == []


def test_real_lacunas_with_cochange():
    _requires_siga()
    lacuna = impact_recall_with_cochange(SIGA, "1a47b86233cceeb3f3729b697c472f8926290b9d")
    assert lacuna["recall_static"] == 0.0
    assert lacuna["recall"] == 1.0, "ProcessadorHtml co-ocorreu antes: gap fechável"
    first_time = impact_recall_with_cochange(SIGA, "fecfd9ced774e2bed71eabf6bfdb6b53f9d539df")
    assert first_time["recall_static"] == 0.0
    assert first_time["recall"] == 0.0, "1ª co-ocorrência É o commit: irredutível sem leakage"
    baseline = impact_recall_with_cochange(SIGA, "c1cb9e1ffa717c0a7fd3c92233d19d46e24307a9")
    assert baseline["recall_static"] == 0.5
    assert baseline["recall"] >= 0.5
