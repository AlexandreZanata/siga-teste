"""F21: correções dos diagnósticos ref2 (history intersecta, trace expande)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tools.siga_history import siga_history
from tools.siga_trace import siga_trace


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "siga-ex").mkdir(parents=True)
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "t@e", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)
    (repo / "siga-ex" / "a.java").write_text("class A {}\n", encoding="utf-8")
    _git("add", ".", cwd=repo)
    _git("commit", "-qm", "assunto tramite", cwd=repo)
    (repo / "siga-ex" / "a.java").write_text("class A { int x; }\n", encoding="utf-8")
    _git("commit", "-qam", "outro assunto", cwd=repo)
    (repo / "siga-ex" / "b.java").write_text("class B {}\n", encoding="utf-8")
    _git("add", ".", cwd=repo)
    _git("commit", "-qm", "assunto tramite em b", cwd=repo)
    (repo / "siga-ex" / "Alfa.java").write_text("public class Alfa {}\n", encoding="utf-8")
    (repo / "siga-ex" / "Beta.java").write_text("public class Beta { Alfa a; }\n", encoding="utf-8")
    _git("add", ".", cwd=repo)
    _git("commit", "-qm", "cadeia alfa beta", cwd=repo)
    return repo


def test_history_intersecta_query_com_target(tmp_path):
    repo = _repo(tmp_path)
    out = siga_history(target="siga-ex/a.java", query="tramite", repo=repo)
    assert out["query_matched"] is True
    assert [c["subject"] for c in out["commits"]] == ["assunto tramite"]
    out2 = siga_history(target="siga-ex/a.java", query="zzz-sem-match", repo=repo)
    assert out2["query_matched"] is False
    assert len(out2["commits"]) == 2


def test_history_so_query_inalterado(tmp_path):
    repo = _repo(tmp_path)
    out = siga_history(query="tramite", repo=repo)
    assert out["query_matched"] is None
    assert len(out["commits"]) == 2


def test_trace_sem_grafo_expande_callers(tmp_path):
    repo = _repo(tmp_path)
    out = siga_trace("Alfa", depth=2, repo=repo)
    hops = {n["hop"] for n in out["chain"]}
    assert 0 in hops and 1 in hops, out["chain"]
    hop1_files = [n["file"] for n in out["chain"] if n["hop"] == 1]
    assert any(str(f).endswith("Beta.java") for f in hop1_files)
    shallow = siga_trace("Alfa", depth=1, repo=repo)
    assert {n["hop"] for n in shallow["chain"]} <= {0, 1}
    assert all(Path(n["file"]).is_file() for n in out["chain"] if n.get("file"))
