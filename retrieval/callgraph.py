"""Call graph + impacto estático 1-hop (P03-T02, sem LLM).

callees via AST (Tree-sitter); callers via `rg -w` no slice;
DEPENDS_ON via imports; testes via *Test*.java que menciona o símbolo.
Tudo determinístico; tudo retornado existe em disco.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from indexer.java_symbols import parse_file
from retrieval.search import search_text


def _java_globs(root: Path | None = None) -> list[str]:
    """Globs `**/*.java` por módulo do escopo ativo (J02: era `SLICE_MODULES`;
    com perfil SIGA ativo reproduz `[siga-ex**/*.java, sigaex**/*.java]`)."""
    from retrieval.search import _current_scope

    return [f"{m}**/*.java" for m in _current_scope()]


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
    return search_text(repo, symbol, globs=_java_globs(), limit=limit)


def file_imports(java_path: str | Path) -> list[str]:
    """Imports do arquivo (DEPENDS_ON)."""
    return parse_file(java_path).get("imports", [])


def related_tests(repo: str | Path, symbol: str, limit: int = 20) -> list[str]:
    """*Test*.java que mencionam o símbolo."""
    hits = search_text(repo, symbol, globs=["**/*Test*.java"], limit=limit)
    return [h["file"] for h in hits]


def static_impact(
    repo: str | Path,
    target: str | Path,
    depth: int = 1,
    with_cochange: bool = False,
    before_sha: str | None = None,
    cochange_limit: int = 5,
) -> dict:
    """Impacto estático 1-hop de um arquivo .java: callers, depends_on, testes.

    `target` é path de arquivo. Retorna paths reais + imports. Com
    `with_cochange`, soma parceiros históricos de co-alteração
    (`CHANGED_WITH`, chave `cochange`); `before_sha` restringe o histórico a
    antes do commit (sem vazar o avaliado).
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
    cochange: list[str] = []
    if with_cochange:
        from indexer import git_history

        root = Path(repo)
        try:
            rel = str(Path(path).relative_to(root))
        except ValueError:
            rel = path
        try:
            partners = git_history.cochange_partners(repo, rel, before_sha=before_sha)
        except (subprocess.SubprocessError, OSError):
            partners = []
        cochange = sorted(
            {
                str(root / partner["path"])
                for partner in partners[: max(cochange_limit, 0)]
                if (root / partner["path"]).is_file()
            }
        )
    return {
        "target": path,
        "symbols": symbols,
        "callers": callers,
        "depends_on": file_imports(path),
        "related_tests": sorted(set(tests)),
        "cochange": cochange,
    }


def impact_recall(repo: str | Path, commit_sha: str) -> dict:
    """Recall de cobertura do static_impact sobre co-alterados reais do commit.

    Para o 1º .java do slice no commit: fração dos demais arquivos do commit
    alcançada por callers (referenciam os símbolos) ou depends_on (importados).
    Commits Git são imutáveis: resultado determinístico.
    """
    from indexer.git_history import files_in_commit

    from retrieval.search import _current_scope

    scope = _current_scope()
    files = [f for f in files_in_commit(repo, commit_sha) if f.endswith(".java")]
    in_slice = [f for f in files if f.startswith(scope)]
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


def impact_recall_with_cochange(repo: str | Path, commit_sha: str, cochange_limit: int = 5) -> dict:
    """Recall estático + parceiros de co-alteração estritamente ANTERIORES ao commit.

    Mesma âncora e mesmos `others` de `impact_recall`; o conjunto alcançado
    soma `cochange` medido só com `{commit_sha}^` (nunca o próprio commit —
    prever o commit a partir dele mesmo seria leakage). `recall_static`
    preserva a medida antiga para comparação honesta.
    """
    from indexer.git_history import files_in_commit

    from retrieval.search import _current_scope

    scope = _current_scope()
    files = [f for f in files_in_commit(repo, commit_sha) if f.endswith(".java")]
    in_slice = [f for f in files if f.startswith(scope)]
    if len(in_slice) < 2:
        return {"sha": commit_sha, "skipped": True, "reason": "<2 java do slice"}
    root = Path(repo)
    anchor = str(root / in_slice[0])
    others = {str(root / f) for f in in_slice[1:]}
    impact = static_impact(repo, anchor, with_cochange=True, before_sha=commit_sha, cochange_limit=cochange_limit)
    reached = (
        set(impact["callers"])
        | {
            str(root / (dotted.replace(".", "/") + ".java")) for dotted in impact["depends_on"]
        }
        | set(impact["cochange"])
    )
    covered = {f for f in others if f in reached or _references(root, f, impact["symbols"])}
    static = impact_recall(repo, commit_sha)
    return {
        "sha": commit_sha,
        "skipped": False,
        "anchor": anchor,
        "others": sorted(others),
        "covered": sorted(covered),
        "recall": len(covered) / len(others) if others else 1.0,
        "recall_static": static.get("recall"),
        "cochange": impact["cochange"],
    }


def _references(root: Path, file: str, symbols: list[str]) -> bool:
    """Arquivo menciona algum dos símbolos (rg -w)."""
    for symbol in symbols:
        for hit in search_text(root, symbol, limit=1000):
            if hit["file"] == file:
                return True
    return False
