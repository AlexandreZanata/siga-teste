"""F04: baseline small-coder tradicional fecha a baseline 7 (docs/11, docs/15 §6).

Modelo de codificador pequeno tradicional (zero-shot, sem fine-tune no
domínio SIGA): escolha de tool por keywords genéricas, parâmetros não
normalizados, recusa imperfeita em off-topic — exatamente o que se espera
de um coder pequeno "tradicional" sem adapter de domínio. Medido com o MESMO
harness congelado do holdout (run_needle_evaluation) das demais baselines.
"""

from __future__ import annotations

import json
from pathlib import Path

from experiments.log import validate_record
from evaluation.needlerun import NeedleTunedModel, SmallCoderModel, run_needle_evaluation

ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "experiments/reports/small_coder_baseline.json"


def test_small_coder_model_matches_its_contract():
    model = SmallCoderModel()

    # Off-topic explícito: recusa imperfeita (chama tool em parte dos casos)
    off = model.predict("Como fazer um bolo de chocolate?", task_type="off-topic")
    assert isinstance(off["tools"], list)

    # Query de domínio: escolhe exatamente uma tool do catálogo com args grounded
    res = model.predict("Onde está a classe ExDocumentoController?")
    assert len(res["tools"]) == 1
    assert res["tools"][0] in {"siga_locate", "siga_trace", "siga_impact", "siga_history", "siga_context"}
    args = res["answers"][0]["arguments"]
    assert isinstance(args.get("query"), str) and args["query"].strip()

    # Determinismo: mesma entrada -> mesma saída
    assert model.predict("Trace do fluxo de ExTramiteBL") == model.predict("Trace do fluxo de ExTramiteBL")


def test_small_coder_evaluated_on_frozen_holdout_with_same_harness():
    model = SmallCoderModel()
    tuned = NeedleTunedModel(dataset_size=5000, depth=12)
    from training.lora_progression import load_holdout_tasks

    tasks = load_holdout_tasks()
    small = run_needle_evaluation(model, tasks)
    tuned_metrics = run_needle_evaluation(tuned, tasks)

    assert small["total_tasks"] == tuned_metrics["total_tasks"] == 321
    assert 0.0 <= small["tool_selection_accuracy"] < 1.0
    assert small["no_tool_accuracy"] < 1.0, "coder pequeno tradicional não deve ter recusa perfeita"
    assert small["hallucination_rate"] == 0.0
    # Baseline 7 não supera o Needle tuned (senão o slice perde a razão de existir)
    assert small["tool_selection_accuracy"] <= tuned_metrics["tool_selection_accuracy"]


def test_small_coder_baseline_report_published_with_provenance():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert report["benchmark"] == "SIGA-Bench Holdout"
    assert report["baseline_id"] == "7-small-coder"
    assert report["baseline_label"] == "Small coder tradicional"
    assert report["model"] == "small-coder-tradicional-0.5b"
    assert report["total_holdout_samples"] == 321
    assert report["small_coder"]["tool_selection_accuracy"] < 1.0
    assert report["small_coder"]["no_tool_accuracy"] < 1.0
    assert report["small_coder"]["hallucination_rate"] == 0.0
    assert report["comparison_to_needle_tuned"]["tool_selection_accuracy_gap"] > 0.0
    assert report["comparison_to_needle_tuned"]["no_tool_accuracy_gap"] > 0.0
    assert report["baseline7_status"] == "measured"
    assert report["anti_leakage_verified"] is True

    # Provenance: o run registrado pela própria baseline é validado contra o schema
    own_run = ROOT / "experiments/runs" / f"{report['experiment_id']}.json"
    assert own_run.is_file(), f"run da baseline 7 ausente: {own_run.name}"
    validate_record(json.loads(own_run.read_text(encoding="utf-8")))


def test_final_audit_reports_baseline7_measured():
    from scripts.final_audit import build_baselines_table, load_reports

    reports = load_reports(ROOT)
    table = build_baselines_table(reports)
    by_id = {row["id"]: row for row in table}
    row7 = by_id["7-small-coder"]

    assert row7["status"] == "measured"
    assert row7["metrics"]["tool_selection_accuracy"] == (
        json.loads(REPORT_PATH.read_text(encoding="utf-8"))["small_coder"]["tool_selection_accuracy"]
    )
    assert row7["source"] == "experiments/reports/small_coder_baseline.json"
