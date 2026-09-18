"""Métricas do SIGA-Bench (P04-T02, lista completa em docs/10 §2).

Funções puras sobre resultados já produzidos (sem I/O, sem LLM).
Contagem de tokens = proxy whitespace documentado (sem tokenizer externo
na V1); custo exige preços explícitos (sem defaults mágicos).
"""

from __future__ import annotations

import statistics


def recall_at_k(ranked: list[str], expected: set[str], k: int) -> float:
    """Fração dos esperados presentes no top-k (file ou symbol)."""
    if not expected:
        return 1.0
    return len(set(ranked[:k]) & expected) / len(expected)


def tool_selection_accuracy(predicted: list[str], expected: list[str]) -> float:
    """Fração de turnos com a tool correta (listas pareadas por turno)."""
    if not expected:
        return 1.0
    return sum(p == e for p, e in zip(predicted, expected)) / len(expected)


def sequence_success(predicted: list[str], expected: list[str]) -> float:
    """1.0 se a sequência de tools é exatamente a esperada, senão 0.0."""
    return 1.0 if list(predicted) == list(expected) else 0.0


def argument_exact_match(predicted: dict, expected: dict) -> float:
    """1.0 se args iguais (chaves e valores), senão 0.0."""
    return 1.0 if dict(predicted) == dict(expected) else 0.0


def invalid_tool_call_rate(calls: list[dict], known_tools: set[str]) -> float:
    """Fração de calls com nome fora do catálogo ou args ausentes (sem 'name')."""
    if not calls:
        return 0.0
    bad = sum(1 for c in calls if c.get("name") not in known_tools)
    return bad / len(calls)


def no_tool_accuracy(predicted_empty: list[bool], expected_empty: list[bool]) -> float:
    """Fração de acertos na decisão chamar-vs-`[]` (listas pareadas)."""
    if not expected_empty:
        return 1.0
    return sum(p == e for p, e in zip(predicted_empty, expected_empty)) / len(expected_empty)


def hallucination_rate(returned: list[str], existing: set[str]) -> float:
    """Fração dos retornados que NÃO existem (paths ou símbolos)."""
    if not returned:
        return 0.0
    return sum(1 for r in returned if r not in existing) / len(returned)


def trace_accuracy(predicted_chain: list[str], expected_chain: list[str]) -> float:
    """Fração dos elos esperados presentes em ordem (subsequência)."""
    if not expected_chain:
        return 1.0
    it = iter(predicted_chain)
    return sum(any(link == got for got in it) for link in expected_chain) / len(expected_chain)


def mean_tool_calls(calls_per_task: list[int]) -> float:
    """Média de calls por tarefa (0.0 se vazio)."""
    return sum(calls_per_task) / len(calls_per_task) if calls_per_task else 0.0


def latency_p50_p95(samples_ms: list[float]) -> dict:
    """P50/P95 de latências em ms (exige ≥1 amostra)."""
    if not samples_ms:
        raise ValueError("sem amostras de latência")
    ordered = sorted(samples_ms)
    return {
        "p50_ms": statistics.median(ordered),
        "p95_ms": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
    }


def count_tokens(text: str) -> int:
    """Proxy whitespace de tokens (V1, documentado; tokenizer real na P09)."""
    return len(text.split())


def cost_usd(tokens_in: int, tokens_out: int, price_in_per_1k: float, price_out_per_1k: float) -> float:
    """Custo em USD; preços explícitos por 1k tokens (sem defaults)."""
    return tokens_in / 1000 * price_in_per_1k + tokens_out / 1000 * price_out_per_1k


def e2e_success(task_results: list[bool]) -> float:
    """Fração de tarefas concluídas ponta a ponta."""
    if not task_results:
        return 1.0
    return sum(1 for r in task_results if r) / len(task_results)


def summarize(task_scores: list[dict]) -> dict:
    """Agrega lista de dicts de métricas por tarefa em médias (chaves numéricas)."""
    if not task_scores:
        return {}
    keys = [k for k, v in task_scores[0].items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return {k: sum(s[k] for s in task_scores) / len(task_scores) for k in keys}
