"""Busca determinística (P03-T01, ADR-012 em docs/05; fallback F01).

ripgrep sobre o checkout real (verdade atual) + `git ls-files` para
arquivos + FTS do graph para símbolos. Sem `rg` no PATH, cai para varredura
puro-Python literal com o mesmo contrato. Tudo retornado existe em disco:
zero hallucination de path por construção. Só stdlib.
"""

from __future__ import annotations

import fnmatch
import json
import shutil
import subprocess
from pathlib import Path

SLICE_MODULES = ("siga-ex/", "sigaex/")

FALLBACK_MAX_BYTES = 8 * 1024 * 1024


def _repo(repo: str | Path) -> Path:
    return Path(repo)


def search_text(
    repo: str | Path,
    pattern: str,
    globs: list[str] | None = None,
    limit: int = 20,
    case_insensitive: bool = False,
) -> list[dict]:
    """Matches literais (`rg --json -F`, case-sensitive por padrão). Com `rg` usa `rg --json -F`; sem `rg`, fallback puro-Python. Retorna [{file, lines[]}]."""
    root = _repo(repo)
    if shutil.which("rg") is None:
        return _search_python(root, pattern, globs=globs, limit=limit, case_insensitive=case_insensitive)
    cmd = ["rg", "--json", "-F", "--no-messages", pattern, "."]
    if case_insensitive:
        cmd.append("-i")
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


def _glob_match(rel_posix: str, globs: list[str] | None) -> bool:
    """Aproximação documentada de `rg --glob`: fnmatch + prefixo `**/` opcional."""
    if not globs:
        return True
    for glob in globs:
        if fnmatch.fnmatch(rel_posix, glob):
            return True
        if glob.startswith("**/") and fnmatch.fnmatch(rel_posix, glob[3:]):
            return True
    return False


def _list_files(root: Path) -> list[str]:
    """Relativos posix dos arquivos candidatos (`git ls-files`, ou rglob sem `.git`)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        return [line for line in out.stdout.splitlines() if line.strip()]
    except (subprocess.SubprocessError, OSError):
        return [
            p.relative_to(root).as_posix()
            for p in sorted(root.rglob("*"))
            if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts
        ]


def _search_python(
    root: Path,
    pattern: str,
    globs: list[str] | None = None,
    limit: int = 20,
    case_insensitive: bool = False,
) -> list[dict]:
    """Varredura literal linha a linha (fallback sem `rg`): mesmo contrato e ranking."""
    hits: dict[str, set[int]] = {}
    needle = pattern.lower() if case_insensitive else pattern
    for rel in _list_files(root):
        if not _glob_match(rel, globs):
            continue
        path = root / rel
        try:
            if path.stat().st_size > FALLBACK_MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            hay = line.lower() if case_insensitive else line
            if needle in hay:
                hits.setdefault(str(path), set()).add(lineno)
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
