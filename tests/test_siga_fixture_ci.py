"""F03: comportamento da fixture como base dos testes no CI (docs/15 §6).

Modo default (sem env): fixture de espelho gerada a cada uso — é o que roda
no CI de fundação. Com SIGA_CLONE_DIR apontando para um clone do SIGA: a
fixture é ignorada em favor do clone. CI não define a env, portanto o modo
default é o que vige no verify.
"""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path

import pytest

from tests import siga_fixture


@pytest.fixture()
def reload_fixture():
    """Recarrega o módulo da fixture para cada teste de env."""
    importlib.reload(siga_fixture)
    yield
    importlib.reload(siga_fixture)


def test_default_mode_generates_mirror_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reload_fixture):
    monkeypatch.delenv("SIGA_CLONE_DIR", raising=False)
    root = siga_fixture.resolve_siga_root(tmp_path)
    assert root != tmp_path, "sem env, fixture gerada em árvore temporária própria"
    assert str(root).startswith(tempfile.gettempdir()), "fixture deve nascer sob temp dir gerenciado"
    assert (root / "siga-ex").is_dir()
    assert (root / "sigaex").is_dir()


def test_clone_env_overrides_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reload_fixture):
    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / "siga-ex").mkdir()
    monkeypatch.setenv("SIGA_CLONE_DIR", str(clone))
    root = siga_fixture.resolve_siga_root(tmp_path)
    assert root == clone
    assert not (tmp_path / "siga-ex").exists(), "fixture não deveria ter sido gerada"


def test_clone_env_with_missing_dir_falls_back_to_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reload_fixture
):
    monkeypatch.setenv("SIGA_CLONE_DIR", str(tmp_path / "clone-inexistente"))
    root = siga_fixture.resolve_siga_root(tmp_path)
    assert (root / "siga-ex").is_dir(), "env inválida deve cair para a fixture gerada"
    assert root != tmp_path / "clone-inexistente"


def test_module_never_imports_real_sigamodules(tmp_path: Path):
    src = Path(siga_fixture.__file__).read_text(encoding="utf-8")
    assert str(tmp_path) not in src
    forbidden = ["PESSOAL-PROJETOS-ALEXANDRE", "/home/"]
    for token in forbidden:
        assert token not in src, f"fixture não pode referenciar ambiente local: {token}"
