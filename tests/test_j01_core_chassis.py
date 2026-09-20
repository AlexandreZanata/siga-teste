"""Testes do J01 — chassi genérico core/ + profiles/siga (docs/20 §5).

Cobre o DoD da ramificação na parte extraível agora:
- contrato de perfil fail-closed (schema, estratégias, JSON malformado);
- discovery Maven real sobre o clone SIGA (25 módulos medidos, ordem do pom);
- cobertura de código/testes pelos globs do perfil, restrita a `src/main`
  (coerência com o baseline: siga-ex 501/237, sigaex 270);
- isolamento por perfil: nada do SIGA hardcodado no core;
- boundary: core sem imports SIGA-acoplados (ver test_boundaries.py).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.discovery import (
    coverage_by_module,
    discover_modules,
    matches_any,
    maven_modules,
    module_sources,
    module_test_sources,
)
from core.profile import ProfileError, from_dict, load_profile
from profiles.siga import PROFILE_PATH, load as load_siga

SIGA_ROOT = Path(__file__).resolve().parent.parent.parent  # clone ../ somente leitura
SIGA_AVAILABLE = (SIGA_ROOT / "pom.xml").is_file()

MINIMAL = {
    "name": "demo",
    "languages": ["java"],
    "code_globs": ["**/*.java"],
    "test_globs": ["**/src/test/**/*.java"],
    "test_command": ["mvn", "test"],
    "module_discovery": "maven",
}


# ---------------------------------------------------------------- perfil ----


def test_siga_profile_loads_and_matches_baseline() -> None:
    profile = load_siga()
    assert profile.name == "siga"
    assert profile.module_discovery == "maven"
    assert profile.languages == ("java", "jsp", "sql")
    assert profile.symbol_suffixes == ("BL", "Controller", "DAO", "Service")


def test_profile_missing_required_field_fails_closed(tmp_path: Path) -> None:
    broken = {k: v for k, v in MINIMAL.items() if k != "test_command"}
    p = tmp_path / "project.json"
    p.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(ProfileError, match="test_command"):
        load_profile(p)


def test_profile_malformed_json_cites_file(tmp_path: Path) -> None:
    p = tmp_path / "project.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ProfileError, match="project.json"):
        load_profile(p)


def test_profile_unknown_strategy_fails_closed() -> None:
    bad = dict(MINIMAL, module_discovery="npm")
    with pytest.raises(ProfileError, match="module_discovery"):
        from_dict(bad)


def test_profile_unknown_symbol_strategy_fails_closed() -> None:
    bad = dict(MINIMAL, symbol_strategy="regex")
    with pytest.raises(ProfileError, match="symbol_strategy"):
        from_dict(bad)


def test_profile_from_dict_rejects_non_object() -> None:
    with pytest.raises(ProfileError, match="objeto JSON"):
        from_dict(["siga"])


def test_profile_empty_globs_rejected() -> None:
    bad = dict(MINIMAL, code_globs=[])
    with pytest.raises(ProfileError, match="code_globs"):
        from_dict(bad)


def test_profile_load_missing_file() -> None:
    with pytest.raises(ProfileError, match="não encontrado"):
        load_profile("/inexistente/project.json")


# -------------------------------------------------------------- discovery ----


class FakeMaven:
    """Perfil mínimo maven para testes sem clone."""

    def __init__(self) -> None:
        self.module_discovery = "maven"
        self.code_globs = ("**/*.java",)
        self.test_globs = ("**/src/test/java/**/*.java",)
        self.module_roots = ()


def test_maven_modules_empty_without_pom(tmp_path: Path) -> None:
    assert maven_modules(tmp_path) == []


@pytest.mark.skipif(not SIGA_AVAILABLE, reason="clone SIGA indisponível")
def test_siga_modules_match_measured_baseline() -> None:
    profile = load_siga()
    mods = discover_modules(SIGA_ROOT, profile)
    assert len(mods) == 24  # pom.xml atual (INDEX G06: "24 de 24 módulos Maven ativos")
    assert mods[:2] == ["siga-base", "siga-ws"]  # ordem do pom
    assert "siga-ex" in mods and "sigaex" in mods


@pytest.mark.skipif(not SIGA_AVAILABLE, reason="clone SIGA indisponível")
def test_siga_coverage_matches_baseline_counts() -> None:
    profile = load_siga()
    cov = coverage_by_module(SIGA_ROOT, profile)
    # Ground truth do INDEX (G05/G06): siga-ex 501 .java + 172 SQLs; sigaex 237 .java + 597 JSPs.
    assert cov["siga-ex"] == {"code": 673, "tests": 5}
    assert cov["sigaex"] == {"code": 834, "tests": 0}


@pytest.mark.skipif(not SIGA_AVAILABLE, reason="clone SIGA indisponível")
def test_module_sources_are_relative_and_exist() -> None:
    profile = load_siga()
    files = module_sources(SIGA_ROOT, "siga-ex", profile)
    assert files, "siga-ex precisa ter arquivos de código"
    assert all(not f.startswith("/") for f in files)
    assert all((SIGA_ROOT / f).is_file() for f in files)
    assert all("/src/main/" in f"/{f}" or f.startswith("siga-ex/src/main") for f in files)


@pytest.mark.skipif(not SIGA_AVAILABLE, reason="clone SIGA indisponível")
def test_module_test_sources_hit_siga_ex_tests() -> None:
    profile = load_siga()
    tests = module_test_sources(SIGA_ROOT, "siga-ex", profile)
    assert tests, "siga-ex precisa ter testes"
    assert all("/src/test/" in f for f in tests)


def test_explicit_discovery_filters_missing_roots(tmp_path: Path) -> None:
    (tmp_path / "mod-a").mkdir()
    profile = from_dict(
        dict(MINIMAL, module_discovery="explicit", module_roots=["mod-a", "mod-b"]),
        source="test",
    )
    assert discover_modules(tmp_path, profile) == ["mod-a"]


def test_glob_discovery_uses_profile_globs(tmp_path: Path) -> None:
    (tmp_path / "pkg" / "src").mkdir(parents=True)
    (tmp_path / "pkg" / "src" / "A.java").write_text("class A {}", encoding="utf-8")
    profile = from_dict(dict(MINIMAL, module_discovery="glob"), source="test")
    assert discover_modules(tmp_path, profile) == ["pkg"]


# ------------------------------------------------------------ isolamento ----


def test_profile_json_contains_no_siga_hardcode_in_core() -> None:
    """O core não pode citar nomes do SIGA — o perfil é quem declara o projeto."""
    for py in (Path(__file__).resolve().parent.parent / "core").glob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert "siga-ex" not in text, f"{py.name} hardcoda módulo do SIGA"
        assert "ExBL" not in text, f"{py.name} hardcoda símbolo do SIGA"


def test_matches_any_endings() -> None:
    assert matches_any("mod/src/main/java/X.java", ("**/*.java",))
    assert matches_any("X.java", ("**/*.java",))  # ** casa zero segmentos
    assert matches_any("deep/nested/X.java", ("**/*.java",))
    assert not matches_any("X.jsp", ("**/*.java",))
    assert matches_any("a/b/src/test/java/T.java", ("**/src/test/java/**/*.java",))
    assert not matches_any("a/b/src/main/java/T.java", ("**/src/test/java/**/*.java",))


def test_siga_profile_file_is_valid_json_with_source_note() -> None:
    data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    assert data["name"] == "siga"
    assert "source" in data and data["source"]
