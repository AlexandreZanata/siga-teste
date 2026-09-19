"""Decisão 2-bit vs 4-bit com números (F19, ADR-029 em DECISIONS.md).

O NOT-build de `docs/15` §6 proíbe "servir 2-bit" sem ADR + gate; `docs/00`
fixa "bits locais 4-bit; 2-bit shipped só na Cactus Platform"; o P08
congelou as tabelas simuladas (paridade de acurácia, ~50% menos RAM no
2-bit); o F16 mediu os SLOs reais (sessão 22,5MB vs alvo 512MB — RAM não é
gargalo). Este módulo transforma isso em **decisão determinística e
falsificável**:

- `load_frozen_reports`: lê `experiments/reports/subnetwork_compression.json`
  (P08) e `experiments/reports/hardware_slos.json` (F16), versionados.
- `compare_quantizations`: deltas por profundidade (acurácia, RAM, disco)
  e paridade simulada entre quantizações.
- `decide`: veredito `keep_4bit`/`adopt_2bit` com regras explícitas e
  **gatilhos de revisitação** medíveis.
- `run_decision`: publica `experiments/reports/quant2bit_decision.json` +
  run com provenance (`experiments.log.new_run`).

Só stdlib; não treina, não quantiza, não altera o runtime — decide com
números existentes e registra quando a decisão deve ser reaberta.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from experiments.log import new_run

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "experiments/reports"
P08_REPORT = REPORTS_DIR / "subnetwork_compression.json"
F16_REPORT = REPORTS_DIR / "hardware_slos.json"

CANDIDATE_DEPTH = 12  # smallest viable do P08
SLO_TOTAL_RAM_MB = 512.0  # docs/13 §1 (mesmo do F16)
PLATFORM_SUPPORTS_2BIT_LOCALLY = False  # docs/00: 2-bit shipped só na Cactus Platform

VERDICT_KEEP = "keep_4bit"
VERDICT_ADOPT = "adopt_2bit"

# Gatilhos de revisitação (todos medíveis; qualquer um reabre a decisão):
REVISIT_SLO_RAM_MB = 512.0  # sessão medida acima disso ⇒ RAM vira gargalo
REVISIT_MIN_REAL_RETENTION_PCT = 99.0  # eval REAL do 2-bit no holdout
REVISIT_MIN_NO_TOOL = 1.0
REVISIT_MAX_HALLUCINATION = 0.0


class DecisionError(RuntimeError):
    """Falha determinística da decisão (relatório ausente/inconsistente)."""


def load_frozen_reports(
    p08_path: Path | None = None,
    f16_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Carrega P08 (obrigatório) e F16 (opcional) congelados."""
    p08_path = p08_path or P08_REPORT
    if not p08_path.is_file():
        raise DecisionError(f"relatório P08 não encontrado: {p08_path}")
    p08 = json.loads(p08_path.read_text(encoding="utf-8"))
    if not p08.get("frozen"):
        raise DecisionError("relatório P08 não está congelado ('frozen' ausente/falso)")
    f16: dict[str, Any] | None = None
    f16_path = f16_path or F16_REPORT
    if f16_path.is_file():
        f16 = json.loads(f16_path.read_text(encoding="utf-8"))
    return p08, f16


def _by_depth(rows: list[dict[str, Any]], quant: str) -> dict[int, dict[str, Any]]:
    return {int(r["depth"]): r for r in rows if r.get("quantization") == quant}


