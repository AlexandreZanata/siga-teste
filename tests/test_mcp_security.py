"""Segurança MCP (F14, ADR-024): token fail-closed + rate limit, stdlib only.

- `load_required_token`: SIGA_MCP_TOKEN_FILE (preferido) ou SIGA_MCP_TOKEN;
  sem nenhuma fonte (ou token vazio) ⇒ `TokenNotConfigured` (fail-closed).
- `verify_token`: tempo constante; vazio/None/tipo errado ⇒ rejeição.
- `RateLimiter`: sliding-window por identidade sha256 do token.
- `handle_request`: -32001 sem/par token, -32002 ao exceder a janela;
  `dispatch()` e o envelope de sucesso intactos (contrato ADR-020).
- Token nunca ecoado em respostas nem erros.
"""

from __future__ import annotations

import io
import json
import subprocess

import pytest

from mcp import server as mcp_server
from mcp.security import (
    AUTH_FIELD,
    RATE_LIMIT_ENV,
    RATE_WINDOW_ENV,
    TOKEN_ENV,
    TOKEN_FILE_ENV,
    RateLimitExceeded,
    RateLimiter,
    TokenNotConfigured,
    load_required_token,
    verify_token,
)

TOKEN = "token-f14-secreto"


class FakeClock:
    """Relógio monotônico controlável para testar a janela deslizante."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _request(method: str = "siga.list_methods", *, auth: bool = True, **extra: object) -> dict:
    req: dict = {"jsonrpc": "2.0", "id": 1, "method": method, "params": {}}
    if auth:
        req[AUTH_FIELD] = TOKEN
    req.update(extra)
    return req


def test_load_required_token_requires_env_or_file():
    with pytest.raises(TokenNotConfigured):
        load_required_token({})
    with pytest.raises(TokenNotConfigured):
        load_required_token({TOKEN_ENV: "   "})


def test_load_required_token_prefers_file(tmp_path):
    token_file = tmp_path / "siga.mcp.token"
    token_file.write_text("tok-do-arquivo\n", encoding="utf-8")
    token = load_required_token({TOKEN_ENV: "tok-do-ambiente", TOKEN_FILE_ENV: str(token_file)})
    assert token == "tok-do-arquivo"
    assert load_required_token({TOKEN_ENV: "tok-do-ambiente"}) == "tok-do-ambiente"


def test_load_required_token_fails_on_unreadable_file(tmp_path):
    with pytest.raises(TokenNotConfigured):
        load_required_token({TOKEN_FILE_ENV: str(tmp_path / "inexistente.token")})


def test_verify_token_constant_time_contract():
    assert verify_token(TOKEN, TOKEN)
    assert not verify_token(TOKEN, "outro")
    assert not verify_token(TOKEN, None)
    assert not verify_token(TOKEN, "")
    assert not verify_token(TOKEN, 42)
    assert not verify_token(TOKEN, [TOKEN])


def test_rate_limiter_sliding_window():
    clock = FakeClock()
    limiter = RateLimiter(max_requests=2, window_seconds=10, clock=clock)
    limiter.check("a")
    clock.now += 5
    limiter.check("a")
    with pytest.raises(RateLimitExceeded):
        limiter.check("a")
    clock.now += 6  # primeiro hit sai da janela
    limiter.check("a")
    with pytest.raises(RateLimitExceeded):
        limiter.check("a")
    limiter.check("b")  # identidades são independentes


def test_rate_limiter_rejects_invalid_config():
    with pytest.raises(ValueError):
        RateLimiter(max_requests=0)
    with pytest.raises(ValueError):
        RateLimiter(window_seconds=0)


def test_rate_limiter_from_env_with_safe_defaults():
    assert RateLimiter.from_env({}).max_requests == 60
    assert RateLimiter.from_env({RATE_LIMIT_ENV: "5", RATE_WINDOW_ENV: "30"}).max_requests == 5
    fallback = RateLimiter.from_env({RATE_LIMIT_ENV: "abc", RATE_WINDOW_ENV: "xyz"})
    assert fallback.max_requests == 60 and fallback.window_seconds == 60.0


def test_handle_request_fail_closed_without_token():
    response = mcp_server.handle_request(_request(auth=False))
    assert response["error"]["code"] == -32001
    # Nem siga.list_methods responde sem auth configurada.
    with_token_none = mcp_server.handle_request(_request(AUTH_FIELD=TOKEN))
    assert with_token_none["error"]["code"] == -32001


def test_handle_request_rejects_missing_or_wrong_token():
    wrong = mcp_server.handle_request(_request(auth=False, AUTH_FIELD="errado"), token=TOKEN)
    assert wrong["error"]["code"] == -32001
    missing = mcp_server.handle_request(_request(auth=False), token=TOKEN)
    assert missing["error"]["code"] == -32001
    malformed = mcp_server.handle_request({"jsonrpc": "1.0", "id": 2, "method": "siga.locate"}, token=TOKEN)
    assert malformed["error"]["code"] == -32600


def test_handle_request_happy_path_and_dispatch_contract_untouched(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Aluno.java").write_text("public class Aluno {}\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "seed"],
        check=True,
    )
    listed = mcp_server.handle_request(_request(), token=TOKEN)
    assert listed["result"] == list(mcp_server.METHODS)
    locate = mcp_server.handle_request(
        _request("siga.locate", params={"query": "Aluno", "repo": str(repo)}), token=TOKEN
    )
    assert "error" not in locate and locate["result"]
    assert set(locate) == {"jsonrpc", "id", "result"}
    # dispatch() continua público e sem auth (contrato ADR-020 preservado).
    direct = mcp_server.dispatch("siga.locate", {"query": "Aluno", "repo": str(repo)})
    assert set(direct) == {"result", "provenance", "cost"}
    bad_params = mcp_server.handle_request(_request("siga.locate", params={}), token=TOKEN)
    assert bad_params["error"]["code"] == -32602


def test_handle_request_rate_limit_returns_32002():
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    first = mcp_server.handle_request(_request(), token=TOKEN, rate_limiter=limiter)
    assert "result" in first
    second = mcp_server.handle_request(_request(id=2), token=TOKEN, rate_limiter=limiter)
    assert second["error"]["code"] == -32002


def test_token_is_never_echoed_in_responses():
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    responses = [
        mcp_server.handle_request(_request(), token=TOKEN, rate_limiter=limiter),
        mcp_server.handle_request(_request(id=2), token=TOKEN, rate_limiter=limiter),
        mcp_server.handle_request(_request(auth=False, AUTH_FIELD="errado"), token=TOKEN),
        mcp_server.handle_request(_request(id=4, params={}), token=TOKEN),
        mcp_server.handle_request({}, token=TOKEN),
    ]
    for response in responses:
        assert TOKEN not in json.dumps(response, ensure_ascii=False)


def test_serve_loads_token_once_and_fails_closed(tmp_path, monkeypatch):
    lines = "\n".join(
        [
            json.dumps({**_request(), AUTH_FIELD: TOKEN}),
            json.dumps({**_request(id=2), AUTH_FIELD: "errado"}),
            json.dumps({**_request(id=3), AUTH_FIELD: TOKEN}),
        ]
    )
    out = io.StringIO()
    mcp_server.serve(io.StringIO(lines), out, token=TOKEN, rate_limiter=RateLimiter(max_requests=10))
    responses = [json.loads(line) for line in out.getvalue().splitlines()]
    assert "result" in responses[0] and responses[1]["error"]["code"] == -32001
    assert "result" in responses[2]

    monkeypatch.delenv(TOKEN_ENV, raising=False)
    monkeypatch.delenv(TOKEN_FILE_ENV, raising=False)
    monkeypatch.delenv(RATE_LIMIT_ENV, raising=False)
    monkeypatch.delenv(RATE_WINDOW_ENV, raising=False)
    with pytest.raises(TokenNotConfigured):
        mcp_server.serve(io.StringIO(""), io.StringIO())
