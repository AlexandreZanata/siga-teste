"""Tool semântica siga_impact (P05-T02, ADR-013 em docs/06).

Ação: Efeitos de modificar arquivo/classe/método/feature.
Args:
  - target: símbolo ou caminho de arquivo real (grounding obrigatório)
  - hops?: raio de expansão (default 1)
Retorna:
  Dicionário com chamadores (callers), métodos invocados (callees),
  testes relacionados, migrações/tabelas e arquivos impactados.
Todo arquivo e símbolo retornado existe em disco ou no grafo.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from tools import primitives


def _resolve_repo(repo: str | Path | None) -> Path:
    if repo is not None:
        return Path(repo).resolve()
    parent = Path(__file__).resolve().parent.parent.parent
    if (parent / "siga-ex").is_dir():
        return parent
    return Path(__file__).resolve().parent.parent


def siga_impact(
    target: str,
    hops: int = 1,
    repo: str | Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Calcula o impacto estático da modificação de um símbolo ou arquivo."""
    if not isinstance(target, str) or not target.strip():
        raise ValueError("target deve ser uma string não vazia")
    if hops < 1:
        raise ValueError(f"hops deve ser >= 1, recebido {hops}")

    root = _resolve_repo(repo)

    target_file: str | None = None
    symbol_name: str = target

    # Identifica se target é arquivo ou símbolo
    if "/" in target or target.endswith((".java", ".jsp", ".sql")):
        p = Path(target)
        if p.is_file():
            target_file = str(p.resolve())
        elif (root / target).is_file():
            target_file = str((root / target).resolve())
        else:
            matches = primitives.find_file(root, p.name, limit=1)
            if matches:
                target_file = matches[0]

        if target_file and target_file.endswith(".java"):
            try:
                outline = primitives.get_file_outline(target_file)
                if outline.get("types"):
                    symbol_name = outline["types"][0]["name"]
            except Exception:
                symbol_name = Path(target_file).stem
        elif target_file:
            symbol_name = Path(target_file).stem
    else:
        # target é nome de símbolo
        symbol_name = target
        matches = primitives.find_file(root, f"{symbol_name}.java", limit=1)
        if matches:
            target_file = matches[0]

    callers = primitives.find_callers(root, symbol_name, limit=50)

    callees: list[str] = []
    if target_file and target_file.endswith(".java"):
        try:
            outline = primitives.get_file_outline(target_file)
            for t in outline.get("types", []):
                for m in t.get("methods", [])[:5]:
                    callees.extend(primitives.find_callees(target_file, m))
        except Exception:
            pass

    related_tests = primitives.find_related_tests(root, symbol_name, limit=20)

    migrations: list[str] = []
    # Busca migrações associadas ao símbolo
    migs = primitives.find_migration(root, symbol_name, conn=conn)
    if migs:
        migrations.extend(migs)
    else:
        # Se for ExDocumento -> siga.ex_documento
        table_guess = f"siga.{symbol_name.lower().removeprefix('ex')}"
        migrations.extend(primitives.find_migration(root, table_guess, conn=conn))

    affected_files: set[str] = set()
    if target_file:
        affected_files.add(target_file)
    for c in callers:
        affected_files.add(c["file"])
    for t in related_tests:
        affected_files.add(t)
    for m in migrations:
        affected_files.add(m)

    return {
        "target": target,
        "hops": hops,
        "symbol": symbol_name,
        "file": target_file,
        "callers": callers,
        "callees": sorted(set(callees)),
        "related_tests": sorted(related_tests),
        "migrations": sorted(set(migrations)),
        "affected_files": sorted(affected_files),
    }
