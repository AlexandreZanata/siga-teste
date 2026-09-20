"""H04: cápsula referencial v2 (docs/19 §4). Só stdlib, offline."""

from __future__ import annotations

import subprocess

import pytest

from context.referential import build_referential_capsule, fetch_snippet
from tools.siga_context import siga_context

JAVA = "package mod;\npublic class Alfa {\n private int x;\n public void run() {}\n}\n"


def _repo(tmp_path):
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "Alfa.java").write_text(JAVA, encoding="utf-8")
    (tmp_path / "mod" / "view.jsp").write_text("jsp", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    return tmp_path


def test_refs_resolvem_modulo_def_e_outline(tmp_path):
    root = _repo(tmp_path)
    cap = build_referential_capsule("t", ["Alfa"], repo=root)
    assert len(cap["refs"]) == 1
    ref = cap["refs"][0]
    assert ref["id"] == "mod/Alfa.java::Alfa"
    assert ref["module"] == "mod"
    assert ref["def_lines"] == [2, 2]
    assert "run" in ref["outline"]["methods"]


def test_simbolo_desconhecido_nao_inventa_ref(tmp_path):
    cap = build_referential_capsule("t", ["Fantasma"], repo=_repo(tmp_path))
    assert cap["refs"] == []


def test_fetch_roundtrip_teto_e_travas(tmp_path):
    root = _repo(tmp_path)
    got = fetch_snippet(root, "mod/Alfa.java::Alfa", max_lines=2)
    assert got["lines"] == [1, 2] and "public class Alfa" in got["content"]
    with pytest.raises(ValueError):
        fetch_snippet(root, "../fora.java::X")
    with pytest.raises(ValueError):
        fetch_snippet(root, "mod/sumiu.java::X")
    with pytest.raises(ValueError):
        fetch_snippet(root, "mod/Alfa.java::Alfa", max_lines=0)
    with pytest.raises(ValueError):
        fetch_snippet(root, "sem-separador")


def test_mode_default_intacto_e_referencial_economiza(tmp_path):
    root = _repo(tmp_path)
    full = siga_context(["Alfa"], "t", repo=root)
    assert "capsule_text" in full and "snippets" in full
    ref = siga_context(["Alfa"], "t", repo=root, mode="referential")
    assert ref["mode"] == "referential" and len(ref["refs"]) == 1
    assert ref["token_estimate"] <= ref["full_token_estimate"]
    with pytest.raises(ValueError):
        siga_context(["Alfa"], "t", repo=root, mode="gigante")
