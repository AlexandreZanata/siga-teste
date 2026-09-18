"""Tool semântica siga_context (P05-T02, ADR-013 em docs/06).

Ação: Produz a cápsula final mínima para a IA grande a partir de símbolos validados.
Args:
  - symbols: lista de símbolos reais verificados em passos anteriores
  - task: descrição verbatim da tarefa a ser executada
Retorna:
  Dicionário com a cápsula estruturada e texto compacto para prompt da IA grande.
Não recupera nada novo; compacta e empacota símbolos e outlines já validados.
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


def siga_context(
    symbols: list[str],
    task: str,
    repo: str | Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Empacota a cápsula de contexto mínima para a IA grande."""
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task deve ser uma string não vazia")
    if not isinstance(symbols, list):
        raise ValueError("symbols deve ser uma lista de strings")

    root = _resolve_repo(repo)

    files: set[str] = set()
    outlines: list[dict[str, Any]] = []
    tests: set[str] = set()
    relations: list[dict[str, Any]] = []

    for sym in symbols:
        if not isinstance(sym, str) or not sym.strip():
            continue

        # Lê relações do grafo se conexão disponível
        if conn is not None:
            sym_data = primitives.read_symbol(conn, sym)
            if sym_data:
                relations.append(sym_data)
                if sym_data.get("file"):
                    files.add(sym_data["file"])

        # Localiza arquivo correspondente
        if not any(sym in f for f in files):
            matches = primitives.find_file(root, f"{sym}.java", limit=1)
            if matches:
                files.add(matches[0])

        # Testes relacionados
        for t in primitives.find_related_tests(root, sym, limit=5):
            tests.add(t)

    # Extrai outlines estruturais dos arquivos encontrados
    for f in sorted(files):
        if f.endswith(".java") and Path(f).is_file():
            try:
                outlines.append(primitives.get_file_outline(f))
            except Exception:
                pass

    # Monta a cápsula textual compacta para o prompt da IA grande
    capsule_lines: list[str] = [
        f"# CONTEXT CAPSULE — {task.strip()}",
        "",
        "## ANCHOR SYMBOLS",
    ]
    for s in symbols:
        capsule_lines.append(f"- {s}")

    capsule_lines.append("")
    capsule_lines.append("## STRUCTURAL OUTLINES")
    for ot in outlines:
        rel_f = ot.get("file", "")
        try:
            rel_f = str(Path(rel_f).relative_to(root))
        except ValueError:
            pass
        capsule_lines.append(f"### File: {rel_f} (pkg: {ot.get('package')})")
        for t in ot.get("types", []):
            capsule_lines.append(f"  {t.get('kind')} {t.get('name')}:")
            if t.get("methods"):
                capsule_lines.append(f"    methods: {', '.join(t['methods'][:10])}")
            if t.get("fields"):
                capsule_lines.append(f"    fields: {', '.join(t['fields'][:10])}")

    if tests:
        capsule_lines.append("")
        capsule_lines.append("## RELEVANT TESTS")
        for t in sorted(tests):
            try:
                rel_t = str(Path(t).relative_to(root))
            except ValueError:
                rel_t = t
            capsule_lines.append(f"- {rel_t}")

    capsule_text = "\n".join(capsule_lines)
    # Estimativa de tokens: ~1 token para cada 4 caracteres
    estimated_tokens = len(capsule_text) // 4

    return {
        "task": task,
        "symbols": symbols,
        "files": sorted(files),
        "outlines": outlines,
        "related_tests": sorted(tests),
        "relations": relations,
        "capsule_text": capsule_text,
        "token_estimate": estimated_tokens,
    }
