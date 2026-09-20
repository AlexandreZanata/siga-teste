"""Testes do G06 — lotes 2–N da biblioteca de contexto + integração (docs/18 §4).

Cobre:
- gerador determinístico (`scripts/gen_context_docs.py`): páginas com grounding
  duplo (path existe no clone + símbolo resolvido por `siga_locate`), INDEX
  listando todos os módulos (incl. lote 1), sincronia byte a byte (`--check`);
- integração (`context/library.py` + `tools.siga_context`): ponteiros de páginas
  só por existência real; cápsula ganha `context_library` sem inventar página.

No CI (sem clone do SIGA ao lado), os checks dependentes do clone são pulados
explicitamente — nunca falso sucesso.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from context import library  # noqa: E402
from scripts.gen_context_docs import BATCH_1, INDEX_NAME, ROLES, build_plan  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONTEXT = ROOT / "docs" / "context"
CLONE = ROOT.parent
HAS_CLONE = (CLONE / "siga-ex").is_dir() and (CLONE / "sigaex").is_dir()

GENERATED_MODULES = sorted(set(ROLES) - BATCH_1)

_PATH_RE = re.compile(r"`((?:[a-z][\w\-]*(?:-[\w\-]+)*)/[\w\-./]+\.(?:java|jsp|sql))`")


def test_pages_batch_1_untouched_and_present():
    """Lote 1 (G05) permanece no disco; gerador não sobrescreve páginas manuais."""
    for module in BATCH_1:
        assert (CONTEXT / f"{module}.md").is_file(), module


@pytest.mark.skipif(not HAS_CLONE, reason="clone do SIGA ausente (CI)")
def test_generated_pages_exist_for_all_modules():
    for module in GENERATED_MODULES:
        assert (CONTEXT / f"{module}.md").is_file(), f"página ausente: {module}.md"


@pytest.mark.skipif(not HAS_CLONE, reason="clone do SIGA ausente (CI)")
def test_every_cited_path_exists_in_clone():
    for module in GENERATED_MODULES:
        text = (CONTEXT / f"{module}.md").read_text(encoding="utf-8")
        for path in _PATH_RE.findall(text):
            assert (CLONE / path).is_file(), f"{module}.md: path inexistente: {path}"


@pytest.mark.skipif(not HAS_CLONE, reason="clone do SIGA ausente (CI)")
def test_every_cited_symbol_has_java_file_in_its_module():
    symbol_re = re.compile(r"símbolo `(\w+)` \(resolvido por `siga_locate`\)")
    for module in GENERATED_MODULES:
        text = (CONTEXT / f"{module}.md").read_text(encoding="utf-8")
        for symbol in set(symbol_re.findall(text)):
            hits = list((CLONE / module / "src").rglob(f"{symbol}.java"))
            assert hits, f"{module}.md: símbolo sem arquivo no próprio módulo: {symbol}"


@pytest.mark.skipif(not HAS_CLONE, reason="clone do SIGA ausente (CI)")
def test_index_lists_all_modules_with_source_commit():
    index = (CONTEXT / INDEX_NAME).read_text(encoding="utf-8")
    for module in sorted(set(GENERATED_MODULES) | BATCH_1):
        assert f"]({module}.md)" in index, f"INDEX não aponta para {module}.md"
    assert "24 de 24 módulos Maven ativos" in index
    assert re.search(r"`[0-9a-f]{40}`", index), "source_commit deve ser sha completo"


@pytest.mark.skipif(not HAS_CLONE, reason="clone do SIGA ausente (CI)")
def test_check_mode_reports_in_sync():
    """--check em memória deve bater byte a byte com o que está em docs/context."""

    head, pages = build_plan(CLONE)
    assert re.fullmatch(r"[0-9a-f]{40}", head)
    for name, content in pages.items():
        filename = name if name == INDEX_NAME else f"{name}.md"
        on_disk = (CONTEXT / filename).read_text(encoding="utf-8")
        assert on_disk == content, f"{filename} divergente do plano regenerado"


@pytest.mark.skipif(not HAS_CLONE, reason="clone do SIGA ausente (CI)")
def test_plan_is_deterministic():
    _, pages1 = build_plan(CLONE)
    _, pages2 = build_plan(CLONE)
    assert pages1 == pages2


def test_library_available_pages_covers_all_modules():
    pages = library.available_pages()
    for module in sorted(set(GENERATED_MODULES) | BATCH_1):
        assert f"{module}.md" in pages, module
    assert "INDEX.md" not in pages


def test_library_read_page_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        library.read_page("nao-existe.md", context_dir=tmp_path)


def test_library_module_of_symbol_requires_unambiguous_hit(tmp_path):
    # contexto fake com páginas a.md e b.md
    ctx = tmp_path / "ctx"
    ctx.mkdir()
    (ctx / "a.md").write_text("# a", encoding="utf-8")
    (ctx / "b.md").write_text("# b", encoding="utf-8")

    # hit único → módulo resolvido
    clone1 = tmp_path / "clone1"
    (clone1 / "a" / "pkg").mkdir(parents=True)
    (clone1 / "a" / "pkg" / "Foo.java").write_text("class Foo {}", encoding="utf-8")
    assert library.module_of_symbol("Foo", clone1, context_dir=ctx) == "a"

    # hit ambíguo (2 módulos) → None (nunca adivinhar)
    clone2 = tmp_path / "clone2"
    (clone2 / "a").mkdir(parents=True)
    (clone2 / "b").mkdir(parents=True)
    (clone2 / "a" / "Foo.java").write_text("class Foo {}", encoding="utf-8")
    (clone2 / "b" / "Foo.java").write_text("class Foo {}", encoding="utf-8")
    assert library.module_of_symbol("Foo", clone2, context_dir=ctx) is None

    # módulo sem página correspondente → None
    clone3 = tmp_path / "clone3"
    (clone3 / "c").mkdir(parents=True)
    (clone3 / "c" / "Bar.java").write_text("class Bar {}", encoding="utf-8")
    assert library.module_of_symbol("Bar", clone3, context_dir=ctx) is None


def test_library_pages_for_matches_by_file_prefix(tmp_path):
    clone = tmp_path  # não usado para arquivos (só prefixo do caminho)
    result = library.pages_for([], ["siga-cp/src/main/java/X.java"], clone)
    assert [r["module"] for r in result] == ["siga-cp"]
    assert result[0]["page"] == "siga-cp.md"
    # nada reconhecível → lista vazia (nunca inventar)
    assert library.pages_for(["SimboloInexistente"], [], clone) == []


@pytest.mark.skipif(not HAS_CLONE, reason="clone do SIGA ausente (CI)")
def test_siga_context_includes_context_library_pointers():
    from tools.siga_context import siga_context

    r = siga_context(symbols=["ExBL"], task="integração G06", repo=CLONE)
    assert r["context_library"], "ExBL deve apontar para a página do siga-ex"
    modules = {e["module"] for e in r["context_library"]}
    assert "siga-ex" in modules
    for entry in r["context_library"]:
        assert Path(entry["path"]).is_file(), entry["path"]


@pytest.mark.skipif(not HAS_CLONE, reason="clone do SIGA ausente (CI)")
def test_siga_context_no_page_for_unknown_symbol():
    from tools.siga_context import siga_context

    r = siga_context(symbols=["SemEssaClasse123"], task="t", repo=CLONE)
    lib_pages = {e["module"] for e in r["context_library"]}
    assert "SemEssaClasse123" not in lib_pages
    assert r["context_library"] == [] or all(
        Path(e["path"]).is_file() for e in r["context_library"]
    )