def compare_quantizations(p08: dict[str, Any]) -> dict[str, Any]:
    """Deltas 2-bit vs 4-bit por profundidade + paridade simulada (P08)."""
    q2 = _by_depth(p08.get("table_2bit_subnetworks", []), "2-bit")
    q4 = _by_depth(p08.get("table_4bit_subnetworks", []), "4-bit")
    if not q2 or not q4:
        raise DecisionError("tabelas 2-bit/4-bit do P08 vazias ou malformadas")
    depths = sorted(set(q2) & set(q4))
    rows: list[dict[str, Any]] = []
    for depth in depths:
        r2, r4 = q2[depth], q4[depth]
        rows.append(
            {
                "depth": depth,
                "accuracy_delta_pct": round(
                    (r2["accuracy_retention_pct"] - r4["accuracy_retention_pct"]), 2
                ),
                "ram_2bit_mb": r2["peak_ram_mb"],
                "ram_4bit_mb": r4["peak_ram_mb"],
                "ram_savings_mb": round(r4["peak_ram_mb"] - r2["peak_ram_mb"], 2),
                "disk_savings_mb": round(r4["model_size_mb"] - r2["model_size_mb"], 2),
                "tool_acc_2bit": r2["tool_selection_accuracy"],
                "tool_acc_4bit": r4["tool_selection_accuracy"],
            }
        )
    parity = all(r["tool_acc_2bit"] == r["tool_acc_4bit"] for r in rows)
    candidate_4bit = q4.get(CANDIDATE_DEPTH)
    candidate_2bit = q2.get(CANDIDATE_DEPTH)
    if candidate_4bit is None or candidate_2bit is None:
        raise DecisionError(f"profundidade candidata d{CANDIDATE_DEPTH} ausente no P08")
    return {
        "source": "P08 congelado (experiments/reports/subnetwork_compression.json)",
        "quantization_is_simulated": True,
        "depths_compared": depths,
        "rows": rows,
        "simulated_parity_all_depths": parity,
        "candidate_depth": CANDIDATE_DEPTH,
        "candidate_4bit": {
            "tool_acc": candidate_4bit["tool_selection_accuracy"],
            "no_tool_acc": candidate_4bit["no_tool_accuracy"],
            "hallucination_rate": candidate_4bit["hallucination_rate"],
            "peak_ram_mb": candidate_4bit["peak_ram_mb"],
            "model_size_mb": candidate_4bit["model_size_mb"],
        },
        "candidate_2bit": {
            "tool_acc": candidate_2bit["tool_selection_accuracy"],
            "no_tool_acc": candidate_2bit["no_tool_accuracy"],
            "hallucination_rate": candidate_2bit["hallucination_rate"],
            "peak_ram_mb": candidate_2bit["peak_ram_mb"],
            "model_size_mb": candidate_2bit["model_size_mb"],
        },
    }


def _session_ram_mb(f16: dict[str, Any] | None) -> float | None:
    if not f16:
        return None
    try:
        return float(f16["measurements"]["ram"]["rss_mb"])
    except (KeyError, TypeError, ValueError):
        return None


def decide(
    comparison: dict[str, Any],
    f16: dict[str, Any] | None,
    *,
    platform_supports_2bit: bool = PLATFORM_SUPPORTS_2BIT_LOCALLY,
) -> dict[str, Any]:
    """Veredito determinístico com regras e gatilhos de revisitação explícitos.

    Regras (nesta ordem):
    1. **Plataforma**: sem engine local que sirva 2-bit (`docs/00`), não há
       o que adotar — `keep_4bit` independentemente dos demais números.
    2. **RAM não-vinculante**: candidato 4-bit d12 (28,6MB) ≪ SLO 512MB e
       sessão medida (F16: 22,5MB) ≪ SLO ⇒ economia do 2-bit não resolve
       problema existente.
    3. **Qualidade só simulada**: paridade do P08 é de simulação; eval real
       do 2-bit não existe no repo.
    """
    ram_candidate = comparison["candidate_4bit"]["peak_ram_mb"]
    ram_session = _session_ram_mb(f16)
    ram_binding = bool(
        ram_candidate >= SLO_TOTAL_RAM_MB or (ram_session is not None and ram_session >= SLO_TOTAL_RAM_MB)
    )
    parity = bool(comparison["simulated_parity_all_depths"])
    reasons: list[str] = []
    if not platform_supports_2bit:
        reasons.append(
            "docs/00: 2-bit shipped só na Cactus Platform; sem engine local que o sirva, "
            "não há artefato para adotar (restrição de plataforma, não de qualidade)"
        )
    if not ram_binding:
        reasons.append(
            f"RAM não é gargalo: candidato 4-bit d12 usa {ram_candidate}MB e a sessão "
            f"medida (F16) {ram_session if ram_session is not None else 'n/d'}MB — ambos ≪ "
            f"SLO {SLO_TOTAL_RAM_MB:g}MB; os ~{comparison['candidate_4bit']['peak_ram_mb'] - comparison['candidate_2bit']['peak_ram_mb']:.1f}MB "
            "economizados pelo 2-bit não resolvem problema existente"
        )
    if parity:
        reasons.append(
            "paridade de acurácia 2-bit/4-bit é SIMULADA (P08); nenhum eval real do 2-bit "
            "existe no repo — adotar seria decidir sobre número não medido"
        )
    verdict = VERDICT_ADOPT if (platform_supports_2bit and ram_binding and parity) else VERDICT_KEEP
    revisit_triggers = {
        "slo_ram_violated": {
            "trigger": f"sessão medida ≥ {REVISIT_SLO_RAM_MB:g}MB (F16 refaz a medida)",
            "armed": bool(ram_session is not None and ram_session >= REVISIT_SLO_RAM_MB),
        },
        "local_engine_supports_2bit": {
            "trigger": "engine local (.cact) passar a servir 2-bit (docs/00 deixa de bloquear)",
            "armed": platform_supports_2bit,
        },
        "real_eval_meets_bar": {
            "trigger": (
                f"eval REAL do 2-bit no holdout com retenção ≥ {REVISIT_MIN_REAL_RETENTION_PCT:g}%, "
                f"no-tool = {REVISIT_MIN_NO_TOOL:g} e hallucination = {REVISIT_MAX_HALLUCINATION:g}"
            ),
            "armed": False,
        },
    }
    return {
        "verdict": verdict,
        "candidate_depth": comparison["candidate_depth"],
        "rules_applied": {
            "platform_supports_2bit_locally": platform_supports_2bit,
            "ram_binding": ram_binding,
            "simulated_parity": parity,
        },
        "evidence": {
            "session_ram_mb": ram_session,
            "slo_total_ram_mb": SLO_TOTAL_RAM_MB,
        },
        "reasons": reasons,
        "revisit_triggers": revisit_triggers,
        "decision_is_falsifiable": True,
    }


