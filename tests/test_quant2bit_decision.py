"""Testes da decisão 2-bit vs 4-bit (F19, ADR-029 em DECISIONS.md).

- `compare_quantizations`: deltas corretos sobre o P08 congelado e paridade simulada;
- `decide`: veredito determinístico — `keep_4bit` hoje (plataforma + RAM
  não-vinculante + paridade só simulada) e `adopt_2bit` quando TODAS as
  regras mudarem;
- gatilhos de revisitação armados/desarmados conforme a evidência;
- `run_decision`: relatório + run com provenance e veredito estável contra
  os relatórios versionados (contrato do gate).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.log import validate_record
from scripts.quant2bit_decision import (
    CANDIDATE_DEPTH,
    DecisionError,
    compare_quantizations,
    decide,
    load_frozen_reports,
    run_decision,
)

ROOT = Path(__file__).resolve().parent.parent
P08 = ROOT / "experiments/reports/subnetwork_compression.json"
F16 = ROOT / "experiments/reports/hardware_slos.json"


def test_load_frozen_reports_requires_frozen_p08(tmp_path: Path):
    p08, f16 = load_frozen_reports()
    assert p08["frozen"] is True
    assert f16 is not None and "measurements" in f16
    not_frozen = tmp_path / "p08.json"
    not_frozen.write_text(json.dumps({"table_2bit_subnetworks": [], "table_4bit_subnetworks": []}), encoding="utf-8")
    with pytest.raises(DecisionError, match="congelado"):
        load_frozen_reports(not_frozen, F16)
    with pytest.raises(DecisionError, match="não encontrado"):
        load_frozen_reports(tmp_path / "ausente.json", None)


def test_compare_quantizations_deltas_and_parity():
    p08, _ = load_frozen_reports()
    comparison = compare_quantizations(p08)
    assert comparison["source"].startswith("P08")
    assert comparison["quantization_is_simulated"] is True
    assert CANDIDATE_DEPTH in comparison["depths_compared"]
    row12 = next(r for r in comparison["rows"] if r["depth"] == CANDIDATE_DEPTH)
    # P08 congelado: d12 — 28,6MB (4-bit) vs 15,4MB (2-bit), acurácias iguais
    assert row12["ram_4bit_mb"] == 28.6
    assert row12["ram_2bit_mb"] == 15.4
    assert row12["ram_savings_mb"] == pytest.approx(13.2)
    assert row12["tool_acc_2bit"] == row12["tool_acc_4bit"] == 0.9844
    assert comparison["simulated_parity_all_depths"] is True
    assert comparison["candidate_2bit"]["peak_ram_mb"] < comparison["candidate_4bit"]["peak_ram_mb"]


def test_decide_keeps_4bit_today_with_explicit_reasons():
    p08, f16 = load_frozen_reports()
    comparison = compare_quantizations(p08)
    decision = decide(comparison, f16)
    assert decision["verdict"] == "keep_4bit"
    assert decision["rules_applied"] == {
        "platform_supports_2bit_locally": False,
        "ram_binding": False,
        "simulated_parity": True,
    }
    assert decision["evidence"]["session_ram_mb"] is not None  # F16 medido
    assert len(decision["reasons"]) == 3  # plataforma + RAM + qualidade simulada
    assert decision["revisit_triggers"]["slo_ram_violated"]["armed"] is False
    assert decision["revisit_triggers"]["local_engine_supports_2bit"]["armed"] is False
    assert decision["decision_is_falsifiable"] is True


def test_decide_adopts_2bit_when_all_rules_flip():
    p08, _ = load_frozen_reports()
    comparison = compare_quantizations(p08)
    decision = decide(
        comparison,
        None,
        platform_supports_2bit=True,
    )
    # Plataforma OK + RAM vinculante (sem F16, candidato ≥ SLO é necessário):
    # força RAM vinculante via cenário sem F16 não basta — usa wrapper direto:
    assert decision["rules_applied"]["platform_supports_2bit_locally"] is True
    tight = decide(
        comparison,
        {"measurements": {"ram": {"rss_mb": 600.0}}},
        platform_supports_2bit=True,
    )
    assert tight["verdict"] == "adopt_2bit"
    assert tight["rules_applied"]["ram_binding"] is True
    assert tight["revisit_triggers"]["slo_ram_violated"]["armed"] is True
    assert tight["revisit_triggers"]["local_engine_supports_2bit"]["armed"] is True


def test_decide_platform_alone_does_not_adopt():
    p08, f16 = load_frozen_reports()
    comparison = compare_quantizations(p08)
    decision = decide(comparison, f16, platform_supports_2bit=True)
    # Mesmo com engine local, RAM não-vinculante + paridade simulada mantêm keep.
    assert decision["verdict"] == "keep_4bit"
    assert len(decision["reasons"]) == 2


def test_run_decision_publishes_report_and_valid_run(tmp_path: Path):
    report = run_decision(
        save_report=False,
        log_run=True,
        now="2026-09-19T15:00:00+00:00",
    )
    assert report["decision"]["verdict"] == "keep_4bit"
    assert report["sources"]["p08"].endswith("(congelado)")
    assert report["sources"]["f16"] is not None
    run_path = ROOT / "experiments/runs" / f"{report['experiment_id']}.json"
    assert run_path.is_file()
    on_disk = json.loads(run_path.read_text(encoding="utf-8"))
    validate_record(on_disk)
    assert on_disk["metrics"]["verdict"] == "keep_4bit"
    run_path.unlink()  # run e2e de teste não polui o histórico versionado


def test_decision_report_is_stable_contract(tmp_path: Path):
    """Contrato do gate: veredito contra os relatórios versionados é estável."""
    p08, f16 = load_frozen_reports()
    comparison = compare_quantizations(p08)
    decision = decide(comparison, f16)
    assert decision["verdict"] == "keep_4bit"
    saved = run_decision(save_report=True, log_run=False)
    on_disk = json.loads((ROOT / "experiments/reports/quant2bit_decision.json").read_text(encoding="utf-8"))
    assert on_disk["decision"]["verdict"] == saved["decision"]["verdict"] == decision["verdict"]
