"""Indexer JSP (P02-T02): includes por path real + referências a símbolos.

Só stdlib (regex + pathlib). Includes estáticos (`<%@ include file>`)
resolvidos contra o diretório do JSP; dinâmicos (`jsp:include`,
`c:import`) registrados como raw quando não literais.
"""

from __future__ import annotations

import re
from pathlib import Path

_STATIC_INCLUDE = re.compile(r'<%@\s*include\s+file\s*=\s*"([^"]+)"')
_DYNAMIC_INCLUDE = re.compile(r"<jsp:include\s+[^>]*page\s*=\s*\"([^\"]+)\"")
_C_IMPORT = re.compile(r"<c:import\s+[^>]*url\s*=\s*\"([^\"]+)\"")


def parse_file(path: str | Path) -> dict:
    """Extrai includes de um JSP real; ausente = FileNotFoundError."""
    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"JSP inexistente: {path}")
    text = resolved.read_text(encoding="utf-8", errors="replace")
    includes: list[dict] = []
    for raw in _STATIC_INCLUDE.findall(text):
        target = (resolved.parent / raw).resolve()
        includes.append({"raw": raw, "static": True, "resolved": str(target), "exists": target.is_file()})
    for pattern in (_DYNAMIC_INCLUDE, _C_IMPORT):
        for raw in pattern.findall(text):
            if raw.startswith(("${", "http:", "https:", "//")):
                includes.append({"raw": raw, "static": False, "resolved": None, "exists": False})
            else:
                target = (resolved.parent / raw).resolve()
                includes.append(
                    {"raw": raw, "static": False, "resolved": str(target), "exists": target.is_file()}
                )
    return {"file": str(resolved), "includes": includes}


def find_referencing(webapp_root: str | Path, symbol: str) -> list[str]:
    """JSPs sob webapp_root cujo texto menciona symbol (ordenado, paths reais)."""
    root = Path(webapp_root)
    return sorted(str(p) for p in root.rglob("*.jsp") if symbol in p.read_text(encoding="utf-8", errors="replace"))
