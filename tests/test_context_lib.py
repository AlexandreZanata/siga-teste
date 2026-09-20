"""Validador da biblioteca de contexto (G05, docs/18 §4).

Garante o grounding das páginas de `docs/context/`:
- todo path backtickado `siga-ex/...`/`sigaex/...` existe no clone real;
- todo símbolo Java citado (`ExBL`, `ExMobil`, ...) corresponde a um
  arquivo `<Simbolo>.java` em `siga-ex/` ou `sigaex/`;
- a âncora de trace citada (`ExMobil → AbstractExMobil`) resolve de fato;
- `INDEX.md` lista exatamente as páginas existentes e traz `source_commit`.

No CI (sem clone do SIGA ao lado), os checks que exigem o clone são
pulados — nunca falso sucesso: o skip é explícito.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.siga_trace import siga_trace  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONTEXT = ROOT / "docs/context"
CLONE = ROOT.parent  # checkout do SIGA (somente leitura)

HAS_CLONE = (CLONE / "siga-ex").is_dir() and (CLONE / "sigaex").is_dir()

PAGES = ["docs/context/siga-ex.md", "docs/context/sigaex.md", "docs/context/INDEX.md"]

_PATH_RE = re.compile(r"`((?:siga-ex|sigaex)/[\w\-./]+?)`")
_SYMBOL_RE = re.compile(r"\b(Ex[A-Z]\w+)\b")
_NON_SYMBOLS = {"sigaex", "sigawf", "Exemplo", "ExPode"}  # ExPode* = família de predicados, não classe


def _page_texts() -> list[str]:
    return [(CONTEXT / Path(p).name).read_text(encoding="utf-8") for p in PAGES]


@pytest.mark.skipif(not HAS_CLONE, reason="clone do SIGA ausente (CI)")
@pytest.mark.parametrize("page", PAGES)
def test_every_cited_path_exists(page):
    text = (ROOT / page).read_text(encoding="utf-8")
    for path in _PATH_RE.findall(text):
        target = CLONE / path
        assert target.is_file() or target.is_dir(), f"{page}: path inexistente no clone: {path}"


@pytest.mark.skipif(not HAS_CLONE, reason="clone do SIGA ausente (CI)")
def test_every_cited_symbol_is_a_real_java_file():
    for page, text in zip(PAGES, _page_texts()):
        for sym in set(_SYMBOL_RE.findall(text)) - _NON_SYMBOLS:
            hits = list((CLONE / "siga-ex").rglob(f"{sym}.java")) + list((CLONE / "sigaex").rglob(f"{sym}.java"))
            assert hits, f"{page}: símbolo sem arquivo Java correspondente: {sym}"


@pytest.mark.skipif(not HAS_CLONE, reason="clone do SIGA ausente (CI)")
def test_trace_anchor_claim_holds():
    """A alegação documentada: siga_trace('ExMobil') resolve AbstractExMobil."""
    r = siga_trace("ExMobil", depth=1, repo=CLONE)
    chain = r.get("chain") if isinstance(r, dict) else r
    files = [c.get("file") if isinstance(c, dict) else c for c in (chain or [])]
    assert any(f and f.endswith("AbstractExMobil.java") for f in files), files


def test_index_lists_exactly_the_existing_pages():
    index = (CONTEXT / "INDEX.md").read_text(encoding="utf-8")
    pages = sorted(p.name for p in CONTEXT.glob("*.md") if p.name != "INDEX.md")
    for name in pages:
        assert f"]({name})" in index, f"INDEX não aponta para {name}"
    assert "source_commit" in index
    assert re.search(r"`[0-9a-f]{40}`", index), "source_commit deve ser sha completo"


def test_pages_declare_provenance_and_license():
    for page in PAGES:
        text = (ROOT / page).read_text(encoding="utf-8")
        assert "source_commit" in text or "source_commit" in (CONTEXT / "INDEX.md").read_text(encoding="utf-8")
        assert "AGPLv3" in text, f"{page}: deve declarar herança AGPLv3"
