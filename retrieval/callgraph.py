"""Call graph + impacto estático 1-hop (P03-T02, sem LLM).

callees via AST (Tree-sitter); callers via `rg -w` no slice;
DEPENDS_ON via imports; testes via *Test*.java que menciona o símbolo.
Tudo determinístico; tudo retornado existe em disco.
"""

from __future__ import annotations

from pathlib import Path

from indexer.java_symbols import parse_file
from retrieval.search import SLICE_MODULES, search_text

_JAVA_GLOBS = [f"{m}**/*.java" for m in SLICE_MODULES]


def method_callees(java_path: str | Path, method_name: str) -> set[str]:
    """Nomes invocados dentro de `method_name` (AST, inclui JDK/getters)."""
    from tree_sitter import Language, Parser
    import tree_sitter_java

    source = Path(java_path).read_bytes()
    tree = Parser(Language(tree_sitter_java.language())).parse(source)

    def find_method(node):
        if node.type == "method_declaration":
            name = node.child_by_field_name("name")
            if name is not None and source[name.start_byte : name.end_byte].decode() == method_name:
                return node
        for child in node.children:
            found = find_method(child)
            if found is not None:
                return found
        return None

    target = find_method(tree.root_node)
    if target is None:
        raise ValueError(f"método ausente: {method_name} em {java_path}")
    called: set[str] = set()

    def walk(node) -> None:
        if node.type == "method_invocation":
            field = node.child_by_field_name("method") or node.child_by_field_name("name")
            if field is not None:
                called.add(source[field.start_byte : field.end_byte].decode())
        for child in node.children:
            walk(child)

    walk(target)
    return called


def defined_symbols(java_path: str | Path) -> list[str]:
    """Classes/interfaces/enums de topo do arquivo (nomes simples)."""
    return [t["name"] for t in parse_file(java_path).get("types", [])]


def find_callers(repo: str | Path, symbol: str, limit: int = 50) -> list[dict]:
    """Arquivos .java do slice com ocorrência word-boundary (exclui nada; chamador filtra)."""
    return search_text(repo, symbol, globs=_JAVA_GLOBS, limit=limit)


def file_imports(java_path: str | Path) -> list[str]:
    """Imports do arquivo (DEPENDS_ON)."""
    return parse_file(java_path).get("imports", [])


def related_tests(repo: str | Path, symbol: str, limit: int = 20) -> list[str]:
    """*Test*.java que mencionam o símbolo."""
    hits = search_text(repo, symbol, globs=["**/*Test*.java"], limit=limit)
    return [h["file"] for h in hits]


def static_impact(repo: str | Path, target: str | Path, depth: int = 1) -> dict:
    """Impacto estático 1-hop de um arquivo .java: callers, depends_on, testes.

    `target` é path de arquivo. Retorna paths reais + imports.
    """
    _ = depth  # V1: só 1-hop; depth>1 adiado p/ P05 (siga_impact)
    path = str(target)
    symbols = defined_symbols(path)
    callers: dict[str, list[int]] = {}
    for symbol in symbols:
        for hit in find_callers(repo, symbol):
            if hit["file"] == path:
                continue
            callers.setdefault(hit["file"], sorted(set(callers.get(hit["file"], [])) | set(hit["lines"])))
    tests = []
    for symbol in symbols:
        tests.extend(t for t in related_tests(repo, symbol) if t != path)
    return {
        "target": path,
        "symbols": symbols,
        "callers": callers,
        "depends_on": file_imports(path),
        "related_tests": sorted(set(tests)),
    }


def impact_recall(repo: str | Path, commit_sha: str) -> dict:
    """Recall de cobertura do static_impact sobre co-alterados reais do commit.

    Para o 1º .java do slice no commit: fração dos demais arquivos do commit
    alcançada por callers (referenciam os símbolos) ou depends_on (importados).
    Commits Git são imutáveis: resultado determinístico.
    """
    from indexer.git_history import files_in_commit

    files = [f for f in files_in_commit(repo, commit_sha) if f.endswith(".java")]
    in_slice = [f for f in files if f.startswith(SLICE_MODULES)]
    if len(in_slice) < 2:
        return {"sha": commit_sha, "skipped": True, "reason": "<2 java do slice"}
    root = Path(repo)
    anchor = str(root / in_slice[0])
    others = {str(root / f) for f in in_slice[1:]}
    impact = static_impact(repo, anchor)
    reached = set(impact["callers"]) | {
        str(root / (dotted.replace(".", "/") + ".java")) for dotted in impact["depends_on"]
    }
    covered = {f for f in others if f in reached or _references(root, f, impact["symbols"])}
    return {
        "sha": commit_sha,
        "skipped": False,
        "anchor": anchor,
        "others": sorted(others),
        "covered": sorted(covered),
        "recall": len(covered) / len(others) if others else 1.0,
    }


def _references(root: Path, file: str, symbols: list[str]) -> bool:
    """Arquivo menciona algum dos símbolos (rg -w)."""
    for symbol in symbols:
        for hit in search_text(root, symbol, limit=1000):
            if hit["file"] == file:
                return True
    return False
