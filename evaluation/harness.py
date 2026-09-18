"""Harness temporal do SIGA-Bench (P04-T01, docs/10 ADR-018, docs/07 §3).

Converte commits reais em tarefas (mensagem→arquivos; parent = estado N-1
cuja região deve ser prevista vs diff N) e impõe splits temporais
train < T1 < valid < T2 < test. Anti-leakage por SHA, verificável por máquina.
Somente leitura no Git. Só stdlib.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TRAIN_DIRS = ("raw", "canonical", "verified")


def _run(repo: str | Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return out.stdout


def commit_info(repo: str | Path, sha: str) -> dict:
    """Metadados + arquivos de um commit real (subject, data, parent, files)."""
    if not SHA_RE.match(sha):
        raise ValueError(f"SHA inválido: {sha!r}")
    fmt = _run(repo, "show", "--no-patch", "--format=%H%x00%P%x00%ad%x00%s", "--date=short", sha)
    parts = fmt.strip().split("\x00")
    full, parent, date, subject = parts[0], parts[1].split()[0] if parts[1] else None, parts[2], parts[3]
    files = sorted(
        line
        for line in _run(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).splitlines()
        if line.strip()
    )
    return {"sha": full, "parent": parent, "date": date, "subject": subject, "files": files}


def commit_task(repo: str | Path, sha: str) -> dict:
    """Commit → tarefa: prever arquivos a partir da mensagem no estado N-1."""
    info = commit_info(repo, sha)
    return {
        "id": f"git-{info['sha'][:12]}",
        "repo_commit": info["sha"],
        "parent_commit": info["parent"],
        "date": info["date"],
        "query": info["subject"],
        "task_type": "commit-localization",
        "ground_truth_files": info["files"],
        "source": "git",
    }


def temporal_split(tasks: list[dict], t1: str, t2: str) -> dict:
    """Divide por data do commit: train < t1 <= valid < t2 <= test. t1<t2 exigido."""
    if not t1 < t2:
        raise ValueError(f"splits inválidos: t1={t1} t2={t2} (exige t1<t2)")
    splits = {"train": [], "valid": [], "test": []}
    for task in tasks:
        date = task["date"]
        if date < t1:
            splits["train"].append(task)
        elif date < t2:
            splits["valid"].append(task)
        else:
            splits["test"].append(task)
    return splits


def find_leakage(bench_shas: set[str], texts: list[str]) -> set[str]:
    """SHAs do bench presentes nos textos (puro, sem I/O)."""
    return {sha for sha in bench_shas for text in texts if sha in text}


def check_no_leakage(bench_shas: set[str], datasets_root: str | Path) -> None:
    """Varre datasets/{raw,canonical,verified}/**/*.jsonl; levanta se houver SHA do bench."""
    root = Path(datasets_root)
    texts = [
        path.read_text(encoding="utf-8", errors="replace")
        for dirname in TRAIN_DIRS
        for path in (root / dirname).rglob("*.jsonl")
        if path.is_file()
    ]
    leaked = find_leakage(bench_shas, texts)
    if leaked:
        raise ValueError(f"LEAKAGE bench→train: {sorted(leaked)}")


def validate_manifest(manifest: dict) -> None:
    """Schema mínimo do manifest: keys, T1<T2, SHAs 40hex, splits disjuntos."""
    for key in ("version", "branch", "t1", "t2", "splits"):
        if key not in manifest:
            raise ValueError(f"manifest sem {key!r}")
    if not manifest["t1"] < manifest["t2"]:
        raise ValueError("manifest exige t1<t2")
    seen: set[str] = set()
    for split in ("train", "valid", "test"):
        shas = manifest["splits"].get(split, [])
        for sha in shas:
            if not SHA_RE.match(sha):
                raise ValueError(f"SHA inválido em {split}: {sha!r}")
            if sha in seen:
                raise ValueError(f"SHA repetido entre splits: {sha[:12]}")
            seen.add(sha)


def write_manifest(path: str | Path, manifest: dict) -> Path:
    """Persiste manifest.validado (JSON ordenado)."""
    validate_manifest(manifest)
    out = Path(path)
    out.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return out


def load_manifest(path: str | Path) -> dict:
    """Lê e valida manifest persistido."""
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_manifest(manifest)
    return manifest


def bench_shas(manifest: dict) -> set[str]:
    """Todos os SHAs do bench (qualquer split)."""
    return {sha for split in ("train", "valid", "test") for sha in manifest["splits"].get(split, [])}
