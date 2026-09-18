"""Indexer SQL + entidade JPA (P02-T02): tabelas lidas/escritas e migration por entidade.

Só stdlib (regex + pathlib). Dialetos Oracle/Postgres do SIGA tratados por
palavras-chave, não por parser completo — precisão medida na P02-T03/P03.
"""

from __future__ import annotations

import re
from pathlib import Path

_TABLE_ANNOTATION = re.compile(r'@Table\s*\(\s*name\s*=\s*"([^"]+)"')
_VERSION = re.compile(r"V(\d+[_\.\d]*)__")

_WRITES = re.compile(
    r"\b(?:CREATE\s+TABLE|ALTER\s+TABLE|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+([A-Za-z_][\w$]*(?:\.[\w$]+)?)",
    re.IGNORECASE,
)
_READS = re.compile(
    r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w$]*(?:\.[\w$]+)?)",
    re.IGNORECASE,
)


def _normalize(name: str) -> str:
    return name.strip().strip(";").lower()


def tables_in_sql(text: str) -> dict:
    """Separa tabelas em writes (DDL/DML de escrita) e reads (FROM/JOIN)."""
    writes = {_normalize(m) for m in _WRITES.findall(text)}
    reads = {_normalize(m) for m in _READS.findall(text)} - writes
    return {"writes": sorted(writes), "reads": sorted(reads)}


def entity_table(java_path: str | Path) -> str | None:
    """Valor de @Table(name=...) de uma entidade JPA real; None se ausente."""
    path = Path(java_path)
    if not path.is_file():
        raise FileNotFoundError(f"entidade inexistente: {java_path}")
    match = _TABLE_ANNOTATION.search(path.read_text(encoding="utf-8", errors="replace"))
    return match.group(1).lower() if match else None


def parse_migration(path: str | Path) -> dict:
    """Uma migration Flyway real: versão (do nome) + tabelas tocadas."""
    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"migration inexistente: {path}")
    text = resolved.read_text(encoding="utf-8", errors="replace")
    version = _VERSION.search(resolved.name)
    tables = tables_in_sql(text)
    return {
        "file": str(resolved),
        "version": version.group(1) if version else None,
        "writes": tables["writes"],
        "reads": tables["reads"],
    }


def migrations_touching(migration_dir: str | Path, table: str) -> list[str]:
    """Migrations cujo SQL toca `table` (nome já normalizado, minúsculas)."""
    wanted = table.lower()
    hits: list[str] = []
    for path in sorted(Path(migration_dir).glob("*.sql")):
        tables = tables_in_sql(path.read_text(encoding="utf-8", errors="replace"))
        if wanted in tables["writes"] or wanted in tables["reads"]:
            hits.append(str(path))
    return hits
