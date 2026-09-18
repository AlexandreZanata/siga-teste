"""Indexer Maven (P02-T02): módulos ativos do pom raiz (comentados excluídos).

Só stdlib (xml.etree). Comentários `<!-- <module>... -->` viram nós
Comment, nunca elementos — então findall já exclui `siga-arq`.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

_NS = "{http://maven.apache.org/POM/4.0.0}"


def parse_root_pom(pom_path: str | Path, repo_root: str | Path | None = None) -> dict:
    """Módulos ativos + comentados de um pom.xml real."""
    resolved = Path(pom_path)
    if not resolved.is_file():
        raise FileNotFoundError(f"pom inexistente: {pom_path}")
    text = resolved.read_text(encoding="utf-8")
    tree = ET.fromstring(text)
    modules = [m.text.strip() for m in tree.findall(f".//{_NS}module") if m.text and m.text.strip()]
    if not modules:  # fallback sem namespace
        modules = [m.text.strip() for m in tree.findall(".//module") if m.text and m.text.strip()]
    commented = sorted(
        {m.strip() for m in re.findall(r"<!--\s*<module>([^<]+)</module>\s*-->", text)}
    )
    root = Path(repo_root) if repo_root is not None else resolved.parent
    entries = [
        {"name": name, "dir": str(root / name), "exists": (root / name).is_dir()} for name in modules
    ]
    return {"pom": str(resolved), "modules": entries, "commented": commented}
