"""Cápsula referencial v2 (H04, docs/19 §4): IDs primeiro, conteúdo sob demanda.

A IA grande recebe referências `{id, path, symbol, module, def_lines,
outline}` — nunca milhares de arquivos. Snippets só via `fetch_snippet`
por id, com teto de linhas e trava anti-traversal. Só stdlib,
determinístico, somente leitura.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from context.capsule import count_tokens

DEF_RE = re.compile(
    r"^\s*(?:(?:public|protected|private|abstract|final|static|strictfp)\s+)*"
    r"(?:class|interface|enum|@interface)\s+([A-Za-z_][A-Za-z0-9_]*)"
)


def _resolve_repo(repo: str | Path | None) -> Path:
    if repo is not None:
        return Path(repo).resolve()
    parent = Path(__file__).resolve().parent.parent.parent
    if (parent / "siga-ex").is_dir():
        return parent
    return Path(__file__).resolve().parent.parent


def _rel(root: Path, path: str) -> str:
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return path


def _def_line(root: Path, rel: str, symbol: str) -> int | None:
    """Linha de `class/interface/enum Symbol` no arquivo; None se ausente."""
    try:
        lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for i, line in enumerate(lines, 1):
        match = DEF_RE.match(line)
        if match and match.group(1) == symbol:
            return i
    return None


def _outline_names(root: Path, rel: str) -> dict[str, list[str]]:
    """Nomes de métodos/campos do outline; vazio quando ilegível."""
    from tools import primitives

    try:
        outline = primitives.get_file_outline(str(root / rel))
    except Exception:
        return {"methods": [], "fields": []}
    methods: list[str] = []
    fields: list[str] = []
    for t in outline.get("types", []):
        methods.extend(t.get("methods", [])[:20])
        fields.extend(t.get("fields", [])[:20])
    return {"methods": methods, "fields": fields}


def build_referential_capsule(
    task: str,
    symbols: list[str],
    files: list[str] | None = None,
    repo: str | Path | None = None,
) -> dict[str, Any]:
    """Referências resolvidas (arquivo existe) com módulo, definição e outline."""
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task deve ser uma string não vazia")
    root = _resolve_repo(repo)
    from tools import primitives
    from tools.module_shards import module_of

    discovered: dict[str, str] = {}
    for f in files or []:
        rel = _rel(root, f)
        if (root / rel).is_file():
            discovered[rel] = Path(rel).stem
    for sym in symbols or []:
        if not isinstance(sym, str) or not sym.strip():
            continue
        if sym in discovered.values():
            continue
        matches = primitives.find_file(root, f"{sym}.java", limit=1)
        if matches:
            rel = _rel(root, matches[0])
            if (root / rel).is_file():
                discovered[rel] = sym
    refs: list[dict[str, Any]] = []
    for rel in sorted(discovered):
        sym = discovered[rel]
        try:
            module = module_of(rel)
        except ValueError:
            module = ""
        line = _def_line(root, rel, sym)
        refs.append(
            {
                "id": f"{rel}::{sym}",
                "path": rel,
                "symbol": sym,
                "module": module,
                "def_lines": [line, line] if line else None,
                "outline": _outline_names(root, rel) if rel.endswith(".java") else {"methods": [], "fields": []},
            }
        )
    text_lines = [f"# REFERENTIAL CAPSULE — {task.strip()}", ""]
    for r in refs:
        loc = f"{r['def_lines'][0]}" if r["def_lines"] else "?"
        text_lines.append(f"- {r['id']} [mod={r['module'] or '?'} line={loc}]")
    text = "\n".join(text_lines) + "\n"
    return {"task": task, "refs": refs, "text": text, "token_estimate": count_tokens(text)}


def fetch_snippet(
    repo: str | Path | None,
    ref_id: str,
    max_lines: int = 40,
) -> dict[str, Any]:
    """Conteúdo sob demanda por id `path::symbol`, com teto e trava de path."""
    if not isinstance(ref_id, str) or "::" not in ref_id:
        raise ValueError(f"ref_id inválido: {ref_id!r}")
    if max_lines < 1:
        raise ValueError("max_lines deve ser >= 1")
    rel, _, symbol = ref_id.partition("::")
    if not rel or not symbol or ".." in Path(rel).parts or Path(rel).is_absolute():
        raise ValueError(f"ref_id fora da raiz: {ref_id!r}")
    root = _resolve_repo(repo)
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError(f"ref_id fora da raiz: {ref_id!r}") from None
    if not target.is_file():
        raise ValueError(f"arquivo do ref_id não existe: {rel!r}")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    start = _def_line(root, rel, symbol) or 1
    start = max(1, start - 2)
    end = min(len(lines), start + max_lines - 1)
    return {
        "id": ref_id,
        "path": rel,
        "lines": [start, end],
        "content": "\n".join(lines[start - 1 : end]),
    }
