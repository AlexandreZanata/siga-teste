"""F13: monitor do gatilho ADR-009 — tuned vs determinístico por janela (docs/15 §6).

Núcleo puro determinístico (windowing, estado do gatilho, controlador por
regras) + verificação do relatório real publicado com provenance, no padrão
F05/F12.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evaluation.adr009_monitor import (
    PROD_TUNED_DATASET_SIZE as PROD_SIZE,
    PROD_TUNED_DEPTH as PROD_DEPTH,
    ControladorPorRegrasModel,
    _trigger_state,
    evaluate_windows,
)
from evaluation.needlerun import (
    HOLDOUT_OFF_TOPIC_TASKS,
    NeedleTunedModel,
)
from tools.selector import select_tool


class _StaticModel:
    """Modelo de teste determinístico (predições fixas, sem pesos)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.dataset_size = 0
        self.depth = 0

    def predict(self, query: str, task_type: str = "") -> dict[str, Any]:
        return {"tools": [], "answers": [], "reasoning": "static"}


def _synthetic_tasks() -> list[dict[str, Any]]:
    """3 janelas × 3 tarefas com datas explícitas e GT real do slice."""
    gt = ["siga-ex/src/main/java/br/gov/jfrj/siga/ex/bl/ExBL.java"]
    tasks: list[dict[str, Any]] = []
    for window, date in (
        ("train", "2015-06-01"),
        ("valid", "2021-06-01"),
        ("test", "2025-06-01"),
    ):
        for i in range(3):
            tasks.append(
                {
                    "id": f"{window}-{i}",
                    "query": f"Localizar ExDocumento procedimento {i}",
                    "task_type": "commit-localization",
                    "date": date,
                    "split": window,
                    "ground_truth_files": gt,
                }
            )
    return tasks


def test_windowing_uses_task_date_frozen_ranges():
    tasks = _synthetic_tasks()
    models = {
        "needle-tuned-fake": _StaticModel("needle-tuned-fake"),
        "controlador-regras-fake": _StaticModel("controlador-regras-fake"),
    }
    result = evaluate_windows(models, tasks, off_topic_tasks=HOLDOUT_OFF_TOPIC_TASKS)

    assert result["tasks_per_window"] == {"train": 3, "valid": 3, "test": 3}
    assert set(result["windows"]) == {"needle-tuned-fake", "controlador-regras-fake"}
    for w in ("train", "valid", "test"):
        for model_windows in result["windows"].values():
            assert model_windows[w]["total_tasks"] == 3
    # Bloco off-topic congelado avaliado separadamente
    assert result["off_topic_block"]["needle-tuned-fake"]["total_tasks"] == len(
        HOLDOUT_OFF_TOPIC_TASKS
    )


def test_trigger_state_hysteresis_current_window():
    """Gatilho tuned <= rules por janela; estado corrente = janela mais recente."""
    models = {"m-tuned": object(), "m-regras": object()}
    windows = {
        "m-tuned": {
            w: {"task_success_rate": r}
            for w, r in (("train", 0.9), ("valid", 0.7), ("test", 0.65))
        },
        "m-regras": {
            w: {"task_success_rate": r} for w, r in (("train", 0.8), ("valid", 0.7), ("test", 0.6))
        },
    }
    state = _trigger_state(models, windows)

    assert state["per_window"]["train"]["trigger"] is False  # 0.9 > 0.8
    assert state["per_window"]["valid"]["trigger"] is True  # 0.7 <= 0.7 (empate aciona)
    assert state["per_window"]["test"]["trigger"] is False  # 0.65 > 0.6
    assert state["current_window"] == "test"
    assert state["current_triggered"] is False
    assert [(h["window"], h["trigger"]) for h in state["historical_triggers"]] == [
        ("train", False),
        ("valid", True),
        ("test", False),
    ]


def test_rules_controller_recuses_off_topic():
    rules = ControladorPorRegrasModel()
    # Recusa por task_type e pelos mesmos marcadores do bloco congelado (P07)
    assert rules.predict("Receita de suflê de espinafre", task_type="off-topic")["tools"] == []
    assert rules.predict("Como fazer violão soar melhor")["tools"] == []


def test_rules_controller_parity_with_tuned_on_offtopic():
    """Política de recusa do controlador espelha a do tuned de produção.

    Queries off-topic sem marcador conhecido não são recusadas por NENHUM dos
    dois lados (limitação compartilhada do contrato congelado) — a comparação
    do gatilho permanece não viesada.
    """
    tuned = NeedleTunedModel(dataset_size=PROD_SIZE, depth=PROD_DEPTH)
    rules = ControladorPorRegrasModel()
    for query in (
        "História da culinária japonesa",
        "Previsão do tempo em Nairóbi",
        "Receita de suflê de espinafre",
        "Biografia de Machado de Assis",
    ):  # com task_type off-topic explícito
        assert (
            tuned.predict(query, task_type="off-topic")["tools"]
            == rules.predict(query, task_type="off-topic")["tools"]
        )


def test_rules_controller_args_grounded_in_query():
    query = "Traçar fluxo do ExTramiteBL"
    pred = ControladorPorRegrasModel().predict(query)
    assert pred["tools"] == [select_tool(query)[0]]
    args = pred["answers"][0]["arguments"]
    assert args.get("symbol") == "ExTramiteBL"  # extraído da própria query, nada inventado


def test_rules_controller_matches_production_selector():
    """Guarda: o candidato ADR-009 usa o selector real do runtime."""
    for query in (
        "Histórico de alterações do ExDocumento",
        "Impacto de mudanças em ExTramiteBL",
        "cápsula de contexto para tramites",
        "Localizar ExMobil",
    ):
        assert ControladorPorRegrasModel().predict(query)["tools"] == [select_tool(query)[0]]


def test_monitor_report_published_with_provenance():
    root = Path(__file__).resolve().parent.parent
    report_path = root / "experiments/reports/adr009_trigger_monitor.json"
    assert report_path.is_file(), "relatório do monitor F13 deve estar versionado"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["task_id"] == "F13-adr009-trigger-monitor"
    assert report["monitor_status"] == "measured"
    assert report["runtime"] == {"cpu_only": True, "network_calls": 0}
    assert report["anti_leakage_verified"] is True
    assert set(report["windows"]) == {"needle-tuned-5000-d12", "controlador-regras-graph"}
    assert report["tasks_per_window"] == {"train": 120, "valid": 120, "test": 71}
    assert report["trigger"]["current_window"] == "test"
    assert isinstance(report["trigger"]["current_triggered"], bool)
    assert report["experiment_id"]
    assert report["slice_reconciliation"]
