"""Harness B1/B2 do Needle 3 real (P13-T03, docs/22 §6–§7, docs/24 §3).

Correções obrigatórias desta tarefa:

- **B1**: uma única geração por tarefa (`RealNeedleModel.complete_once`), sem
  executar tools — o perfil antigo `Needle.run(max_steps=8)` com schemas sem
  callables produzia loop de `unknown tool` e não mede decisão isolada;
- **labels no scorer**: `expected_tool`, `task_type` e argumentos esperados
  ficam no record de avaliação e nunca entram no prompt (só `query` é enviada);
- **schema completo**: cada chamada é validada contra o JSON Schema do tool
  (`inference.needle_real.validate_arguments`);
- **timeout por tarefa**, progresso `[i/N]` com flush, checkpoint JSONL
  idempotente com resume e aborto por projeção 25% acima do orçamento;
- **B2 separado**, com as cinco tools reais registradas como callables.

O test cego do benchmark v2 não é lido aqui: B1/B2 usam a validation temporal
(`datasets/needle_export/needle_val.jsonl`, congelada) e o test segue fechado.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent

TOOL_ORDER = ("siga_locate", "siga_trace", "siga_impact", "siga_history", "siga_context")
STAGE_BUDGETS = {4: 120.0, 16: 300.0, 60: 1200.0}
DEFAULT_TASKS_PATH = ROOT / "datasets/needle_export/needle_val.jsonl"
DEFAULT_TOOLS_PATH = ROOT / "inference/siga_tools_schema.json"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: list[float], pct: float) -> float:
    """Percentil interpolado (mesma fórmula de evaluation/hardware_slos.py)."""
    if not values:
        raise ValueError("percentile exige lista não vazia")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    index = (pct / 100.0) * (len(ordered) - 1)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _rel(path: str | Path | None) -> str | None:
    if path is None:
        return None
    candidate = Path(path).resolve()
    try:
        return str(candidate.relative_to(ROOT))
    except ValueError:
        return str(candidate)


def load_validation_tasks(
    path: str | Path = DEFAULT_TASKS_PATH,
    stage: int = 4,
    seed: int = 0,
) -> list[dict[str, Any]]:
    """Tarefas da validation temporal com labels derivados das respostas reais.

    O id é sintetizado pela posição no arquivo congelado (`val-NNN`) porque o
    export não carrega id; qualquer mudança do arquivo é detectável pelo hash
    registrado no relatório.
    """
    records = [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    tasks: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        answers = [answer for answer in (record.get("answers") or []) if isinstance(answer, dict)]
        first = answers[0] if answers else {}
        tasks.append(
            {
                "id": f"val-{index:03d}",
                "query": record["query"],
                "expected_tool": first.get("name"),
                "expected_arguments": first.get("arguments") or {},
                "expected_sequence": [answer.get("name") for answer in answers],
                "task_type": "no-tool" if not answers else "tool",
            }
        )
    if stage < 1 or stage > len(tasks):
        raise ValueError(f"estágio {stage} inválido para {len(tasks)} tarefas de validation")
    return stratified_sample(tasks, stage, seed)


def stratified_sample(tasks: list[dict[str, Any]], n: int, seed: int) -> list[dict[str, Any]]:
    """Amostra estratificada determinística, aninhada no funil 4→16→60.

    A ordem canônica intercala as cinco tools em round-robin e insere um caso
    no-tool a cada oito posições (1/8, como no treino). Estágios maiores são
    prefixos dos menores, então o funil nunca troca os casos já avaliados; a
    seed registrada randomiza apenas a ordem de execução (docs/21 §7.2).
    """
    canonical = _canonical_order(tasks)
    picked = canonical[:n]
    random.Random(seed).shuffle(picked)
    return picked


def _canonical_order(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {tool: [] for tool in TOOL_ORDER}
    no_tool: list[dict[str, Any]] = []
    for task in tasks:
        tool = task.get("expected_tool")
        if tool in buckets:
            buckets[tool].append(task)
        else:
            no_tool.append(task)
    cursors = {tool: 0 for tool in TOOL_ORDER}
    rotation = 0
    no_tool_index = 0
    ordered: list[dict[str, Any]] = []

    def next_tool() -> dict[str, Any] | None:
        nonlocal rotation
        for _ in range(len(TOOL_ORDER)):
            tool = TOOL_ORDER[rotation % len(TOOL_ORDER)]
            rotation += 1
            if cursors[tool] < len(buckets[tool]):
                task = buckets[tool][cursors[tool]]
                cursors[tool] += 1
                return task
        return None

    while len(ordered) < len(tasks):
        if len(ordered) % 8 == 1 and no_tool_index < len(no_tool):
            ordered.append(no_tool[no_tool_index])
            no_tool_index += 1
            continue
        task = next_tool()
        if task is None:
            ordered.extend(no_tool[no_tool_index:])
            no_tool_index = len(no_tool)
            break
        ordered.append(task)
    return ordered


def _load_checkpoint(path: Path | None) -> dict[str, dict[str, Any]]:
    done: dict[str, dict[str, Any]] = {}
    if path is not None and path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("task_id"):
                done[record["task_id"]] = record
    return done


def _run_loop(
    *,
    tasks: list[dict[str, Any]],
    predict: Callable[[dict[str, Any]], dict[str, Any]],
    checkpoint: Path | None,
    resume: bool,
    progress: bool,
    budget_s: float | None,
) -> dict[str, Any]:
    done = _load_checkpoint(checkpoint) if resume else {}
    done_at_start = len(done)
    pending = max(0, len(tasks) - done_at_start)
    handle = checkpoint.open("a", encoding="utf-8") if checkpoint else None
    start = time.perf_counter()
    status = "completed"
    abort_reason: str | None = None
    processed = 0
    try:
        for index, task in enumerate(tasks):
            if task["id"] in done:
                if progress:
                    print(f"[{index + 1}/{len(tasks)}] {task['id']} skipped (checkpoint)", flush=True)
                continue
            prediction = predict(task)
            record = dict(prediction)
            record.update(
                {
                    "task_id": task["id"],
                    "expected_tool": task.get("expected_tool"),
                    "expected_arguments": task.get("expected_arguments") or {},
                    "expected_sequence": task.get("expected_sequence") or [],
                    "task_type": task.get("task_type"),
                }
            )
            done[task["id"]] = record
            if handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                handle.flush()
            processed += 1
            elapsed = time.perf_counter() - start
            projection = elapsed * pending / processed if processed else 0.0
            if progress:
                print(
                    f"[{index + 1}/{len(tasks)}] {task['id']} "
                    f"tool={record.get('tool')} valid={record.get('schema_valid')} "
                    f"{record.get('latency_ms', 0.0):.0f}ms "
                    f"proj={projection:.0f}s",
                    flush=True,
                )
            if record.get("timeout"):
                status = "aborted_timeout"
                abort_reason = f"timeout na tarefa {task['id']}"
                break
            if budget_s and projection > budget_s * 1.25:
                status = "aborted_projection"
                abort_reason = (
                    f"projeção {projection:.0f}s acima de 125% do orçamento {budget_s:.0f}s"
                )
                print(f"ABORTO: {abort_reason}", file=sys.stderr, flush=True)
                break
    finally:
        if handle:
            handle.close()
    predictions = [done[task["id"]] for task in tasks if task["id"] in done]
    if status == "completed" and len(predictions) < len(tasks):
        status = "partial"
    return {
        "status": status,
        "abort_reason": abort_reason,
        "predictions": predictions,
        "elapsed_s": time.perf_counter() - start,
        "num_tasks": len(tasks),
        "num_done": len(predictions),
    }


def run_b1(
    model: Any,
    tasks: list[dict[str, Any]],
    checkpoint: str | Path | None = None,
    resume: bool = True,
    max_new_tokens: int = 128,
    escalate_to: int | None = 256,
    budget_s: float | None = 300.0,
    progress: bool = True,
) -> dict[str, Any]:
    """B1: uma geração por tarefa, labels só no record de avaliação."""

    def predict(task: dict[str, Any]) -> dict[str, Any]:
        return model.complete_once(
            task["query"], max_new_tokens=max_new_tokens, escalate_to=escalate_to
        )

    return _run_loop(
        tasks=tasks,
        predict=predict,
        checkpoint=Path(checkpoint) if checkpoint else None,
        resume=resume,
        progress=progress,
        budget_s=budget_s,
    )


def run_b2(
    model: Any,
    tasks: list[dict[str, Any]],
    tool_log: list[dict[str, Any]],
    checkpoint: str | Path | None = None,
    resume: bool = True,
    max_steps: int = 3,
    max_new_tokens: int = 256,
    budget_s: float | None = 120.0,
    progress: bool = True,
) -> dict[str, Any]:
    """B2: loop modelo→tool→observação com callables reais já registrados."""

    def predict(task: dict[str, Any]) -> dict[str, Any]:
        tool_log.clear()
        record = model.run_agent(
            task["query"], max_steps=max_steps, max_new_tokens=max_new_tokens
        )
        record["tool_sequence"] = [entry.get("name") for entry in tool_log]
        record["tool_calls"] = [
            {
                "name": entry.get("name"),
                "arguments": entry.get("arguments"),
                "ok": entry.get("ok", False),
                "error": entry.get("error"),
            }
            for entry in tool_log
        ]
        return record

    return _run_loop(
        tasks=tasks,
        predict=predict,
        checkpoint=Path(checkpoint) if checkpoint else None,
        resume=resume,
        progress=progress,
        budget_s=budget_s,
    )


def summarize_b1(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    """Métricas B1 sobre records já rotulados (nenhum label entra no prompt)."""
    total = len(predictions)
    tool_tasks = [p for p in predictions if p.get("expected_tool")]
    no_tool_tasks = [p for p in predictions if not p.get("expected_tool")]
    correct = sum(1 for p in tool_tasks if p.get("tool") == p.get("expected_tool"))
    exact_args = sum(
        1
        for p in tool_tasks
        if p.get("tool") == p.get("expected_tool")
        and dict(p.get("arguments") or {}) == dict(p.get("expected_arguments") or {})
    )
    schema_valid = sum(1 for p in predictions if p.get("schema_valid"))
    invalid = sum(1 for p in predictions if p.get("is_invalid_call"))
    no_tool_ok = sum(1 for p in no_tool_tasks if not p.get("tool"))
    grounding_clean = sum(1 for p in predictions if not p.get("grounding_violations"))
    latencies = [float(p.get("latency_ms") or 0.0) for p in predictions]
    generations = [int(p.get("generations") or 0) for p in predictions]
    return {
        "counts": {"tasks": total, "tool_tasks": len(tool_tasks), "no_tool_tasks": len(no_tool_tasks)},
        "tool_selection_accuracy": (correct / len(tool_tasks)) if tool_tasks else None,
        "argument_exact_match": (exact_args / len(tool_tasks)) if tool_tasks else None,
        "schema_validity_rate": (schema_valid / total) if total else None,
        "invalid_tool_call_rate": (invalid / total) if total else None,
        "no_tool_accuracy": (no_tool_ok / len(no_tool_tasks)) if no_tool_tasks else None,
        "grounding_clean_rate": (grounding_clean / total) if total else None,
        "timeout_count": sum(1 for p in predictions if p.get("timeout")),
        "truncation_count": sum(1 for p in predictions if p.get("truncated")),
        "escalated_count": sum(1 for p in predictions if p.get("escalated")),
        "generations_max": max(generations) if generations else 0,
        "generations_mean": (sum(generations) / len(generations)) if generations else 0.0,
        "latency_ms": {
            "p50": percentile(latencies, 50.0) if latencies else None,
            "p95": percentile(latencies, 95.0) if latencies else None,
            "mean": (sum(latencies) / len(latencies)) if latencies else None,
        },
    }


def summarize_b2(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    """Métricas B2: sequência de tools reais executadas + erros de execução."""
    total = len(predictions)
    sequence_ok = sum(
        1
        for p in predictions
        if [name for name in (p.get("tool_sequence") or [])] == list(p.get("expected_sequence") or [])
    )
    first_tool_ok = sum(
        1
        for p in predictions
        if (p.get("tool_sequence") or [None])[:1] == (p.get("expected_sequence") or [None])[:1]
    )
    unknown_tool = sum(
        1
        for p in predictions
        for call in (p.get("tool_calls") or [])
        if call.get("error") and "unknown tool" in str(call.get("error"))
    )
    tool_errors = sum(
        1 for p in predictions for call in (p.get("tool_calls") or []) if call.get("error")
    )
    calls = [len(p.get("tool_sequence") or []) for p in predictions]
    latencies = [float(p.get("latency_ms") or 0.0) for p in predictions]
    return {
        "counts": {"tasks": total},
        "sequence_success_rate": (sequence_ok / total) if total else None,
        "first_tool_accuracy": (first_tool_ok / total) if total else None,
        "unknown_tool_count": unknown_tool,
        "tool_error_count": tool_errors,
        "calls_total": sum(calls),
        "calls_mean": (sum(calls) / len(calls)) if calls else 0.0,
        "timeout_count": sum(1 for p in predictions if p.get("timeout")),
        "schema_validity_rate": (
            sum(1 for p in predictions if p.get("schema_valid")) / total if total else None
        ),
        "latency_ms": {
            "p50": percentile(latencies, 50.0) if latencies else None,
            "p95": percentile(latencies, 95.0) if latencies else None,
            "mean": (sum(latencies) / len(latencies)) if latencies else None,
        },
    }


def _schema_from_tool(tool: Any) -> dict[str, Any] | None:
    if isinstance(tool, dict):
        return tool
    schema = getattr(tool, "_needle_tool", None)
    return schema if isinstance(schema, dict) else None


def build_tool_callables(
    schema_path: str | Path = DEFAULT_TOOLS_PATH,
    log: list[dict[str, Any]] | None = None,
    repo: str | Path | None = None,
    extra_site: str | None = None,
) -> list[Callable[..., Any]]:
    """Registra as cinco tools reais como callables do engine (`_needle_tool`).

    `extra_site` cobre o runtime de tools ausente no venv de treino (append no
    fim do `sys.path`, sem sobrescrever numpy/jax do venv); só é usado quando o
    ambiente de inferência não carrega `tree-sitter` por conta própria.
    """
    if extra_site and extra_site not in sys.path:
        sys.path.append(str(extra_site))
    from tools.siga_context import siga_context
    from tools.siga_history import siga_history
    from tools.siga_impact import siga_impact
    from tools.siga_locate import siga_locate
    from tools.siga_trace import siga_trace

    real_functions = {
        "siga_locate": siga_locate,
        "siga_trace": siga_trace,
        "siga_impact": siga_impact,
        "siga_history": siga_history,
        "siga_context": siga_context,
    }
    schemas = [
        entry for entry in json.loads(Path(schema_path).read_text(encoding="utf-8"))
        if isinstance(entry, dict) and entry.get("name") in real_functions
    ]
    callables: list[Callable[..., Any]] = []
    for schema in schemas:
        callables.append(_make_wrapper(schema, real_functions[schema["name"]], log, repo))
    return callables


def _make_wrapper(
    schema: dict[str, Any],
    real_function: Callable[..., Any],
    log: list[dict[str, Any]] | None,
    repo: str | Path | None,
) -> Callable[..., Any]:
    name = schema["name"]

    def wrapper(**kwargs: Any) -> Any:
        entry: dict[str, Any] = {"name": name, "arguments": kwargs}
        if log is not None:
            log.append(entry)
        try:
            result = real_function(repo=repo, **kwargs)
        except Exception as exc:  # erro real de execução é medido, não escondido
            entry["error"] = f"{type(exc).__name__}: {exc}"
            raise
        entry["ok"] = True
        return result

    wrapper.__name__ = name
    wrapper.__doc__ = schema.get("description")
    wrapper._needle_tool = schema  # type: ignore[attr-defined]
    return wrapper


def preflight(require_gpu: bool = False) -> dict[str, Any]:
    """Pré-voo read-only: GPU visível + backend JAX (docs/22 §4.1)."""
    info: dict[str, Any] = {"devices": [], "gpu_list": None, "gpu_query": None, "jax": None}
    info["devices"] = sorted(path.name for path in Path("/dev").glob("nvidia*"))
    try:
        listing = subprocess.run(
            ["nvidia-smi", "-L"], capture_output=True, text=True, timeout=15
        )
        info["gpu_list"] = [line for line in listing.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        info["gpu_list"] = None
    try:
        query = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,uuid,driver_version,memory.total,memory.free,temperature.gpu",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        info["gpu_query"] = query.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        info["gpu_query"] = None
    try:
        import jax

        info["jax"] = {
            "version": jax.__version__,
            "backend": jax.default_backend(),
            "devices": [str(device) for device in jax.devices()],
        }
    except Exception as exc:  # ambiente sem jax é permitido; fica registrado
        info["jax"] = {"error": f"{type(exc).__name__}: {exc}"}
    if require_gpu:
        backend = (info.get("jax") or {}).get("backend")
        listed = "\n".join(info.get("gpu_list") or [])
        if backend != "gpu" or "RTX 4060" not in listed:
            raise RuntimeError("BLOCKED: pré-voo GPU obrigatório falhou (docs/22 §4.1)")
    return info


def engine_version() -> str:
    try:
        return f"cactus-needle {importlib.metadata.version('cactus-needle')}"
    except importlib.metadata.PackageNotFoundError:
        return "cactus-needle (versão indisponível)"


def peak_rss_mb() -> float:
    """Pico de RSS do processo via VmHWM do procfs (Linux)."""
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def _trim_prediction(prediction: dict[str, Any]) -> dict[str, Any]:
    trimmed = {key: value for key, value in prediction.items() if key != "raw"}
    if "executed_calls" in trimmed:
        trimmed["executed_calls"] = len(trimmed["executed_calls"])
    return trimmed


def build_report(
    *,
    mode: str,
    label: str,
    result: dict[str, Any],
    metrics: dict[str, Any],
    weights_path: str | Path,
    weights_sha: str,
    schema_path: str | Path | None,
    schema_sha: str | None,
    tasks_path: str | Path,
    tasks_sha: str,
    stage: int,
    seed: int,
    profile: dict[str, Any],
    preflight_info: dict[str, Any],
    checkpoint: str | Path | None,
    backend_note: str,
) -> dict[str, Any]:
    predictions = [_trim_prediction(prediction) for prediction in result["predictions"]]
    return {
        "task": "P13-T03",
        "mode": mode,
        "label": label,
        "status": result["status"],
        "abort_reason": result["abort_reason"],
        "model": {
            "weights": _rel(weights_path),
            "weights_sha256": weights_sha,
            "engine": engine_version(),
            "engine_backend_note": backend_note,
        },
        "tools_schema": {"path": _rel(schema_path), "sha256": schema_sha},
        "dataset": {
            "path": _rel(tasks_path),
            "sha256": tasks_sha,
            "split": "valid (temporal, test cego nunca lido)",
            "stage": stage,
            "seed": seed,
            "counts": metrics.get("counts"),
        },
        "profile": profile,
        "preflight": preflight_info,
        "timing": {
            "elapsed_s": round(result["elapsed_s"], 2),
            "num_tasks": result["num_tasks"],
            "num_done": result["num_done"],
            "peak_rss_mb": peak_rss_mb(),
        },
        "checkpoint": _rel(checkpoint),
        "metrics": metrics,
        "predictions": predictions,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harness B1/B2 do Needle 3 real (P13-T03)")
    parser.add_argument("--mode", choices=("b1", "b2"), default="b1")
    parser.add_argument("--stage", type=int, choices=tuple(sorted(STAGE_BUDGETS)), default=16)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--weights", required=True, help="caminho do .cact real")
    parser.add_argument("--label", default="real")
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS_PATH))
    parser.add_argument("--tools", default=str(DEFAULT_TOOLS_PATH))
    parser.add_argument("--max-new-tokens", type=int, default=128)
    parser.add_argument("--escalate-to", type=int, default=256)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--budget-s", type=float, default=None)
    parser.add_argument("--max-steps", type=int, default=3)
    parser.add_argument("--report", default=None)
    parser.add_argument("--checkpoint", default=None)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument(
        "--no-log-run",
        action="store_true",
        help="não registra experiment run (usado em estágios estruturais do funil)",
    )
    parser.add_argument("--require-gpu", action="store_true")
    parser.add_argument("--repo", default=os.environ.get("SIGA_REPO_DIR"))
    parser.add_argument("--extra-site", default=os.environ.get("SIGA_RUNTIME_SITE"))
    args = parser.parse_args(argv)

    budget = args.budget_s if args.budget_s is not None else STAGE_BUDGETS[args.stage]
    report_path = Path(
        args.report or ROOT / f"experiments/reports/needle_real_{args.mode}_{args.label}.json"
    )
    checkpoint_path = Path(
        args.checkpoint
        or ROOT / f"data/needle-real/runs/P13-T03/{args.mode}-{args.label}-stage{args.stage}.partial.jsonl"
    )
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        preflight_info = preflight(require_gpu=args.require_gpu)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 3

    tasks = load_validation_tasks(args.tasks, stage=args.stage, seed=args.seed)
    schema_path = Path(args.tools)
    schema_sha = sha256_file(schema_path) if schema_path.is_file() else None
    weights_sha = sha256_file(args.weights)

    if args.mode == "b1":
        from inference.needle_real import RealNeedleModel

        schemas = json.loads(schema_path.read_text(encoding="utf-8"))
        model = RealNeedleModel(
            weights_path=args.weights, tools=schemas, task_timeout_s=args.timeout_s
        )
        try:
            result = run_b1(
                model,
                tasks,
                checkpoint=checkpoint_path,
                resume=not args.no_resume,
                max_new_tokens=args.max_new_tokens,
                escalate_to=args.escalate_to or None,
                budget_s=budget,
            )
        finally:
            model.close()
        metrics = summarize_b1(result["predictions"])
        backend_note = (
            "engine oficial cactus-needle: inferência CPU-only publicada pelo upstream; "
            "treino JAX gpu registrado no train_summary.json do run de treino; "
            "nenhum fallback silencioso"
        )
        profile = {
            "max_new_tokens": args.max_new_tokens,
            "escalate_to": args.escalate_to,
            "timeout_s": args.timeout_s,
            "budget_s": budget,
        }
    else:
        tool_log: list[dict[str, Any]] = []
        callables = build_tool_callables(
            schema_path, log=tool_log, repo=args.repo, extra_site=args.extra_site
        )
        from inference.needle_real import RealNeedleModel

        model = RealNeedleModel(
            weights_path=args.weights, tools=callables, task_timeout_s=args.timeout_s
        )
        try:
            result = run_b2(
                model,
                tasks,
                tool_log,
                checkpoint=checkpoint_path,
                resume=not args.no_resume,
                max_steps=args.max_steps,
                max_new_tokens=args.max_new_tokens,
                budget_s=budget,
            )
        finally:
            model.close()
        metrics = summarize_b2(result["predictions"])
        backend_note = (
            "engine oficial + cinco callables reais (tools SIGA read-only); "
            "inferência CPU-only do upstream registrada; treino real em JAX gpu"
        )
        profile = {
            "max_steps": args.max_steps,
            "max_new_tokens": args.max_new_tokens,
            "timeout_s": args.timeout_s,
            "budget_s": budget,
            "extra_site_used": bool(args.extra_site),
        }

    report = build_report(
        mode=args.mode,
        label=args.label,
        result=result,
        metrics=metrics,
        weights_path=args.weights,
        weights_sha=weights_sha,
        schema_path=schema_path if schema_path.is_file() else None,
        schema_sha=schema_sha,
        tasks_path=args.tasks,
        tasks_sha=sha256_file(args.tasks),
        stage=args.stage,
        seed=args.seed,
        profile=profile,
        preflight_info=preflight_info,
        checkpoint=checkpoint_path,
        backend_note=backend_note,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report["harness"] = {
        "real_needle_eval_sha256": sha256_file(__file__),
        "needle_real_sha256": sha256_file(ROOT / "inference/needle_real.py"),
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[{args.mode}] relatório: {_rel(report_path)} status={result['status']}", flush=True)

    if result["predictions"] and not args.no_log_run:
        from experiments import log as exp_log

        run = exp_log.new_run(
            config={
                "task": "P13-T03",
                "mode": args.mode,
                "label": args.label,
                "weights_sha256": weights_sha,
                "stage": args.stage,
                "seed": args.seed,
                "profile": profile,
            },
            dataset_version=f"needle_val-v1-stage{args.stage}-seed{args.seed}",
            tool_version="inference/siga_tools_schema.json",
            index_version="not-used-b1b2",
            bench_version="needle_val-temporal",
            metrics={
                key: metrics[key]
                for key in ("tool_selection_accuracy", "schema_validity_rate", "no_tool_accuracy")
                if key in metrics
            },
            latency={
                "p50_ms": (metrics.get("latency_ms") or {}).get("p50") or 0.0,
                "p95_ms": (metrics.get("latency_ms") or {}).get("p95"),
            },
            needle_version=engine_version(),
            needle_depth=20,
            artifact_hash=weights_sha,
            siga_root=ROOT.parent,
            work_root=ROOT,
            notes=(
                f"P13-T03 {args.mode} stage={args.stage} seed={args.seed} "
                f"status={result['status']}; labels só no scorer; engine real sem simulador"
            ),
        )
        exp_log.save(run, ROOT / f"experiments/runs/{run['experiment_id']}.json")
        print(f"[{args.mode}] run {run['experiment_id']} registrado", flush=True)

    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
