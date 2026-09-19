"""Segurança do servidor MCP: auth por token fail-closed + rate limit (F14, ADR-024).

O NOT-build de `docs/15` §6 proíbe "MCP público sem auth"; `docs/12` §1 já
desenhava "auth local por token em arquivo (sem rede externa obrigatória)".
Este módulo é a implementação mínima disso, stdlib only (determinístico
primeiro — nada de rede, hash ou dependência nova):

- **Token:** `SIGA_MCP_TOKEN` (valor literal) ou `SIGA_MCP_TOKEN_FILE`
  (caminho de arquivo com o token; preferência explícita ao arquivo).
  Sem nenhuma das duas variáveis, `load_required_token` levanta
  `TokenNotConfigured` — o servidor **não sobe** (fail-closed).
- **Verificação:** `hmac.compare_digest` (tempo constante); token vazio é
  sempre rejeitado, mesmo que o esperado também seja vazio.
- **Rate limit:** sliding-window em memória por identidade (token sha256),
  janela padrão 60s e máximo padrão 60 requisições por token, ajustável via
  `SIGA_MCP_RATE_LIMIT` / `SIGA_MCP_RATE_WINDOW_SECONDS`. Exceder ⇒
  `RateLimitExceeded`. Estado é por processo (stdio = um cliente).
- O token é recebido por requisição (`request["_siga_auth"]`) e **nunca**
  é ecoado em respostas, erros ou provenance.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from collections import deque
from pathlib import Path

TOKEN_ENV = "SIGA_MCP_TOKEN"
TOKEN_FILE_ENV = "SIGA_MCP_TOKEN_FILE"
RATE_LIMIT_ENV = "SIGA_MCP_RATE_LIMIT"
RATE_WINDOW_ENV = "SIGA_MCP_RATE_WINDOW_SECONDS"

DEFAULT_RATE_LIMIT = 60
DEFAULT_RATE_WINDOW_SECONDS = 60.0

AUTH_FIELD = "_siga_auth"


class TokenNotConfigured(RuntimeError):
    """Nenhum mecanismo de token configurado: servidor deve falhar ao subir."""


class RateLimitExceeded(RuntimeError):
    """Requisições do token excederam o máximo na janela atual."""


def load_required_token(environ: dict[str, str] | None = None) -> str:
    """Carrega o token exigido: SIGA_MCP_TOKEN_FILE (preferido) ou SIGA_MCP_TOKEN.

    Falha (`TokenNotConfigured`) se nenhuma fonte existir ou se o token
    resultante for vazio/whitespace — fail-closed, nunca token implícito.
    """
    env = os.environ if environ is None else environ
    file_path = env.get(TOKEN_FILE_ENV)
    if file_path:
        try:
            token = Path(file_path).read_text(encoding="utf-8")
        except OSError as err:
            raise TokenNotConfigured(f"{TOKEN_FILE_ENV} ilegível: {err}") from err
    else:
        token = env.get(TOKEN_ENV, "")
    token = token.strip()
    if not token:
        raise TokenNotConfigured(
            f"auth fail-closed: defina {TOKEN_FILE_ENV} (preferido) ou {TOKEN_ENV}"
        )
    return token


def _identity(token: str) -> str:
    """Identidade estável do token para contagem, sem reter o segredo."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class RateLimiter:
    """Sliding-window em memória: no máx. `max_requests` por `window_seconds` por token."""

    def __init__(
        self,
        max_requests: int = DEFAULT_RATE_LIMIT,
        window_seconds: float = DEFAULT_RATE_WINDOW_SECONDS,
        *,
        clock=time.monotonic,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests deve ser >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds deve ser > 0")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> RateLimiter:
        """Constrói dos limites de ambiente, com defaults seguros em valor inválido."""
        env = os.environ if environ is None else environ
        try:
            max_requests = int(env.get(RATE_LIMIT_ENV, DEFAULT_RATE_LIMIT))
        except ValueError:
            max_requests = DEFAULT_RATE_LIMIT
        try:
            window = float(env.get(RATE_WINDOW_ENV, DEFAULT_RATE_WINDOW_SECONDS))
        except ValueError:
            window = DEFAULT_RATE_WINDOW_SECONDS
        return cls(max_requests=max_requests, window_seconds=window)

    def check(self, token: str) -> None:
        """Registra a requisição do token; levanta `RateLimitExceeded` se exceder."""
        key = _identity(token)
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self.window_seconds:
                hits.popleft()
            if len(hits) >= self.max_requests:
                raise RateLimitExceeded(
                    f"rate limit excedido: {self.max_requests} req/{self.window_seconds:g}s"
                )
            hits.append(now)


def verify_token(expected: str, provided: object) -> bool:
    """Compara em tempo constante; vazio/None/tipo errado é sempre rejeição."""
    if not isinstance(provided, str) or not provided:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8"))
