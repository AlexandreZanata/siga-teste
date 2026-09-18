"""Indexer Git (P02-T02, somente leitura): commits como fonte de CHANGED_WITH.

Apenas comandos read-only (`log`, `diff-tree`, `rev-parse`). Nenhum comando
de escrita é executado aqui — o updater incremental vive em P02-T03.
"""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path


def _run(repo: str | Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return out.stdout


def recent_commits(repo: str | Path, limit: int = 20) -> list[dict]:
    """Últimos commits: [{sha, subject}]."""
    lines = _run(repo, "log", f"-{limit}", "--format=%H%x00%s").splitlines()
    commits = []
    for line in lines:
        sha, _, subject = line.partition("\x00")
        if sha:
            commits.append({"sha": sha, "subject": subject})
    return commits


def files_in_commit(repo: str | Path, sha: str) -> list[str]:
    """Paths tocados por um commit (strings, ordenados)."""
    out = _run(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", sha)
    return sorted(line for line in out.splitlines() if line.strip())


def cochange_partners(repo: str | Path, path: str, limit_commits: int = 200) -> list[dict]:
    """Arquivos que mais co-ocorrem com `path` nos commits (fonte de CHANGED_WITH)."""
    log = _run(repo, "log", f"-{limit_commits}", "--format=%H", "--name-only")
    counts: Counter[str] = Counter()
    current: list[str] = []
    touched = 0

    def flush() -> None:
        nonlocal touched
        if path in current:
            touched += 1
            for other in current:
                if other != path:
                    counts[other] += 1

    for line in log.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) == 40 and all(c in "0123456789abcdef" for c in line):
            flush()
            current = []
        else:
            current.append(line)
    flush()
    return [
        {"path": other, "cochanges": n, "of_commits": touched}
        for other, n in counts.most_common()
    ]
