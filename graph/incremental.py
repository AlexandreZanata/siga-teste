"""Update incremental do graph (P02-T03, docs/05 §3).

`git pull` + `git diff --name-only OLD..NEW` + reparse só dos afetados.
Somente leitura no Git; reparse via indexers de P02-T01/T02.
`git pull` real no clone de produção NUNCA roda em teste.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from graph import store
from indexer import java_symbols, jsp_symbols, sql_tables


def changed_files(repo: str | Path, old_sha: str, new_sha: str) -> dict:
    """Arquivos alterados/adicionados/removidos entre SHAs (só leitura)."""
    out = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-status", "-z", f"{old_sha}..{new_sha}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    changed: list[str] = []
    removed: list[str] = []
    tokens = [t for t in out.stdout.split("\x00") if t]
    changed: list[str] = []
    removed: list[str] = []
    i = 0
    while i < len(tokens):
        code = tokens[i][0]
        if code == "R":  # R100\x00OLD\x00NEW
            removed.append(tokens[i + 1])
            changed.append(tokens[i + 2])
            i += 3
        elif code in ("A", "M", "T"):
            changed.append(tokens[i + 1])
            i += 2
        elif code == "D":
            removed.append(tokens[i + 1])
            i += 2
        else:
            i += 1
    return {"changed": sorted(changed), "removed": sorted(removed)}


def apply_incremental(
    conn,
    repo: str | Path,
    old_sha: str,
    new_sha: str,
) -> dict:
    """Reparseia só afetados (.java/.jsp/.sql); remove deletados. Retorna stats."""
    started = time.perf_counter()
    repo_root = Path(repo)
    diff = changed_files(repo, old_sha, new_sha)
    updated = 0
    for rel in diff["changed"]:
        path = repo_root / rel
        if not path.is_file():
            continue
        store.delete_file(conn, str(path))
        if rel.endswith(".java"):
            store.upsert_java(conn, java_symbols.parse_file(path))
            updated += 1
        elif rel.endswith(".jsp"):
            store.upsert_jsp(conn, jsp_symbols.parse_file(path))
            updated += 1
        elif rel.endswith(".sql"):
            store.upsert_migration(conn, sql_tables.parse_migration(path))
            updated += 1
    removed = 0
    for rel in diff["removed"]:
        removed += store.delete_file(conn, str(repo_root / rel))
    conn.commit()
    return {
        "old_sha": old_sha,
        "new_sha": new_sha,
        "changed": len(diff["changed"]),
        "removed_files": len(diff["removed"]),
        "updated": updated,
        "removed_nodes": removed,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }
