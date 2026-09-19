"""Edição determinística e confinada para o experimento F10.

A edição só aceita um patch unificado de um arquivo, valida todos os hunks antes
de escrever e nunca permite escapar do checkout fornecido.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _safe_path(root: Path, raw: str) -> Path:
    name = raw.strip().split("\t", 1)[0]
    if name.startswith(("a/", "b/")):
        name = name[2:]
    candidate = (root / name).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"patch fora do checkout: {raw!r}") from exc
    return candidate


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def apply_unified_patch(root: str | Path, patch: str) -> dict[str, str | int]:
    """Aplica um patch de arquivo único e retorna hashes antes/depois.

    O patch precisa conter `---`, `+++` e hunks `@@`. Todos os contextos são
    conferidos antes da primeira escrita, tornando falhas não destrutivas.
    """
    checkout = Path(root).resolve()
    lines = patch.splitlines(keepends=True)
    headers = [line for line in lines if line.startswith(("--- ", "+++ "))]
    if len(headers) != 2 or not headers[0].startswith("--- ") or not headers[1].startswith("+++ "):
        raise ValueError("patch deve conter exatamente os cabeçalhos --- e +++")
    old_path = _safe_path(checkout, headers[0][4:])
    new_path = _safe_path(checkout, headers[1][4:])
    if old_path != new_path:
        raise ValueError("patch multi-arquivo não é permitido")
    if not old_path.is_file():
        raise FileNotFoundError(old_path)

    source = old_path.read_text(encoding="utf-8").splitlines(keepends=True)
    hunks: list[tuple[int, list[str], list[str]]] = []
    index = 2
    while index < len(lines):
        match = _HUNK.match(lines[index])
        if not match:
            index += 1
            continue
        start = int(match.group(1)) - 1
        before: list[str] = []
        after: list[str] = []
        index += 1
        while index < len(lines) and not lines[index].startswith("@@ "):
            line = lines[index]
            if line.startswith(("\\ No newline", "--- ", "+++ ")):
                index += 1
                continue
            if not line or line[0] not in " +-":
                raise ValueError(f"linha de hunk inválida: {line!r}")
            if line[0] in " -":
                before.append(line[1:])
            if line[0] in " +":
                after.append(line[1:])
            index += 1
        hunks.append((start, before, after))
    if not hunks:
        raise ValueError("patch sem hunk")

    result = list(source)
    offset = 0
    for start, before, after in hunks:
        position = start + offset
        if result[position : position + len(before)] != before:
            raise ValueError(f"contexto do patch não corresponde ao arquivo em linha {start + 1}")
        result[position : position + len(before)] = after
        offset += len(after) - len(before)

    updated = "".join(result)
    original = "".join(source)
    old_path.write_text(updated, encoding="utf-8")
    return {
        "path": str(old_path.relative_to(checkout)),
        "before_sha256": _digest(original),
        "after_sha256": _digest(updated),
        "changed_lines": sum(len(before) + len(after) for _, before, after in hunks),
    }
