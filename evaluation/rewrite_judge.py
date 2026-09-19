"""Julgamento local de propostas de reescrita JSP/SQL (F11).

O juiz não reescreve nem executa o artefato: verifica invariantes de segurança
antes de qualquer promoção para um fluxo de edição real.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_DESTRUCTIVE_SQL = re.compile(r"\b(?:drop\s+table|truncate\s+table|alter\s+table)\b", re.IGNORECASE)
_UNSAFE_JSP = re.compile(r"<%|\bjavascript\s*:|\b(?:runtime|processbuilder)\b", re.IGNORECASE)
_EXTERNAL_URL = re.compile(r"(?:href|action)\s*=\s*[\"'](?:https?:)?//", re.IGNORECASE)


def _check_sql(text: str) -> list[str]:
    reasons: list[str] = []
    if _DESTRUCTIVE_SQL.search(text):
        reasons.append("DDL destrutivo não permitido")
    for statement in re.split(r";\s*", text):
        if re.match(r"\s*(?:update\s+\w+|delete\s+from\s+\w+)", statement, re.IGNORECASE) and not re.search(
            r"\bwhere\b", statement, re.IGNORECASE
        ):
            reasons.append("DML sem WHERE")
            break
    if re.search(r"\$\{[^}]+\}|\+\s*\w+", text):
        reasons.append("interpolação dinâmica não verificada")
    return reasons


def _check_jsp(text: str) -> list[str]:
    reasons: list[str] = []
    if _UNSAFE_JSP.search(text):
        reasons.append("scriptlet ou execução arbitrária em JSP")
    if _EXTERNAL_URL.search(text):
        reasons.append("ação ou link externo ao repositório")
    return reasons


def judge_rewrite(path: str | Path, original: str, revised: str) -> dict[str, Any]:
    """Avalia uma proposta sem executá-la e retorna decisão explicável.

    A proposta precisa alterar o conteúdo, usar extensão JSP/SQL e passar as
    invariantes do tipo. O resultado é somente um registro de avaliação local.
    """
    target = str(path)
    suffix = Path(target).suffix.lower()
    reasons: list[str] = []
    if not original or not revised:
        reasons.append("conteúdo vazio")
    if original == revised:
        reasons.append("proposta sem alteração")
    if suffix == ".sql":
        reasons.extend(_check_sql(revised))
    elif suffix == ".jsp":
        reasons.extend(_check_jsp(revised))
    else:
        reasons.append("extensão fora do escopo JSP/SQL")
    checks = {
        "non_empty": bool(original and revised),
        "changed": original != revised,
        "supported_extension": suffix in {".jsp", ".sql"},
        "safety_rules": not any(reason for reason in reasons if reason not in {"conteúdo vazio", "proposta sem alteração", "extensão fora do escopo JSP/SQL"}),
    }
    passed = not reasons
    return {
        "path": target,
        "verdict": "PASS" if passed else "REJECT",
        "score": 1.0 if passed else 0.0,
        "checks": checks,
        "reasons": reasons,
    }
