-- Graph do slice SIGA (P02-T03, nodes/edges de docs/05 §2, ADR-011).
-- SQLite + WAL + FTS5. Vocabulário fechado via CHECK; só o usado na V1 é populado.

PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN (
        'repository', 'module', 'file', 'package', 'class', 'interface',
        'enum', 'annotation', 'method', 'constructor', 'field', 'endpoint',
        'controller', 'entity', 'dao', 'service', 'jsp', 'table',
        'migration', 'test', 'commit', 'feature'
    )),
    name TEXT NOT NULL,
    file TEXT,
    extra TEXT NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_nodes_kind_name_file
    ON nodes (kind, name, file);

CREATE TABLE IF NOT EXISTS edges (
    src INTEGER NOT NULL REFERENCES nodes (id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN (
        'CONTAINS', 'DEFINES', 'CALLS', 'CALLED_BY', 'EXTENDS',
        'IMPLEMENTS', 'IMPORTS', 'USES', 'ENDPOINT', 'HANDLED_BY',
        'VIEW', 'ENTITY', 'PERSISTED_BY', 'READS_TABLE', 'WRITES_TABLE',
        'MIGRATION', 'TESTED_BY', 'DEPENDS_ON', 'CHANGED_WITH', 'MODIFIED_BY'
    )),
    dst INTEGER NOT NULL REFERENCES nodes (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_edges_src ON edges (src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges (dst);
CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_unique ON edges (src, type, dst);

CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5 (
    name,
    file,
    kind,
    tokenize = 'unicode61'
);
