"""Testes para o congelamento do relatório de compressão (F02, docs/15-roadmap.md §6).

Validações:
- Reprodutibilidade byte-a-byte: relatório regenerado é idêntico ao relatório congelado
  (métricas de latência nunca divergem entre execuções — fim do jitter de wall-clock)
- Jitter de latência não muda o relatório publicado (estatísticas de latência ficam
  congeladas; acurácias continuam recalculadas e veríveis)
- Substituição apenas do bloco de latência; nenhum outro campo é tocado
- Cambaço do relatório congelado cobre as chaves raiz e as chaves por linha de tabela
"""

from __future__ import annotations

import json
from pathlib import Path

from training.compress import (
    LATENCY_SENSITIVE_KEYS,
    freeze_compression_report,
    publish_compression_report,
    restore_frozen_latency,
)

ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "experiments/reports/subnetwork_compression.json"

# Âncoras do congelamento F02 (docs/15 §6) — mesma constante usada pelo módulo.
FROZEN_AT = "2026-09-18T00:00:00Z"
FROZEN_COMMIT = "b46c2946117782d2d529089852a7ebb583690a18"

LATENCY_KEYS = ("latency_p50_ms", "latency_p95_ms", "latency_reduction_pct")


def test_freeze_compression_report_is_idempotent_and_stamps_provenance():
    """Congelar duas vezes não muda nada; marcadores carregam timestamp e commit do repo."""
    first = freeze_compression_report()
    second = freeze_compression_report()

    assert first == second, "re-congelamento alterou o relatório"
    assert first["frozen"] is True
    assert first["frozen_at"] == FROZEN_AT, "timestamp de congelamento não é o calibrado"
    assert first["frozen_commit"] == FROZEN_COMMIT, "commit de congelamento não é o do repo"


def test_frozen_report_is_byte_identical_after_regeneration():
    """Regenerar a compressão não pode alterar um único byte do relatório congelado."""
    frozen = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert frozen.get("frozen") is True, "relatório publicado deve estar congelado"

    report = publish_compression_report(log_run=False)

    assert json.dumps(report, indent=2, ensure_ascii=False) == json.dumps(
        frozen, indent=2, ensure_ascii=False
    ), "regeneração divergiu do relatório congelado (jitter de latência vazando no relatório)"


def test_latency_jitter_cannot_change_published_report():
    """Latências medidas ao vivo (ruidosas) são descartadas em favor das congeladas."""
    frozen = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    report = publish_compression_report(log_run=False)

    for table in ("table_4bit_subnetworks", "table_2bit_subnetworks"):
        for row_frozen, row_live in zip(frozen[table], report[table]):
            for key in LATENCY_KEYS:
                assert row_frozen[key] == row_live[key]

    for key in LATENCY_KEYS:
        assert frozen["smallest_viable_subnetwork"][key] == report["smallest_viable_subnetwork"][key]


