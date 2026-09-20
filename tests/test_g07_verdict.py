"""G07: regra do veredito MCP (docs/18 §5). Só stdlib, offline."""

from __future__ import annotations

from evaluation.g07_verdict import decide


def test_go_exige_duas_refs_e_auditoria():
    assert decide({"ref1": "mcp_helps", "ref2": "mcp_helps", "audit_pass": True})["verdict"] == "GO"


def test_divergencia_vira_condicional_com_ref3():
    out = decide({"ref1": "mcp_helps", "ref2": "mcp_hurts", "audit_pass": True})
    assert out["verdict"] == "CONDITIONAL" and "ref3" in out["condition"]


def test_auditoria_reprovada_veta_tudo():
    out = decide({"ref1": "mcp_helps", "ref2": "mcp_helps", "audit_pass": False})
    assert out["verdict"] == "NO-GO"
