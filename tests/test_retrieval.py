"""Baseline determinístico de busca (P03-T01, ADR-012 em docs/05).

Queries reais do slice com gabarito. File Recall@5 publicado aqui:
alvo 1.0 — tudo que o determinístico resolve sem LLM.
Zero hallucination: todo path retornado existe em disco.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from retrieval import outline, search
from retrieval.baseline import naive_locate, terms

SIGA = Path(__file__).resolve().parent.parent.parent

# (método, query, basename esperado no top-5)
QUERIES = [
    ("search_text", "ExDocumentoController", "ExDocumentoController.java"),
    ("search_text", "calcularTramitesPendentes", "ExTramiteBL.java"),
    ("search_text", "SigaRoutesParser", "SigaRoutesParser.java"),
    ("find_files", "marcar.jsp", "marcar.jsp"),
    ("search_text", "ExMobilSelecao", "ExMobilSelecao.java"),
]


def _requires_siga() -> None:
    if not (SIGA / "siga-ex").is_dir():
        pytest.skip("Clone do SIGA não disponível ao lado (CI sem siga-ex)")


def _top5(method: str, query: str) -> list[str]:
    if method == "search_text":
        return [hit["file"] for hit in search.search_text(SIGA, query, limit=5)]
    return search.find_files(SIGA, query, limit=5)


def test_file_recall_at_5_is_total():
    _requires_siga()
    hits = 0
    for method, query, expected in QUERIES:
        top5 = _top5(method, query)
        assert top5, f"sem resultados p/ {query!r}"
        if any(Path(f).name == expected for f in top5):
            hits += 1
        else:
            print(f"\nMISS @{method} {query!r}: {[Path(f).name for f in top5]}")
    recall = hits / len(QUERIES)
    print(f"\ndeterminístico File Recall@5: {recall:.2f} ({hits}/{len(QUERIES)})")
    assert recall == 1.0


def test_zero_path_hallucination():
    _requires_siga()
    probed = [q for _, q, _ in QUERIES]
    for method, query in {m: q for m, q, _ in QUERIES}.items():
        for path in _top5(method, query):
            assert Path(path).is_file(), f"path inventado: {path}"
    assert probed


def test_find_references_word_boundary():
    _requires_siga()
    refs = search.find_references(SIGA, "ExTramiteBL", limit=10)
    assert refs
    assert all(Path(r["file"]).is_file() for r in refs)


def test_naive_locate_terms_and_anchor():
    assert terms("Remove currentView fantasma em assinar_mov_login_senha_gravar") == [
        "remove",
        "currentview",
        "fantasma",
        "assinar",
        "login",
        "senha",
        "gravar",
    ]
    _requires_siga()
    top5 = naive_locate(SIGA, "Evita JSP inexistente após assinar com senha")
    assert any(p.endswith("ExSpringMovimentacaoController.java") for p in top5)
    assert all(Path(p).is_file() for p in top5)


def test_file_outline_without_source():
    with pytest.raises(FileNotFoundError):
        outline.get_file_outline(SIGA / "siga-ex/NaoExiste.java")
    _requires_siga()
    rec = outline.get_file_outline(
        SIGA / "siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl/ExTramiteBL.java"
    )
    assert rec["package"] == "br.gov.jfrj.siga.ex.bl"
    main = next(t for t in rec["types"] if t["name"] == "ExTramiteBL")
    assert "calcularTramitesPendentes" in main["methods"]
    assert any(n["name"] == "Pendencias" for n in main["nested"])


def _seed_repo(root: Path) -> Path:
    (root / "ServicoExemplo.java").write_text(
        "package br.gov.exemplo;\npublic class ServicoExemplo {\n    public void executar() {}\n}\n",
        encoding="utf-8",
    )
    (root / "sub").mkdir(exist_ok=True)
    (root / "sub" / "Outro.java").write_text("public class Outro {}\n", encoding="utf-8")
    (root / "nota.txt").write_text("ServicoExemplo citado aqui\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "seed"],
        check=True,
    )
    return root


def test_search_text_fallback_without_rg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    repo = _seed_repo(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    hits = search.search_text(repo, "ServicoExemplo")
    names = [Path(hit["file"]).name for hit in hits]
    assert "ServicoExemplo.java" in names
    assert "nota.txt" in names
    assert all(Path(hit["file"]).is_file() for hit in hits)
    assert all(hit["lines"] for hit in hits)
    java_hit = next(hit for hit in hits if hit["file"].endswith("ServicoExemplo.java"))
    assert java_hit["lines"] == [2]


def test_search_text_fallback_glob_filtering(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    repo = _seed_repo(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    hits = search.search_text(repo, "class", globs=["sub/**"])
    assert [Path(hit["file"]).name for hit in hits] == ["Outro.java"]


def test_search_text_fallback_parity_with_rg(tmp_path: Path):
    if shutil.which("rg") is None:
        pytest.skip("rg ausente: paridade só faz sentido com rg presente")
    repo = _seed_repo(tmp_path)
    expected = {(hit["file"], tuple(hit["lines"])) for hit in search.search_text(repo, "ServicoExemplo")}
    assert expected, "rg deveria achar ServicoExemplo no repo sintético"
    got = {(hit["file"], tuple(hit["lines"])) for hit in search._search_python(repo, "ServicoExemplo")}
    assert got == expected
