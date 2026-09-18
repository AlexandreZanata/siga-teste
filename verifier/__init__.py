"""Módulo verifier (P06-T01, ADR-016 em docs/08).

Verificação determinística de dados gerados por teachers:
- AST (Tree-sitter)
- Símbolos e grafo (SQLite)
- Grep (ripgrep)
- Git histórico e diff
- Maven módulos
- Testes unitários
- Anti-leakage contra benchmark

Regra central: Resposta só entra em verified/ se verificação determinística passa;
consenso LLM nunca é ground truth.
"""

from verifier.checker import (
    check_anti_leakage,
    check_ast,
    check_diff,
    check_git,
    check_grep,
    check_maven,
    check_symbol,
    check_tests,
)
from verifier.pipeline import promote_to_verified, verify_candidate

__all__ = [
    "check_ast",
    "check_symbol",
    "check_grep",
    "check_git",
    "check_diff",
    "check_maven",
    "check_tests",
    "check_anti_leakage",
    "verify_candidate",
    "promote_to_verified",
]
