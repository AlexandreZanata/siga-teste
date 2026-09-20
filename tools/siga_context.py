"""Tool semântica siga_context (P05-T02, ADR-013 em docs/06, P09-T01).

Ação: Produz a cápsula final mínima para a IA grande a partir de símbolos validados.
Args:
  - symbols: lista de símbolos reais verificados em passos anteriores
  - task: descrição verbatim da tarefa a ser executada
  - mode?: 'full' (default, cápsula rica) ou 'referential' (H04: só IDs +
    outlines, snippets via fetch sob demanda; exposição MCP futura)
Retorna:
  Dicionário com a cápsula estruturada e texto compacto para prompt da IA grande.
Não recupera nada novo; compacta e empacota símbolos e outlines já validados.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from context.capsule import build_context_capsule, count_tokens
from context.referential import build_referential_capsule
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
    mode: str = "full",
) -> dict[str, Any]:
    """Empacota a cápsula de contexto mínima para a IA grande."""
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task deve ser uma string não vazia")
    if not isinstance(symbols, list):
        raise ValueError("symbols deve ser uma lista de strings")
    if mode not in ("full", "referential"):
        raise ValueError(f"mode inválido: {mode!r} (full|referential)")

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

    # Constrói cápsula estruturada rica da Phase 09
    rich_capsule = build_context_capsule(
        task=task,
        repo=root,
        conn=conn,
        symbols=symbols,
        files=sorted(files),
    )

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

    if tests or rich_capsule.tests:
        capsule_lines.append("")
        capsule_lines.append("## RELEVANT TESTS")
        for t in sorted(tests | set(rich_capsule.tests)):
            try:
                rel_t = str(Path(t).relative_to(root))
            except ValueError:
                rel_t = t
            capsule_lines.append(f"- {rel_t}")

    capsule_text = "\n".join(capsule_lines)
    estimated_tokens = count_tokens(capsule_text)

    if mode == "referential":
        ref = build_referential_capsule(task, symbols, sorted(files), repo=root)
        return {
            "task": task,
            "mode": "referential",
            "symbols": symbols,
            "refs": ref["refs"],
            "capsule_text": ref["text"],
            "token_estimate": ref["token_estimate"],
            "full_token_estimate": estimated_tokens,
            "fetch": "context.referential.fetch_snippet(repo, id, max_lines=40)",
        }

    return {
        "task": task,
        "symbols": symbols,
        "files": sorted(files),
        "outlines": outlines,
        "related_tests": sorted(tests | set(rich_capsule.tests)),
        "relations": relations,
        "primary_symbols": rich_capsule.primary_symbols,
        "flow": rich_capsule.flow,
        "domain": rich_capsule.domain,
        "persistence": rich_capsule.persistence,
        "views": rich_capsule.views,
        "migrations": rich_capsule.migrations,
        "snippets": [s.to_dict() for s in rich_capsule.snippets],
        "capsule_text": capsule_text,
        "capsule_json": rich_capsule.to_json(compact=True),
        "compact_text": rich_capsule.to_compact_text(),
        "token_estimate": estimated_tokens,
    }
