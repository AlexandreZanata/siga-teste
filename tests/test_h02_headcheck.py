"""H02: history com --follow + resolução p/ HEAD + drop de stale (docs/19)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from graph import store
from indexer import java_symbols
from tools import primitives
from tools.siga_history import siga_history
from tools.siga_locate import siga_locate

JAVA = "package ex;\npublic class Stale {\n public void run() {}\n}\n"


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "mod").mkdir(parents=True)
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "t@e", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)
    (repo / "mod" / "a.java").write_text(JAVA, encoding="utf-8")
    _git("add", ".", cwd=repo)
    _git("commit", "-qm", "cria a", cwd=repo)
    _git("mv", "mod/a.java", "mod/b.java", cwd=repo)
    _git("commit", "-qm", "renomeia a para b", cwd=repo)
    return repo


def test_history_follow_atravessa_rename(tmp_path):
    repo = _repo(tmp_path)
    hist = primitives.git_history(repo, path="mod/b.java", limit=10)
    assert [c["subject"] for c in hist] == ["renomeia a para b", "cria a"]
    assert hist[0]["renames"] == [{"from": "mod/a.java", "to": "mod/b.java"}]
    assert hist[1]["renames"] == []


def test_resolve_to_head_mapeia_antigo_para_novo(tmp_path):
    repo = _repo(tmp_path)
    assert primitives.resolve_to_head(repo, "mod/a.java") == "mod/b.java"
    assert primitives.resolve_to_head(repo, "mod/b.java") == "mod/b.java"
    assert primitives.resolve_to_head(repo, "mod/sumiu.java") == "mod/sumiu.java"


def test_siga_history_traz_resolved_e_files_at_head(tmp_path):
    repo = _repo(tmp_path)
    out = siga_history(target="mod/b.java", repo=repo)
    assert out["resolved_target"] == "mod/b.java"
    old = [c for c in out["commits"] if c["subject"] == "cria a"][0]
    by_path = {e["path"]: e["exists"] for e in old["files_at_head"]}
    assert by_path.get("mod/b.java") is True


def test_locate_com_grafo_descarta_stale(tmp_path):
    repo = _repo(tmp_path)
    target = repo / "mod" / "stale.java"
    target.write_text(JAVA.replace("Stale", "StaleUnico"), encoding="utf-8")
    conn = store.connect()
    store.upsert_java(conn, java_symbols.parse_file(target))
    conn.commit()
    assert siga_locate("StaleUnico", repo=repo, conn=conn, limit=5), "antes de deletar deve achar"
    target.unlink()
    hits = siga_locate("StaleUnico", repo=repo, conn=conn, limit=5)
    assert all(h.get("file") is None or "stale.java" not in str(h["file"]) for h in hits)
