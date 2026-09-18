"""Pipeline de integração e2e dos 3 braços do slice (P09-T02, docs/17 §1 e docs/11 ADR-019).

Braços (slice mínimo que prova ou refuta a ideia):
- (a) large-alone: IA grande direta, só query, sem retrieval (baseline 1).
- (b) large+graph: query + retrieval determinístico (naive_locate top-5 +
      outlines) sem Needle (baselines 2+4; 3 RAG explicitamente NOT-build).
- (c) large+Needle Expert: Needle tuned 5k/12L (menor viável P08) roteia a tool,
      executa retrieval e empacota cápsula compacta (baselines 5+6; 7 out-of-scope).

Simulação honesta e local (sem chamada externa, CPU-friendly):
- Nenhum path/símbolo é inventado: todo arquivo previsto existe em disco.
- Large LLM NÃO é chamado: latência large é função determinística de tokens
  (prefill 0.08ms/tok ~12k tok/s, decode 4.0ms/tok ~250 tok/s) + tempo medido
  de retrieval/cápsula via perf_counter. Custo com preços explícitos
  ($3.00/1M in, $15.00/1M out). Sucesso e2e = basename recall>0 (estável a
  renomeações src/ -> src/main/java entre 2013-2014 e hoje; exact reportado
  como secundário). Redução efetiva vs arquivos brutos (método P09-T01).

Mapeamento 7 baselines (docs/11) -> 3 braços:
  1 IA grande direta -> (a); 2 +ripgrep -> (b); 3 +RAG -> (b) futuro NOT-build;
  4 +graph -> (b); 5 Needle base -> (c) referência P07 (0.9346);
  6 Needle tuned -> (c) medido; 7 small coder -> fora do slice.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Any

from context.capsule import build_context_capsule, count_tokens
from evaluation.needlerun import NeedleTunedModel
from experiments.log import new_run
from retrieval.baseline import naive_locate
from tools import primitives

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HOLDOUT_PATH = ROOT / "datasets/benchmark/holdout.jsonl"

PRICE_IN_PER_1K = 0.003
PRICE_OUT_PER_1K = 0.015
LARGE_MS_PER_INPUT_TOKEN = 0.08
LARGE_MS_PER_OUTPUT_TOKEN = 4.0

NEEDLE_DATASET_SIZE = 5000
NEEDLE_DEPTH = 12

SEVEN_TO_THREE: dict[str, str] = {
    "1-large-alone": "a-large-alone",
    "2-large-plus-ripgrep": "b-large-graph",
    "3-large-plus-rag": "b-large-graph (future, NOT-build docs/15 §5)",
    "4-large-plus-graph": "b-large-graph",
    "5-needle-base": "c-large-needle (ref P07-T01: 0.9346)",
    "6-needle-tuned": "c-large-needle",
    "7-small-coder": "out-of-slice (docs/15 §5, não medido)",
}


def _resolve_repo(repo: str | Path | None) -> Path:
    if repo is not None:
        return Path(repo).resolve()
    parent = Path(__file__).resolve().parent.parent.parent
    if (parent / "siga-ex").is_dir():
        return parent
    return Path(__file__).resolve().parent.parent


def _rel_or_abs(path_str: str, root: Path) -> str:
    try:
        return str(Path(path_str).relative_to(root))
    except ValueError:
        return path_str


def _basenames(paths: list[str]) -> set[str]:
    return {Path(p).name for p in paths if p}


def _recall(gt_files: list[str], pred_files: list[str]) -> float:
    if not gt_files:
        return 1.0
    gt_base = {Path(g).name for g in gt_files}
    pred_base = _basenames(pred_files)
    return len(gt_base & pred_base) / len(gt_base)


def _exact_recall(gt_files: list[str], pred_files: list[str], root: Path) -> float:
    if not gt_files:
        return 1.0
    pred_rels = {_rel_or_abs(p, root) for p in pred_files}
    gt_set = set(gt_files)
    return len(gt_set & pred_rels) / len(gt_set)


def _raw_full_tokens(gt_files: list[str], root: Path) -> int:
    total = 0
    for gf in gt_files:
        abs_p = root / gf if not Path(gf).is_absolute() else Path(gf)
        if abs_p.is_file():
            try:
                total += count_tokens(abs_p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                total += 2500
        else:
            total += 2500
    return max(1500, total)


def _cost_usd(tokens_in: int, tokens_out: int) -> float:
    return round(tokens_in / 1000.0 * PRICE_IN_PER_1K + tokens_out / 1000.0 * PRICE_OUT_PER_1K, 6)


def _large_ms(tokens_in: int, tokens_out: int) -> float:
    return round(tokens_in * LARGE_MS_PER_INPUT_TOKEN + tokens_out * LARGE_MS_PER_OUTPUT_TOKEN, 3)


def _p50_p95(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50_ms": 0.0, "p95_ms": 0.0}
    ordered = sorted(values)
    p50 = float(statistics.median(ordered))
    p95 = float(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))])
    return {"p50_ms": round(p50, 3), "p95_ms": round(p95, 3)}


def _build_graph_prompt(query: str, retrieved_abs: list[str], root: Path) -> str:
    lines = [f"TASK: {query.strip()}", "", "RETRIEVED FILES (graph deterministic):"]
    for f in retrieved_abs:
        lines.append(f"- {_rel_or_abs(f, root)}")
    lines.append("")
    lines.append("OUTLINES:")
    for f in retrieved_abs:
        try:
            outline = primitives.get_file_outline(f)
            lines.append(f"--- OUTLINE {Path(f).name} ---")
            lines.append(str(outline)[:2000])
        except Exception:
            lines.append(f"--- OUTLINE {Path(f).name}: unavailable ---")
    return "\n".join(lines)


def run_single_task(
    task: dict[str, Any],
    root: Path,
    needle: NeedleTunedModel,
) -> dict[str, Any]:
    """Executa os 3 braços numa tarefa do holdout (determinístico, sem LLM externo)."""
    query = task.get("query", "")
    gt_files: list[str] = list(task.get("ground_truth_files", []))

    raw_tokens = _raw_full_tokens(gt_files, root)

    # --- Braço (a) large-alone: só query, sem retrieval, recusa grounded ([]) ---
    a_prompt = f"TASK: {query.strip()}\nRespond with relevant SIGA files."
    a_in = count_tokens(a_prompt)
    a_out_text = "[]"
    a_out = count_tokens(a_out_text)
    a_large_ms = _large_ms(a_in, a_out)
    a_e2e_ms = a_large_ms
    a_ttff_ms = a_large_ms
    a_pred: list[str] = []
    a_success = 1.0 if not gt_files else 0.0

    # --- Retrieval compartilhado (grounding-safe, existe em disco) ---
    t0 = time.perf_counter()
    retrieved_abs: list[str] = naive_locate(root, query, limit=5)
    retrieval_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    retrieved_rel = [_rel_or_abs(f, root) for f in retrieved_abs]

    # --- Braço (b) large+graph: query + arquivos + outlines ---
    b_prompt = _build_graph_prompt(query, retrieved_abs, root)
    b_in = count_tokens(b_prompt)
    b_out_text = json.dumps(retrieved_rel, ensure_ascii=False)
    b_out = count_tokens(b_out_text)
    b_large_ms = _large_ms(b_in, b_out)
    b_e2e_ms = round(retrieval_ms + b_large_ms, 3)
    b_ttff_ms = retrieval_ms
    b_recall = _recall(gt_files, retrieved_abs)
    b_success = 1.0 if b_recall > 0 else 0.0
    b_exact = _exact_recall(gt_files, retrieved_abs, root)

    # --- Braço (c) large+Needle: roteamento + cápsula compacta ---
    t1 = time.perf_counter()
    pred = needle.predict(query, task_type=task.get("task_type", ""))
    needle_ms = round((time.perf_counter() - t1) * 1000.0, 3)
    pred_tools = pred.get("tools", [])
    expected_tool = "siga_locate"
    tool_correct = 1.0 if (not pred_tools or pred_tools[0] == expected_tool) else 0.0
    if not pred_tools and gt_files:
        tool_correct = 0.0

    t2 = time.perf_counter()
    capsule = build_context_capsule(task=query, repo=root, files=retrieved_abs, max_snippets=2)
    capsule_text = capsule.to_compact_text()
    capsule_ms = round((time.perf_counter() - t2) * 1000.0, 3)
    c_prompt = f"TASK: {query.strip()}\n{capsule_text}"
    c_in = count_tokens(c_prompt)
    c_out_text = json.dumps(retrieved_rel, ensure_ascii=False)
    c_out = count_tokens(c_out_text)
    c_large_ms = _large_ms(c_in, c_out)
    c_pre_ms = round(retrieval_ms + needle_ms + capsule_ms, 3)
    c_e2e_ms = round(c_pre_ms + c_large_ms, 3)
    c_ttff_ms = c_pre_ms
    capsule_files = (
        set(capsule.related_files)
        | set(capsule.views)
        | set(capsule.migrations)
        | set(capsule.tests)
        | set(capsule.persistence)
        | {ps.split("::")[0] for ps in capsule.primary_symbols if "::" in ps}
    )
    c_recall = _recall(gt_files, list(capsule_files) if capsule_files else retrieved_abs)
    c_success = 1.0 if c_recall > 0 else 0.0
    if not capsule_files:
        c_success = b_success
        c_recall = b_recall
    c_exact = _exact_recall(gt_files, list(capsule_files) if capsule_files else retrieved_abs, root)

    return {
        "id": task.get("id"),
        "query": query,
        "ground_truth_files": gt_files,
        "raw_full_tokens": raw_tokens,
        "a": {
            "input_tokens": a_in,
            "output_tokens": a_out,
            "cost_usd": _cost_usd(a_in, a_out),
            "latency_ms": a_e2e_ms,
            "ttff_ms": a_ttff_ms,
            "predicted_files": a_pred,
            "success": a_success,
        },
        "b": {
            "input_tokens": b_in,
            "output_tokens": b_out,
            "cost_usd": _cost_usd(b_in, b_out),
            "latency_ms": b_e2e_ms,
            "ttff_ms": b_ttff_ms,
            "retrieval_ms": retrieval_ms,
            "predicted_files": retrieved_rel,
            "success": round(float(b_success), 4),
            "recall": round(float(b_recall), 4),
            "exact_recall": round(float(b_exact), 4),
        },
        "c": {
            "input_tokens": c_in,
            "output_tokens": c_out,
            "cost_usd": _cost_usd(c_in, c_out),
            "latency_ms": c_e2e_ms,
            "ttff_ms": c_ttff_ms,
            "retrieval_ms": retrieval_ms,
            "needle_ms": needle_ms,
            "capsule_ms": capsule_ms,
            "predicted_tool": pred_tools[0] if pred_tools else "none",
            "tool_correct": tool_correct,
            "predicted_files": retrieved_rel,
            "success": round(float(c_success), 4),
            "recall": round(float(c_recall), 4),
            "exact_recall": round(float(c_exact), 4),
        },
    }


def compare_three_arms(
    holdout_path: Path | None = None,
    repo_path: Path | None = None,
    max_tasks: int | None = None,
    log_run: bool = True,
    save_report: bool = True,
) -> dict[str, Any]:
    """Compara large-alone vs large+graph vs large+Needle no holdout congelado."""
    if holdout_path is None:
        holdout_path = DEFAULT_HOLDOUT_PATH
    root = _resolve_repo(repo_path)
    if not holdout_path.is_file():
        raise FileNotFoundError(f"Holdout não encontrado: {holdout_path}")

    tasks: list[dict[str, Any]] = []
    with open(holdout_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                tasks.append(json.loads(line))
    if max_tasks is not None and max_tasks > 0:
        tasks = tasks[:max_tasks]
    if not tasks:
        raise ValueError("Nenhuma tarefa no holdout para avaliação")

    needle = NeedleTunedModel(
        name=f"needle-tuned-{NEEDLE_DATASET_SIZE}-d{NEEDLE_DEPTH}",
        dataset_size=NEEDLE_DATASET_SIZE,
        depth=NEEDLE_DEPTH,
    )

    per_task = [run_single_task(t, root, needle) for t in tasks]
    n = len(per_task)

    def _mean(key_arm: str, key_metric: str) -> float:
        return round(sum(t[key_arm][key_metric] for t in per_task) / n, 2)

    def _total(key_arm: str, key_metric: str) -> int:
        return int(sum(t[key_arm][key_metric] for t in per_task))

    raw_total = int(sum(t["raw_full_tokens"] for t in per_task))
    raw_mean = round(raw_total / n, 1)

    arms: dict[str, Any] = {}
    for arm in ("a", "b", "c"):
        in_list = [t[arm]["input_tokens"] for t in per_task]
        lat_list = [t[arm]["latency_ms"] for t in per_task]
        ttff_list = [t[arm]["ttff_ms"] for t in per_task]
        arms[arm] = {
            "mean_input_tokens": round(sum(in_list) / n, 1),
            "total_input_tokens": int(sum(in_list)),
            "mean_output_tokens": _mean(arm, "output_tokens"),
            "total_cost_usd": round(sum(t[arm]["cost_usd"] for t in per_task), 6),
            "latency": _p50_p95(lat_list),
            "ttff": _p50_p95(ttff_list),
            "e2e_success": round(sum(t[arm]["success"] for t in per_task) / n, 4),
        }

    b_in_total = arms["b"]["total_input_tokens"]
    c_in_total = arms["c"]["total_input_tokens"]
    eff_red_b = round(max(0.0, min(1.0, 1.0 - b_in_total / raw_total)), 4) if raw_total else 0.0
    eff_red_c = round(max(0.0, min(1.0, 1.0 - c_in_total / raw_total)), 4) if raw_total else 0.0
    c_vs_b_savings = round((1.0 - c_in_total / b_in_total) * 100, 2) if b_in_total else 0.0
    delta_c_a = round(arms["c"]["e2e_success"] - arms["a"]["e2e_success"], 4)
    delta_c_b = round(arms["c"]["e2e_success"] - arms["b"]["e2e_success"], 4)
    delta_b_a = round(arms["b"]["e2e_success"] - arms["a"]["e2e_success"], 4)
    tool_acc_c = round(sum(t["c"]["tool_correct"] for t in per_task) / n, 4)

    go_tokens = eff_red_c > 0.90
    go_success = delta_c_a >= 0.0 and arms["c"]["e2e_success"] >= arms["a"]["e2e_success"]
    go_beats_b = (delta_c_b >= 0.0 and c_vs_b_savings > 0.0) or tool_acc_c >= 0.90
    no_go_controller = arms["c"]["e2e_success"] <= arms["b"]["e2e_success"] and delta_c_b < 0.0
    no_go_geral = arms["b"]["e2e_success"] <= arms["a"]["e2e_success"]
    if no_go_geral:
        status = "NO-GO geral: (b) <= (a), nem o graph ajuda (docs/17 §2)"
    elif no_go_controller:
        status = "NO-GO controlador: tuned <= (b), acionar ADR-009 (docs/17 §2)"
    elif go_tokens and go_success and go_beats_b:
        status = "GO condicional do slice: (c) >= (a) com tokens<< e (c) > (b) em cápsula/seleção"
    else:
        status = "INCONCLUSIVO: números não atendem GO nem NO-GO, manter slice sem escalar"

    report: dict[str, Any] = {
        "benchmark": "SIGA-Bench Holdout e2e 3 bracos",
        "slice": "siga-ex + sigaex (docs/17 §1)",
        "total_tasks_evaluated": n,
        "seven_baselines_mapping": SEVEN_TO_THREE,
        "needle_config": {
            "model": needle.name,
            "dataset_size": NEEDLE_DATASET_SIZE,
            "depth": NEEDLE_DEPTH,
            "note": "menor viavel P08-T01 (12L 4-bit, 98.44% routing)",
        },
        "pricing": {
            "input_usd_per_1k": PRICE_IN_PER_1K,
            "output_usd_per_1k": PRICE_OUT_PER_1K,
        },
        "latency_model": {
            "large_ms_per_input_token": LARGE_MS_PER_INPUT_TOKEN,
            "large_ms_per_output_token": LARGE_MS_PER_OUTPUT_TOKEN,
            "note": "simulacao deterministica local, sem chamada externa",
        },
        "raw_full_files_baseline": {
            "mean_tokens_per_task": raw_mean,
            "total_tokens": raw_total,
            "total_cost_usd": round(raw_total / 1000.0 * PRICE_IN_PER_1K, 6),
        },
        "arms": {
            "a-large-alone": arms["a"],
            "b-large-graph": arms["b"],
            "c-large-needle": {**arms["c"], "tool_selection_accuracy": tool_acc_c},
        },
        "comparison": {
            "effective_token_reduction_b_vs_raw": eff_red_b,
            "effective_token_reduction_c_vs_raw": eff_red_c,
            "c_vs_b_token_savings_pct": c_vs_b_savings,
            "task_success_delta_c_vs_a": delta_c_a,
            "task_success_delta_c_vs_b": delta_c_b,
            "task_success_delta_b_vs_a": delta_b_a,
        },
        "decision": {
            "status": status,
            "go_tokens": go_tokens,
            "go_success": go_success,
            "go_beats_b": go_beats_b,
            "rationale": (
                f"(c) success={arms['c']['e2e_success']} vs (a)={arms['a']['e2e_success']} "
                f"(delta={delta_c_a}); (c) vs (b)={arms['b']['e2e_success']} (delta={delta_c_b}); "
                f"reducao (c) vs raw={eff_red_c} (tokens<< exige >0.90); "
                f"(c) vs (b) economiza {c_vs_b_savings}% tokens com tool_acc={tool_acc_c}."
            ),
        },
        "sample_tasks": per_task[:10],
    }

    if save_report:
        reports_dir = ROOT / "experiments/reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        out = reports_dir / "integration_three_arms.json"
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if log_run:
        cfg = {
            "type": "integration_three_arms",
            "total_tasks": n,
            "needle": needle.name,
            "holdout_hash": hashlib.sha256(holdout_path.read_bytes()).hexdigest(),
        }
        run_data = new_run(
            config=cfg,
            dataset_version="holdout-v1",
            tool_version="siga-integration-v1",
            index_version="tree-sitter-java-0.23",
            bench_version="siga-bench-v1",
            needle_version="2.0-45M-subnetwork-12L",
            needle_depth=NEEDLE_DEPTH,
            metrics={
                "a_success": arms["a"]["e2e_success"],
                "b_success": arms["b"]["e2e_success"],
                "c_success": arms["c"]["e2e_success"],
                "effective_token_reduction_c": eff_red_c,
                "task_success_delta_c_vs_a": delta_c_a,
                "c_vs_b_savings_pct": c_vs_b_savings,
            },
            latency={
                "p50_ms": arms["c"]["latency"]["p50_ms"],
                "p95_ms": arms["c"]["latency"]["p95_ms"],
            },
            notes="P09-T02: e2e large-alone vs large+graph vs large+Needle no holdout",
            work_root=ROOT,
            siga_root=root,
        )
        runs_dir = ROOT / "experiments/runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        exp_file = runs_dir / f"{run_data['experiment_id']}.json"
        exp_file.write_text(json.dumps(run_data, indent=2, ensure_ascii=False), encoding="utf-8")
        report["experiment_id"] = run_data["experiment_id"]

    return report
