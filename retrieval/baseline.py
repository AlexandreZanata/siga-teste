"""Baseline ingênua de localização (P04-T02): termos da query + agregação.

Pipeline determinístico que o bench usa para rodar tarefas ponta a ponta
sem LLM: tokeniza a mensagem, busca cada termo no slice e agrega por
arquivo (contagem de termos distintos). É o piso que o nano deve superar.
Só stdlib + retrieval.search.
"""

from __future__ import annotations

import re
from pathlib import Path

from retrieval.search import search_text

STOPWORDS = frozenset(
    "a ao aos aquela aquelas aquele aqueles aquilo as ate com como da das de "
    "dela delas dele deles depois do dos e ela elas ele eles em enquanto entre "
    "era eram essa essas esse esses esta estas este estes foi foram fazer ha "
    "isso isto ja lhe lhes mais mas me mesmo minha minhas meu meus muito na "
    "nas nao nem no nos nossa nossas nosso nossos nunca o os ou para pela "
    "pelas pelo pelos por qual quando que quem se sem ser seu seus sim sobre "
    "sua suas talvez tambem te tem tenho um uma umas uns".split()
)


def terms(query: str) -> list[str]:
    """Termos buscáveis: minúsculos, split em não-alfanuméricos, ≥4 chars, fora de stopwords."""
    seen: list[str] = []
    for token in re.split(r"[^a-z0-9]+", query.lower()):
        if len(token) >= 4 and token not in STOPWORDS and token not in seen:
            seen.append(token)
    return seen


def naive_locate(repo: str | Path, query: str, limit: int = 5) -> list[str]:
    """Top arquivos por nº de termos distintos que ocorrem (desempate: nome)."""
    root = Path(repo)
    votes: dict[str, int] = {}
    for term in terms(query):
        for hit in search_text(root, term, globs=["siga-ex/**", "sigaex/**"], limit=100):
            votes[hit["file"]] = votes.get(hit["file"], 0) + 1
    ranked = sorted(votes, key=lambda f: (-votes[f], f))
    return ranked[:limit]
