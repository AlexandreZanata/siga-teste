"""Primitivas determinísticas internas (P05-T01, ADR-013 em docs/06).

Camada de baixo nível sobre indexer, graph e retrieval:
- `repo_tree`, `find_file`, `find_symbol`, `find_references`, `find_callers`,
  `find_callees`, `search_text`, `read_symbol`, `get_file_outline`,
  `git_history`, `git_diff`, `find_related_tests`, `find_migration`.

Schemas JSON congelados em `tools/primitives_schema.json`.
Todo símbolo retornado pelo grafo existe por construção nos nós indexados.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any

from graph import store
from indexer import sql_tables
from retrieval import callgraph, outline, search

SCHEMA_PATH = Path(__file__).resolve().parent / "primitives_schema.json"


def _load_schemas() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


PRIMITIVE_SCHEMAS: dict[str, Any] = _load_schemas()["primitives"]


def list_primitives() -> list[str]:
    """Lista os nomes das 13 primitivas congeladas."""
    return sorted(PRIMITIVE_SCHEMAS.keys())


def get_primitive_schema(name: str) -> dict[str, Any]:
    """Retorna o schema JSON de uma primitiva ou levanta ValueError."""
    if name not in PRIMITIVE_SCHEMAS:
        raise ValueError(f"primitiva desconhecida: {name!r}")
    return PRIMITIVE_SCHEMAS[name]


def _check_type(data: Any, expected: str, context: str) -> None:
    if expected == "object":
        if not isinstance(data, dict):
            raise ValueError(
                f"{context}: esperado object, recebido {type(data).__name__}"
            )
    elif expected == "array":
        if not isinstance(data, list):
            raise ValueError(
                f"{context}: esperado array, recebido {type(data).__name__}"
            )
    elif expected == "string":
        if not isinstance(data, str):
            raise ValueError(
                f"{context}: esperado string, recebido {type(data).__name__}"
            )
    elif expected == "integer":
        if not isinstance(data, int) or isinstance(data, bool):
            raise ValueError(
                f"{context}: esperado integer, recebido {type(data).__name__}"
            )
    elif expected == "number":
        if not isinstance(data, (int, float)) or isinstance(data, bool):
            raise ValueError(
                f"{context}: esperado number, recebido {type(data).__name__}"
            )
    elif expected == "boolean":
        if not isinstance(data, bool):
            raise ValueError(
                f"{context}: esperado boolean, recebido {type(data).__name__}"
            )
    elif expected == "null":
        if data is not None:
            raise ValueError(
                f"{context}: esperado null, recebido {type(data).__name__}"
            )
    else:
        raise ValueError(f"{context}: tipo de schema não suportado: {expected!r}")


def _validate_schema(data: Any, schema: dict[str, Any], context: str = "") -> None:
    expected_type = schema.get("type")
    if expected_type is not None:
        allowed = expected_type if isinstance(expected_type, list) else [expected_type]
        matched = False
        last_err = None
        for t in allowed:
            try:
                _check_type(data, t, context)
                matched = True
                break
            except ValueError as err:
                last_err = err
        if not matched:
            raise last_err or ValueError(f"{context}: tipo inválido")

    if isinstance(data, dict):
        required = schema.get("required", [])
        for req in required:
            if req not in data:
                raise ValueError(f"{context}: campo obrigatório {req!r} ausente")
        properties = schema.get("properties", {})
        for key, val in data.items():
            if key in properties:
                _validate_schema(val, properties[key], context=f"{context}.{key}")
            elif schema.get("additionalProperties") is False:
                raise ValueError(f"{context}: propriedade não permitida: {key!r}")

    elif isinstance(data, list):
        items_schema = schema.get("items")
        if items_schema:
            for idx, item in enumerate(data):
                _validate_schema(item, items_schema, context=f"{context}[{idx}]")

    elif isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            raise ValueError(
                f"{context}: valor {data} menor que o mínimo {schema['minimum']}"
            )


def validate_primitive_args(name: str, args: dict[str, Any]) -> None:
    """Valida argumentos contra o schema da primitiva."""
    schema = get_primitive_schema(name)
    param_schema = schema["parameters"]
    _validate_schema(args, param_schema, context=f"args de {name}")
    try:
        import jsonschema

        jsonschema.validate(instance=args, schema=param_schema)
    except ImportError:
        pass
    except Exception as e:
        raise ValueError(str(e)) from e


def validate_primitive_result(name: str, result: Any) -> None:
    """Valida o resultado retornado contra o schema da primitiva."""
    schema = get_primitive_schema(name)
    return_schema = schema["returns"]
    _validate_schema(result, return_schema, context=f"result de {name}")
    try:
        import jsonschema

        jsonschema.validate(instance=result, schema=return_schema)
    except ImportError:
        pass
    except Exception as e:
        raise ValueError(str(e)) from e


# --- 13 Primitivas ---


def repo_tree(repo: str | Path, subpath: str = "", max_depth: int = 2) -> dict[str, Any]:
    """Árvore determinística de diretórios e arquivos a partir de git ls-files."""
    root = Path(repo).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"repositório inexistente: {repo}")
    target_dir = (root / subpath).resolve() if subpath else root
    if not target_dir.is_dir():
        raise FileNotFoundError(f"subpath inexistente: {subpath}")

    files_raw: list[str] = []
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        files_raw = [line.strip() for line in out.stdout.splitlines() if line.strip()]
    except Exception:
        for p in root.rglob("*"):
            if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts:
                files_raw.append(str(p.relative_to(root)))

    subpath_clean = subpath.strip("/").strip()
    directories: set[str] = set()
    files: set[str] = set()

    for rel_path in files_raw:
        if subpath_clean and not (
            rel_path == subpath_clean or rel_path.startswith(subpath_clean + "/")
        ):
            continue

        if subpath_clean:
            rel_to_sub = rel_path[len(subpath_clean) :].lstrip("/")
        else:
            rel_to_sub = rel_path

        parts = rel_to_sub.split("/")
        if len(parts) <= max_depth:
            files.add(rel_path)

        for d in range(1, min(len(parts), max_depth + 1)):
            dir_parts = parts[:d]
            if subpath_clean:
                dir_path = f"{subpath_clean}/{'/'.join(dir_parts)}"
            else:
                dir_path = "/".join(dir_parts)
            directories.add(dir_path)

    return {
        "root": str(root),
        "subpath": subpath,
        "directories": sorted(directories),
        "files": sorted(files),
    }


def find_file(repo: str | Path, pattern: str, limit: int = 20) -> list[str]:
    """Arquivos rastreados cujo nome contenha o padrão."""
    return search.find_files(repo, pattern, limit=limit)


find_files = find_file


def find_symbol(conn: sqlite3.Connection, name: str, limit: int = 20) -> list[dict[str, Any]]:
    """Busca de símbolos no índice do grafo (FTS5 com fallback SQL LIKE)."""
    escaped = name.replace('"', '""')
    fts_query = f'"{escaped}"'
    hits: list[dict[str, Any]] = []
    try:
        hits = store.search_fts(conn, fts_query, limit=limit)
    except sqlite3.OperationalError:
        pass

    if not hits:
        rows = conn.execute(
            "SELECT name, file, kind FROM nodes WHERE name LIKE ? ORDER BY name LIMIT ?",
            (f"%{name}%", limit),
        ).fetchall()
        hits = [{"name": r[0], "file": r[1], "kind": r[2]} for r in rows]
    return hits


def find_references(
    repo: str | Path,
    symbol: str,
    globs: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Ocorrências de referência textual a símbolo no código."""
    root = Path(repo)
    if globs is None:
        if (root / "siga-ex").is_dir():
            globs = ["siga-ex/**", "sigaex/**"]
        else:
            globs = None
    return search.search_text(root, symbol, globs=globs, limit=limit)


