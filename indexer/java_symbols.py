"""Indexer Java via Tree-sitter (P02-T01, ADR-010 em docs/05).

Extrai por arquivo: package, imports, tipos (class/interface/enum) com
anotações, extends/implements, métodos, construtores e campos.
Gramática tolerante a código legado; sem JVM no runtime.
Só depende de `tree_sitter` + `tree_sitter_java` além da stdlib.
"""

from __future__ import annotations

from pathlib import Path

try:
    from tree_sitter import Language, Parser
    import tree_sitter_java
except ImportError:  # pragma: no cover - falha explícita sem a dependência
    raise

_TYPE_NODES = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "annotation_type_declaration": "annotation",
}

_parser: Parser | None = None


def get_parser() -> Parser:
    """Parser Java compartilhado (construção única, thread-hostil por design)."""
    global _parser
    if _parser is None:
        _parser = Parser(Language(tree_sitter_java.language()))
    return _parser


def _text(source: bytes, node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _child_text(source: bytes, node, field: str) -> str | None:
    child = node.child_by_field_name(field)
    return _text(source, child) if child is not None else None


def _annotations_of(source: bytes, node) -> list[str]:
    """Nomes de anotações no `modifiers` do nó (ex.: @Controller -> Controller)."""
    names: list[str] = []
    for child in node.children:
        if child.type != "modifiers":
            continue
        for mod in child.children:
            if mod.type in ("annotation", "marker_annotation"):
                name_node = mod.child_by_field_name("name")
                if name_node is not None:
                    names.append(_text(source, name_node).split(".")[-1])
    return names


def _first_type_name(source: bytes, node) -> str | None:
    """Primeiro nome de tipo dentro do nó (ignora keywords como `extends`)."""
    if node.type in ("type_identifier", "scoped_identifier", "generic_type"):
        return _text(source, node).split(".")[-1]
    for child in node.children:
        found = _first_type_name(source, child)
        if found is not None:
            return found
    return None


def _parse_type(source: bytes, node) -> dict:
    """Um type node + nested types (classes internas como Pendencias)."""
    body = next((c for c in node.children if c.type.endswith("_body")), None)
    methods: list[dict] = []
    constructors: list[dict] = []
    fields: list[str] = []
    nested: list[dict] = []
    if body is not None:
        for child in body.children:
            if child.type == "method_declaration":
                methods.append(
                    {
                        "name": _child_text(source, child, "name") or "",
                        "annotations": _annotations_of(source, child),
                    }
                )
            elif child.type == "constructor_declaration":
                constructors.append({"name": _child_text(source, child, "name") or ""})
            elif child.type == "field_declaration":
                for declarator in child.children:
                    if declarator.type == "variable_declarator":
                        fname = _child_text(source, declarator, "name")
                        if fname:
                            fields.append(fname)
            elif child.type in _TYPE_NODES:
                nested.append(_parse_type(source, child))
    superclass_node = node.child_by_field_name("superclass")
    superclass = _first_type_name(source, superclass_node) if superclass_node is not None else None
    interfaces_node = node.child_by_field_name("superinterfaces")
    implements: list[str] = []
    if interfaces_node is not None:
        implements = [
            _text(source, c).split(".")[-1]
            for c in interfaces_node.children
            if c.type in ("type_identifier", "scoped_identifier", "generic_type")
        ]
    return {
        "kind": _TYPE_NODES[node.type],
        "name": _child_text(source, node, "name") or "",
        "annotations": _annotations_of(source, node),
        "extends": superclass,
        "implements": implements,
        "methods": methods,
        "constructors": constructors,
        "fields": fields,
        "nested": nested,
    }


def parse_file(path: str | Path) -> dict:
    """Indexa um .java real; levanta FileNotFoundError se o path não existir."""
    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"arquivo java inexistente: {path}")
    source = resolved.read_bytes()
    tree = get_parser().parse(source)
    root = tree.root_node
    package: str | None = None
    imports: list[str] = []
    types: list[dict] = []
    for child in root.children:
        if child.type == "package_declaration":
            package = _text(source, child).removeprefix("package").strip().rstrip(";")
        elif child.type == "import_declaration":
            stmt = _text(source, child).removeprefix("import").strip().rstrip(";")
            imports.append(stmt.removeprefix("static ").strip())
        elif child.type in _TYPE_NODES:
            types.append(_parse_type(source, child))
    return {"file": str(resolved), "package": package, "imports": imports, "types": types}


def index_files(paths: list[str | Path]) -> list[dict]:
    """Indexa lista de paths reais (nenhum path é inventado: ausente = erro)."""
    return [parse_file(p) for p in paths]
