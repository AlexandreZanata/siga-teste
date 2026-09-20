"""F22: inferência de módulo p/ o locate (3º diagnóstico ref2)."""

from __future__ import annotations

import subprocess

from tools.module_shards import infer_module
from tools.siga_locate import siga_locate


def _repo(tmp_path):
    (tmp_path / "siga-ex").mkdir()
    (tmp_path / "siga-ex" / "Alfa.java").write_text("public class Alfa {}\n", encoding="utf-8")
    (tmp_path / "siga-ex" / "Normativa.java").write_text("public class Normativa {}\n", encoding="utf-8")
    (tmp_path / "sigaex").mkdir()
    (tmp_path / "sigaex" / "Beta.java").write_text("public class Beta {}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    return tmp_path


def test_inferencia_por_mencao_explicita(tmp_path):
    root = _repo(tmp_path)
    assert infer_module("corrigir bug no sigaex hoje", root) == "sigaex"


def test_ambiguidade_retorna_none(tmp_path):
    root = _repo(tmp_path)
    assert infer_module("sincronizar siga-ex com sigaex", root) is None
    assert infer_module("zzz nada aqui", root) is None
    assert infer_module("", root) is None


def test_evidencia_fraca_nao_infere(tmp_path):
    # Votação por símbolos foi medida e rejeitada: sem menção explícita,
    # nunca filtrar no escuro (0 flips em 15 fails + custo de precisão).
    root = _repo(tmp_path)
    assert infer_module("Alfa aplica Normativa vigente", root) is None


def test_auto_filtra_e_none_preserva(tmp_path):
    root = _repo(tmp_path)
    auto = siga_locate("Alfa", repo=root, module="auto", limit=10)
    assert auto and all("siga-ex" in (h.get("file") or "") for h in auto if h.get("file"))
    full = siga_locate("Alfa", repo=root, limit=10)
    assert len(full) >= len(auto)
