"""Tool semântica siga_history (P05-T02, ADR-013 em docs/06).

Ação: Mudanças semelhantes e co-change no Git.
Args:
  - target?: símbolo ou caminho de arquivo real
  - query?: texto para buscar em mensagens de commit
  - since?: data inicial da busca
  - limit?: limite de commits retornados (default 10)
Retorna:
  Dicionário com commits relevantes, diff recente e parceiros de co-alteração.
  H02: `resolved_target` (alvo no HEAD), commits com `renames` e
  `files_at_head` ([{path, exists}] resolvidos p/ HEAD).
Comandos Git estritamente somente leitura.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
import subprocess
from typing import Any

from indexer.git_history import cochange_partners
from tools import primitives


def _resolve_repo(repo: str | Path | None) -> Path:
    if repo is not None:
        return Path(repo).resolve()
    parent = Path(__file__).resolve().parent.parent.parent
    if (parent / "siga-ex").is_dir():
        return parent
    return Path(__file__).resolve().parent.parent


def siga_history(
    target: str | None = None,
    query: str | None = None,
    since: str | None = None,
    limit: int = 10,
    repo: str | Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Recupera histórico Git de um alvo ou query com diffs e co-alterações."""
    if target is None and query is None:
        raise ValueError("Ao menos um entre target e query deve ser fornecido")
    if limit < 1:
        raise ValueError(f"limit deve ser >= 1, recebido {limit}")

    root = _resolve_repo(repo)

    target_path: str | None = None
    if target:
        if (root / target).is_file():
            try:
                target_path = str((root / target).resolve().relative_to(root))
            except ValueError:
                target_path = target
        elif Path(target).is_file():
            try:
                target_path = str(Path(target).resolve().relative_to(root))
            except ValueError:
                target_path = target
        else:
            pattern = target if target.endswith((".java", ".jsp", ".sql")) else f"{target}.java"
            matches = primitives.find_file(root, pattern, limit=1)
            if matches:
                try:
                    target_path = str(Path(matches[0]).resolve().relative_to(root))
                except ValueError:
                    target_path = matches[0]
            else:
                target_path = target

    commits: list[dict[str, Any]] = []
    if target_path:
        commits = primitives.git_history(root, path=target_path, limit=limit)
    elif query:
        cmd = [
            "git",
            "-C",
            str(root),
            "log",
            f"-{limit}",
            f"--grep={query}",
            "--format=%H%x00%s%x00%ad%x00%an",
            "--date=short",
        ]
        if since:
            cmd.append(f"--since={since}")
        out = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
        for line in out.stdout.splitlines():
            parts = line.split("\x00")
            if len(parts) >= 4 and parts[0]:
                sha, subject, date, author = parts[0], parts[1], parts[2], parts[3]
                commits.append(
                    {
                        "sha": sha,
                        "subject": subject,
                        "date": date,
                        "author": author,
                        "files": [],
                    }
                )

    recent_diff: dict[str, Any] | None = None
    if commits:
        latest_sha = commits[0]["sha"]
        recent_diff = primitives.git_diff(root, commit=latest_sha, path=target_path)

    cochanges: list[dict[str, Any]] = []
    if target_path:
        cochanges = cochange_partners(root, target_path, limit_commits=100)

    # H02: alvo resolvido p/ HEAD + arquivos de cada commit resolvidos p/ HEAD
    # (renomeações atravessadas; no máximo 30 arquivos/commit p/ custo limitado).
    resolved_target = primitives.resolve_to_head(root, target_path) if target_path else None
    for commit in commits:
        at_head = []
        for f in (commit.get("files") or [])[:30]:
            resolved = primitives.resolve_to_head(root, f)
            at_head.append({"path": resolved, "exists": (root / resolved).is_file()})
        commit["files_at_head"] = at_head

    return {
        "target": target,
        "query": query,
        "resolved_target": resolved_target,
        "commits": commits,
        "recent_diff": recent_diff,
        "changed_with": cochanges[:10],
    }
