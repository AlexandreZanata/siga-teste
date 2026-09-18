"""Callers/callees via AST + Impact Recall em commits reais (P03-T02).

SHAs Git são imutáveis: resultados determinísticos enquanto o checkout
estiver no commit medido. Se o clone evoluir (`git pull`), divergências
aqui SINALIZAM drift — não são flake.
Lacunas (recall 0.0 sem chamada direta) são evidência p/ o gate da fase:
"o que não precisa de nano" vs onde history/Needle agregam.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from retrieval.callgraph import find_callers, impact_recall, method_callees, static_impact

SIGA = Path(__file__).resolve().parent.parent.parent.parent
EX_TRAMITE = SIGA / "siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl/ExTramiteBL.java"


def _requires_siga() -> None:
    if not (SIGA / "siga-ex").is_dir():
        pytest.skip("Clone do SIGA não disponível ao lado (CI sem siga-ex)")

ANCHOR_CALLEES = {"contemAlgumTramite", "equivaleENaoENulo", "igual", "getApensos", "hasRecebimento"}

# (sha, recall medido em 2026-09-18 no desenvolvimento)
IMPACT_CASES = [
    ("c1cb9e1ffa717c0a7fd3c92233d19d46e24307a9", 0.5),
    ("1a47b86233cceeb3f3729b697c472f8926290b9d", 0.0),
    ("fecfd9ced774e2bed71eabf6bfdb6b53f9d539df", 0.0),
]


def test_callees_ast_match_anchors():
    _requires_siga()
    callees = method_callees(EX_TRAMITE, "calcularTramitesPendentes")
    assert ANCHOR_CALLEES <= callees


def test_callees_reject_unknown_method():
    _requires_siga()
    with pytest.raises(ValueError):
        method_callees(EX_TRAMITE, "metodoQueNaoExiste")


def test_callers_include_structural_callers():
    _requires_siga()
    files = {hit["file"] for hit in find_callers(SIGA, "calcularTramitesPendentes")}
    assert any(f.endswith("ExMobil.java") for f in files)
    assert any(f.endswith("ExBL.java") for f in files)
    assert all(Path(f).is_file() for f in files)


def test_static_impact_is_grounded():
    _requires_siga()
    impact = static_impact(SIGA, str(EX_TRAMITE))
    assert impact["target"].endswith("ExTramiteBL.java")
    assert "ExTramiteBL" in impact["symbols"]
    assert any(f.endswith("ExBL.java") for f in impact["callers"])
    assert all(Path(f).is_file() for f in impact["callers"])
    assert all(Path(f).is_file() for f in impact["related_tests"])


def test_impact_recall_on_real_commits():
    _requires_siga()
    recalls = []
    for sha, expected in IMPACT_CASES:
        result = impact_recall(SIGA, sha)
        assert not result.get("skipped"), sha
        assert result["recall"] == expected, f"{sha[:9]}: {result}"
        recalls.append(result["recall"])
    mean = sum(recalls) / len(recalls)
    print(f"\nImpact Recall determinístico (3 commits reais): {recalls} média={mean:.2f}")
    assert mean == pytest.approx(1 / 6)