def find_callers(
    repo: str | Path,
    symbol: str,
    globs: list[str] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Chamadores estáticos de um símbolo no repositório."""
    root = Path(repo)
    if globs is None:
        if (root / "siga-ex").is_dir():
            globs = ["siga-ex/**/*.java", "sigaex/**/*.java"]
        else:
            globs = ["**/*.java"]
    return search.search_text(root, symbol, globs=globs, limit=limit)


def find_callees(java_path: str | Path, method_name: str) -> list[str]:
    """Métodos invocados por um método Java a partir da AST Tree-sitter."""
    path = Path(java_path)
    if not path.is_file():
        raise FileNotFoundError(f"arquivo java inexistente: {java_path}")
    try:
        callees = callgraph.method_callees(path, method_name)
        return sorted(callees)
    except ValueError:
        return []


def search_text(
    repo: str | Path,
    pattern: str,
    globs: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Busca textual determinística por padrão via ripgrep."""
    return search.search_text(repo, pattern, globs=globs, limit=limit)


def read_symbol(
    conn: sqlite3.Connection,
    name: str,
    file: str | None = None,
) -> dict[str, Any] | None:
    """Leitura de nó de símbolo e suas conexões no grafo SQLite."""
    row = None
    if file:
        row = conn.execute(
            "SELECT id, kind, name, file FROM nodes WHERE name = ? AND file = ? LIMIT 1",
            (name, file),
        ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT id, kind, name, file FROM nodes WHERE name = ? LIMIT 1",
            (name,),
        ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT id, kind, name, file FROM nodes WHERE LOWER(name) = LOWER(?) LIMIT 1",
            (name,),
        ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT id, kind, name, file FROM nodes WHERE name LIKE ? ORDER BY LENGTH(name) LIMIT 1",
            (f"%{name}",),
        ).fetchone()

    if not row:
        return None

    node_id, kind, node_name, node_file = row

    out_rows = conn.execute(
        """SELECT e.type, n.name, n.kind, n.file
           FROM edges e JOIN nodes n ON e.dst = n.id
           WHERE e.src = ?
           ORDER BY e.type, n.name""",
        (node_id,),
    ).fetchall()
    outgoing = [
        {"type": r[0], "name": r[1], "kind": r[2], "file": r[3]} for r in out_rows
    ]

    in_rows = conn.execute(
        """SELECT e.type, n.name, n.kind, n.file
           FROM edges e JOIN nodes n ON e.src = n.id
           WHERE e.dst = ?
           ORDER BY e.type, n.name""",
        (node_id,),
    ).fetchall()
    incoming = [
        {"type": r[0], "name": r[1], "kind": r[2], "file": r[3]} for r in in_rows
    ]

    return {
        "name": node_name,
        "kind": kind,
        "file": node_file,
        "incoming": incoming,
        "outgoing": outgoing,
    }


def get_file_outline(file: str | Path) -> dict[str, Any]:
    """Outline estrutural de arquivo Java extraído via Tree-sitter."""
    return outline.get_file_outline(file)


def _files_in_commit(repo: str | Path, sha: str) -> list[str]:
    out = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            "--root",
            sha,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return sorted(line.strip() for line in out.stdout.splitlines() if line.strip())


def _renames_in_commit(repo: str | Path, sha: str) -> list[dict[str, str]]:
    """Renomeações do commit via name-status (`R100 old new`)."""
    out = subprocess.run(
        ["git", "-C", str(repo), "show", "--name-status", "--format=", sha],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    renames: list[dict[str, str]] = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].startswith("R"):
            renames.append({"from": parts[1].strip(), "to": parts[2].strip()})
    return renames


_RESOLVE_CACHE: dict[tuple[str, str], str] = {}


def resolve_to_head(repo: str | Path, path: str) -> str:
    """Mapeia um path histórico para o equivalente no HEAD via cadeia de renames.

    Fast path: se existe no HEAD com o mesmo nome, é identidade (limitação
    documentada: renomeado-para-fora-e-recriado resolve para o recriado).
    Só stdlib + git read-only; resultado cacheado por processo.
    """
    key = (str(repo), path)
    cached = _RESOLVE_CACHE.get(key)
    if cached is not None:
        return cached
    current = path
    if (Path(repo) / current).is_file():
        _RESOLVE_CACHE[key] = current
        return current
    for _ in range(25):
        out = subprocess.run(
            ["git", "-C", str(repo), "log", "--format=%H", "--", current],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        moved = False
        for sha in out.stdout.splitlines():
            sha = sha.strip()
            if not sha:
                continue
            for ren in _renames_in_commit(repo, sha):
                if ren["from"] == current:
                    current = ren["to"]
                    moved = True
                    break
            if moved:
                break
        if not moved:
            break
    _RESOLVE_CACHE[key] = current
    return current


def git_history(
    repo: str | Path,
    path: str | None = None,
    limit: int = 20,
    follow: bool = True,
) -> list[dict[str, Any]]:
    """Histórico de commits somente leitura com autor, data e arquivos tocados.

    `follow` (default True) atravessa renomeações (`git log --follow`, um path);
    cada commit carrega `renames` (lista vazia quando não há).
    """
    cmd = [
        "git",
        "-C",
        str(repo),
        "log",
        f"-{limit}",
        "--format=%H%x00%s%x00%ad%x00%an",
        "--date=short",
    ]
    if path:
        if follow:
            cmd.append("--follow")
        cmd += ["--", path]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
    commits: list[dict[str, Any]] = []
    for line in out.stdout.splitlines():
        parts = line.split("\x00")
        if len(parts) >= 4 and parts[0]:
            sha, subject, date, author = parts[0], parts[1], parts[2], parts[3]
            files = _files_in_commit(repo, sha)
            commits.append(
                {
                    "sha": sha,
                    "subject": subject,
                    "date": date,
                    "author": author,
                    "files": files,
                    "renames": _renames_in_commit(repo, sha),
                }
            )
    return commits


def git_diff(
    repo: str | Path,
    commit: str,
    path: str | None = None,
    parent: str | None = None,
) -> dict[str, Any]:
    """Diff unificado somente leitura entre commits ou com o commit pai."""
    if parent:
        cmd = ["git", "-C", str(repo), "diff", "--no-color", parent, commit]
    else:
        cmd = ["git", "-C", str(repo), "show", "--no-color", "--format=", commit]
    if path:
        cmd += ["--", path]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
    return {
        "commit": commit,
        "parent": parent,
        "path": path,
        "diff": out.stdout,
    }


def find_related_tests(repo: str | Path, symbol: str, limit: int = 20) -> list[str]:
    """Arquivos de teste relacionados que referenciam um símbolo."""
    return callgraph.related_tests(repo, symbol, limit=limit)


_SQL_TABLES_CACHE: dict[Path, dict[str, list[str]]] = {}
_SQL_FILES_CACHE: dict[Path, list[Path]] = {}


def _sql_tables_cached(path: Path) -> dict[str, list[str]]:
    """tables_in_sql por arquivo, cacheado (conteúdo imutável durante o processo)."""
    cached = _SQL_TABLES_CACHE.get(path)
    if cached is None:
        try:
            cached = sql_tables.tables_in_sql(
                path.read_text(encoding="utf-8", errors="replace")
            )
        except Exception:
            cached = {"writes": [], "reads": []}
        _SQL_TABLES_CACHE[path] = cached
    return cached


def _sql_files_cached(root: Path) -> list[Path]:
    """Lista de *.sql do repositório, cacheada por raiz (árvore imutável no processo)."""
    cached = _SQL_FILES_CACHE.get(root)
    if cached is None:
        cached = sorted(p for p in root.glob("**/*.sql") if ".git" not in p.parts)
        _SQL_FILES_CACHE[root] = cached
    return cached


def _table_in_sql_file(path: Path, table: str) -> bool:
    tables = _sql_tables_cached(path)
    all_tables = [t.lower() for t in tables["writes"] + tables["reads"]]
    return table.lower() in all_tables


def find_migration(
    repo: str | Path,
    table: str,
    conn: sqlite3.Connection | None = None,
) -> list[str]:
    """Arquivos de migração SQL que tocam uma tabela via grafo ou varredura."""
    if conn is not None:
        try:
            rows = conn.execute(
                """SELECT DISTINCT n.file
                   FROM edges e
                   JOIN nodes t ON e.src = t.id
                   JOIN nodes n ON e.dst = n.id
                   WHERE t.kind = 'table' AND LOWER(t.name) = LOWER(?) AND e.type = 'MIGRATION'
                   ORDER BY n.file""",
                (table,),
            ).fetchall()
            if rows:
                return [r[0] for r in rows if r[0]]
        except sqlite3.OperationalError:
            pass

    root = Path(repo)
    all_sql = _sql_files_cached(root)
    migration_dir_sql = [
        p for p in all_sql if "db" in p.parts and "migration" in p.parts and p.parts.index("migration") == p.parts.index("db") + 1
    ]
    hits: list[str] = []
    for sql_path in migration_dir_sql:
        if _table_in_sql_file(sql_path, table):
            hits.append(str(sql_path))
    if not hits:
        for sql_path in all_sql:
            if _table_in_sql_file(sql_path, table):
                hits.append(str(sql_path))
    return sorted(set(hits))
