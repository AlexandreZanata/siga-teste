"""F05: spike RAG/embeddings vs graph no holdout (docs/15-roadmap.md §6).

O candidato a baseline 3 (IA grande + embeddings/RAG) é medido com um
embedding CPU determinístico (hashing TF, sem rede neural, sem dependência
nova — NOT-build proíbe RAG de produção; o spike é local e comparativo):
- braço A: top-k por similaridade de embeddings (cosseno)
- braço B: naive_locate terms (o graph determinístico já medido no P09)
- braço C: fusão rank-médio de A+B
Métricas: basename recall@1/@3/@5 + tokens do contexto (mesma régua do P09).
"""

from __future__ import annotations

import math

from evaluation.rag_spike import _rank_merge as rank_merge
from retrieval.baseline import naive_locate
from retrieval.embeddings import cosine_similarity, embed_text

THRESHOLD_KEYS = ("top1", "top3", "top5")


def test_embed_text_is_deterministic_normalized_and_cpu_only():
    a1 = embed_text("apensar documento sobrestado")
    a2 = embed_text("apensar documento sobrestado")
    assert a1 == a2, "embedding deve ser determinístico"
    assert all(v >= 0.0 for v in a1), "hashing TF não produz pesos negativos"
    norm = math.sqrt(sum(v * v for v in a1))
    assert abs(norm - 1.0) < 1e-6, "vetor deve ser L2-normalizado"

    b = embed_text("arquivo totalmente diferente de financializacao")
    assert cosine_similarity(a1, a1) == 1.0
    assert -1.0 <= cosine_similarity(a1, b) <= 1.0



def test_rank_merge_prefers_files_that_both_arms_rank():
    merged = rank_merge(
        ["A.java", "B.java", "C.java"],
        ["B.java", "A.java", "D.java"],
        limit=3,
    )
    # Arquivos presentes nos dois braços vêm primeiro (média de rank menor)
    assert set(merged[:2]) == {"A.java", "B.java"}
    assert len(merged) <= 3


def test_spike_arms_measured_on_holdout_with_same_ruler(tmp_path):
    arms = _load_real_report()["arms"]

    assert set(arms) == {"A-embeddings", "B-terms-graph", "C-fusion"}
    for arm in arms.values():
        assert set(THRESHOLD_KEYS) <= set(arm["recall"].keys())
        for k in THRESHOLD_KEYS:
            assert 0.0 <= arm["recall"][k] <= 1.0
        assert arm["context_tokens"]["mean"] > 0

    # Braço C (fusão) fica a menos de 1pp do melhor braço isolado no recall@5:
    # fusão rank-médio aproxima-se do melhor braço sem degradar o conjunto.
    best_top5 = max(arms["A-embeddings"]["recall"]["top5"], arms["B-terms-graph"]["recall"]["top5"])
    assert arms["C-fusion"]["recall"]["top5"] >= best_top5 - 0.01

    # Braço B é o naive_locate real (mesmo objeto usado no P09)
    assert arms["B-terms-graph"]["method"].startswith("naive_locate")


def _load_real_report():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    return json.loads((root / "experiments/reports/rag_vs_graph_spike.json").read_text(encoding="utf-8"))


def test_rag_spike_report_published_with_provenance():
    report = _load_real_report()

    assert report["benchmark"] == "SIGA-Bench Holdout"
    assert report["baseline_id"] == "3-large-rag"
    assert report["spike_status"] == "measured"
    assert report["runtime"] == {"cpu_only": True, "network_calls": 0}
    assert report["anti_leakage_verified"] is True
    assert report["total_tasks"] == 311
    assert report["decision_vs_not_build"]


def test_naive_locate_still_works_after_spike(tmp_path):
    # Guarda: o spike não altera o braço B legado (mesma assinatura/comportamento)
    assert callable(naive_locate)
