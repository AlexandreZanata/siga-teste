"""Store SQLite do graph (P02-T03, ADR-011 em docs/05).

Só stdlib (sqlite3). Popula nodes/edges a partir dos indexers de P02-T01/T02:
file, package, class/interface/enum (+nested), method, field, jsp, table,
migration, module, entity (@Entity), controller (*Controller/@Controller),
IMPORTS, EXTENDS/IMPLEMENTS, MIGRATION (tabela->migration), CHANGED_WITH.
Busca via FTS5; trace = BFS até depth N.
"""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

_TRACE_EDGES = (
    "CONTAINS",
    "DEFINES",
    "EXTENDS",
    "IMPLEMENTS",
    "IMPORTS",
    "HANDLED_BY",
    "VIEW",
    "ENTITY",
    "PERSISTED_BY",
    "MIGRATION",
    "TESTED_BY",
    "DEPENDS_ON",
)


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    """Conexão com schema aplicado e chaves estrangeiras ligadas."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def _node(conn: sqlite3.Connection, kind: str, name: str, file: str | None = None) -> int:
    conn.execute(
        "INSERT OR IGNORE INTO nodes (kind, name, file) VALUES (?, ?, ?)",
        (kind, name, file),
    )
    row = conn.execute(
        "SELECT id FROM nodes WHERE kind = ? AND name = ? AND file IS ?",
        (kind, name, file),
    ).fetchone()
    return int(row[0])


def _edge(conn: sqlite3.Connection, src: int, type_: str, dst: int) -> None:
    conn.execute("INSERT OR IGNORE INTO edges (src, type, dst) VALUES (?, ?, ?)", (src, type_, dst))


def _index_fts(conn: sqlite3.Connection, kind: str, name: str, file: str | None) -> None:
    conn.execute(
        "INSERT INTO fts (name, file, kind) VALUES (?, ?, ?)", (name, file or "", kind)
    )


def delete_file(conn: sqlite3.Connection, file: str) -> int:
    """Remove nodes do arquivo (edges caem em cascata) + entradas FTS. Retorna removidos."""
    ids = [r[0] for r in conn.execute("SELECT id FROM nodes WHERE file = ?", (file,))]
    if not ids:
        return 0
    conn.execute("DELETE FROM nodes WHERE file = ?", (file,))
    conn.execute("DELETE FROM fts WHERE file = ?", (file,))
    return len(ids)


def upsert_java(conn: sqlite3.Connection, rec: dict) -> int:
    """Insere parse de indexer/java_symbols.py. Retorna nodes criados (aprox)."""
    before = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    file = rec["file"]
    file_id = _node(conn, "file", file, file)
    if rec.get("package"):
        pkg_id = _node(conn, "package", rec["package"])
        _edge(conn, file_id, "CONTAINS", pkg_id)

    def add_type(node: dict, parent_id: int) -> None:
        type_id = _node(conn, node["kind"], node["name"], file)
        _edge(conn, parent_id, "DEFINES", type_id)
        _index_fts(conn, node["kind"], node["name"], file)
        for ann in node.get("annotations", []):
            if ann == "Entity":
                entity_id = _node(conn, "entity", node["name"], file)
                _edge(conn, type_id, "ENTITY", entity_id)
        if node.get("extends"):
            base_id = _node(conn, "class", node["extends"])
            _edge(conn, type_id, "EXTENDS", base_id)
        for iface in node.get("implements", []):
            iface_id = _node(conn, "interface", iface)
            _edge(conn, type_id, "IMPLEMENTS", iface_id)
        for method in node.get("methods", []):
            method_id = _node(conn, "method", f"{node['name']}::{method['name']}", file)
            _edge(conn, type_id, "DEFINES", method_id)
            _index_fts(conn, "method", f"{node['name']}::{method['name']}", file)
        for field in node.get("fields", []):
            field_id = _node(conn, "field", f"{node['name']}::{field}", file)
            _edge(conn, type_id, "DEFINES", field_id)
            _index_fts(conn, "field", f"{node['name']}::{field}", file)
        for nested in node.get("nested", []):
            add_type(nested, type_id)

    for type_node in rec.get("types", []):
        add_type(type_node, file_id)
        if type_node["name"].endswith("Controller") or "Controller" in type_node.get("annotations", []):
            ctrl_id = _node(conn, "controller", type_node["name"], file)
            _edge(conn, file_id, "HANDLED_BY", ctrl_id)
    for imp in rec.get("imports", []):
        imp_id = _node(conn, "package", imp)
        _edge(conn, file_id, "IMPORTS", imp_id)
    after = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    return after - before


def upsert_jsp(conn: sqlite3.Connection, rec: dict) -> int:
    """Insere parse de indexer/jsp_symbols.py (nó jsp + VIEW p/ includes existentes)."""
    before = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    file = rec["file"]
    jsp_id = _node(conn, "jsp", Path(file).name, file)
    _index_fts(conn, "jsp", Path(file).name, file)
    for inc in rec.get("includes", []):
        if inc.get("exists") and inc.get("resolved"):
            target_id = _node(conn, "jsp", Path(inc["resolved"]).name, inc["resolved"])
            _edge(conn, jsp_id, "VIEW", target_id)
    after = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    return after - before


def upsert_migration(conn: sqlite3.Connection, rec: dict) -> int:
    """Insere parse de indexer/sql_tables.py (nó migration + tabelas + WRITES_TABLE)."""
    before = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    mig_id = _node(conn, "migration", Path(rec["file"]).name, rec["file"])
    for table in rec.get("writes", []) + rec.get("reads", []):
        table_id = _node(conn, "table", table)
        _edge(conn, table_id, "MIGRATION", mig_id)
        _index_fts(conn, "table", table, rec["file"])
    after = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    return after - before


def upsert_module(conn: sqlite3.Connection, name: str, repo: str) -> int:
    """Nó module + DEPENDS_ON placeholder resolvido na P02-T03? Não: só o nó + file-link."""
    _node(conn, "module", name)
    return 1


def upsert_cochange(conn: sqlite3.Connection, path: str, partners: list[dict]) -> int:
    """Edges CHANGED_WITH a partir de indexer/git_history.cochange_partners."""
    before = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    src = _node(conn, "file", path, path)
    for partner in partners:
        dst = _node(conn, "file", partner["path"], partner["path"])
        _edge(conn, src, "CHANGED_WITH", dst)
    after = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    return after - before


def search_fts(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[dict]:
    """Busca textual no índice (FTS5). Verdade atual é rg/git-grep (ADR-012)."""
    rows = conn.execute(
        "SELECT name, file, kind FROM fts WHERE fts MATCH ? LIMIT ?", (query, limit)
    ).fetchall()
    return [{"name": name, "file": file, "kind": kind} for name, file, kind in rows]


def trace(conn: sqlite3.Connection, symbol: str, depth: int = 3) -> list[dict]:
    """BFS de `depth` hops a partir de nodes cujo nome contém symbol. Retorna cadeia."""
    escaped = symbol.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    starts = conn.execute(
        "SELECT id, kind, name, file FROM nodes WHERE name LIKE ? ESCAPE '\\' LIMIT 20",
        (f"%{escaped}%",),
    ).fetchall()
    if not starts:
        return []
    hops = ",".join(f"'{e}'" for e in _TRACE_EDGES)
    seen: set[int] = set()
    chain: list[dict] = []
    queue: deque[tuple[int, int]] = deque((row[0], 0) for row in starts)
    for row in starts:
        seen.add(row[0])
        chain.append({"id": row[0], "kind": row[1], "name": row[2], "file": row[3], "hop": 0})
    while queue:
        node_id, hop = queue.popleft()
        if hop >= depth:
            continue
        neighbours = conn.execute(
            f"""SELECT DISTINCT n.id, n.kind, n.name, n.file
                FROM edges e JOIN nodes n
                  ON (n.id = e.dst AND e.src = ?) OR (n.id = e.src AND e.dst = ?)
                WHERE e.type IN ({hops})""",
            (node_id, node_id),
        ).fetchall()
        for nid, kind, name, file in neighbours:
            if nid not in seen:
                seen.add(nid)
                chain.append({"id": nid, "kind": kind, "name": name, "file": file, "hop": hop + 1})
                queue.append((nid, hop + 1))
    return chain


def stats(conn: sqlite3.Connection) -> dict:
    """Contagens p/ sanity + serialização em experiments (JSON-safe)."""
    nodes = dict(conn.execute("SELECT kind, COUNT(*) FROM nodes GROUP BY kind").fetchall())
    edges = dict(conn.execute("SELECT type, COUNT(*) FROM edges GROUP BY type").fetchall())
    return {"nodes": nodes, "edges": edges, "meta": json.dumps({"store": "sqlite-fts5"})}
