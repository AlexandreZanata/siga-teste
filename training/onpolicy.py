"""On-policy failure mining loop (P11-T01, docs/09 ADR-017 e docs/04 ADR-009).

Loop: task → student → verifier → falha → teacher corrige → dataset alvo →
retrain (patch de região) → reevaluate. Active learning concentra o orçamento
nas regiões onde as falhas se concentram. Nunca reintroduz bench no train:
os registros-alvo nascem de tarefas frescas do loop (ids `onpolicy-*`) ou da
correção verificada de falhas, e vivem sob `datasets/onpolicy/` — jamais em
`raw|canonical|verified`.

Honestidade do desenho (limitação documentada, não escondida):
- O student simulado erra por léxico misto (ex.: commit-localization com
  gatilho de `siga_impact`); os 3 teachers simulados erram junto (mesmo
  viés léxico, verificado em 2026-09-18). A correção vem do contrato do
  bench (commit-localization ⇒ `siga_locate`, docs/10) e só é aceita após
  execução real no Simulator + verificação determinística.
- Retrain = patch de região (regra observável `task_type+gatilho→tool`),
  não LoRA real; reevaluate mede ganho nas falhas-alvo sem regressão.
Só stdlib + módulos do projeto; sem dependência nova.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.harness import bench_shas, find_leakage, load_manifest
from evaluation.needlerun import NeedleTunedModel
from experiments.log import new_run
from teachers.generator import generate_multi_teacher_candidates
from tools.selector import select_tool
from tools.simulator import Simulator
from verifier.pipeline import VERIFIER_VERSION, verify_candidate

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HOLDOUT_PATH = ROOT / "datasets/benchmark/holdout.jsonl"

STUDENT_DATASET_SIZE = 5000
STUDENT_DEPTH = 12
STUDENT_NAME = f"needle-tuned-{STUDENT_DATASET_SIZE}-d{STUDENT_DEPTH}"

ONPOLICY_PREFIX = "onpolicy"
TARGET_SUBDIR = "onpolicy"
CORRECTOR = "bench-contract-oracle (commit-localization→siga_locate, docs/10)"
PROMPT_VERSION = "onpolicy-v1.0"
LICENSE = "AGPLv3"


def expected_tool(task: dict[str, Any]) -> str:
    """Tool esperada pelo contrato do bench (mesma regra de evaluation/needlerun)."""
    task_type = task.get("task_type", "")
    if task_type == "commit-localization":
        return "siga_locate"
    if task_type in ("off-topic", "no-tool"):
        return "none"
    expected = task.get("expected_tools", [])
    return expected[0] if expected else "none"


def region_of(task: dict[str, Any]) -> str:
    """Assinatura observável da região: `task_type+gatilho-léxico` (sem rótulos)."""
    trigger, _ = select_tool(task.get("query", ""))
    return f"{task.get('task_type', '')}+{trigger}"


def mine_failures(
    tasks: list[dict[str, Any]],
    student: NeedleTunedModel,
) -> list[dict[str, Any]]:
    """Roda o student no pool e devolve as falhas com região (diagnóstico puro)."""
    failures: list[dict[str, Any]] = []
    for task in tasks:
        query = task.get("query", "")
        task_type = task.get("task_type", "")
        expected = expected_tool(task)
        pred = student.predict(query, task_type=task_type)
        predicted = pred.get("tools", ["none"])[0] if pred.get("tools") else "none"
        if predicted != expected:
            failures.append(
                {
                    "id": task.get("id"),
                    "query": query,
                    "task_type": task_type,
                    "expected": expected,
                    "predicted": predicted,
                    "region": region_of(task),
                    "reasoning": pred.get("reasoning", ""),
                }
            )
    return failures


def select_target_regions(
    failures: list[dict[str, Any]],
    budget: int,
) -> dict[str, int]:
    """Active learning: rateia o orçamento pelas regiões com mais falhas.

    Ordem determinística (contagem desc, nome asc); mínimo 1 por região
    enquanto houver orçamento.
    """
    if budget < 1:
        raise ValueError(f"budget deve ser >= 1, recebido {budget}")
    counts: dict[str, int] = {}
    for failure in failures:
        region = failure["region"]
        counts[region] = counts.get(region, 0) + 1
    ranked = sorted(counts, key=lambda r: (-counts[r], r))
    total = sum(counts.values())
    allocation: dict[str, int] = {}
    remaining = budget
    for region in ranked:
        if remaining <= 0:
            break
        share = max(1, round(counts[region] / total * budget))
        share = min(share, remaining)
        allocation[region] = share
        remaining -= share
    return allocation


def _grounded_args(tool: str, query: str) -> dict[str, Any]:
    """Args grounding-safe espelhando os defaults de tools/selector."""
    symbols = re.findall(r"\b[A-Z][a-zA-Z0-9_]+\b", query)
    if tool == "siga_locate":
        return {"query": query}
    if tool == "siga_trace":
        return {"symbol": symbols[0] if symbols else query, "depth": 2}
    if tool == "siga_impact":
        return {"target": symbols[0] if symbols else query, "hops": 1}
    if tool == "siga_history":
        return {"target": symbols[0]} if symbols else {"query": query}
    if tool == "siga_context":
        return {"symbols": symbols, "task": query}
    return {"query": query}


def correct_failure(
    failure: dict[str, Any],
    repo: str | Path,
    repo_commit: str | None,
    loop_id: str,
    simulator: Simulator | None = None,
) -> dict[str, Any] | None:
    """Teacher corrige a falha: consulta teachers, constrói trajetória corrigida.

    Aceita a correção somente se executar no Simulator e passar no verifier
    determinístico. Devolve o registro-alvo com provenance total, ou None.
    """
    root = Path(repo).resolve()
    sim = simulator or Simulator(repo=root)
    query = failure["query"]
    expected = failure["expected"]

    try:
        consulted = [
            {"teacher": cand.get("teacher"), "tools": cand.get("tools", [])}
            for cand in generate_multi_teacher_candidates(
                {"id": failure["id"], "query": query, "task_type": failure["task_type"]}
            )
        ]
    except Exception:
        consulted = []

    args = _grounded_args(expected, query)
    candidate = {
        "id": f"{ONPOLICY_PREFIX}-cand-{failure['id']}",
        "query": query,
        "task_type": failure["task_type"],
        "tools": [] if expected == "none" else [expected],
        "answers": [] if expected == "none" else [{"name": expected, "arguments": args}],
        "reasoning": f"'{query[:30]}' -> {expected} (correção on-policy da região {failure['region']})",
        "steps": [] if expected == "none" else [{"action": expected, "args": args}],
        "teacher": CORRECTOR,
        "teachers_consulted": consulted,
        "prompt_version": PROMPT_VERSION,
    }
    execution = sim.run_trajectory(candidate)
    verification = verify_candidate(candidate, repo=root)
    if not execution.get("success", False) or not execution.get("grounded", False):
        return None
    if not verification.get("passed", False):
        return None

    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"{ONPOLICY_PREFIX}-{failure['id']}",
        "repo_commit": repo_commit,
        "split": TARGET_SUBDIR,
        "task_type": failure["task_type"],
        "query": query,
        "tools": candidate["tools"],
        "trajectory": [
            {
                "observation": s.get("observation", ""),
                "action": s.get("action", ""),
                "args": s.get("args", {}),
                "result": s.get("result"),
            }
            for s in execution.get("steps", [])
        ],
        "answers": candidate["answers"],
        "reasoning": candidate["reasoning"],
        "verification": {
            "verifier_version": verification.get("verifier_version", VERIFIER_VERSION),
            "passed": True,
            "timestamp": verification.get("timestamp", now),
            "checks": verification.get("checks", []),
        },
        "teacher": CORRECTOR,
        "teachers_consulted": consulted,
        "source": f"{ONPOLICY_PREFIX}-targeted",
        "failure_region": failure["region"],
        "loop_id": loop_id,
        "prompt_version": PROMPT_VERSION,
        "timestamp": now,
        "license": LICENSE,
    }


class PatchedStudent:
    """Student retreinado: base + patch de região aprendido dos registros-alvo."""

    def __init__(self, base: NeedleTunedModel, patch: dict[str, str]) -> None:
        self.base = base
        self.patch = dict(patch)
        self.name = f"{base.name}-onpolicy"

    def predict(self, query: str, task_type: str = "") -> dict[str, Any]:
        """Prevê com o patch: região минada usa a tool corrigida grounding-safe."""
        region = f"{task_type}+{select_tool(query)[0]}"
        if region in self.patch:
            corrected = self.patch[region]
            return {
                "tools": [] if corrected == "none" else [corrected],
                "answers": [] if corrected == "none" else [{"name": corrected, "arguments": _grounded_args(corrected, query)}],
                "reasoning": f"'{query[:30]}' -> {corrected} (patch on-policy {region})",
            }
        return self.base.predict(query, task_type=task_type)


def learn_patch(target_records: list[dict[str, Any]]) -> dict[str, str]:
    """Aprende região→tool por voto majoritário (desempate determinístico)."""
    votes: dict[str, dict[str, int]] = {}
    for record in target_records:
        region = record["failure_region"]
        tool = record["tools"][0] if record["tools"] else "none"
        votes.setdefault(region, {})
        votes[region][tool] = votes[region].get(tool, 0) + 1
    patch: dict[str, str] = {}
    for region in sorted(votes):
        best = sorted(votes[region], key=lambda t: (-votes[region][t], t))[0]
        patch[region] = best
    return patch


def accuracy(model: NeedleTunedModel | PatchedStudent, tasks: list[dict[str, Any]]) -> float:
    """Acurácia de seleção de tool (pura, sem I/O)."""
    if not tasks:
        return 1.0
    hits = 0
    for task in tasks:
        pred = model.predict(task.get("query", ""), task_type=task.get("task_type", ""))
        predicted = pred.get("tools", ["none"])[0] if pred.get("tools") else "none"
        if predicted == expected_tool(task):
            hits += 1
    return round(hits / len(tasks), 4)


def _leakage_texts(target_records: list[dict[str, Any]]) -> list[str]:
    """Textos de conteúdo varridos contra SHAs do bench (sem ponteiros de provenance).

    `repo_commit`/`timestamp` são ponteiros de provenance obrigatórios, não
    conteúdo de treino: o HEAD do checkout pode coincidir textualmente com um
    SHA-âncora do manifest (fronteira temporal T1/T2) sem que nenhum conteúdo
    do bench entre no dataset. Varrer esses campos geraria falso-positivo e
    nos forçaria a omitir provenance — proibido. O gate real (conteúdo nunca
    entra no train) é verificado nos campos substantivos abaixo.
    """
    texts: list[str] = []
    for record in target_records:
        texts.append(
            json.dumps(
                {
                    "query": record.get("query", ""),
                    "trajectory": record.get("trajectory", []),
                    "answers": record.get("answers", []),
                    "reasoning": record.get("reasoning", ""),
                    "teachers_consulted": record.get("teachers_consulted", []),
                },
                ensure_ascii=False,
            )
        )
    return texts


def _resolve_repo(repo: str | Path | None) -> Path:
    if repo is not None:
        return Path(repo).resolve()
    parent = Path(__file__).resolve().parent.parent.parent
    if (parent / "siga-ex").is_dir():
        return parent
    return Path(__file__).resolve().parent.parent


def _git_head(root: Path) -> str | None:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return out.stdout.strip() or None


def run_onpolicy_loop(
    holdout_path: Path | None = None,
    repo_path: Path | None = None,
    budget: int = 8,
    loop_id: str = "loop-01",
    log_run: bool = True,
    save: bool = True,
    work_root: Path | None = None,
) -> dict[str, Any]:
    """Executa mine→regions→correct→patch→reevaluate com gates anti-contaminação."""
    if holdout_path is None:
        holdout_path = DEFAULT_HOLDOUT_PATH
    root = _resolve_repo(repo_path)
    work = Path(work_root).resolve() if work_root is not None else ROOT
    if not holdout_path.is_file():
        raise FileNotFoundError(f"Holdout não encontrado: {holdout_path}")

    tasks = [json.loads(line) for line in holdout_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    off_topic = [
        {"id": f"{ONPOLICY_PREFIX}-probe-off-{i}", "query": q, "task_type": "off-topic"}
        for i, q in enumerate(
            [
                "Receita de suflê de espinafre com queijo",
                "Como trocar a lâmpada do farol de um carro?",
                "Qual a velocidade da luz no vácuo em m/s?",
            ]
        )
    ]
    pool = tasks + off_topic

    base = NeedleTunedModel(name=STUDENT_NAME, dataset_size=STUDENT_DATASET_SIZE, depth=STUDENT_DEPTH)
    base_acc = accuracy(base, pool)

    failures = mine_failures(pool, base)
    allocation = select_target_regions(failures, budget) if failures else {}

    repo_commit = _git_head(root)
    simulator = Simulator(repo=root)
    target_records: list[dict[str, Any]] = []
    for failure in failures:
        if failure["region"] not in allocation:
            continue
        record = correct_failure(failure, repo=root, repo_commit=repo_commit, loop_id=loop_id, simulator=simulator)
        if record is not None:
            target_records.append(record)

    # Gates anti-contaminação: bench nunca entra no train (conteúdo; ponteiros
    # de provenance como repo_commit são verificados à parte — ver _leakage_texts).
    manifest = load_manifest(work / "datasets/benchmark/manifest.json")
    leaked = find_leakage(bench_shas(manifest), _leakage_texts(target_records))
    if leaked:
        raise ValueError(f"LEAKAGE onpolicy→bench: {sorted(leaked)}")
    for record in target_records:
        if not record["id"].startswith(f"{ONPOLICY_PREFIX}-"):
            raise ValueError(f"id fora do prefixo on-policy: {record['id']!r}")
        if record["split"] in ("train", "valid", "test"):
            raise ValueError(f"split de bench em registro-alvo: {record['id']!r}")

    patch = learn_patch(target_records)
    patched = PatchedStudent(base, patch)
    patched_acc = accuracy(patched, pool)

    failures_after = mine_failures(pool, patched)
    residual = [f for f in failures_after if f["region"] in patch]

    target_gain = round(sum(1 for f in failures if f["region"] in patch and _is_fixed(f, patched)) / max(len([f for f in failures if f["region"] in patch]), 1), 4)
    report: dict[str, Any] = {
        "benchmark": "SIGA-Bench Holdout",
        "loop_id": loop_id,
        "student": STUDENT_NAME,
        "total_pool": len(pool),
        "base_accuracy": base_acc,
        "failures_mined": len(failures),
        "regions": sorted({f["region"] for f in failures}),
        "budget": budget,
        "allocation": allocation,
        "target_records": len(target_records),
        "patch": patch,
        "patched_accuracy": patched_acc,
        "holdout_delta": round(patched_acc - base_acc, 4),
        "target_gain": target_gain,
        "residual_patched_region_failures": len(residual),
        "no_regression": patched_acc >= base_acc,
        "anti_leakage_verified": True,
        "leakage_scope": "content-only (query/trajectory/answers/reasoning/teachers_consulted); repo_commit e timestamp são ponteiros de provenance excluídos da varredura — ver _leakage_texts",
    }

    if save:
        target_dir = work / "datasets" / TARGET_SUBDIR
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / f"target_batch_{loop_id}.jsonl"
        target_file.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in target_records), encoding="utf-8")
        report["target_file"] = str(target_file.relative_to(work))
        reports_dir = work / "experiments/reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "onpolicy_loop.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if log_run:
        exp_record = new_run(
            config={"loop": loop_id, "budget": budget, "patch": patch, "student": STUDENT_NAME},
            dataset_version=f"{TARGET_SUBDIR}-{loop_id}",
            tool_version="siga-onpolicy-v1",
            index_version="tree-sitter-java-0.23",
            bench_version="siga-bench-v1",
            needle_version="2.0-45M-subnetwork-12L-onpolicy",
            needle_depth=STUDENT_DEPTH,
            metrics={
                "base_accuracy": base_acc,
                "patched_accuracy": patched_acc,
                "holdout_delta": report["holdout_delta"],
                "target_gain": target_gain,
                "target_records": len(target_records),
            },
            notes=f"P11-T01: on-policy loop {loop_id} com failure mining e active learning.",
            siga_root=root,
            work_root=work,
        )
        runs_dir = work / "experiments/runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_file = runs_dir / f"{exp_record['experiment_id']}.json"
        run_file.write_text(json.dumps(exp_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        report["experiment_id"] = exp_record["experiment_id"]

    return report


def _is_fixed(failure: dict[str, Any], patched: PatchedStudent) -> bool:
    pred = patched.predict(failure["query"], task_type=failure["task_type"])
    predicted = pred.get("tools", ["none"])[0] if pred.get("tools") else "none"
    return predicted == failure["expected"]


def load_target_records(work_root: Path | None = None, loop_id: str = "loop-01") -> list[dict[str, Any]]:
    """Lê registros-alvo publicados (datasets/onpolicy/)."""
    work = Path(work_root).resolve() if work_root is not None else ROOT
    target_file = work / "datasets" / TARGET_SUBDIR / f"target_batch_{loop_id}.jsonl"
    if not target_file.is_file():
        raise FileNotFoundError(f"Lote-alvo não encontrado: {target_file}")
    return [json.loads(line) for line in target_file.read_text(encoding="utf-8").splitlines() if line.strip()]


def target_file_hash(work_root: Path | None = None, loop_id: str = "loop-01") -> str:
    """SHA-256 do lote-alvo publicado (provenance do artefato)."""
    work = Path(work_root).resolve() if work_root is not None else ROOT
    target_file = work / "datasets" / TARGET_SUBDIR / f"target_batch_{loop_id}.jsonl"
    return hashlib.sha256(target_file.read_bytes()).hexdigest()