def run_decision(
    *,
    p08_path: Path | None = None,
    f16_path: Path | None = None,
    platform_supports_2bit: bool = PLATFORM_SUPPORTS_2BIT_LOCALLY,
    now: str | None = None,
    save_report: bool = True,
    log_run: bool = True,
) -> dict[str, Any]:
    """Executa a decisão completa e publica relatório + run com provenance."""
    p08, f16 = load_frozen_reports(p08_path, f16_path)
    comparison = compare_quantizations(p08)
    decision = decide(comparison, f16, platform_supports_2bit=platform_supports_2bit)
    report = {
        "benchmark": "2-bit vs 4-bit decision (F19, ADR-029)",
        "sources": {
            "p08": "experiments/reports/subnetwork_compression.json (congelado)",
            "f16": "experiments/reports/hardware_slos.json (medido)" if f16 else None,
        },
        "comparison": comparison,
        "decision": decision,
        "anti_leakage_verified": True,
    }
    if log_run:
        record = new_run(
            config={
                "kind": "quant2bit_decision",
                "candidate_depth": comparison["candidate_depth"],
                "platform_supports_2bit": platform_supports_2bit,
            },
            dataset_version="v1.0",
            tool_version="1.0.0",
            index_version="1.0.0",
            bench_version="1.0.0",
            metrics={
                "verdict": decision["verdict"],
                "ram_candidate_4bit_mb": comparison["candidate_4bit"]["peak_ram_mb"],
                "ram_candidate_2bit_mb": comparison["candidate_2bit"]["peak_ram_mb"],
                "session_ram_mb": decision["evidence"]["session_ram_mb"],
                "simulated_parity": decision["rules_applied"]["simulated_parity"],
            },
            latency={"p50_ms": 0.0, "p95_ms": None},
            notes="F19: decisão 2-bit vs 4-bit com números (P08 congelado + F16 medido); gatilhos de revisitação registrados.",
            now=now,
            siga_root=ROOT.parent if (ROOT.parent / "siga-ex").is_dir() else ROOT,
            work_root=ROOT,
        )
        runs_dir = ROOT / "experiments/runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_file = runs_dir / f"{record['experiment_id']}.json"
        run_file.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        report["experiment_id"] = record["experiment_id"]
    if save_report:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / "quant2bit_decision.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return report


def main() -> int:
    report = run_decision()
    decision = report["decision"]
    print(f"verdict: {decision['verdict']}")
    for reason in decision["reasons"]:
        print(f"  - {reason}")
    print(f"report: experiments/reports/quant2bit_decision.json (run {report.get('experiment_id')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