def test_freeze_replaces_only_latency_fields():
    """A substituição é restrita ao bloco de latência; todo o resto vem da execução ao vivo."""
    live = {
        "table_4bit_subnetworks": [
            {
                "depth": 12,
                "latency_p50_ms": 0.11,
                "latency_p95_ms": 0.23,
                "latency_reduction_pct": 7.5,
                "tool_selection_accuracy": 0.9844,
                "no_tool_accuracy": 1.0,
                "hallucination_rate": 0.0,
                "task_success_rate": 0.9844,
            }
        ],
        "table_2bit_subnetworks": [
            {
                "depth": 12,
                "latency_p50_ms": 0.99,
                "latency_p95_ms": 1.97,
                "latency_reduction_pct": 50.0,
                "tool_selection_accuracy": 0.9844,
                "no_tool_accuracy": 1.0,
                "hallucination_rate": 0.0,
                "task_success_rate": 0.9844,
            }
        ],
        "smallest_viable_subnetwork": {
            "depth": 12,
            "latency_p50_ms": 0.31,
            "latency_p95_ms": 0.41,
            "latency_reduction_pct": 9.0,
            "tool_selection_accuracy": 0.9844,
        },
    }
    frozen_4bit = {"depth": 12, "latency_p50_ms": 0.02, "latency_p95_ms": 0.04, "latency_reduction_pct": 33.3}
    frozen_2bit = {"depth": 12, "latency_p50_ms": 0.015, "latency_p95_ms": 0.03, "latency_reduction_pct": 44.4}
    frozen_smallest = {"depth": 12, "latency_p50_ms": 0.02, "latency_p95_ms": 0.04, "latency_reduction_pct": 33.3}
    frozen_tables = {
        "table_4bit_subnetworks": [dict(live["table_4bit_subnetworks"][0], **frozen_4bit)],
        "table_2bit_subnetworks": [dict(live["table_2bit_subnetworks"][0], **frozen_2bit)],
    }
    frozen_smallest_block = dict(live["smallest_viable_subnetwork"], **frozen_smallest)

    merged = restore_frozen_latency(live, frozen_tables, frozen_smallest_block)

    # Campos de latência substituídos pelos valores congelados
    assert merged["table_4bit_subnetworks"][0]["latency_p50_ms"] == 0.02
    assert merged["table_4bit_subnetworks"][0]["latency_p95_ms"] == 0.04
    assert merged["table_4bit_subnetworks"][0]["latency_reduction_pct"] == 33.3
    assert merged["table_2bit_subnetworks"][0]["latency_p50_ms"] == 0.015
    # Campos fora do bloco de latência preservados da execução ao vivo
    assert merged["table_4bit_subnetworks"][0]["tool_selection_accuracy"] == 0.9844
    assert merged["table_2bit_subnetworks"][0]["depth"] == 12
    assert merged["smallest_viable_subnetwork"]["tool_selection_accuracy"] == 0.9844
    assert merged["smallest_viable_subnetwork"]["latency_p50_ms"] == 0.02


def test_frozen_report_covers_expected_schema():
    """Cambaço do relatório congelado: chaves raiz + chaves por linha de tabela + marcador."""
    frozen = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    expected_root_keys = {
        "benchmark",
        "compression_study",
        "dataset_size",
        "tested_depths",
        "table_4bit_subnetworks",
        "table_2bit_subnetworks",
        "smallest_viable_subnetwork",
        "exit_gate_assessment",
        "anti_leakage_verified",
        "frozen",
        "frozen_at",
        "frozen_commit",
    }
    assert expected_root_keys.issubset(frozen.keys()), "relatório congelado sem chaves de congelamento"

    assert frozen["frozen_at"], "frozen_at vazio"
    assert frozen["frozen_commit"], "frozen_commit vazio"
    assert set(frozen["tested_depths"]) == {20, 18, 16, 14, 12, 10, 8, 6, 4, 2}

    row_keys = {
        "depth",
        "quantization",
        "dataset_size",
        "tool_selection_accuracy",
        "no_tool_accuracy",
        "hallucination_rate",
        "task_success_rate",
        "latency_p50_ms",
        "latency_p95_ms",
        "model_size_mb",
        "peak_ram_mb",
        "accuracy_retention_pct",
        "ram_reduction_pct",
        "latency_reduction_pct",
    }
    for table in ("table_4bit_subnetworks", "table_2bit_subnetworks"):
        assert len(frozen[table]) == 10
        for row in frozen[table]:
            assert row_keys.issubset(row.keys()), f"{table} com linha fora do schema"
            for key in LATENCY_SENSITIVE_KEYS:
                assert isinstance(row[key], (int, float)), f"{table}.{key} não numérico"

    smallest = frozen["smallest_viable_subnetwork"]
    assert smallest["depth"] == 12
    assert smallest["quantization"] == "4-bit"
    assert smallest["accuracy_target_met"] is True
    assert frozen["exit_gate_assessment"]["status"] == "PASSED"
    assert frozen["exit_gate_assessment"]["smallest_viable_depth"] == smallest["depth"]
