"""Graph + incremental + reconciliação rg×FTS (P02-T03, ADR-011/012).

100% autocontido: repo git temporário com Java/JSP/SQL sintéticos.
Nada aqui lê o clone do SIGA — passa em qualquer checkout limpo (CI).
Latência do slice real é medida ad-hoc e publicada no PROGRESS (P02-T03).
"""

from __future__ import annotations

import statistics
import subprocess
import time
from pathlib import Path

from graph import incremental, store
from indexer import java_symbols, jsp_symbols, sql_tables

ALUNO_JAVA = """package br.exemplo.escola;
import java.util.List;
public class Aluno extends Pessoa {
    private String matricula;
    public String getMatricula() { return matricula; }
    public void matricular(String turma) {}
}
"""

PESSOA_JAVA = """package br.exemplo.escola;
public class Pessoa {
    protected String nome;
    public String getNome() { return nome; }
}
"""

TURMA_JAVA = """package br.exemplo.escola;
public class Turma {
    public void adicionar(Aluno a) {}
}
"""

EXIBE_JSP = '<%@ include file="cabecalho.jsp"%>\n<html>${aluno.matricula}</html>\n'
CABECALHO_JSP = "<header>escola</header>\n"

MIGR_SQL = "CREATE TABLE escola.aluno (id NUMBER PRIMARY KEY, matricula VARCHAR2(32));\n"


def _git(*args: str, cwd: Path) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@e", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return out.stdout.strip()


def _seed_repo(root: Path) -> None:
    _git("init", "-b", "main", cwd=root)
    (root / "Aluno.java").write_text(ALUNO_JAVA)
    (root / "Pessoa.java").write_text(PESSOA_JAVA)
    (root / "Turma.java").write_text(TURMA_JAVA)
    (root / "exibe.jsp").write_text(EXIBE_JSP)
    (root / "cabecalho.jsp").write_text(CABECALHO_JSP)
    (root / "V001__aluno.sql").write_text(MIGR_SQL)
    _git("add", ".", cwd=root)
    _git("commit", "-m", "seed", cwd=root)


def _populate(conn, root: Path) -> None:
    for java in sorted(root.glob("*.java")):
        store.upsert_java(conn, java_symbols.parse_file(java))
    for jsp in sorted(root.glob("*.jsp")):
        store.upsert_jsp(conn, jsp_symbols.parse_file(jsp))
    for sql in sorted(root.glob("*.sql")):
        store.upsert_migration(conn, sql_tables.parse_migration(sql))
    conn.commit()


def test_trace_3hop_finds_chain(tmp_path: Path):
    _seed_repo(tmp_path)
    conn = store.connect()
    _populate(conn, tmp_path)
    chain = store.trace(conn, "matricular", depth=3)
    names = {step["name"] for step in chain}
    assert "Aluno::matricular" in names
    assert "Aluno" in names
    assert any(step["hop"] >= 1 for step in chain)


def test_fts_matches_rg_no_drift(tmp_path: Path):
    _seed_repo(tmp_path)
    conn = store.connect()
    _populate(conn, tmp_path)
    out = subprocess.run(
        ["rg", "-l", "--no-messages", "matricula", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    rg_files = {line for line in out.stdout.splitlines() if line.strip()}
    fts_files = {hit["file"] for hit in store.search_fts(conn, "matricula", limit=50)}
    assert fts_files, "FTS vazio para termo presente"
    assert fts_files <= rg_files, f"FTS além de rg (drift): {fts_files - rg_files}"


def test_incremental_reparses_only_affected(tmp_path: Path):
    _seed_repo(tmp_path)
    conn = store.connect()
    _populate(conn, tmp_path)
    old_sha = _git("rev-parse", "HEAD", cwd=tmp_path)
    evolved = ALUNO_JAVA.replace(
        "    public void matricular(String turma) {}\n}",
        "    public void matricular(String turma) {}\n    public void evadir() {}\n}",
    )
    (tmp_path / "Aluno.java").write_text(evolved)
    (tmp_path / "cabecalho.jsp").unlink()
    _git("add", "-A", cwd=tmp_path)
    _git("commit", "-m", "evadir", cwd=tmp_path)
    new_sha = _git("rev-parse", "HEAD", cwd=tmp_path)
    stats = incremental.apply_incremental(conn, tmp_path, old_sha, new_sha)
    assert stats["updated"] == 1, stats
    assert stats["removed_files"] == 1, stats
    chain = store.trace(conn, "evadir", depth=2)
    assert any(s["name"] == "Aluno::evadir" for s in chain)
    assert store.search_fts(conn, "cabecalho", limit=50) == []


def test_trace_latency_budget(tmp_path: Path):
    _seed_repo(tmp_path)
    conn = store.connect()
    _populate(conn, tmp_path)
    symbols = ["matricular", "Aluno", "getNome", "Turma", "escola.aluno"]
    samples = []
    for _ in range(4):
        for symbol in symbols:
            started = time.perf_counter()
            store.trace(conn, symbol, depth=3)
            samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    p50 = statistics.median(samples)
    p95 = samples[min(len(samples) - 1, int(len(samples) * 0.95))]
    print(f"\nfixture trace 3-hop: n={len(samples)} P50={p50:.2f}ms P95={p95:.2f}ms")
    assert p95 < 500, f"P95 acima do teto: {p95:.2f}ms"
