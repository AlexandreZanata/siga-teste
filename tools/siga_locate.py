"""Tool semântica siga_locate (P05-T02, ADR-013/014 em docs/06).

Ação: Localiza arquivos, símbolos e componentes de uma funcionalidade no repositório.
Args:
  - query: texto da funcionalidade (span da tarefa)
  - kind?: tipo opcional ('file', 'symbol', 'controller', 'entity', 'jsp', 'migration', 'test')
Retorna:
  Lista de candidatos reais [ {target, file, symbol, kind, score} ]
Todo arquivo e símbolo retornado existe em disco ou no grafo.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from retrieval.baseline import expanded_terms as extract_terms
from tools import primitives

VALID_KINDS = frozenset(
    {"file", "symbol", "controller", "entity", "jsp", "migration", "test"}
)


def _resolve_repo(repo: str | Path | None) -> Path:
    if repo is not None:
        return Path(repo).resolve()
    # Padrão: SIGA no pai se existir, senão repo atual
    parent = Path(__file__).resolve().parent.parent.parent
    if (parent / "siga-ex").is_dir():
        return parent
    return Path(__file__).resolve().parent.parent


def siga_locate(
    query: str,
    kind: str | None = None,
    repo: str | Path | None = None,
    conn: sqlite3.Connection | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Localiza arquivos/símbolos de uma funcionalidade a partir de termos da query."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query deve ser uma string não vazia")
    if kind is not None and kind not in VALID_KINDS:
        raise ValueError(
            f"kind {kind!r} inválido; valores permitidos: {sorted(VALID_KINDS)}"
        )
    if limit < 1:
        raise ValueError(f"limit deve ser >= 1, recebido {limit}")

    root = _resolve_repo(repo)
    query_terms = extract_terms(query)
    candidates: dict[str, dict[str, Any]] = {}

    def add_hit(
        file: str | None,
        symbol: str | None,
        hit_kind: str,
        score: float,
    ) -> None:
        target = f"{file}::{symbol}" if (file and symbol) else (file or symbol or "")
        if not target:
            return
        if target in candidates:
            candidates[target]["score"] += score
        else:
            candidates[target] = {
                "target": target,
                "file": file,
                "symbol": symbol,
                "kind": hit_kind,
                "score": score,
            }

    # 1. Busca por kind específico
    if kind == "file":
        for term in query_terms or [query]:
            for path in primitives.find_file(root, term, limit=limit):
                add_hit(path, None, "file", 1.0)

    elif kind in ("symbol", "controller", "entity"):
        if conn is not None:
            for term in query_terms or [query]:
                for sym in primitives.find_symbol(conn, term, limit=limit):
                    sym_kind = sym.get("kind", "symbol")
                    if kind == "controller" and sym_kind != "controller":
                        if not sym["name"].endswith("Controller"):
                            continue
                    elif kind == "entity" and sym_kind != "entity":
                        continue
                    add_hit(sym.get("file"), sym["name"], sym_kind, 1.2)
        else:
            for term in query_terms or [query]:
                pattern = f"class {term}" if kind != "controller" else f"{term}Controller"
                for hit in primitives.search_text(root, pattern, limit=limit):
                    add_hit(hit["file"], term, kind, 1.0)

    elif kind == "jsp":
        for term in query_terms or [query]:
            for path in primitives.find_file(root, f"{term}.jsp", limit=limit):
                add_hit(path, None, "jsp", 1.0)
            for hit in primitives.search_text(root, term, globs=["**/*.jsp"], limit=limit):
                add_hit(hit["file"], None, "jsp", 0.8)

    elif kind == "migration":
        for term in query_terms or [query]:
            for mig in primitives.find_migration(root, term, conn=conn):
                add_hit(mig, None, "migration", 1.0)
            for path in primitives.find_file(root, f"*{term}*.sql", limit=limit):
                add_hit(path, None, "migration", 0.8)

    elif kind == "test":
        for term in query_terms or [query]:
            for t in primitives.find_related_tests(root, term, limit=limit):
                add_hit(t, None, "test", 1.0)

    else:
        # kind is None: busca híbrida ranqueada (símbolos + arquivos + texto)
        if conn is not None:
            # Símbolos no grafo
            for term in query_terms or [query]:
                for sym in primitives.find_symbol(conn, term, limit=limit):
                    sym_kind = sym.get("kind", "symbol")
                    weight = 1.5 if query.lower() in sym["name"].lower() else 1.0
                    add_hit(sym.get("file"), sym["name"], sym_kind, weight)

        # Arquivos por nome
        for term in query_terms or [query]:
            for path in primitives.find_file(root, term, limit=limit):
                base = Path(path).name.lower()
                weight = 1.2 if term.lower() in base else 0.8
                add_hit(path, None, "file", weight)

        # Busca textual no slice
        for term in query_terms:
            text_terms = {term, term.capitalize()}
            for text_term in text_terms:
                for hit in primitives.search_text(
                    root,
                    text_term,
                    globs=["siga-ex/**", "sigaex/**"] if (root / "siga-ex").is_dir() else None,
                    limit=limit,
                ):
                    add_hit(hit["file"], None, "file", 0.5)

    # Ordenar por score desc, depois por nome do target asc (determinístico)
    ranked = sorted(
        candidates.values(),
        key=lambda c: (-c["score"], c["target"]),
    )
    # Formatação final: arredonda score
    for c in ranked:
        c["score"] = round(c["score"], 3)

    return ranked[:limit]
