"""F03: a fixture SIGA mínima deve reproduzir os âncoras consumidos pelos testes.

Gabaritos extraídos por leitura read-only do clone real (desenvolvimento,
2026-09-18). A fixture é gerada a cada uso em árvore temporária; se um
gabarito divergir do âncora real, este teste falha antes do CI usar a fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from indexer import sql_tables
from indexer.java_symbols import parse_file
from indexer.jsp_symbols import find_referencing, parse_file as parse_jsp
from indexer.maven_modules import parse_root_pom
from retrieval.callgraph import method_callees
from retrieval.search import find_files, search_text
from tests.siga_fixture import build_siga_fixture, fixture_java_files, verify_fixture_java

_ANCHOR_CALLEES = {"contemAlgumTramite", "equivaleENaoENulo", "igual", "getApensos", "hasRecebimento"}


@pytest.fixture(scope="module")
def fixture_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Uma única fixture por módulo (barata: árvore pequena + 1 commit)."""
    return build_siga_fixture(tmp_path_factory.mktemp("siga-fixture"))


def test_fixture_mirrors_real_slice_layout(fixture_root: Path):
    assert (fixture_root / "siga-ex").is_dir()
    assert (fixture_root / "sigaex").is_dir()
    for anchor in (
        fixture_root / "siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl/ExTramiteBL.java",
        fixture_root / "siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl/ExBL.java",
        fixture_root / "siga-ex/src/main/java/br/gov/jfrj/siga/ex/ExDocumento.java",
        fixture_root / "siga-ex/src/main/java/br/gov/jfrj/siga/ex/ExMobil.java",
        fixture_root / "sigaex/src/legacy/java/br/gov/jfrj/siga/vraptor/ExDocumentoController.java",
        fixture_root / "siga-ex/src/main/resources/db/migration/SIGA_UTF8_V104__Documento_com_Principal.sql",
        fixture_root / "sigaex/src/main/webapp/WEB-INF/page/exDocumento/exibe.jsp",
    ):
        assert anchor.is_file(), f"âncora ausente na fixture: {anchor}"


def test_fixture_java_indexing_matches_real_anchors(fixture_root: Path):
    java_files = fixture_java_files(fixture_root)
    assert len(java_files) >= 7
    recs = verify_fixture_java(fixture_root)
    by_type = {t["name"]: t for r in recs for t in r["types"]}

    tramite = next(r for r in recs if r["file"].endswith("ExTramiteBL.java"))
    assert tramite["package"] == "br.gov.jfrj.siga.ex.bl"
    assert "calcularTramitesPendentes" in {m["name"] for m in tramite["types"][0]["methods"]}
    nested = next(t for t in tramite["types"][0]["nested"] if t["name"] == "Pendencias")
    assert "getRecebimentosPendentesSemNotificacoes" in {m["name"] for m in nested["methods"]}
    assert any(i.endswith("siga.base.util.Utils") for i in tramite["imports"])

    bl = by_type["ExBL"]
    bl_methods = {m["name"] for m in bl["methods"]}
    assert {"assinarDocumento", "cancelarMovimentacao", "arquivarCorrente"} <= bl_methods
    bl_file = next(r for r in recs if r["file"].endswith("ExBL.java"))
    assert bl_file["package"] == "br.gov.jfrj.siga.ex.bl"

    ctrl = by_type["ExDocumentoController"]
    assert "Controller" in ctrl["annotations"]
    assert ctrl["extends"] == "ExController"
    ctrl_file = next(r for r in recs if r["file"].endswith("ExDocumentoController.java"))
    assert ctrl_file["package"] == "br.gov.jfrj.siga.vraptor"
    assert "br.com.caelum.vraptor.Controller" in ctrl_file["imports"]
    assert "jakarta.inject.Inject" in ctrl_file["imports"]


def test_fixture_entity_migration_jsp_maven_match_real_anchors(fixture_root: Path):
    doc_java = fixture_root / "siga-ex/src/main/java/br/gov/jfrj/siga/ex/ExDocumento.java"
    migr_dir = fixture_root / "siga-ex/src/main/resources/db/migration"
    v104 = migr_dir / "SIGA_UTF8_V104__Documento_com_Principal.sql"
    webapp = fixture_root / "sigaex/src/main/webapp"
    exibe = webapp / "WEB-INF/page/exDocumento/exibe.jsp"
    pom = fixture_root / "pom.xml"

    assert sql_tables.entity_table(doc_java) == "siga.ex_documento"
    rec = sql_tables.parse_migration(v104)
    assert rec["version"] == "104"
    assert "siga.ex_documento" in rec["writes"]
    hits = sql_tables.migrations_touching(migr_dir, "siga.ex_documento")
    assert str(v104) in hits

    refs = find_referencing(webapp, "ExDocumento")
    assert str(exibe) in refs
    assert len(refs) >= 3
    rec_jsp = parse_jsp(exibe)
    marcar = next(i for i in rec_jsp["includes"] if i["raw"] == "marcar.jsp")
    assert marcar["static"] and marcar["exists"]

    rec_pom = parse_root_pom(pom, repo_root=fixture_root)
    names = [m["name"] for m in rec_pom["modules"]]
    assert len(names) == 24
    assert "siga-ex" in names and "sigaex" in names
    assert "siga-arq" in rec_pom["commented"] and "siga-arq" not in names
    assert all(m["exists"] for m in rec_pom["modules"])


def test_fixture_supports_retrieval_and_callgraph(fixture_root: Path):
    ex_tramite = fixture_root / "siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl/ExTramiteBL.java"

    hits = search_text(fixture_root, "calcularTramitesPendentes", limit=5)
    assert any(h["file"].endswith("ExTramiteBL.java") for h in hits)

    found = find_files(fixture_root, "ExDocumentoController.java", limit=5)
    assert any(f.endswith("ExDocumentoController.java") for f in found)

    assert _ANCHOR_CALLEES <= method_callees(ex_tramite, "calcularTramitesPendentes")

    parse_file(ex_tramite)


def test_fixture_is_a_git_repo_with_seed_commit(fixture_root: Path):
    assert (fixture_root / ".git").is_dir()
