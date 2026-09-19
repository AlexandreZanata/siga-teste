"""Cliente MCP externo de referência (P10-T01, ADR-020 em docs/12).

Demonstra o gate da fase: um agente externo (OpenCode/Codex/Claude/Cursor)
resolve tarefas do slice falando JSON-RPC 2.0 via stdio com o servidor como
subprocesso, sem importar o core (`tools`, `inference`, `teachers`,
`training`, `graph`, `indexer`). Só stdlib.

Segurança (F14, ADR-024): o cliente envia o token por requisição em
`_siga_auth`, lido de `SIGA_MCP_TOKEN_FILE` (preferido) ou `SIGA_MCP_TOKEN`
no boot (`start()`); sem token configurado o cliente não inicia (fail-closed,
espelho do servidor). Recusas de auth chegam como `MCPError` com código
-32001; rate limit como -32002.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.security import AUTH_FIELD, TOKEN_ENV, TokenNotConfigured, load_required_token

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


class MCPError(RuntimeError):
    """Erro retornado pelo servidor MCP (código JSON-RPC em `code`)."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class MCPClient:
    """Cliente MCP via stdio; o servidor roda como subprocesso isolado."""

    def __init__(
        self,
        server_cmd: list[str] | None = None,
        cwd: str | Path | None = None,
        timeout: int = 180,
        *,
        token: str | None = None,
        environ: dict[str, str] | None = None,
    ) -> None:
        self.server_cmd = list(server_cmd or [sys.executable, "-m", "mcp.server"])
        self.cwd = str(cwd or PACKAGE_ROOT)
        self.timeout = timeout
        self._token = token
        self._environ = environ
        self._proc: subprocess.Popen[str] | None = None
        self._next_id = 0

    def __enter__(self) -> MCPClient:
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def start(self) -> None:
        """Sobe o servidor como subprocesso (sem importar o core no cliente).

        O token é resolvido uma única vez aqui: argumento explícito ou, na
        falta, `SIGA_MCP_TOKEN_FILE`/`SIGA_MCP_TOKEN` do ambiente. Sem nenhum
        dos dois, `start()` levanta `TokenNotConfigured` (fail-closed).
        """
        if self._proc is not None:
            return
        if self._token is None:
            self._token = load_required_token(self._environ)
        # Provisiona o token no ambiente do servidor que este cliente lança
        # (padrão ssh-agent): o subprocesso nasce autenticado com o mesmo
        # segredo que este cliente enviará por requisição. Se o operador já
        # provisionou TOKEN_ENV no ambiente, ele vence (nunca rebaixar um
        # segredo explícito) — e um cliente com token divergente então
        # recebe -32001 do servidor do operador.
        child_env = {**os.environ}
        child_env.setdefault(TOKEN_ENV, self._token)
        self._proc = subprocess.Popen(
            self.server_cmd,
            cwd=self.cwd,
            env=child_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

    def close(self) -> None:
        """Encerra o servidor."""
        if self._proc is None:
            return
        try:
            self._proc.stdin.close()
        except (BrokenPipeError, AttributeError):
            pass
        self._proc.wait(timeout=15)
        self._proc = None

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Chama um método MCP e devolve o envelope `{result, provenance, cost}`."""
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise MCPError("cliente não iniciado (use `with MCPClient():`)")
        self._next_id += 1
        if self._token is None:
            raise TokenNotConfigured("cliente sem token (use `with MCPClient():` após start bem-sucedido)")
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params or {},
            AUTH_FIELD: self._token,
        }
        try:
            self._proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except BrokenPipeError as err:
            raise MCPError(f"servidor encerrou a entrada: {err}") from err
        line = self._proc.stdout.readline()
        if not line:
            raise MCPError("servidor encerrou a saída sem resposta")
        try:
            response = json.loads(line)
        except json.JSONDecodeError as err:
            raise MCPError(f"resposta não-JSON do servidor: {err}") from err
        if response.get("id") != self._next_id:
            raise MCPError(f"id de resposta inesperado: {response!r}")
        if "error" in response:
            err = response["error"] or {}
            raise MCPError(str(err.get("message", err)), code=err.get("code"))
        return response["result"]
