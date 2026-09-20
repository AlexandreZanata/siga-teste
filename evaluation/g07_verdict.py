"""Veredito GO/NO-GO do MCP (G07, docs/18 §5): regra sobre evidências.

GO pleno exige: ambas as refs `mcp_helps` + auditoria PASS.
Qualquer divergência entre refs → CONDICIONAL (uso assistido) com
ref3 cega obrigatória pós-correções; meta 0.99 separada (H05: NO-GO).
Só stdlib, determinístico.
"""

from __future__ import annotations

from typing import Any

GOOD = "mcp_helps"


def decide(evidence: dict[str, Any]) -> dict[str, Any]:
    """Veredito a partir de {ref1, ref2, audit_pass, capsule_reduction}."""
    refs = [evidence.get("ref1"), evidence.get("ref2")]
    audit = bool(evidence.get("audit_pass"))
    if all(r == GOOD for r in refs) and audit:
        return {"verdict": "GO", "condition": None}
    if not audit:
        return {"verdict": "NO-GO", "condition": "auditoria reprovada — corrigir contaminação antes de tudo"}
    return {
        "verdict": "CONDITIONAL",
        "condition": "uso assistido em dev; ref3 cega obrigatória pós-correções antes de alegar economia",
    }
