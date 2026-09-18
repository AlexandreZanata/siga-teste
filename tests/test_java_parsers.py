"""Gatilho P02/ADR-010 executado (F07, docs/05): Tree-sitter vs javalang.

Validações (na fixture espelho — roda no CI; mesmos asserts valem no clone):
- Ambos extraem package, tipos, métodos e aninhados das 3 âncoras.
- Acordo total de símbolos entre os parsers na fixture.
- Diferença documentada: Tree-sitter tolera arquivo quebrado; javalang
  levanta JavaSyntaxError (veredito F07, não defeito).
- Comparador publica estrutura válida de relatório + run tracking válido.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.log import validate_record
from indexer import java_symbols as tree_sitter
from indexer import javalang_symbols as javalang_mod
from scripts.compare_java_parsers import compare_file, decide_verdict, run_comparison

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def fixture_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from tests.siga_fixture import build_siga_fixture

    return build_siga_fixture(tmp_path_factory.mktemp("siga-fixture-parsers"))


def _anchor_paths(fixture_root: Path) -> dict[str, Path]:
    base = fixture_root / "siga-ex/src/main/java/br/gov/jfrj/siga/ex"
    legacy = fixture_root / "sigaex/src/legacy/java/br/gov/jfrj/siga/vraptor"
    return {
        "ExTramiteBL": base / "bl/ExTramiteBL.java",
        "ExBL": base / "bl/ExBL.java",
        "ExDocumentoController": legacy / "ExDocumentoController.java",
    }


def _methods(record: dict) -> set[str]:
    names: set[str] = set()

    def rec(types: list[dict]) -> None:
        for type_rec in types:
            names.update(method.get("name", "") for method in type_rec.get("methods", []))
            rec(type_rec.get("nested", []))

    rec(record["types"])
    return {name for name in names if name}


def test_both_parsers_extract_anchors(fixture_root: Path):
    anchors = _anchor_paths(fixture_root)
    tram = tree_sitter.parse_file(anchors["ExTramiteBL"])
    assert tram["package"] == "br.gov.jfrj.siga.ex.bl"
    assert "calcularTramitesPendentes" in _methods(tram)
    assert any(nested["name"] == "Pendencias" for nested in tram["types"][0]["nested"])

    tram_jl = javalang_mod.parse_file(anchors["ExTramiteBL"])
    assert tram_jl["package"] == "br.gov.jfrj.siga.ex.bl"
    assert "calcularTramitesPendentes" in _methods(tram_jl)
    assert any(nested["name"] == "Pendencias" for nested in tram_jl["types"][0]["nested"])

    ctrl = tree_sitter.parse_file(anchors["ExDocumentoController"])
    ctrl_jl = javalang_mod.parse_file(anchors["ExDocumentoController"])
    assert ctrl["package"] == ctrl_jl["package"] == "br.gov.jfrj.siga.vraptor"
    assert "Controller" in ctrl["types"][0]["annotations"]
    assert "Controller" in ctrl_jl["types"][0]["annotations"]
    assert ctrl["types"][0]["extends"] == ctrl_jl["types"][0]["extends"] == "ExController"


def test_parsers_agree_on_fixture_symbols(fixture_root: Path):
    from tests.siga_fixture import fixture_java_files

    for path in fixture_java_files(fixture_root):
        result = compare_file(path)
        assert result["ts_parse_ok"] is True
        assert result["jl_parse_ok"] is True
        assert result["package_equal"] is True
        assert result["symbol_agreement"] == 1.0, f"divergência em {path.name}"


def test_tolerance_difference_is_documented(tmp_path: Path):
    broken = tmp_path / "Quebrado.java"
    broken.write_text("public class Quebrado { void m( { }\n", encoding="utf-8")
    tolerant = tree_sitter.parse_file(broken)
    assert [t["name"] for t in tolerant["types"]] == ["Quebrado"]
    with pytest.raises(Exception):
        javalang_mod.parse_file(broken)


def test_compare_report_and_tracking_structure(fixture_root: Path, tmp_path: Path):
    from tests.siga_fixture import fixture_java_files

    files = fixture_java_files(fixture_root)[:3]
    report = run_comparison(files, tmp_path, log_run=True, save=True)
    assert report["files_compared"] == 3
    assert report["ts_parse_rate"] == 1.0
    assert report["jl_parse_rate"] == 1.0
    assert report["verdict"]["decision"] == "keep-tree-sitter"
    assert "report_sha256" in report and "experiment_id" in report
    saved = json.loads((tmp_path / "experiments/reports/java_parser_comparison.json").read_text(encoding="utf-8"))
    assert saved["verdict"]["decision"] == "keep-tree-sitter"
    validate_record(json.loads((tmp_path / "experiments/runs" / f"{report['experiment_id']}.json").read_text(encoding="utf-8")))


def test_verdict_switches_only_on_rescue():
    assert decide_verdict([])["decision"] == "INCONCLUSIVO"
    rescued = [{"file": "a.java", "ts_parse_ok": False, "jl_parse_ok": True, "symbol_agreement": 0.0}]
    assert decide_verdict(rescued)["decision"] == "switch-candidate"
