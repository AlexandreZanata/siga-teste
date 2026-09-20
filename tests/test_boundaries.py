"""Fronteiras de dependência (P01-T01, docs/04 §2).

Núcleo desacoplado de clientes e de geração de dados:
- `tools/` e `inference/` não podem importar `teachers`;
- `training/` não pode importar `mcp`.

Inspeção estática via `ast` (stdlib): nenhum módulo do projeto é
importado, então o teste nunca exige dependências externas.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# package escaneado -> packages raiz proibidos nos seus imports
# `core` é o chassi genérico (docs/20 §5): nunca importa código acoplado ao SIGA.
RULES: dict[str, frozenset[str]] = {
    "tools": frozenset({"teachers"}),
    "inference": frozenset({"teachers"}),
    "training": frozenset({"mcp"}),
    "core": frozenset(
        {"tools", "retrieval", "graph", "indexer", "teachers", "training", "mcp", "context"}
    ),
}


def _package_of(path: Path, root: Path) -> tuple[str, ...]:
    """Package pontuado do arquivo relativo à raiz (ex.: tools/foo.py -> ("tools",))."""
    rel = path.relative_to(root).with_suffix("")
    parts = rel.parts[:-1] if rel.name == "__init__" else rel.parts[:-1]
    return parts


def _resolve_base(package: tuple[str, ...], level: int) -> tuple[str, ...]:
    """Base de um import relativo: level=1 é o próprio package, 2 sobe um, ..."""
    if level <= 1:
        return package
    up = level - 1
    return package[: len(package) - up] if up <= len(package) else ()


def violations_in(path: Path, root: Path) -> list[str]:
    """Retorna descrições de imports proibidos no arquivo (lista vazia = ok)."""
    package = _package_of(path, root)
    if not package or package[0] not in RULES:
        return []
    denied = RULES[package[0]]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in denied:
                    found.append(f"{path}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module and node.module.split(".")[0] in denied:
                    found.append(f"{path}:{node.lineno}: from {node.module} import ...")
            else:
                base = _resolve_base(package, node.level)
                firsts = (
                    [node.module.split(".")[0]]
                    if node.module
                    else [a.name.split(".")[0] for a in node.names if a.name != "*"]
                )
                for first in firsts:
                    target = (*base, first) if first else base
                    if target and target[0] in denied:
                        found.append(
                            f"{path}:{node.lineno}: relative import reaches {'.'.join(target)}"
                        )
    return found


def collect_violations(root: Path = ROOT) -> list[str]:
    """Varre os packages com regras, ignorando __pycache__."""
    found: list[str] = []
    for package in RULES:
        for path in sorted((root / package).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            found.extend(violations_in(path, root))
    return found


def test_no_forbidden_imports():
    assert collect_violations() == []
