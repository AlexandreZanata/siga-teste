"""Package context: geração e comparação de cápsulas de contexto mínimas para a IA grande."""

from __future__ import annotations

from context.capsule import (
    CodeSnippet,
    ContextCapsule,
    build_context_capsule,
    calculate_cost_usd,
    calculate_token_reduction,
    compare_capsule_formats,
    count_tokens,
    count_tokens_whitespace,
)

__all__ = [
    "CodeSnippet",
    "ContextCapsule",
    "build_context_capsule",
    "calculate_cost_usd",
    "calculate_token_reduction",
    "compare_capsule_formats",
    "count_tokens",
    "count_tokens_whitespace",
]
