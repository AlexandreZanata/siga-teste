"""H01: shards por módulo + filtro no locate (docs/19 §4). Só stdlib, offline."""

from __future__ import annotations

import subprocess

import pytest

from tools.module_shards import (
    filter_by_module,
    iter_modules,
    module_of,
    shard_stats,
    validate_module,
)
from tools.siga_locate import siga_locate


def _repo(tmp_path) -> object:
    (tmp_path / "siga-ex" / "src").mkdir(parents=True)
    (tmp_path / "siga-ex" / "src" / "ExBL.java").write_text("class ExBL {}", encoding="utf-8")
    (tmp_path / "sigaex" / "page").mkdir(parents=True)
    (tmp_path / "sigaex" / "page" / "edita.jsp").write_text("jsp", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "README.md").write_text("doc", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    return tmp_path


def test_module_of_primeiro_segmento(tmp_path):
    assert module_of("siga-ex/src/ExBL.java") == "siga-ex"
    assert module_of("sigaex/page/edita.jsp") == "sigaex"
    assert module_of(str(tmp_path / "siga-ex" / "a.java"), tmp_path) == "siga-ex"
    with pytest.raises(ValueError):
        module_of("../fora.java")
    with pytest.raises(ValueError):
        module_of(str(tmp_path / "siga-ex" / "a.java"))
    with pytest.raises(ValueError):
        module_of("/etc/passwd", tmp_path)


def test_iter_modules_so_codigo_ou_pom(tmp_path):
    root = _repo(tmp_path)
    assert iter_modules(root) == ["siga-ex", "sigaex"]


def test_shard_stats_conta_java_jsp(tmp_path):
    stats = shard_stats(_repo(tmp_path))
    assert stats["siga-ex"] == {"java": 1, "jsp": 0}
    assert stats["sigaex"] == {"java": 0, "jsp": 1}


def test_validate_module():
    assert validate_module(None) is None
    assert validate_module("siga-ex") == "siga-ex"
    with pytest.raises(ValueError):
        validate_module("../x")
    with pytest.raises(ValueError):
        validate_module("")


def test_filter_preserva_sem_arquivo_e_sem_filtro(tmp_path):
    cands = [{"file": "siga-ex/a.java"}, {"file": None, "symbol": "X"}, {"file": "sigaex/b.jsp"}]
    assert filter_by_module(cands, None) == cands
    kept = filter_by_module(cands, "siga-ex")
    assert [c.get("file") for c in kept] == ["siga-ex/a.java", None]
    abs_cands = [{"file": str(tmp_path / "siga-ex" / "a.java")}, {"file": "/etc/passwd"}]
    kept_abs = filter_by_module(abs_cands, "siga-ex", tmp_path)
    assert [c.get("file") for c in kept_abs] == [str(tmp_path / "siga-ex" / "a.java"), "/etc/passwd"]


def test_locate_com_filtro_de_modulo(tmp_path):
    from pathlib import Path as _P

    root = _repo(tmp_path)
    all_hits = siga_locate("ExBL", repo=root)
    assert all_hits, "sintético deve localizar sem filtro"
    mod_hits = siga_locate("ExBL", repo=root, module="siga-ex")
    assert mod_hits
    for h in mod_hits:
        f = h.get("file")
        assert f is None or module_of(f, root) == "siga-ex"
        assert f is None or _P(f).is_file(), f"path inventado: {f}"
    assert siga_locate("ExBL", repo=root, module="modulo-inexistente-xyz") == []
    with pytest.raises(ValueError):
        siga_locate("ExBL", repo=root, module="../x")
