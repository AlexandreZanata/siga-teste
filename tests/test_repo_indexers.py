"""Indexers JSP/SQL/Maven/Git (P02-T02): ExDocumento liga tabelas+migration+JSPs.

Âncoras do código real (desenvolvimento, 2026-09-18). Co-change testado em
repo temporário determinístico; no clone real, só contrato read-only.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from indexer import git_history, jsp_symbols, maven_modules, sql_tables

SIGA = Path(__file__).resolve().parent.parent.parent
EX_DOCUMENTO = SIGA / "siga-ex/src/main/java/br/gov/jfrj/siga/ex/ExDocumento.java"
MIGR_DIR = SIGA / "siga-ex/src/main/resources/db/migration"
V104 = MIGR_DIR / "SIGA_UTF8_V104__Documento_com_Principal.sql"
WEBAPP = SIGA / "sigaex/src/main/webapp"
EXIBE = WEBAPP / "WEB-INF/page/exDocumento/exibe.jsp"


def test_ex_documento_table_and_migration():
    assert sql_tables.entity_table(EX_DOCUMENTO) == "siga.ex_documento"
    rec = sql_tables.parse_migration(V104)
    assert rec["version"] == "104"
    assert "siga.ex_documento" in rec["writes"]
    hits = sql_tables.migrations_touching(MIGR_DIR, "siga.ex_documento")
    assert str(V104) in hits


def test_ex_documento_jsps_and_include():
    refs = jsp_symbols.find_referencing(WEBAPP, "ExDocumento")
    assert str(EXIBE) in refs
    assert len(refs) >= 3
    rec = jsp_symbols.parse_file(EXIBE)
    marcar = next(i for i in rec["includes"] if i["raw"] == "marcar.jsp")
    assert marcar["static"] and marcar["exists"]


def test_maven_modules_active_and_commented():
    rec = maven_modules.parse_root_pom(SIGA / "pom.xml", repo_root=SIGA)
    names = [m["name"] for m in rec["modules"]]
    assert len(names) == 24
    assert "siga-ex" in names and "sigaex" in names
    assert "siga-arq" in rec["commented"] and "siga-arq" not in names
    assert all(m["exists"] for m in rec["modules"])


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@e", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        timeout=60,
    )


def test_git_readonly_contract_on_real_clone():
    commits = git_history.recent_commits(SIGA, limit=5)
    assert len(commits) >= 1
    assert len(commits[0]["sha"]) == 40
    assert git_history.files_in_commit(SIGA, commits[0]["sha"])


def test_cochange_partners_deterministic(tmp_path: Path):
    _git("init", "-b", "main", cwd=tmp_path)
    (tmp_path / "A.txt").write_text("a")
    (tmp_path / "B.txt").write_text("b")
    _git("add", ".", cwd=tmp_path)
    _git("commit", "-m", "ab", cwd=tmp_path)
    (tmp_path / "A.txt").write_text("a2")
    _git("commit", "-am", "a", cwd=tmp_path)
    partners = git_history.cochange_partners(tmp_path, "A.txt")
    assert partners[0] == {"path": "B.txt", "cochanges": 1, "of_commits": 2}
