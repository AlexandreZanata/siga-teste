"""Verificadores determinísticos (P06-T01, ADR-016 em docs/08).

Implementa verificações determinísticas de candidatos a gold:
- AST: símbolos, classes, métodos existem no código-fonte via Tree-sitter
- Symbol: símbolos existem nos nós do grafo
- Grep: padrões textuais ocorrem nos arquivos via ripgrep
- Git: commits e arquivos tocados conferem com histórico real
- Diff: linhas adicionadas/removidas conferem com o diff real do Git
- Maven: módulos existem no pom.xml raiz
- Testes: classes de teste existem e referenciam o alvo
- Anti-leakage: ausência de qualquer SHA do benchmark
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
from functools import lru_cache

from indexer import java_symbols, maven_modules
from retrieval import search

MANIFEST_PATH = (
    Path(__file__).resolve().parent.parent / "datasets/benchmark/manifest.json"
)


def check_ast(repo: Path, file_rel_or_abs: str, expected_symbol: str) -> bool:
    """Verifica via Tree-sitter se expected_symbol está declarado no arquivo Java."""
    p = Path(file_rel_or_abs)
    if not p.is_file():
        p = repo / file_rel_or_abs
    if not p.is_file():
        return False
    try:
        data = java_symbols.parse_file(p)
        for t in data.get("types", []):
            if t["name"] == expected_symbol:
                return True
            for m in t.get("methods", []):
                if m["name"] == expected_symbol or f"{t['name']}::{m['name']}" == expected_symbol:
                    return True
        return False
    except Exception:
        return False


def check_symbol(conn: sqlite3.Connection, symbol: str) -> bool:
    """Verifica se o símbolo existe no grafo de nós SQLite."""
    row = conn.execute(
        "SELECT id FROM nodes WHERE name = ? OR name LIKE ? LIMIT 1",
        (symbol, f"%{symbol}"),
    ).fetchone()
    return row is not None


@lru_cache(maxsize=8192)
def check_grep(repo: Path, pattern: str, globs: tuple[str, ...] | None = None) -> bool:
    """Verifica via ripgrep se o padrão textual existe no repositório.

    Pura em (repo, pattern, globs) e com repositório imutável durante o processo:
    cache LRU evita re-varrer o repo inteiro para padrões repetidos.
    """
    hits = search.search_text(repo, pattern, globs=list(globs) if globs else None, limit=1)
    return len(hits) > 0


def check_git(repo: Path, sha: str, file_rel: str | None = None) -> bool:
    """Verifica se o commit SHA existe no repositório Git e tocou o arquivo."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-t", sha],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        if out.stdout.strip() != "commit":
            return False
        if file_rel:
            files_out = subprocess.run(
                ["git", "-C", str(repo), "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            files = {line.strip() for line in files_out.stdout.splitlines()}
            return file_rel in files or any(file_rel in f for f in files)
        return True
    except Exception:
        return False


def check_diff(repo: Path, sha: str, snippet: str) -> bool:
    """Verifica se o fragmento de diff realmente pertence ao commit."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "show", "--no-color", "--format=", sha],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return snippet.strip() in out.stdout
    except Exception:
        return False


def check_maven(repo: Path, module_name: str) -> bool:
    """Verifica se o módulo Maven existe no pom.xml do repositório."""
    pom = repo / "pom.xml"
    if not pom.is_file():
        return False
    try:
        info = maven_modules.parse_root_pom(pom, repo_root=repo)
        module_names = [m["name"] for m in info["modules"]]
        return module_name in module_names
    except Exception:
        return False


def check_tests(repo: Path, test_file_rel: str, target_symbol: str) -> bool:
    """Verifica se o arquivo de teste existe e menciona o símbolo alvo."""
    p = repo / test_file_rel if not Path(test_file_rel).is_file() else Path(test_file_rel)
    if not p.is_file():
        return False
    content = p.read_text(encoding="utf-8", errors="replace")
    return target_symbol in content


def check_anti_leakage(candidate_text: str, manifest_path: Path = MANIFEST_PATH) -> bool:
    """Garante que nenhum SHA do benchmark contamina o candidato."""
    if not manifest_path.is_file():
        return True
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        bench_shas = {
            sha
            for split in ("train", "valid", "test")
            for sha in manifest.get("splits", {}).get(split, [])
        }
        for sha in bench_shas:
            if sha in candidate_text:
                return False
        return True
    except Exception:
        return False
