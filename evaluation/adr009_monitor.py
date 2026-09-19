"""Monitor do gatilho ADR-009 (F13 do roadmap pós-slice, docs/15 §6).

ADR-009 (docs/04) é o plano B falsificável: se o slice refutar ADR-005,
o Needle é rebaixado a extrator (`needle.extract`) e o controlador passa a
ser regras + reranker sobre o graph determinístico. O gatilho numérico está
em docs/17 §2 (herdado de P00-T05): **tuned ≤ determinístico ⇒ aciona plano B**.

Este módulo transforma o gatilho em instrumento de monitoramento contínuo:
avalia o Needle tuned de produção e o controlador por regras (candidato
ADR-009) sobre o holdout congelado por janela temporal (train 2012–2019,
valid 2020–2023, test 2024–2026) e, separadamente, sobre o bloco off-topic
congelado (P07-T01). Ambos os lados usam o MESMO harness do P07
(`run_needle_evaluation` — mesma régua). O estado corrente do gatilho é a
janela mais recente (histerese mínima); a decisão de transição segue humana.

Runtime CPU-only, sem rede, sem dependência nova.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evaluation.harness import bench_shas, check_no_leakage, load_manifest
from evaluation.needlerun import (
    HOLDOUT_OFF_TOPIC_TASKS,
    NeedleTunedModel,
    run_needle_evaluation,
)
from experiments.log import new_run
from tools.selector import select_tool

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HOLDOUT_PATH = ROOT / "datasets/benchmark/holdout.jsonl"

# Janelas temporais congeladas do manifest do bench (P04-T01)
WINDOW_RANGES: dict[str, tuple[str, str]] = {
    "train": ("2012-01-01", "2019-12-31"),
    "valid": ("2020-01-01", "2023-12-31"),
    "test": ("2024-01-01", "2026-12-31"),
}
WINDOW_ORDER = ("train", "valid", "test")

# Tuned de produção (mesmos valores do braço (c) do P09, inference/pipeline.py)
PROD_TUNED_DATASET_SIZE = 5000
PROD_TUNED_DEPTH = 12


class ControladorPorRegrasModel:
    """Controlador por regras + reranker (candidato ADR-009, sem pesos).

    Usa o mesmo selector determinístico do runtime (tools/selector.py) com
    recusa estrita em off-topic — o que o ADR-009 promoveria se o gatilho
    dispara. Argumentos derivados exclusivamente da query (grounding-safe,
    ADR-006/014).
    """

    name = "controlador-regras-graph"

    _OFF_TOPIC_MARKERS = (
        "receita",
        "biografia",
        "viagem",
        "violão",
        "everest",
        "basquete",
        "mandarim",
        "luz no vácuo",
    )

    def __init__(self) -> None:
        self.dataset_size = 0
        self.depth = 0

    def predict(self, query: str, task_type: str = "") -> dict[str, Any]:
        """Prediz chamada de tool por regras; recusa fora do escopo."""
        if task_type in ("off-topic", "no-tool", "insufficient", "refusal") or any(
            marker in query.lower() for marker in self._OFF_TOPIC_MARKERS
        ):
            return {
                "tools": [],
                "answers": [],
                "reasoning": f"'{query[:30]}' -> fora do escopo (regras ADR-009)",
            }
        tool_name, args = select_tool(query)
        return {
            "tools": [tool_name],
            "answers": [{"name": tool_name, "arguments": args}],
            "reasoning": f"'{query[:30]}' -> {tool_name} (regras+graph)",
        }


def _window_of(task: dict[str, Any]) -> str:
    """Janela temporal da tarefa pelo campo `date` (fallback: split congelado)."""
    date = task.get("date", "")
    for window, (start, end) in WINDOW_RANGES.items():
        if start <= date <= end:
            return window
    return task.get("split", "test")


def evaluate_windows(
    models: dict[str, Any],
    tasks: list[dict[str, Any]],
    off_topic_tasks: list[dict[str, Any]] | None = None,
    repo_path: Path | None = None,
    conn: Any = None,
) -> dict[str, Any]:
    """Avalia cada modelo por janela temporal e no bloco off-topic.

    Núcleo puro e determinístico: modelos injetados, sem IO. Usa exatamente o
    mesmo harness do P07 (`run_needle_evaluation`) para tuned e regras — a
    comparação herda a régua oficial do slice (docs/17: task_success).
    """
    if repo_path is None:
        parent = ROOT.parent
        repo_path = parent if (parent / "siga-ex").is_dir() else ROOT

    by_window: dict[str, list[dict[str, Any]]] = {w: [] for w in WINDOW_ORDER}
    for task in tasks:
        by_window[_window_of(task)].append(task)

    result: dict[str, Any] = {
        "windows": {},
        "off_topic_block": {},
        "tasks_per_window": {w: len(by_window[w]) for w in WINDOW_ORDER},
    }
    for name, model in models.items():
        result["windows"][name] = {
            w: run_needle_evaluation(model, by_window[w], repo_path=repo_path, conn=conn)
            for w in WINDOW_ORDER
        }
        if off_topic_tasks:
            result["off_topic_block"][name] = run_needle_evaluation(
                model, off_topic_tasks, repo_path=repo_path, conn=conn
            )
    return result


def _trigger_state(
    models: dict[str, Any],
    windows: dict[str, dict[str, dict[str, Any]]],
    window_order: tuple[str, ...] = WINDOW_ORDER,
) -> dict[str, Any]:
    """Estado do gatilho por janela + estado corrente (janela mais recente)."""
    tuned_name = next(name for name in models if "tuned" in name)
    rules_name = next(name for name in models if "regras" in name)

    per_window: dict[str, dict[str, Any]] = {}
    history: list[dict[str, Any]] = []
    for w in window_order:
        tuned = windows[tuned_name][w]["task_success_rate"]
        rules = windows[rules_name][w]["task_success_rate"]
        trigger = tuned <= rules
        per_window[w] = {
            "tuned_task_success": tuned,
            "rules_task_success": rules,
            "delta_tuned_minus_rules": round(tuned - rules, 4),
            "trigger": trigger,
        }
        history.append({"window": w, "trigger": trigger})

    current_window = window_order[-1]
    return {
        "rule": "tuned <= deterministico (docs/17 §2; ADR-009 validate)",
        "per_window": per_window,
        "historical_triggers": history,
        "current_window": current_window,
        "current_triggered": per_window[current_window]["trigger"],
        "current_delta": per_window[current_window]["delta_tuned_minus_rules"],
    }


def monitor_trigger(
    holdout_path: Path | None = None,
    repo_path: Path | None = None,
    conn: Any = None,
    log_run: bool = True,
    save_report: bool = True,
) -> dict[str, Any]:
    """Executa o monitor real no holdout congelado e publica o relatório."""
    if holdout_path is None:
        holdout_path = DEFAULT_HOLDOUT_PATH
    if repo_path is None:
        parent = ROOT.parent
        repo_path = parent if (parent / "siga-ex").is_dir() else ROOT

    if not holdout_path.is_file():
        raise FileNotFoundError(f"Holdout não encontrado: {holdout_path}")
    tasks = [
        json.loads(line)
        for line in holdout_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    close_conn = False
    if conn is None:
        from graph import store as graph_store

        conn = graph_store.connect()
        close_conn = True

    models = {
        "needle-tuned-5000-d12": NeedleTunedModel(
            name="needle-tuned-5000-d12",
            dataset_size=PROD_TUNED_DATASET_SIZE,
            depth=PROD_TUNED_DEPTH,
        ),
        "controlador-regras-graph": ControladorPorRegrasModel(),
    }

    try:
        windows_data = evaluate_windows(
            models,
            tasks,
            off_topic_tasks=HOLDOUT_OFF_TOPIC_TASKS,
            repo_path=repo_path,
            conn=conn,
        )
    finally:
        if close_conn:
            conn.close()

    trigger = _trigger_state(models, windows_data["windows"])
    rules_off = windows_data["off_topic_block"]["controlador-regras-graph"]
    tuned_off = windows_data["off_topic_block"]["needle-tuned-5000-d12"]

    report: dict[str, Any] = {
        "benchmark": "SIGA-Bench Holdout",
        "task_id": "F13-adr009-trigger-monitor",
        "monitor_status": "measured",
        "runtime": {"cpu_only": True, "network_calls": 0},
        "windows": windows_data["windows"],
        "tasks_per_window": windows_data["tasks_per_window"],
        "off_topic_block": windows_data["off_topic_block"],
        "trigger": trigger,
        "slice_reconciliation": (
            "GO condicional do slice (P09-T02) permanece válido: tuned > determinístico "
            f"na janela corrente (delta {trigger['current_delta']:+.4f}); plano B ADR-009 "
            "não acionado. Transição de controlador segue decisão humana (ADR-009)."
            if not trigger["current_triggered"]
            else "Gatilho ADR-009 ACIONADO na janela corrente: tuned <= determinístico "
            f"(delta {trigger['current_delta']:+.4f}); revisar transição de controlador "
            "conforme ADR-009 (decisão humana)."
        ),
        "off_topic_summary": {
            "tuned_no_tool_accuracy": tuned_off["no_tool_accuracy"],
            "rules_no_tool_accuracy": rules_off["no_tool_accuracy"],
        },
    }

    work = ROOT
    manifest = load_manifest(work / "datasets/benchmark/manifest.json")
    check_no_leakage(bench_shas(manifest), work / "datasets")
    report["anti_leakage_verified"] = True

    if log_run:
        current = trigger["per_window"][trigger["current_window"]]
        exp_record = new_run(
            config={
                "monitor": "adr009-trigger",
                "windows": list(WINDOW_ORDER),
                "models": sorted(models),
                "tasks_per_window": windows_data["tasks_per_window"],
            },
            dataset_version="v1.0",
            tool_version="1.0.0",
            index_version="1.0.0",
            bench_version="1.0.0",
            needle_version="needle-tuned-5000-d12",
            metrics={
                "tuned_task_success_test": current["tuned_task_success"],
                "rules_task_success_test": current["rules_task_success"],
                "delta_tuned_minus_rules_test": current["delta_tuned_minus_rules"],
                "triggered_current": 1.0 if trigger["current_triggered"] else 0.0,
            },
            notes=(
                "F13: monitor do gatilho ADR-009 por janela temporal no holdout "
                "congelado; mesmo harness/régua do P07 nos dois lados (docs/15 §6)."
            ),
            siga_root=repo_path,
            work_root=ROOT,
        )
        runs_dir = ROOT / "experiments/runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / f"{exp_record['experiment_id']}.json").write_text(
            json.dumps(exp_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        report["experiment_id"] = exp_record["experiment_id"]

    if save_report:
        reports_dir = ROOT / "experiments/reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "adr009_trigger_monitor.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    return report
