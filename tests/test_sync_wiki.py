"""Testes do sync docs/ → wiki (F18, ADR-028 em DECISIONS.md).

- `build_home`: índice determinístico com provenance (source_commit, pages);
- `sync_to`: idempotência byte a byte, páginas = stems dos docs, Home gerado,
  detecção de páginas estranhas ao plano;
- `run_sync` sem wiki_repo: prepara em tempdir e nunca toca a rede;
- `plan_pages`: espelha exatamente os `docs/*.md` da fonte.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.sync_wiki import (
    WikiSyncError,
    build_home,
    list_doc_files,
    plan_pages,
    run_sync,
    sync_to,
)

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def _docs_stub(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "01-alfa.md").write_text("# Alfa\n\nconteudo alfa\n", encoding="utf-8")
    (docs / "02-beta.md").write_text("# Beta\n\nconteudo beta\n", encoding="utf-8")
    (docs / "README.md").write_text("# README do projeto\n\nvisao geral\n", encoding="utf-8")
    return docs


def test_build_home_is_deterministic_and_has_provenance(tmp_path: Path):
    docs = _docs_stub(tmp_path)
    first = build_home("abc123", docs, now="2026-09-19 14:00 UTC")
    second = build_home("abc123", docs, now="2026-09-19 14:00 UTC")
    assert first == second  # mesmos inputs ⇒ mesmos bytes
    assert "source_commit: `abc123`" in first
    assert "pages: 3" in first
    assert "[Alfa](01-alfa)" in first
    assert "[Beta](02-beta)" in first
    # README por último, com descrição própria
    assert first.index("[Alfa]") < first.index("[README do projeto]")
    assert "AGPLv3" in first  # herda obrigação da fonte (docs/14)


def test_list_doc_files_readme_last():
    files = list_doc_files(DOCS)
    names = [f.stem for f in files]
    assert names[-1] == "README"
    assert len(files) == 19  # 00–17 + README
    assert names[0].startswith("00-")


def test_plan_pages_mirrors_real_docs():
    plan = plan_pages(DOCS)
    assert len(plan) == 19
    assert "00-research" in plan and "17-first-experiment" in plan and "README" in plan
    # Conteúdo byte idêntico à fonte
    assert plan["17-first-experiment"] == (DOCS / "17-first-experiment.md").read_text(encoding="utf-8")


def test_sync_to_is_byte_idempotent(tmp_path: Path):
    docs = _docs_stub(tmp_path)
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    first = sync_to(wiki, docs, source_commit="abc123", now="2026-09-19 14:00 UTC")
    assert sorted(first["changed"]) == ["01-alfa", "02-beta", "Home", "README"]
    assert first["unchanged"] == []
    snapshot = {p.name: p.read_bytes() for p in wiki.glob("*.md")}
    second = sync_to(wiki, docs, source_commit="abc123", now="2026-09-19 14:00 UTC")
    assert second["changed"] == []
    assert sorted(second["unchanged"]) == ["01-alfa", "02-beta", "Home", "README"]
    assert {p.name: p.read_bytes() for p in wiki.glob("*.md")} == snapshot


def test_sync_to_updates_when_source_changes_and_flags_stray(tmp_path: Path):
    docs = _docs_stub(tmp_path)
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    sync_to(wiki, docs, source_commit="abc123")
    (docs / "01-alfa.md").write_text("# Alfa v2\n\nnovo\n", encoding="utf-8")
    (wiki / "Stranger.md").write_text("pagina fora do plano\n", encoding="utf-8")
    result = sync_to(wiki, docs, source_commit="def456")
    assert result["changed"] == ["Home", "01-alfa"]  # Home primeiro, por desenho
    assert result["stray_pages"] == ["Stranger"]
    assert "Alfa v2" in (wiki / "01-alfa.md").read_text(encoding="utf-8")
    assert "def456" in (wiki / "Home.md").read_text(encoding="utf-8")


def test_sync_to_requires_existing_wiki_dir(tmp_path: Path):
    with pytest.raises(WikiSyncError, match="inexistente"):
        sync_to(tmp_path / "nao-existe", _docs_stub(tmp_path))


def test_run_sync_prepare_mode_never_touches_network(tmp_path: Path):
    result = run_sync(None, workdir=tmp_path, now="2026-09-19 14:00 UTC")
    wiki_dir = Path(result["wiki_dir"])
    assert wiki_dir.is_dir()
    assert "Home.md" in {p.name for p in wiki_dir.glob("*.md")}
    assert len(list(wiki_dir.glob("*.md"))) == 20  # Home + 19 docs reais
    assert result["source_commit"]  # HEAD do siga-teste real
    assert result.get("pushed") is None  # modo prepare não empurra


def test_run_sync_push_requires_repo():
    with pytest.raises(WikiSyncError, match="--push"):
        run_sync(None, push=True)
