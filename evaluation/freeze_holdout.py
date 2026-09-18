"""Congela o holdout do bench (P04-T02, docs/10): tarefas commit-localization.

Amostra deterministicamente (seed fixo) commits que tocam 1–8 arquivos
.java/.jsp/.sql do slice por janela temporal. Categorias sintéticas
(ambíguas, off-topic, no-tool, insuficiente) são slots da P06, não aqui.
Somente leitura no Git. Só stdlib.
"""

from __future__ import annotations

import json
import random
import subprocess
from pathlib import Path

from evaluation.harness import commit_task

SLICE_PREFIXES = ("siga-ex/", "sigaex/")
CODE_EXTENSIONS = (".java", ".jsp", ".sql")


def _run(repo: str | Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=300,
    )
    return out.stdout


def candidate_shas(repo: str | Path, since: str, until: str) -> list[str]:
    """SHAs no intervalo [since, until) que tocam 1–8 arquivos de código do slice."""
    shas = _run(repo, "rev-list", "HEAD", f"--since={since}", f"--until={until}", "--", *SLICE_PREFIXES)
    candidates = []
    for sha in shas.splitlines():
        sha = sha.strip()
        if not sha:
            continue
        files = _run(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).splitlines()
        code = [f for f in files if f.strip().endswith(CODE_EXTENSIONS)]
        if 1 <= len(code) <= 8:
            candidates.append(sha)
    return sorted(candidates)


def freeze(
    repo: str | Path,
    out_path: str | Path,
    per_window: int = 100,
    seed: int = 42,
    windows: tuple[tuple[str, str, str], ...] = (
        ("train", "1970-01-01", "2020-01-01"),
        ("valid", "2020-01-01", "2024-01-01"),
        ("test", "2024-01-01", "2030-01-01"),
    ),
) -> dict:
    """Amostra por janela e escreve holdout.jsonl. Retorna contagens."""
    rng = random.Random(seed)
    out = Path(out_path)
    counts: dict[str, int] = {}
    with out.open("w", encoding="utf-8") as fh:
        for split, since, until in windows:
            pool = candidate_shas(repo, since, until)
            picked = rng.sample(pool, min(per_window, len(pool)))
            counts[split] = len(picked)
            for sha in sorted(picked):
                task = commit_task(repo, sha)
                task["split"] = split
                task["category"] = "commit-localization"
                fh.write(json.dumps(task, sort_keys=True, ensure_ascii=False) + "\n")
    counts["seed"] = seed
    return counts
