"""Shards por módulo do repositório (H01, docs/19 §4).

Cada arquivo pertence ao shard do diretório de primeiro nível
(`siga-ex`, `sigaex`, `siga-cp`, ...). O locate usa o shard para
filtrar candidatos ao módulo da tarefa, em vez de ranquear o repo
inteiro — passo H01 rumo a recall@5 0.65 sem despejar milhares de
arquivos na IA grande. Só stdlib, determinístico.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def module_of(path: str | Path, root: str | Path | None = None) -> str:
    """Shard de um path (primeiro segmento relativo à raiz).

    Absoluto exige `root` para relativizar; sem root, ValueError.
    """
    text = str(path).replace("\\", "/")
    parts = Path(text).parts
    if parts and parts[0] not in (".", "..", "/", ""):
        return parts[0]
    if root is None:
        raise ValueError(f"path inválido para shard sem root: {path!r}")
    try:
        rel = Path(text).relative_to(Path(root).resolve())
    except ValueError:
        raise ValueError(f"path fora da raiz para shard: {path!r}") from None
    if not rel.parts or rel.parts[0] in (".", ".."):
        raise ValueError(f"path inválido para shard: {path!r}")
    return rel.parts[0]


def iter_modules(root: str | Path) -> list[str]:
    """Módulos = diretórios de primeiro nível com código ou pom."""
    root = Path(root)
    modules: list[str] = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        has_code = any(entry.rglob("*.java"))
        has_jsp = any(entry.rglob("*.jsp"))
        has_pom = (entry / "pom.xml").is_file()
        if has_code or has_jsp or has_pom:
            modules.append(entry.name)
    return modules


def shard_stats(root: str | Path) -> dict[str, dict[str, int]]:
    """Contagem .java/.jsp por módulo (para priorizar shards no locate)."""
    root = Path(root)
    stats: dict[str, dict[str, int]] = {}
    for module in iter_modules(root):
        base = root / module
        stats[module] = {
            "java": sum(1 for _ in base.rglob("*.java")),
            "jsp": sum(1 for _ in base.rglob("*.jsp")),
        }
    return stats


def validate_module(module: str | None) -> str | None:
    """Formato de módulo; None passa (sem filtro)."""
    if module is None:
        return None
    if not isinstance(module, str) or not module.strip():
        raise ValueError("module deve ser string não vazia ou None")
    clean = module.strip().strip("/")
    if not clean or clean in (".", "..") or "/" in clean or "\\" in clean:
        raise ValueError(f"module inválido: {module!r}")
    return clean


def filter_by_module(
    candidates: list[dict[str, Any]],
    module: str | None,
    root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Mantém candidatos do shard; sem arquivo ou sem shard atribuível passam."""
    module = validate_module(module)
    if module is None:
        return list(candidates)
    kept: list[dict[str, Any]] = []
    for cand in candidates:
        file = cand.get("file")
        if file is None:
            kept.append(cand)
            continue
        try:
            same = module_of(str(file), root) == module
        except ValueError:
            same = True
        if same:
            kept.append(cand)
    return kept
