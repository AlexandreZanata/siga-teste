"""Precisão do indexer Java na amostra etiquetada (P02-T01, ADR-010).

Alvo definido aqui: recall 1.0 em todos os símbolos-âncora abaixo
(extraídos do código real em 2026-09-18, branch desenvolvimento) +
nenhum path inventado (todo file do resultado existe em disco).
Se o recall cair, o gatilho é trocar p/ JavaParser/JDT (docs/05).
"""

from __future__ import annotations

from pathlib import Path

from indexer.java_symbols import index_files, parse_file

SIGA = Path(__file__).resolve().parent.parent.parent

EX_TRAMITE = SIGA / "siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl/ExTramiteBL.java"
EX_BL = SIGA / "siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl/ExBL.java"
EX_DOC_CTRL = SIGA / "sigaex/src/legacy/java/br/gov/jfrj/siga/vraptor/ExDocumentoController.java"

SAMPLE = [EX_TRAMITE, EX_BL, EX_DOC_CTRL]


def _methods(rec: dict, type_name: str) -> set[str]:
    for t in rec["types"]:
        if t["name"] == type_name:
            return {m["name"] for m in t["methods"]}
    return set()


def test_sample_files_exist_no_invented_paths():
    for path in SAMPLE:
        assert path.is_file(), f"amostra sumiu do clone: {path}"
    for rec in index_files(SAMPLE):
        assert Path(rec["file"]).is_file()


def test_ex_tramite_bl_anchors():
    rec = parse_file(EX_TRAMITE)
    assert rec["package"] == "br.gov.jfrj.siga.ex.bl"
    assert "calcularTramitesPendentes" in _methods(rec, "ExTramiteBL")
    nested = next(t for t in rec["types"][0]["nested"] if t["name"] == "Pendencias")
    assert "getRecebimentosPendentesSemNotificacoes" in {m["name"] for m in nested["methods"]}
    assert any(i.endswith("siga.base.util.Utils") for i in rec["imports"])


def test_ex_bl_anchors():
    rec = parse_file(EX_BL)
    assert rec["package"] == "br.gov.jfrj.siga.ex.bl"
    methods = _methods(rec, "ExBL")
    for anchor in ("assinarDocumento", "cancelarMovimentacao", "arquivarCorrente"):
        assert anchor in methods, f"âncora ausente: {anchor}"


def test_ex_documento_controller_anchors():
    rec = parse_file(EX_DOC_CTRL)
    assert rec["package"] == "br.gov.jfrj.siga.vraptor"
    ctrl = next(t for t in rec["types"] if t["name"] == "ExDocumentoController")
    assert "Controller" in ctrl["annotations"]
    assert ctrl["extends"] == "ExController"
    assert "br.com.caelum.vraptor.Controller" in rec["imports"]
    assert "jakarta.inject.Inject" in rec["imports"]


def test_slice_coverage_counts():
    java_files = [
        p
        for module in ("siga-ex", "sigaex")
        for p in (SIGA / module).rglob("*.java")
        if "__pycache__" not in p.parts
    ]
    assert len(java_files) >= 700, f"slice encolheu inesperadamente: {len(java_files)}"
    recs = index_files(java_files)
    assert len(recs) == len(java_files)
    names = {t["name"] for r in recs for t in r["types"]}
    for anchor in ("ExBL", "ExTramiteBL", "ExDocumentoController"):
        assert anchor in names
