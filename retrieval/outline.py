"""Outlines estruturais (P03-T01): estrutura sem código-fonte.

`get_file_outline` resume um .java real via indexer/java_symbols:
package, tipos, métodos, campos, imports (contagem). É o que a cápsula
(P09) envia em vez do arquivo inteiro.
"""

from __future__ import annotations

from pathlib import Path

from indexer.java_symbols import parse_file


def get_file_outline(path: str | Path) -> dict:
    """Outline de um .java real; ausente = FileNotFoundError."""
    rec = parse_file(path)

    def slim(node: dict) -> dict:
        return {
            "kind": node["kind"],
            "name": node["name"],
            "annotations": node.get("annotations", []),
            "extends": node.get("extends"),
            "implements": node.get("implements", []),
            "methods": [m["name"] for m in node.get("methods", [])],
            "constructors": [c["name"] for c in node.get("constructors", [])],
            "fields": node.get("fields", []),
            "nested": [slim(n) for n in node.get("nested", [])],
        }

    return {
        "file": rec["file"],
        "package": rec["package"],
        "imports_count": len(rec.get("imports", [])),
        "types": [slim(t) for t in rec.get("types", [])],
    }
