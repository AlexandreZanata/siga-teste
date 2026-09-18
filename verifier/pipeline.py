"""Pipeline de verificação determinística e promoção para verified/ (P06-T01, docs/08).

Regra inegociável:
Resposta só entra em `verified/` se o verificador determinístico passar.
Consenso LLM nunca é ground truth.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from verifier import checker

VERIFIER_VERSION = "1.0.0"


def verify_candidate(
    candidate: dict[str, Any],
    repo: Path,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Executa conjunto de verificações determinísticas sobre uma trajetória candidata."""
    candidate_id = candidate.get("id", "cand-unknown")
    task_type = candidate.get("task_type", "")
    steps = candidate.get("steps", [])

    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    # 1. Anti-leakage: ausência de qualquer commit SHA do benchmark
    cand_str = json.dumps(candidate, ensure_ascii=False)
    no_leak = checker.check_anti_leakage(cand_str)
    checks.append({"name": "anti_leakage", "passed": no_leak})
    if not no_leak:
        errors.append("Contaminação com SHA do benchmark detectada")

    # 2. Casos off-topic e no-tool: verificador checa ausência de chamadas
    no_tool_types = (
        "off-topic",
        "no-tool",
        "ambiguous-incomplete",
        "insufficient",
        "refusal",
        "clarification_needed",
    )
    if task_type in no_tool_types or candidate.get("tools") == []:
        has_no_calls = len(steps) == 0 or (len(steps) == 1 and steps[0].get("action") in ("none", ""))
        checks.append({"name": "no_tool_compliance", "passed": has_no_calls})
        if not has_no_calls:
            errors.append("Caso off-topic/no-tool tentou invocar ferramentas")
    else:
        # 3. Verificação de chamadas de ferramenta
        for idx, step in enumerate(steps, 1):
            args = step.get("args", {})

            # Verificação de target / symbol
            target = args.get("target") or args.get("symbol")
            if target and isinstance(target, str):
                target_clean = target.replace(".java", "").replace(".jsp", "").replace(".sql", "")
                # Se houver conexão com o grafo, checa existência de nó
                if conn is not None:
                    has_sym = checker.check_symbol(conn, target_clean)
                    checks.append(
                        {
                            "name": f"step_{idx}_symbol_in_graph",
                            "target": target_clean,
                            "passed": has_sym,
                        }
                    )
                    if not has_sym:
                        errors.append(f"Símbolo {target_clean!r} não encontrado no grafo")

                # Checagem via grep no repositório
                has_grep = checker.check_grep(repo, target_clean)
                checks.append(
                    {
                        "name": f"step_{idx}_grep_match",
                        "target": target_clean,
                        "passed": has_grep,
                    }
                )
                if not has_grep:
                    errors.append(f"Alvo {target_clean!r} não ocorre textualmente no repositório")

    passed = len(errors) == 0 and all(c.get("passed", False) for c in checks)

    return {
        "candidate_id": candidate_id,
        "passed": passed,
        "verifier_version": VERIFIER_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "errors": errors,
        "score": 1.0 if passed else 0.0,
    }


def promote_to_verified(
    candidate: dict[str, Any],
    verification_report: dict[str, Any],
    datasets_root: Path,
) -> Path:
    """Promove candidato para verified/ somente se verificação determinística passar.

    Se reprovado, arquiva em rejected/ com os motivos da falha.
    Consenso LLM nunca é ground truth.
    """
    passed = verification_report.get("passed", False)
    target_dir = datasets_root / ("verified" if passed else "rejected")
    target_dir.mkdir(parents=True, exist_ok=True)

    dest_file = target_dir / ("gold_candidates.jsonl" if passed else "rejected_candidates.jsonl")

    # Anexa registro com metadados de verificação (provenance total)
    enriched = dict(candidate)
    enriched["verification"] = {
        "verifier_version": verification_report.get("verifier_version", VERIFIER_VERSION),
        "passed": passed,
        "timestamp": verification_report.get("timestamp"),
        "checks_count": len(verification_report.get("checks", [])),
        "errors": verification_report.get("errors", []),
    }

    with dest_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(enriched, ensure_ascii=False) + "\n")

    return dest_file
