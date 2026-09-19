"""Servidor MCP fino do SIGA Needle Expert (P10-T01, ADR-020 em docs/12).

Expõe as 5 tools semânticas como métodos `siga.locate/trace/impact/history/context`
sobre transporte stdio JSON-RPC 2.0 (só stdlib, sem dependência nova). O cliente
externo (OpenCode/Codex/Claude/Cursor) fala JSON-RPC e nunca importa o core:
`tools/` não importa `mcp` e `mcp/` não importa nenhum cliente.

Cada resposta carrega `{result, provenance{index_version, repo_commit},
cost{tokens, latency_ms}}` (desenho em docs/12 §1). Privacidade: o servidor
devolve exatamente o que as tools retornam (candidatos/outlines/cápsula
mínima); nunca despeja código bruto além dos snippets da cápsula.

Segurança (F14, ADR-024): auth fail-closed por token (`SIGA_MCP_TOKEN_FILE`
preferido ou `SIGA_MCP_TOKEN`) recebido por requisição em `_siga_auth`,
verificação em tempo constante e rate limit sliding-window por token
(`-32001` auth, `-32002` rate). Sem token configurado o servidor não serve
nenhum método.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, TextIO

from mcp.security import (
    AUTH_FIELD,
    RateLimitExceeded,
    RateLimiter,
    TokenNotConfigured,
    load_required_token,
    verify_token,
)
from tools import siga_context, siga_history, siga_impact, siga_locate, siga_trace

METHODS = ("siga.locate", "siga.trace", "siga.impact", "siga.history", "siga.context")

AUTH_ERROR_CODE = -32001
RATE_LIMIT_ERROR_CODE = -32002

INDEX_VERSION = "tree-sitter-java-0.23"


def _default_repo() -> Path:
    parent = Path(__file__).resolve().parent.parent.parent
    if (parent / "siga-ex").is_dir():
        return parent
    return Path(__file__).resolve().parent.parent


def _repo_commit(root: Path) -> str | None:
    """HEAD do repo (somente leitura); None fora de repo git."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return out.stdout.strip() or None


def _cost_tokens(result: Any) -> int:
    """Proxy whitespace de tokens do resultado (V1, mesmo de evaluation/metrics)."""
    return len(json.dumps(result, ensure_ascii=False, default=str).split())


def _required(params: dict[str, Any], name: str) -> Any:
    if name not in params:
        raise ValueError(f"param obrigatório ausente: {name!r}")
    return params[name]


def dispatch(method: str, params: dict[str, Any] | None, repo_root: Path | None = None) -> dict[str, Any]:
    """Executa um método MCP e devolve o envelope `{result, provenance, cost}`."""
    if method not in METHODS:
        raise KeyError(f"método desconhecido: {method!r} (esperado um de {list(METHODS)})")
    if not isinstance(params, dict):
        raise ValueError("params deve ser um objeto")

    root = Path(params.get("repo") or repo_root or _default_repo()).resolve()
    if not root.is_dir():
        raise ValueError(f"repo inexistente: {params.get('repo')!r}")

    started = time.perf_counter()
    if method == "siga.locate":
        result = siga_locate(
            _required(params, "query"),
            kind=params.get("kind"),
            repo=root,
            limit=int(params.get("limit", 10)),
        )
    elif method == "siga.trace":
        result = siga_trace(
            _required(params, "symbol"),
            depth=int(params.get("depth", 2)),
            repo=root,
        )
    elif method == "siga.impact":
        result = siga_impact(
            _required(params, "target"),
            hops=int(params.get("hops", 1)),
            repo=root,
        )
    elif method == "siga.history":
        result = siga_history(
            target=params.get("target"),
            query=params.get("query"),
            since=params.get("since"),
            limit=int(params.get("limit", 10)),
            repo=root,
        )
    else:
        result = siga_context(
            symbols=_required(params, "symbols"),
            task=_required(params, "task"),
            repo=root,
        )
    latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
    return {
        "result": result,
        "provenance": {"index_version": INDEX_VERSION, "repo_commit": _repo_commit(root)},
        "cost": {"tokens": _cost_tokens(result), "latency_ms": latency_ms},
    }


def _error_response(req_id: Any, code: int, message: str) -> dict[str, Any]:
    """Envelope de erro JSON-RPC; nunca ecoa o token recebido."""
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle_request(
    request: dict[str, Any],
    repo_root: Path | None = None,
    *,
    token: str | None = None,
    rate_limiter: RateLimiter | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Trata uma requisição JSON-RPC 2.0 autenticada (F14, ADR-024).

    `token` é o segredo esperado, carregado uma vez no boot via
    `load_required_token`; o cliente envia o dele por requisição em
    `AUTH_FIELD`. Fail-closed: sem `token`, toda requisição é recusada com
    -32001. Exceder a taxa do token devolve -32002. `dispatch()` e o
    envelope de sucesso permanecem intactos (contrato ADR-020).
    """
    req_id = request.get("id") if isinstance(request, dict) else None
    if not token:
        return _error_response(
            req_id,
            AUTH_ERROR_CODE,
            "servidor sem auth configurada (fail-closed); defina SIGA_MCP_TOKEN_FILE ou SIGA_MCP_TOKEN",
        )
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return _error_response(req_id, -32600, "requisição inválida")
    if not verify_token(token, request.get(AUTH_FIELD)):
        return _error_response(req_id, AUTH_ERROR_CODE, "token ausente ou inválido")
    try:
        (rate_limiter if rate_limiter is not None else RateLimiter.from_env(environ)).check(token)
    except RateLimitExceeded as err:
        return _error_response(req_id, RATE_LIMIT_ERROR_CODE, str(err))
    method = request.get("method")
    if method == "siga.list_methods":
        return {"jsonrpc": "2.0", "id": req_id, "result": list(METHODS)}
    try:
        envelope = dispatch(method, request.get("params"), repo_root=repo_root)
    except KeyError as err:
        return _error_response(req_id, -32601, str(err))
    except (ValueError, TypeError, FileNotFoundError) as err:
        return _error_response(req_id, -32602, str(err))
    return {"jsonrpc": "2.0", "id": req_id, "result": envelope}


def serve(
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    repo_root: Path | None = None,
    *,
    token: str | None = None,
    rate_limiter: RateLimiter | None = None,
    environ: dict[str, str] | None = None,
) -> None:
    """Loop stdio: uma requisição JSON-RPC por linha, uma resposta por linha.

    O token é carregado uma única vez no boot (fail-closed): sem
    `SIGA_MCP_TOKEN_FILE`/`SIGA_MCP_TOKEN`, `serve` levanta
    `TokenNotConfigured` e não serve nenhum método.
    """
    expected = token if token is not None else load_required_token(environ)
    limiter = rate_limiter if rate_limiter is not None else RateLimiter.from_env(environ)
    for line in stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as err:
            stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"JSON inválido: {err}"}}, ensure_ascii=False) + "\n")
            stdout.flush()
            continue
        response = handle_request(request, repo_root=repo_root, token=expected, rate_limiter=limiter)
        stdout.write(json.dumps(response, ensure_ascii=False, default=str) + "\n")
        stdout.flush()


if __name__ == "__main__":
    try:
        serve()
    except TokenNotConfigured as err:
        print(f"mcp.server: {err}", file=sys.stderr)
        sys.exit(1)
