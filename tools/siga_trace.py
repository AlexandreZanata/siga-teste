"""Tool semântica siga_trace (P05-T02, ADR-013 em docs/06).

Ação: Traça o fluxo endpoint→controller→negócio(BL)→entidade→persistência→view.
Args:
  - symbol: símbolo real obtido de passo anterior (grounding obrigatório)
  - depth?: profundidade do rastreamento (1–3, default 2)
Retorna:
  Dicionário com a cadeia completa, estágios do fluxo e arquivos envolvidos.
Todo símbolo e arquivo retornado existe no grafo ou em disco.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from graph import store
from tools import primitives


def _resolve_repo(repo: str | Path | None) -> Path:
    if repo is not None:
        return Path(repo).resolve()
    parent = Path(__file__).resolve().parent.parent.parent
    if (parent / "siga-ex").is_dir():
        return parent
    return Path(__file__).resolve().parent.parent


def siga_trace(
    symbol: str,
    depth: int = 2,
    repo: str | Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Traça a cadeia de execução e dependências a partir de um símbolo real."""
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("symbol deve ser uma string não vazia")
    if depth not in (1, 2, 3):
        raise ValueError(f"depth deve ser 1, 2 ou 3, recebido {depth}")

    root = _resolve_repo(repo)

    chain: list[dict[str, Any]] = []
    if conn is not None:
        chain = store.trace(conn, symbol, depth=depth)
    else:
        # Sem grafo: expande via referências textuais (F21 — antes era 1 nó).
        # hop0 = símbolo; hopN (N<=depth) = arquivos que referenciam o
        # símbolo do hop anterior (nome = stem .java, kind = caller).
        # Tampos: 10 arquivos no hop1, 3 por nó no hop2+, 25 nós no total.
        sym_file = None
        for path in primitives.find_file(root, f"{symbol}.java", limit=1):
            sym_file = path
            break
        if sym_file:
            outline = primitives.get_file_outline(sym_file)
            chain.append(
                {
                    "id": 1,
                    "kind": outline["types"][0]["kind"] if outline.get("types") else "class",
                    "name": symbol,
                    "file": sym_file,
                    "hop": 0,
                }
            )
            seen_files = {sym_file}
            frontier = [(symbol, 0)]
            next_id = 2
            while frontier and len(chain) < 25:
                current, hop = frontier.pop(0)
                if hop >= depth:
                    continue
                per_node = 10 if hop == 0 else 3
                callers = primitives.find_callers(root, current, limit=per_node)
                for ref in sorted({r["file"] for r in callers if r.get("file")}):
                    if ref in seen_files or len(chain) >= 25:
                        continue
                    seen_files.add(ref)
                    stem = Path(ref).stem if ref.endswith(".java") else Path(ref).name
                    chain.append(
                        {"id": next_id, "kind": "caller", "name": stem, "file": ref, "hop": hop + 1}
                    )
                    next_id += 1
                    if hop + 1 < depth and ref.endswith(".java"):
                        frontier.append((stem, hop + 1))

    # Categorização nos estágios do fluxo arquitetural
    stages: dict[str, list[dict[str, Any]]] = {
        "controllers": [],
        "business_logic": [],
        "entities": [],
        "persistence": [],
        "views": [],
        "other": [],
    }

    files: set[str] = set()
    for node in chain:
        f = node.get("file")
        if f and Path(f).is_file():
            files.add(f)

        name = node.get("name", "")
        kind = node.get("kind", "")
        entry = {"name": name, "kind": kind, "file": f, "hop": node.get("hop", 0)}

        if kind == "controller" or name.endswith("Controller"):
            stages["controllers"].append(entry)
        elif name.endswith("BL") or name.endswith("Service") or "/bl/" in (f or ""):
            stages["business_logic"].append(entry)
        elif kind == "entity" or "/model/" in (f or ""):
            stages["entities"].append(entry)
        elif kind in ("table", "migration") or (f and f.endswith(".sql")):
            stages["persistence"].append(entry)
        elif kind == "jsp" or (f and f.endswith(".jsp")):
            stages["views"].append(entry)
        else:
            stages["other"].append(entry)

    return {
        "symbol": symbol,
        "depth": depth,
        "chain": chain,
        "stages": stages,
        "files": sorted(files),
    }
