"""Embeddings determinísticos CPU-only para o spike F05 (docs/15 §6).

Hashing TF (feature hashing) sobre 3-gramas de caracteres + unigramas de
palavras: vetor esparso L2-normalizado, sem rede neural, sem rede externa e
sem dependência nova (só stdlib + hashlib). O índice é gerado a cada uso a
partir do repositório — nada é treinado e nenhum dado novo é produzido.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

EMBEDDING_DIM = 512
_NGRAM_RE = re.compile(r"[a-z0-9]+")

_WORD_HASH = hashlib.md5
_BIGRAM_SEED = b"bigram:"
_TRIGRAM_SEED = b"trigram:"


def _bucket(digest: bytes, dim: int) -> int:
    return int.from_bytes(digest[:4], "little") % dim


def _features(text: str) -> dict[int, float]:
    """Pesos TF por bucket: unigramas de palavras + 2/3-gramas de caracteres."""
    weights: dict[int, float] = {}
    lowered = text.lower()
    words = _NGRAM_RE.findall(lowered)

    def add(seed: bytes) -> None:
        idx = _bucket(_WORD_HASH(seed).digest(), EMBEDDING_DIM)
        weights[idx] = weights.get(idx, 0.0) + 1.0

    for word in words:
        add(word.encode("utf-8"))
        if len(word) < 2:
            continue
        for i in range(len(word) - 1):
            add(_BIGRAM_SEED + word[i : i + 2].encode("utf-8"))
        if len(word) < 3:
            continue
        for i in range(len(word) - 2):
            add(_TRIGRAM_SEED + word[i : i + 3].encode("utf-8"))

    norm = math.sqrt(sum(v * v for v in weights.values()))
    if norm == 0.0:
        return {}
    return {idx: v / norm for idx, v in weights.items()}


def embed_text(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """Vetor denso L2-normalizado (dim=512) via feature hashing determinístico."""
    sparse = _features(text)
    return [sparse.get(i, 0.0) for i in range(dim)]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosseno entre dois vetores densos (|a|=|b|; vetores zerados -> 0.0)."""
    if len(a) != len(b):
        raise ValueError("vetores de dimensões diferentes")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def build_index(repo: str | Path, globs: tuple[str, ...] = ("siga-ex/**/*.java", "sigaex/**/*.java", "siga-ex/**/*.jsp", "sigaex/**/*.jsp")) -> tuple[list[Path], list[list[float]]]:
    """Indexa os arquivos do slice: leitura única + embedding por arquivo."""
    root = Path(repo)
    files: list[Path] = []
    for pattern in globs:
        files.extend(p for p in root.glob(pattern) if p.is_file())
    files = sorted(set(files))
    vectors = [embed_text(p.read_text(encoding="utf-8", errors="replace")) for p in files]
    return files, vectors


def rank_by_query(
    query: str,
    files: list[Path],
    vectors: list[list[float]],
    limit: int = 5,
    root: str | Path | None = None,
) -> list[str]:
    """Top-`limit` arquivos por cosseno query↔arquivo (desempate: path)."""
    if not files:
        return []
    q = embed_text(query)
    scores: list[tuple[float, str]] = []
    for path, vec in zip(files, vectors):
        scores.append((cosine_similarity(q, vec), str(path)))
    scores.sort(key=lambda item: (-item[0], item[1]))
    return [path for _, path in scores[:limit]]
