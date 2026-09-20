"""Testes de contrato das primitivas determinísticas (P05-T01, docs/06 ADR-013).

- Schemas JSON congelados das 13 primitivas são Draft-07 válidos.
- Schemas validam args e results (sucesso e rejeição estrita).
- Todo símbolo retornado por find_symbol e read_symbol existe no grafo.
- Execução determinística ponta a ponta em repo sintético e no clone real.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
import subprocess

import pytest

from graph import store
from indexer import java_symbols, sql_tables
from tools import primitives

ROOT = Path(__file__).resolve().parent.parent.parent
SIGA = ROOT.parent

EXPECTED_PRIMITIVES = {
    "find_callees",
    "find_callers",
    "find_file",
    "find_migration",
    "find_references",
    "find_related_tests",
    "find_symbol",
    "get_file_outline",
    "git_diff",
    "git_history",
    "read_symbol",
    "repo_tree",
    "search_text",
}

SAMPLE_JAVA = """package br.gov.exemplo;

import java.util.List;

public class ServicoExemplo extends BaseServico implements Operavel {
    private String codigo;

    public ServicoExemplo() {}

    public String executar(String parametro) {
        validar(parametro);
        return parametro;
    }

    private void validar(String p) {}
}
"""

BASE_JAVA = """package br.gov.exemplo;

public class BaseServico {
    protected Long id;
}
"""

OPERAVEL_JAVA = """package br.gov.exemplo;

public interface Operavel {
    String executar(String p);
}
"""

TEST_JAVA = """package br.gov.exemplo;

