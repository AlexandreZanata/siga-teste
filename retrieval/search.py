"""Busca determinística (P03-T01, ADR-012 em docs/05).

ripgrep sobre o checkout real (verdade atual) + `git ls-files` para
arquivos + FTS do graph para símbolos. Tudo retornado existe em disco:
zero hallucination de path por construção. Só stdlib + rg no PATH.
"""

from __future__ import annotations

import fnmatch
import json
import subprocess
from pathlib import Path

SLICE_MODULES = ("siga-ex/", "sigaex/")


def _repo(repo: str | Path) -> Path:
    return Path(repo)


def search_text(
    repo: str | Path,
    pattern: str,
    globs: list[str] | None = None,
    limit: int = 20,
) -> list[dict]:
    """Matches literais via `rg --json -F` (case-sensitive). Retorna [{file, lines[]}]."""
    root = _repo(repo)
    cmd = ["rg", "--json", "-F", "--no-messages", pattern, "."]
    for glob in globs or []:
        cmd += ["--glob", glob]
    out = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=120)
    hits: dict[str, set[int]] = {}
    for line in out.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        rel = event["data"]["path"]["text"]
        path = str(root / rel)
        lineno = event["data"]["line_number"]
        hits.setdefault(path, set()).add(lineno)
    ranked = sorted(hits, key=lambda f: (_rank_file(f, pattern), f))
    return [{"file": f, "lines": sorted(hits[f])} for f in ranked[:limit]]


def _rank_file(path: str, pattern: str) -> tuple[int, int]:
    """Determinístico: basename com o termo primeiro, slice antes do resto."""
    base = path.rsplit("/", 1)[-1].lower()
    in_slice = 0 if any(m in path for m in SLICE_MODULES) else 1
    return (0 if pattern.lower() in base else 1, in_slice)


def find_files(repo: str | Path, name_part: str, limit: int = 20) -> list[str]:
    """Arquivos tracked cujo basename contém name_part (git ls-files + fnmatch)."""
    root = _repo(repo)
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    matches = [
        line
        for line in out.stdout.splitlines()
        if fnmatch.fnmatch(line.rsplit("/", 1)[-1].lower(), f"*{name_part.lower()}*")
    ]
    matches.sort(key=lambda f: (_rank_file(f, name_part), f))
    return [str(root / m) if not m.startswith("/") else m for m in matches[:limit]]


def find_references(repo: str | Path, symbol: str, limit: int = 20) -> list[dict]:
    """Ocorrências word-boundary do símbolo no slice (`rg -w`)."""
    return search_text(repo, symbol, globs=["siga-ex/**", "sigaex/**"], limit=limit)


def find_symbol(conn, name: str, limit: int = 20) -> list[dict]:
    """Símbolos no índice (graph.store.search_fts). Verdade = índice; rg = atual."""
    from graph import store

    return store.search_fts(conn, name, limit=limit)
