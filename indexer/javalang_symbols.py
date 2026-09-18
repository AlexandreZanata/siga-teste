"""Parser Java alternativo via javalang (F07, gatilho P02/ADR-010 em docs/05).

Comparador puro-Python (sem JVM) da mesma classe do JavaParser para decidir
com números se o Tree-sitter permanece. `parse_file` devolve o MESMO schema
de `indexer.java_symbols.parse_file` (package, imports, types[] com kind,
name, annotations, extends, implements, methods, constructors, fields,
nested) para comparação direta. Erro de sintaxe propaga
`javalang.parser.JavaSyntaxError` (diferente do Tree-sitter tolerante —
essa diferença faz parte do veredito F07).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import javalang
from javalang import tree as jtree

_KIND_BY_NODE = {
    jtree.ClassDeclaration: "class",
    jtree.InterfaceDeclaration: "interface",
    jtree.EnumDeclaration: "enum",
    jtree.AnnotationDeclaration: "annotation",
}


def _annotation_names(node: Any) -> list[str]:
    return [ann.name for ann in (getattr(node, "annotations", None) or [])]


def _type_name(node: Any) -> str:
    name = getattr(node, "name", "") or ""
    return str(name).split(".")[-1]


def _parse_type(node: Any) -> dict[str, Any]:
    kind = _KIND_BY_NODE.get(type(node), "class")
    methods = [
        {"name": m.name, "annotations": _annotation_names(m)} for m in (getattr(node, "methods", None) or [])
    ]
    constructors = [{"name": c.name} for c in (getattr(node, "constructors", None) or [])]
    fields: list[str] = [
        d.name for f in (getattr(node, "fields", None) or []) for d in (getattr(f, "declarators", None) or [])
    ]
    nested = [_parse_type(n) for n in (getattr(node, "body", None) or []) if isinstance(n, jtree.TypeDeclaration)]
    extends_node = getattr(node, "extends", None)
    implements_nodes = getattr(node, "implements", None) or []
    return {
        "kind": kind,
        "name": getattr(node, "name", "") or "",
        "annotations": _annotation_names(node),
        "extends": _type_name(extends_node) if extends_node is not None else None,
        "implements": [_type_name(i) for i in implements_nodes],
        "methods": methods,
        "constructors": constructors,
        "fields": fields,
        "nested": nested,
    }


def parse_file(path: str | Path) -> dict[str, Any]:
    """Indexa um .java real; FileNotFoundError se ausente; JavaSyntaxError se inválido."""
    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"arquivo java inexistente: {path}")
    unit = javalang.parse.parse(resolved.read_text(encoding="utf-8", errors="replace"))
    package = unit.package.name if unit.package is not None else None
    imports = []
    for imp in unit.imports or []:
        stmt = ("static " if imp.static else "") + imp.path
        if imp.wildcard:
            stmt += ".*"
        imports.append(stmt)
    return {
        "file": str(resolved),
        "package": package,
        "imports": imports,
        "types": [_parse_type(t) for t in unit.types or []],
    }