public class ServicoExemploTest {
    public void testExecutar() {
        ServicoExemplo s = new ServicoExemplo();
        s.executar("ok");
    }
}
"""

MIGR_SQL = """CREATE TABLE exemplo.servico (
    id NUMBER PRIMARY KEY,
    codigo VARCHAR2(64)
);
"""


def _git(*args: str, cwd: Path) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=tester", "-c", "user.email=tester@siga.test", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return out.stdout.strip()


def _setup_synthetic_repo_and_graph(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)

    pkg_dir = repo / "src/main/java/br/gov/exemplo"
    pkg_dir.mkdir(parents=True)
    test_dir = repo / "src/test/java/br/gov/exemplo"
    test_dir.mkdir(parents=True)
    mig_dir = repo / "src/main/resources/db/migration"
    mig_dir.mkdir(parents=True)

    (pkg_dir / "ServicoExemplo.java").write_text(SAMPLE_JAVA, encoding="utf-8")
    (pkg_dir / "BaseServico.java").write_text(BASE_JAVA, encoding="utf-8")
    (pkg_dir / "Operavel.java").write_text(OPERAVEL_JAVA, encoding="utf-8")
    (test_dir / "ServicoExemploTest.java").write_text(TEST_JAVA, encoding="utf-8")
    (mig_dir / "V001__servico.sql").write_text(MIGR_SQL, encoding="utf-8")

    _git("add", ".", cwd=repo)
    _git("commit", "-m", "feat: initial commit", cwd=repo)

    conn = store.connect()
    for jf in repo.rglob("*.java"):
        store.upsert_java(conn, java_symbols.parse_file(jf))
    for sf in repo.rglob("*.sql"):
        store.upsert_migration(conn, sql_tables.parse_migration(sf))
    conn.commit()
    return repo, conn


def test_schema_coverage_and_draft7():
    prims = primitives.list_primitives()
    assert set(prims) == EXPECTED_PRIMITIVES
    assert len(prims) == 13

    try:
        from jsonschema import Draft7Validator

        for name in prims:
            schema = primitives.get_primitive_schema(name)
            Draft7Validator.check_schema(schema["parameters"])
            Draft7Validator.check_schema(schema["returns"])
    except ImportError:
        pass


def test_args_validation_accepts_valid_and_rejects_invalid():
    valid_cases: dict[str, dict] = {
        "repo_tree": {"repo": "/tmp", "subpath": "src", "max_depth": 2},
        "find_file": {"repo": "/tmp", "pattern": "Doc", "limit": 10},
        "find_symbol": {"name": "ExDocumento", "limit": 5},
        "find_references": {"repo": "/tmp", "symbol": "ExDocumento", "limit": 10},
        "find_callers": {"repo": "/tmp", "symbol": "ExDocumento", "limit": 20},
        "find_callees": {"java_path": "/tmp/A.java", "method_name": "executar"},
        "search_text": {"repo": "/tmp", "pattern": "texto", "limit": 5},
        "read_symbol": {"name": "ExDocumento", "file": "/tmp/ExDocumento.java"},
        "get_file_outline": {"file": "/tmp/A.java"},
        "git_history": {"repo": "/tmp", "limit": 10},
        "git_diff": {"repo": "/tmp", "commit": "a" * 40},
        "find_related_tests": {"repo": "/tmp", "symbol": "ExDocumento", "limit": 5},
        "find_migration": {"repo": "/tmp", "table": "siga.ex_documento"},
    }

    for name, args in valid_cases.items():
        primitives.validate_primitive_args(name, args)

    # Rejeição de campo obrigatório ausente
    with pytest.raises(ValueError):
        primitives.validate_primitive_args("find_symbol", {})

    with pytest.raises(ValueError):
        primitives.validate_primitive_args("search_text", {"repo": "/tmp"})

    # Rejeição de tipo errado
    with pytest.raises(ValueError):
        primitives.validate_primitive_args("find_file", {"repo": 123, "pattern": "a"})

    # Rejeição de número menor que o mínimo
    with pytest.raises(ValueError):
        primitives.validate_primitive_args(
            "repo_tree", {"repo": "/tmp", "max_depth": 0}
        )

    # Rejeição de campo adicional não permitido
    with pytest.raises(ValueError):
        primitives.validate_primitive_args(
            "find_symbol", {"name": "A", "campo_fantasma": True}
        )

    # Primitiva desconhecida
    with pytest.raises(ValueError, match="desconhecida"):
        primitives.validate_primitive_args("primitiva_inexistente", {})


def test_results_validation_accepts_valid_and_rejects_invalid():
    valid_results: dict[str, object] = {
        "repo_tree": {
            "root": "/tmp",
            "subpath": "",
            "directories": ["src"],
            "files": ["pom.xml"],
        },
        "find_file": ["/tmp/A.java"],
        "find_symbol": [{"name": "A", "kind": "class", "file": "/tmp/A.java"}],
        "find_references": [{"file": "/tmp/A.java", "lines": [1, 5]}],
        "find_callers": [{"file": "/tmp/B.java", "lines": [10]}],
        "find_callees": ["validar", "println"],
        "search_text": [{"file": "/tmp/A.java", "lines": [1]}],
        "read_symbol": {
            "name": "A",
            "kind": "class",
            "file": "/tmp/A.java",
            "incoming": [],
            "outgoing": [
                {"type": "EXTENDS", "name": "B", "kind": "class", "file": None}
            ],
        },
        "get_file_outline": {
            "file": "/tmp/A.java",
            "package": "br.gov",
            "imports_count": 0,
            "types": [
                {
                    "kind": "class",
                    "name": "A",
                    "annotations": [],
                    "extends": None,
                    "implements": [],
                    "methods": ["executar"],
                    "constructors": ["A"],
                    "fields": ["codigo"],
                    "nested": [],
                }
            ],
        },
        "git_history": [
            {
                "sha": "a" * 40,
                "subject": "commit",
                "date": "2026-09-18",
                "author": "tester",
                "files": ["A.java"],
                "renames": [{"from": "Old.java", "to": "A.java"}],
            }
        ],
        "git_diff": {
            "commit": "a" * 40,
            "parent": None,
            "path": None,
            "diff": "+line\n",
        },
        "find_related_tests": ["/tmp/ATest.java"],
        "find_migration": ["/tmp/V001__init.sql"],
    }

    for name, result in valid_results.items():
        primitives.validate_primitive_result(name, result)

    # read_symbol aceita None (símbolo não encontrado)
    primitives.validate_primitive_result("read_symbol", None)

    # Rejeição de resultado incompatível
    with pytest.raises(ValueError):
        primitives.validate_primitive_result("find_callees", "não_é_lista")

    with pytest.raises(ValueError):
        primitives.validate_primitive_result("find_file", [123])

    with pytest.raises(ValueError):
        primitives.validate_primitive_result("repo_tree", {"root": "/tmp"})


def test_all_returned_symbols_exist_in_graph(tmp_path: Path):
    repo, conn = _setup_synthetic_repo_and_graph(tmp_path)

    # 1. find_symbol
    symbols_found = primitives.find_symbol(conn, "ServicoExemplo")
    assert symbols_found, "ServicoExemplo deve existir no grafo"
    primitives.validate_primitive_result("find_symbol", symbols_found)

    for sym in symbols_found:
        row = conn.execute(
            "SELECT id FROM nodes WHERE name = ? AND kind = ?",
            (sym["name"], sym["kind"]),
        ).fetchone()
        assert row is not None, f"símbolo {sym} retornado não existe na tabela nodes"

    # 2. find_symbol por método
    methods_found = primitives.find_symbol(conn, "executar")
    assert methods_found, "método executar deve ser encontrado"
    for m in methods_found:
        row = conn.execute(
            "SELECT id FROM nodes WHERE name = ? AND kind = ?", (m["name"], m["kind"])
        ).fetchone()
        assert row is not None, f"método {m} retornado não existe no grafo"

    # 3. read_symbol nó e conexões
    symbol_details = primitives.read_symbol(conn, "ServicoExemplo")
    assert symbol_details is not None
    primitives.validate_primitive_result("read_symbol", symbol_details)

    node_row = conn.execute(
        "SELECT id FROM nodes WHERE name = ? AND kind = ?",
        (symbol_details["name"], symbol_details["kind"]),
    ).fetchone()
    assert (
        node_row is not None
    ), f"nó principal {symbol_details['name']} não existe no grafo"

    for edge in symbol_details["outgoing"]:
        target_row = conn.execute(
            "SELECT id FROM nodes WHERE name = ? AND kind = ?",
            (edge["name"], edge["kind"]),
        ).fetchone()
        assert (
            target_row is not None
        ), f"símbolo de saída {edge['name']} não existe no grafo"

    for edge in symbol_details["incoming"]:
        src_row = conn.execute(
            "SELECT id FROM nodes WHERE name = ? AND kind = ?",
            (edge["name"], edge["kind"]),
        ).fetchone()
        assert (
            src_row is not None
        ), f"símbolo de entrada {edge['name']} não existe no grafo"

    # 4. Símbolo inexistente retorna None
    missing = primitives.read_symbol(conn, "SimboloInexistenteTotal")
    assert missing is None
    primitives.validate_primitive_result("read_symbol", missing)


def test_primitives_execution_synthetic_repo(tmp_path: Path):
    repo, conn = _setup_synthetic_repo_and_graph(tmp_path)
    commit_sha = _git("rev-parse", "HEAD", cwd=repo)

    # repo_tree
    args_tree = {"repo": str(repo), "subpath": "", "max_depth": 2}
    primitives.validate_primitive_args("repo_tree", args_tree)
    tree = primitives.repo_tree(**args_tree)
    primitives.validate_primitive_result("repo_tree", tree)
    assert "src" in tree["directories"]
    assert "src/main" in tree["directories"]

    # find_file
    args_ff = {"repo": str(repo), "pattern": "ServicoExemplo"}
    primitives.validate_primitive_args("find_file", args_ff)
    files = primitives.find_file(**args_ff)
    primitives.validate_primitive_result("find_file", files)
    assert any("ServicoExemplo.java" in f for f in files)
    assert all(Path(f).is_file() for f in files)

    # find_references
    args_ref = {"repo": str(repo), "symbol": "ServicoExemplo"}
    primitives.validate_primitive_args("find_references", args_ref)
    refs = primitives.find_references(**args_ref)
    primitives.validate_primitive_result("find_references", refs)
    assert refs, "referência a ServicoExemplo deve ser encontrada"
    assert all(Path(r["file"]).is_file() for r in refs)

    # find_callers
    args_callers = {"repo": str(repo), "symbol": "ServicoExemplo"}
    primitives.validate_primitive_args("find_callers", args_callers)
    callers = primitives.find_callers(**args_callers)
    primitives.validate_primitive_result("find_callers", callers)
    assert any("ServicoExemploTest.java" in c["file"] for c in callers)

    # find_callees
    target_java = repo / "src/main/java/br/gov/exemplo/ServicoExemplo.java"
    args_callees = {"java_path": str(target_java), "method_name": "executar"}
    primitives.validate_primitive_args("find_callees", args_callees)
    callees = primitives.find_callees(**args_callees)
    primitives.validate_primitive_result("find_callees", callees)
    assert "validar" in callees

    # search_text
    args_st = {"repo": str(repo), "pattern": "Operavel"}
    primitives.validate_primitive_args("search_text", args_st)
    hits = primitives.search_text(**args_st)
    primitives.validate_primitive_result("search_text", hits)
    assert hits

    # get_file_outline
    args_outline = {"file": str(target_java)}
    primitives.validate_primitive_args("get_file_outline", args_outline)
    outline_data = primitives.get_file_outline(**args_outline)
    primitives.validate_primitive_result("get_file_outline", outline_data)
    assert outline_data["package"] == "br.gov.exemplo"
    assert outline_data["types"][0]["name"] == "ServicoExemplo"
    assert "executar" in outline_data["types"][0]["methods"]

    # git_history
    args_gh = {"repo": str(repo), "limit": 5}
    primitives.validate_primitive_args("git_history", args_gh)
    history = primitives.git_history(**args_gh)
    primitives.validate_primitive_result("git_history", history)
    assert len(history) == 1
    assert history[0]["sha"] == commit_sha
    assert len(history[0]["files"]) >= 4

    # git_diff
    args_gd = {"repo": str(repo), "commit": commit_sha}
    primitives.validate_primitive_args("git_diff", args_gd)
    diff = primitives.git_diff(**args_gd)
    primitives.validate_primitive_result("git_diff", diff)
    assert diff["commit"] == commit_sha
    assert "ServicoExemplo" in diff["diff"]

    # find_related_tests
    args_rt = {"repo": str(repo), "symbol": "ServicoExemplo"}
    primitives.validate_primitive_args("find_related_tests", args_rt)
    tests = primitives.find_related_tests(**args_rt)
    primitives.validate_primitive_result("find_related_tests", tests)
    assert any("ServicoExemploTest.java" in t for t in tests)

    # find_migration (via grafo e via arquivos)
    args_mig = {"repo": str(repo), "table": "exemplo.servico"}
    primitives.validate_primitive_args("find_migration", args_mig)
    migs_graph = primitives.find_migration(
        repo=str(repo), table="exemplo.servico", conn=conn
    )
    primitives.validate_primitive_result("find_migration", migs_graph)
    assert any("V001__servico.sql" in m for m in migs_graph)

    migs_scan = primitives.find_migration(repo=str(repo), table="exemplo.servico")
    assert any("V001__servico.sql" in m for m in migs_scan)


def test_primitives_on_real_slice_if_available():
    if not (SIGA / "siga-ex").is_dir():
        pytest.skip("Clone do SIGA não disponível ao lado")

    # 1. find_file
    args_ff = {"repo": str(SIGA), "pattern": "ExDocumentoController.java", "limit": 5}
    primitives.validate_primitive_args("find_file", args_ff)
    files = primitives.find_file(**args_ff)
    primitives.validate_primitive_result("find_file", files)
    assert any(f.endswith("ExDocumentoController.java") for f in files)
    assert all(Path(f).is_file() for f in files)

    # 2. search_text
    args_st = {"repo": str(SIGA), "pattern": "calcularTramitesPendentes", "limit": 5}
    primitives.validate_primitive_args("search_text", args_st)
    hits = primitives.search_text(**args_st)
    primitives.validate_primitive_result("search_text", hits)
    assert any("ExTramiteBL.java" in h["file"] for h in hits)

    # 3. find_references
    args_ref = {"repo": str(SIGA), "symbol": "ExTramiteBL", "limit": 5}
    primitives.validate_primitive_args("find_references", args_ref)
    refs = primitives.find_references(**args_ref)
    primitives.validate_primitive_result("find_references", refs)
    assert refs

    # 4. find_callers
    args_callers = {"repo": str(SIGA), "symbol": "ExTramiteBL", "limit": 5}
    primitives.validate_primitive_args("find_callers", args_callers)
    callers = primitives.find_callers(**args_callers)
    primitives.validate_primitive_result("find_callers", callers)
    assert callers

    # 5. get_file_outline
    bl_file = SIGA / "siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl/ExTramiteBL.java"
    args_outline = {"file": str(bl_file)}
    primitives.validate_primitive_args("get_file_outline", args_outline)
    outline_data = primitives.get_file_outline(**args_outline)
    primitives.validate_primitive_result("get_file_outline", outline_data)
    assert outline_data["package"] == "br.gov.jfrj.siga.ex.bl"

    # 6. git_history
    args_gh = {"repo": str(SIGA), "limit": 3}
    primitives.validate_primitive_args("git_history", args_gh)
    history = primitives.git_history(**args_gh)
    primitives.validate_primitive_result("git_history", history)
    assert len(history) == 3
    assert len(history[0]["sha"]) == 40

    # 7. git_diff
    args_gd = {"repo": str(SIGA), "commit": history[0]["sha"]}
    primitives.validate_primitive_args("git_diff", args_gd)
    diff = primitives.git_diff(**args_gd)
    primitives.validate_primitive_result("git_diff", diff)
    assert diff["commit"] == history[0]["sha"]

    # 8. find_migration
    args_mig = {"repo": str(SIGA), "table": "siga.ex_documento"}
    primitives.validate_primitive_args("find_migration", args_mig)
    migs = primitives.find_migration(**args_mig)
    primitives.validate_primitive_result("find_migration", migs)
    assert any("V104__Documento_com_Principal.sql" in m for m in migs)
