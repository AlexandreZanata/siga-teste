"""Contrato MCP do SIGA Needle Expert (P10-T01, ADR-020 em docs/12).

- `mcp/schema.json` lista exatamente os 5 métodos com params grounding-safe.
- `mcp/server.py` despacha cada método em repo sintético (sempre no CI).
- `mcp/client.py` resolve tarefa via stdio sem importar o core (gate da fase).
- Privacidade: respostas nunca despejam código bruto além da cápsula mínima.
- Desacoplamento: core nunca importa cliente; `mcp/` nunca importa cliente.
- Tarefa real do slice via cliente externo (pula no CI sem o clone do SIGA).
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from mcp import client as mcp_client_module
from mcp import server as mcp_server_module
from mcp.client import MCPClient, MCPError

ROOT = Path(__file__).resolve().parent.parent.parent
SIGA = ROOT.parent
SCHEMA_PATH = ROOT / "mcp/schema.json"

EXPECTED_METHODS = ("siga.locate", "siga.trace", "siga.impact", "siga.history", "siga.context")

SYNTH_JAVA = """package br.gov.exemplo;
import java.util.List;
public class ServicoExemplo extends BaseServico {
    private String codigo;
    public String executar(String parametro) {
        validar(parametro);
        return parametro;
    }
    private void validar(String p) {}
    public void rotina01() { validar("a"); }
    public void rotina02() { validar("b"); }
    public void rotina03() { validar("c"); }
    public void rotina04() { validar("d"); }
    public void rotina05() { validar("e"); }
    public void rotina06() { validar("f"); }
    public void rotina07() { validar("g"); }
    public void rotina08() { validar("h"); }
    public void rotina09() { validar("i"); }
    public void rotina10() { validar("j"); }
    public void rotina11() { validar("k"); }
    public void rotina12() { validar("l"); }
    public void rotina13() { validar("m"); }
    public void rotina14() { validar("n"); }
    public void rotina15() { validar("o"); }
    public void rotina16() { validar("p"); }
    public void rotina17() { validar("q"); }
    public void rotina18() { validar("r"); }
    public void rotina19() { validar("s"); }
    public void rotina20() { validar("t"); }
}
"""

RAW_MARKER = "CONTEUDO-BRUTO-QUE-NAO-PODE-VAZAR-INTEGRO"


def _requires_siga() -> None:
    if not (SIGA / "siga-ex").is_dir():
        pytest.skip("Clone do SIGA não disponível ao lado (CI sem siga-ex)")


def _seed_repo(root: Path) -> Path:
    (root / "ServicoExemplo.java").write_text(SYNTH_JAVA.replace("validar(parametro);", f"validar(parametro); // {RAW_MARKER}"), encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "seed"],
        check=True,
    )
    return root


def _schema_methods(schema: dict) -> dict:
    return schema["properties"]["methods"]["properties"]


def _method_params(methods: dict, name: str) -> dict:
    return methods[name]["properties"]["parameters"]


def test_schema_lists_five_methods_with_grounding_safe_params():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    methods = _schema_methods(schema)
    assert set(methods) == set(EXPECTED_METHODS)
    assert set(methods) == set(mcp_server_module.METHODS)

    locate_params = _method_params(methods, "siga.locate")
    assert locate_params["required"] == ["query"]
    assert set(locate_params["properties"]["kind"]["enum"]) == {"file", "symbol", "controller", "entity", "jsp", "migration", "test"}

    trace_params = _method_params(methods, "siga.trace")
    assert trace_params["required"] == ["symbol"]
    assert trace_params["properties"]["depth"]["maximum"] == 3

    impact_params = _method_params(methods, "siga.impact")
    assert impact_params["required"] == ["target"]

    history_params = _method_params(methods, "siga.history")
    required_sets = [set(branch["required"]) for branch in history_params["anyOf"]]
    assert {"target"} in required_sets and {"query"} in required_sets

    context_params = _method_params(methods, "siga.context")
    assert context_params["required"] == ["symbols", "task"]


def test_server_dispatches_all_methods_on_synthetic_repo(tmp_path: Path):
    repo = _seed_repo(tmp_path)

    locate = mcp_server_module.dispatch("siga.locate", {"query": "ServicoExemplo executar", "repo": str(repo)})
    assert locate["result"], "locate deve retornar candidatos no repo sintético"
    assert all(Path(hit["file"]).is_file() for hit in locate["result"] if hit.get("file"))

    trace = mcp_server_module.dispatch("siga.trace", {"symbol": "ServicoExemplo", "repo": str(repo)})
    assert trace["result"]["symbol"] == "ServicoExemplo"

    impact = mcp_server_module.dispatch("siga.impact", {"target": "ServicoExemplo", "repo": str(repo)})
    assert "ServicoExemplo" in impact["result"].get("symbols", []) or impact["result"].get("target")

    history = mcp_server_module.dispatch("siga.history", {"query": "seed", "repo": str(repo)})
    assert history["result"]["commits"], "histórico deve listar o commit seed"

    context = mcp_server_module.dispatch(
        "siga.context", {"symbols": ["ServicoExemplo"], "task": "tarefa sintética", "repo": str(repo)}
    )
    assert "ServicoExemplo" in context["result"]["symbols"]

    for envelope in (locate, trace, impact, history, context):
        assert set(envelope) == {"result", "provenance", "cost"}
        assert envelope["provenance"]["index_version"] == mcp_server_module.INDEX_VERSION
        assert envelope["cost"]["tokens"] > 0
        assert envelope["cost"]["latency_ms"] >= 0

    with pytest.raises(KeyError):
        mcp_server_module.dispatch("siga.inventada", {}, repo_root=repo)

    bad = mcp_server_module.handle_request({"jsonrpc": "2.0", "id": 7, "method": "siga.locate", "params": {}})
    assert bad["error"]["code"] == -32602


def test_external_client_resolves_task_without_importing_core(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    with MCPClient() as external:
        envelope = external.call("siga.locate", {"query": "ServicoExemplo executar", "repo": str(repo)})
        assert envelope["result"], "cliente externo deve localizar via MCP"
        assert all(Path(hit["file"]).is_file() for hit in envelope["result"] if hit.get("file"))
        capsule = external.call(
            "siga.context",
            {"symbols": ["ServicoExemplo"], "task": "tarefa sintética via MCP", "repo": str(repo)},
        )
        assert "ServicoExemplo" in capsule["result"]["symbols"]
        assert capsule["provenance"]["repo_commit"] is not None

        with pytest.raises(MCPError):
            external.call("siga.inventada", {})

    probe = subprocess.run(
        [sys.executable, "-c", "import mcp.client, sys; print(sorted(m for m in sys.modules if m.split('.')[0] in {'tools', 'inference', 'teachers', 'training', 'graph', 'indexer'}))"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert probe.stdout.strip() == "[]", f"cliente importou o core: {probe.stdout.strip()}"
    assert mcp_client_module.__name__ == "mcp.client"


def test_privacy_no_raw_code_beyond_capsule(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    raw = (repo / "ServicoExemplo.java").read_text(encoding="utf-8")

    locate = mcp_server_module.dispatch("siga.locate", {"query": "ServicoExemplo", "repo": str(repo)})
    locate_text = json.dumps(locate["result"], ensure_ascii=False)
    assert RAW_MARKER not in locate_text
    assert raw not in locate_text

    context = mcp_server_module.dispatch(
        "siga.context", {"symbols": ["ServicoExemplo"], "task": "auditoria de privacidade", "repo": str(repo)}
    )
    snippets_text = json.dumps(context["result"].get("snippets", []), ensure_ascii=False)
    assert len(snippets_text) < len(raw), "snippets da cápsula devem ser mínimos, não o arquivo inteiro"


def test_decoupling_core_never_imports_clients():
    client_names = {"opencode", "codex", "claude", "cursor", "mcp"}
    for package in ("tools", "inference", "training", "context", "retrieval", "graph", "indexer"):
        for path in sorted((ROOT / package).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name.split(".")[0] not in client_names, f"{path}:{node.lineno}"
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    assert node.module.split(".")[0] not in client_names, f"{path}:{node.lineno}"
    for path in sorted((ROOT / "mcp").rglob("*.py")):
        if "__pycache__" in path.parts or path.name.startswith("test"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in {"opencode", "codex", "claude", "cursor", "teachers"}, f"{path}:{node.lineno}"
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                assert node.module.split(".")[0] not in {"opencode", "codex", "claude", "cursor", "teachers"}, f"{path}:{node.lineno}"


def test_slice_task_via_external_mcp_client():
    _requires_siga()
    with MCPClient() as external:
        envelope = external.call("siga.locate", {"query": "ExDocumentoController"})
        names = [Path(hit["file"]).name for hit in envelope["result"] if hit.get("file")]
        assert "ExDocumentoController.java" in names, f"cliente MCP deveria localizar o controller: {names[:5]}"
        capsule = external.call(
            "siga.context",
            {"symbols": ["ExDocumentoController"], "task": "ExDocumentoController"},
        )
        assert "ExDocumentoController" in capsule["result"]["symbols"]
