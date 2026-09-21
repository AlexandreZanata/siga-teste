"""Testes do J02 — runtime dirigido pelo perfil (docs/20 §2/§5, ADR-035).

Cobre:
- perfil default neutro e resolução env > sentinela > default (fail-closed);
- byte-compatibilidade: com o perfil SIGA ativo, `_slice_globs` reproduz
  exatamente os globs hardcodados antigos (`siga-ex/**`, `sigaex/**`);
- escopo dirigindo o runtime de verdade: com perfil custom (tmp), busca
  textual, find_references/find_callers e naive_locate ficam restritos ao
  escopo declarado no perfil — nada do SIGA no código do runtime.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.profile import (
    DEFAULT_RUNTIME_GLOBS,
    PROFILE_ENV_VAR,
    ProfileError,
    active_profile,
    runtime_scope_modules,
)
from retrieval import search
from retrieval.baseline import naive_locate
from retrieval.callgraph import _java_globs
from tools import primitives

SIGA_ROOT = Path(__file__).resolve().parent.parent.parent  # clone ../ somente leitura
SIGA_AVAILABLE = (SIGA_ROOT / "siga-ex").is_dir()


CUSTOM_PROFILE = {
    "name": "demo",
    "languages": ["java"],
    "code_globs": ["src/**"],
    "test_globs": ["src/**/*Test.java"],
    "test_command": ["true"],
    "module_discovery": "glob",
    "scope_modules": ["src"],
}


@pytest.fixture()
def custom_profile_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Ativa um perfil custom (escopo `src`) e um repo tmp com código dentro e fora do escopo."""
    profile_path = tmp_path / "project.json"
    profile_path.write_text(json.dumps(CUSTOM_PROFILE), encoding="utf-8")
    monkeypatch.setenv(PROFILE_ENV_VAR, str(profile_path))

    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "Widget.java").write_text("class Widget {\n  void go() { helper(); }\n}\n", encoding="utf-8")
    (repo / "vendor" / "Other.java").parent.mkdir()
    (repo / "vendor" / "Other.java").write_text("class Other { Widget w; }\n", encoding="utf-8")
    return repo


# ------------------------------------------------------------- resolução ----


def test_default_profile_is_neutral_chassis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PROFILE_ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)  # sem sentinela ao lado
    profile = active_profile()
    assert profile.name == "default"
    assert profile.code_globs == DEFAULT_RUNTIME_GLOBS
    assert profile.code_scope_modules() == ()  # repo inteiro, sem slice


def test_env_profile_overrides_everything(custom_profile_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(custom_profile_env)  # mesmo com cwd em outro lugar, env vence
    profile = active_profile()
    assert profile.name == "demo"
    assert profile.code_scope_modules() == ("src/",)


def test_env_profile_invalid_path_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(PROFILE_ENV_VAR, str(tmp_path / "nao-existe.json"))
    with pytest.raises(ProfileError, match="nao-existe.json"):
        active_profile()


def test_siga_sentinel_activates_siga_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PROFILE_ENV_VAR, raising=False)
    fake = tmp_path / "checkout"
    (fake / "siga-ex").mkdir(parents=True)
    (fake / "siga-teste").mkdir()
    (fake / "siga-teste" / "profiles" / "siga").mkdir(parents=True)
    (fake / "siga-teste" / "profiles" / "siga" / "project.json").write_text(
        json.dumps({**CUSTOM_PROFILE, "name": "siga", "scope_modules": ["siga-ex", "sigaex"]}),
        encoding="utf-8",
    )
    monkeypatch.chdir(fake / "siga-teste")
    profile = active_profile()
    assert profile.name == "siga"
    assert profile.code_scope_modules() == ("siga-ex/", "sigaex/")


@pytest.mark.skipif(not SIGA_AVAILABLE, reason="Clone do SIGA não disponível ao lado")
def test_siga_profile_runtime_values_are_byte_compatible() -> None:
    """Com o sentinela real (cwd no siga-teste), o runtime vê os valores antigos."""
    profile = active_profile()
    assert profile.name == "siga"
    assert runtime_scope_modules() == ("siga-ex/", "sigaex/")  # == SLICE_MODULES antigo
    assert profile.code_globs == ("**/*.java", "**/*.jsp", "**/*.sql")  # cobertura (J01)
    # byte-compat: referência cruzada entre módulos do escopo continua visível
    cross = [Path(r["file"]).as_posix() for r in primitives.find_references(SIGA_ROOT, "ExDocumento")]
    assert any("/sigaex/" in p for p in cross)


# ---------------------------------------------------------------- runtime ----


def test_slice_globs_byte_compatible_with_old_hardcode() -> None:
    if SIGA_AVAILABLE:
        assert search._slice_globs(SIGA_ROOT) == ["siga-ex/**", "sigaex/**"]
    else:
        # Sem clone, o default neutro aplica os globs genéricos (nunca repo inteiro silencioso)
        assert search._slice_globs(SIGA_ROOT) == list(DEFAULT_RUNTIME_GLOBS)


def test_search_text_unscoped_is_verbatim_but_scope_first(custom_profile_env: Path) -> None:
    """Sem globs explícitos, `search_text` é `rg` verbatim (repo inteiro);
    a restrição ao escopo acontece nas tools, que passam os globs do perfil
    (find_references/find_callers/naive_locate). O ranking é escopo-primeiro."""
    ranked = [Path(h["file"]).name for h in search.search_text(custom_profile_env, "Widget")]
    assert ranked[0] == "Widget.java"  # escopo antes de vendor/


def test_find_references_and_callers_respect_profile_scope(custom_profile_env: Path) -> None:
    refs = [Path(r["file"]).name for r in primitives.find_references(custom_profile_env, "Widget")]
    callers = [Path(c["file"]).name for c in primitives.find_callers(custom_profile_env, "Widget")]
    assert refs == ["Widget.java"]
    assert callers == ["Widget.java"]


def test_naive_locate_respects_profile_scope(custom_profile_env: Path) -> None:
    top = naive_locate(custom_profile_env, "Widget helper", limit=5)
    assert top
    assert all("/vendor/" not in p for p in top)


def test_rank_file_prioritizes_active_scope(custom_profile_env: Path) -> None:
    inside = str(custom_profile_env / "src" / "Widget.java")
    outside = str(custom_profile_env / "vendor" / "Other.java")
    assert search._rank_file(inside, "widget") < search._rank_file(outside, "widget")


def test_callgraph_java_globs_follow_profile(custom_profile_env: Path) -> None:
    assert _java_globs() == ["src/**/*.java"]


def test_callgraph_java_globs_byte_compatible_on_siga() -> None:
    if SIGA_AVAILABLE:
        assert _java_globs() == ["siga-ex/**/*.java", "sigaex/**/*.java"]
    else:
        assert _java_globs() == [f"{m}**/*.java" for m in search._DEFAULT_SCOPE_MODULES]


def test_module_filter_is_generic_no_siga_hardcode(custom_profile_env: Path) -> None:
    """O filtro de shards é genérico por construção: aceita o módulo do perfil
    custom sem nenhuma lista fixa de nomes."""
    from tools.module_shards import filter_by_module

    cands = [
        {"file": str(custom_profile_env / "src" / "Widget.java")},
        {"file": str(custom_profile_env / "vendor" / "Other.java")},
    ]
    kept = [Path(c["file"]).name for c in filter_by_module(cands, "src", custom_profile_env)]
    assert kept == ["Widget.java"]
