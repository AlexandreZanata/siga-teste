"""Baseline ingênua de localização (P04-T02): termos da query + agregação.

Pipeline determinístico que o bench usa para rodar tarefas ponta a ponta
sem LLM: tokeniza a mensagem, busca cada termo no slice e agrega por
arquivo (contagem de termos distintos). É o piso que o nano deve superar.
Só stdlib + retrieval.search.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from retrieval.search import _slice_globs, search_text

STOPWORDS = frozenset(
    "a ao aos aquela aquelas aquele aqueles aquilo as ate com como da das de "
    "dela delas dele deles depois do dos e ela elas ele eles em enquanto entre "
    "era eram essa essas esse esses esta estas este estes foi foram fazer ha "
    "isso isto ja lhe lhes mais mas me mesmo minha minhas meu meus muito na "
    "nas nao nem no nos nossa nossas nosso nossos nunca o os ou para pela "
    "pelas pelo pelos por qual quando que quem se sem ser seu seus sim sobre "
    "sua suas talvez tambem te tem tenho um uma umas uns".split()
)


def _ascii(token: str) -> str:
    """Remove acentos para aproximar linguagem natural de identificadores do código."""
    return "".join(
        char for char in unicodedata.normalize("NFKD", token) if not unicodedata.combining(char)
    )


def terms(query: str) -> list[str]:
    """Termos buscáveis: normalizados, ≥4 chars e fora de stopwords."""
    seen: list[str] = []
    for raw_token in re.findall(r"[^\W_]+", query.lower(), flags=re.UNICODE):
        token = _ascii(raw_token)
        if len(token) >= 4 and token not in STOPWORDS and token not in seen:
            seen.append(token)
    return seen


def expanded_terms(query: str) -> list[str]:
    """Termos + formas previsíveis de domínio para queries curtas e pouco contextuais."""
    expanded: list[str] = []
    for token in terms(query):
        variants = [token]
        if token.endswith("acao") and len(token) > 7:
            variants.append(token[:-4] + "ar")
        if token.endswith("acoes") and len(token) > 7:
            variants.append(token[:-5] + "ar")
        if token.endswith("oes") and len(token) > 5:
            variants.append(token[:-3] + "ao")
        if token.endswith("atura") and len(token) > 7:
            variants.append(token[:-5] + "ar")
        if token.endswith("s") and len(token) > 4:
            variants.append(token[:-1])
        for variant in variants:
            if len(variant) >= 4 and variant not in expanded:
                expanded.append(variant)
    return expanded


def broadened_terms(query: str) -> list[str]:
    """Termos ampliados p/ fallback antes de declarar vazio (H03, docs/19).

    Base (`expanded_terms`) + quebra camelCase do token original
    (`LimiteDias` → limite/dias), sem dígitos finais (`relatorio2` →
    `relatorio`), mínimo 3 chars. Superset determinístico da base.
    """
    base = expanded_terms(query)
    extra: list[str] = []
    for raw_token in re.findall(r"[^\W_]+", query, flags=re.UNICODE):
        ascii_token = _ascii(raw_token)
        parts = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", ascii_token).split()
        for part in parts:
            lowered = part.lower()
            for cand in (lowered, re.sub(r"\d+$", "", lowered)):
                if len(cand) >= 3 and cand not in STOPWORDS and cand not in base and cand not in extra:
                    extra.append(cand)
    return base + extra


def naive_locate(repo: str | Path, query: str, limit: int = 5) -> list[str]:
    """Top arquivos por nº de termos distintos que ocorrem (desempate: nome)."""
    root = Path(repo)
    globs = _slice_globs(root)
    votes: dict[str, int] = {}
    for term in expanded_terms(query):
        for hit in search_text(root, term, globs=globs, limit=100):
            votes[hit["file"]] = votes.get(hit["file"], 0) + 1
    ranked = sorted(votes, key=lambda f: (-votes[f], f))
    return ranked[:limit]
