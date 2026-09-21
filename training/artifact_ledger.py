"""Consolidação dos artefatos reais do Needle já produzidos (P13-T04, docs/24 §4).

Nenhuma época nova. O módulo apenas:

1. recalcula e verifica SHA-256 de datasets, adapters, exports e checkpoint
   base já produzidos;
2. classifica explicitamente cada artefato: `smoke` (N=100) ou `candidate`
   (candidato real de 350 registros/3 épocas, nome histórico `smoke_adapter`);
3. registra o batch seguro comprovado e a chave de cache da configuração
   (`checkpoint + max_len + rank + dtype`, docs/22 §8);
4. opcionalmente carrega **offline** os exports candidatos 20L/12L e executa
   4 casos estruturais em cada um com o harness B1 corrigido do P13-T03
   (`--check-loads` — gate do P13-T04).

Pesos, checkpoints e logs brutos permanecem locais/ignorados; o relatório
versionado é `experiments/reports/real_needle_artifacts.json`.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import time
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent

SMOKE = "smoke"
CANDIDATE = "candidate"
BASE = "base"

# Fonte única de verdade dos artefatos já produzidos (auditados em 2026-09-21).
# `expected_sha256` é o carimbo; divergência é falha, nunca aviso.
ARTIFACT_SPEC: tuple[dict[str, Any], ...] = (
    {
        "role": "dataset",
        "classification": SMOKE,
        "path": "data/needle-real/v1/train-100.jsonl",
        "expected_sha256": "bd2e2aa75e269ca38d7c722996dc86b1b5a7085e6e55b4bbc6360fde839d0ae2",
        "records": 100,
    },
    {
        "role": "adapter",
        "classification": SMOKE,
        "path": "data/needle-real/runs/P13-T04/adapter.safetensors",
        "expected_sha256": "57dd537aaf5c2f1090b5e95113e7c935326047be744c178e7b483967386efacc",
        "trained_from": "data/needle-real/v1/train-100.jsonl",
        "epochs": 1,
    },
    {
        "role": "export",
        "classification": SMOKE,
        "path": "data/needle-real/runs/P13-T04/tuned-20L.cact",
        "expected_sha256": "b41ced7695d63d1fb5336901cf5e4c2af0a37e5816795c561460b3ccfdb65b26",
        "layers": 20,
    },
    {
        "role": "dataset",
        "classification": CANDIDATE,
        "path": "datasets/needle_export/needle_train.jsonl",
        "expected_sha256": "f8b988ef9c5fa182d13202718b183662db4cfcbdc305acecc28eba20ae77871d",
        "records": 350,
    },
    {
        "role": "adapter",
        "classification": CANDIDATE,
        "path": "data/needle-real/adapters/smoke_adapter.safetensors",
        "expected_sha256": "94ee8bbcbd6db5969db5c4d030ee27be8c27a207af18eae4ff93875afcbcbc28",
        "trained_from": "datasets/needle_export/needle_train.jsonl",
        "epochs": 3,
        "historical_note": (
            "nome histórico 'smoke_adapter'; evidência P13-T01 = 350 exemplos/3 épocas "
            "(candidato real), não smoke"
        ),
    },
    {
        "role": "export",
        "classification": CANDIDATE,
        "path": "data/needle-real/exports/tuned-20L.cact",
        "expected_sha256": "69a506dce529cd83f7a272eb6daa2cf1651056062f20cf96dc6eaf9b6e314d05",
        "layers": 20,
    },
    {
        "role": "export",
        "classification": CANDIDATE,
        "path": "data/needle-real/exports/tuned-12L.cact",
        "expected_sha256": "943fb74f044dbd3618c0fe2792fe9dd8d9ac5e4b7f539d181fabd86911bbcce4",
        "layers": 12,
    },
    {
        "role": "base_checkpoint",
        "classification": BASE,
        "path": "data/needle-real/checkpoints/needle3.safetensors",
        "expected_sha256": "c234c70dccc7a9115e7c41ac2e41d3655fea3b85c245dd898b46179fb90c6c0c",
    },
    {
        "role": "base_archive",
        "classification": BASE,
        "path": "data/needle-real/checkpoints/needle3.cact",
        "expected_sha256": "c9d915eca282ed42d1a09b143b592adb4cc6744ffe2d294adf5cfc5548170c38",
    },
)

DEFAULT_TRAIN_SUMMARY = "data/needle-real/runs/P13-T04/train_summary.json"
DEFAULT_REPORT = "experiments/reports/real_needle_artifacts.json"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cache_key(checkpoint_sha256: str, max_len: int, rank: int, scheme: str) -> str:
    """Chave determinística de cache do treino (docs/22 §8): checkpoint+len+rank+dtype."""
    return f"checkpoint={checkpoint_sha256}|max_len={int(max_len)}|rank={int(rank)}|scheme={scheme}"


def read_batch_evidence(train_summary: str | Path) -> dict[str, Any]:
    """Lê o probe de batch real e devolve o batch seguro comprovado.

    Fail-closed: sem `best_batch_size` com status `ok`, levanta ValueError —
    o ledger nunca inventa batch.
    """
    data = json.loads(Path(train_summary).read_text(encoding="utf-8"))
    search = data.get("batch_search") or {}
    attempts = list(search.get("attempts") or [])
    best = search.get("best_batch_size")
    if not attempts or not best:
        raise ValueError(f"batch probe incompleto em {train_summary}: sem best_batch_size")
    safe = [attempt for attempt in attempts if attempt.get("status") == "ok"]
    if not safe or int(best) != max(int(attempt["batch_size"]) for attempt in safe):
        raise ValueError(
            f"batch seguro inválido em {train_summary}: best={best} ok={[a.get('batch_size') for a in safe]}"
        )
    config = data.get("config") or {}
    dataset = data.get("dataset") or {}
    return {
        "best_batch_size": int(best),
        "attempts": [
            {
                "batch_size": attempt.get("batch_size"),
                "status": attempt.get("status"),
                "elapsed_s": attempt.get("elapsed_s"),
                "peak_vram_mib": attempt.get("peak_vram_mib"),
            }
            for attempt in attempts
        ],
        "dataset": dataset.get("path"),
        "dataset_sha256": dataset.get("sha256"),
        "checkpoint_sha256": data.get("checkpoint_sha256"),
        "config": config,
        "cache_key": cache_key(
            data.get("checkpoint_sha256") or "",
            config.get("max_len") or 0,
            config.get("lora_rank") or 0,
            "W4STE_A8",
        ),
        "source": str(train_summary),
    }


def build_ledger(
    root: str | Path = ROOT,
    spec: tuple[dict[str, Any], ...] | list[dict[str, Any]] = ARTIFACT_SPEC,
    train_summary: str | Path = DEFAULT_TRAIN_SUMMARY,
) -> dict[str, Any]:
    """Verifica hashes e classifica smoke/candidato/base sem treinar nada."""
    root = Path(root)
    artifacts: list[dict[str, Any]] = []
    for item in spec:
        entry = dict(item)
        path = root / item["path"]
        entry["present"] = path.is_file()
        entry["sha256"] = sha256_file(path) if entry["present"] else None
        entry["verified"] = entry["sha256"] == item["expected_sha256"]
        artifacts.append(entry)
    by_class: dict[str, list[str]] = {}
    for entry in artifacts:
        by_class.setdefault(entry["classification"], []).append(entry["path"])
    try:
        batch = read_batch_evidence(root / train_summary)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        batch = {"error": str(exc)}
    return {
        "artifacts": artifacts,
        "classifications": by_class,
        "counts": {name: len(paths) for name, paths in by_class.items()},
        "all_verified": all(entry["verified"] for entry in artifacts),
        "missing": [entry["path"] for entry in artifacts if not entry["present"]],
        "batch": batch,
    }


def _default_runner(
    artifact: dict[str, Any],
    stage: int,
    seed: int,
    timeout_s: float,
    budget_s: float,
    checkpoint: Path,
) -> dict[str, Any]:
    """Carrega o `.cact` real offline e roda o funil B1 estrutural do P13-T03."""
    from evaluation import real_needle_eval as harness
    from inference.needle_real import RealNeedleModel

    schemas = json.loads((ROOT / "inference/siga_tools_schema.json").read_text(encoding="utf-8"))
    tasks = harness.load_validation_tasks(stage=stage, seed=seed)
    start = time.perf_counter()
    model = RealNeedleModel(
        weights_path=ROOT / artifact["path"], tools=schemas, task_timeout_s=timeout_s
    )
    try:
        result = harness.run_b1(
            model,
            tasks,
            checkpoint=checkpoint,
            resume=False,
            max_new_tokens=128,
            escalate_to=256,
            budget_s=budget_s,
            progress=True,
        )
    finally:
        model.close()
    return {
        "loaded": True,
        "weights_sha256": artifact["expected_sha256"],
        "status": result["status"],
        "metrics": harness.summarize_b1(result["predictions"]),
        "elapsed_s": round(time.perf_counter() - start, 2),
        "checkpoint": str(checkpoint),
    }


def structural_check(
    ledger: dict[str, Any],
    *,
    stage: int = 4,
    seed: int = 0,
    timeout_s: float = 120.0,
    budget_s: float = 120.0,
    checkpoint_dir: str | Path = ROOT / "data/needle-real/runs/P13-T04",
    runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Carrega offline os exports candidatos e roda 4 casos estruturais em cada.

    `HF_HUB_OFFLINE=1` é imposto durante os carregamentos e restaurado depois;
    nenhum download é permitido. Falha de um artefato vira `loaded=false` com
    erro registrado (fail-closed), nunca sucesso parcial silencioso.
    """
    runner = runner or _default_runner
    checkpoint_dir = Path(checkpoint_dir)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    exports = [
        entry
        for entry in ledger["artifacts"]
        if entry["role"] == "export" and entry["classification"] == CANDIDATE and entry["present"]
    ]
    previous = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    results: list[dict[str, Any]] = []
    try:
        for artifact in exports:
            checkpoint = checkpoint_dir / f"consolidate-{artifact['layers']}L.partial.jsonl"
            try:
                outcome = runner(artifact, stage, seed, timeout_s, budget_s, checkpoint)
            except Exception as exc:  # artefato que não carrega/executa nunca é sucesso
                outcome = {"loaded": False, "error": f"{type(exc).__name__}: {exc}"}
            results.append({"path": artifact["path"], "layers": artifact["layers"], **outcome})
    finally:
        if previous is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = previous
    return {
        "stage": stage,
        "seed": seed,
        "timeout_s": timeout_s,
        "budget_s": budget_s,
        "offline_enforced": True,
        "artifacts": results,
        "all_loaded": bool(results) and all(result.get("loaded") for result in results),
    }


def engine_version() -> str | None:
    try:
        return f"cactus-needle {importlib.metadata.version('cactus-needle')}"
    except importlib.metadata.PackageNotFoundError:
        return None


def _rel(root: Path, path: str | Path | None) -> str | None:
    if path is None:
        return None
    candidate = Path(path)
    try:
        return str(candidate.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(candidate)


def _rel_if_absolute(root: Path, value: Any) -> Any:
    """Relativiza apenas paths absolutos (relativos são preservados como estão)."""
    if isinstance(value, str) and Path(value).is_absolute():
        return _rel(root, value)
    return value


def build_report(
    ledger: dict[str, Any],
    structural: dict[str, Any] | None,
    root: str | Path = ROOT,
) -> dict[str, Any]:
    root_path = Path(root)
    artifacts = []
    for entry in ledger["artifacts"]:
        record = {key: value for key, value in entry.items() if key != "trained_from"}
        artifacts.append(record)
    if structural is not None:
        structural = json.loads(json.dumps(structural))  # cópia profunda simples
        for result in structural["artifacts"]:
            if result.get("checkpoint"):
                result["checkpoint"] = _rel(root_path, result["checkpoint"])
    batch = {key: value for key, value in (ledger["batch"] or {}).items() if key != "source"}
    batch["dataset"] = _rel_if_absolute(root_path, batch.get("dataset"))
    return {
        "task": "P13-T04",
        "scope": "consolidação de artefatos existentes; nenhuma época nova",
        "classifications": ledger["classifications"],
        "counts": ledger["counts"],
        "all_verified": ledger["all_verified"],
        "missing": ledger["missing"],
        "artifacts": artifacts,
        "batch": batch,
        "structural": structural,
        "engine": engine_version(),
        "offline": (structural or {}).get("offline_enforced"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ledger de artefatos reais do Needle (P13-T04)")
    parser.add_argument("--report", default=str(ROOT / DEFAULT_REPORT))
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--train-summary", default=str(ROOT / DEFAULT_TRAIN_SUMMARY))
    parser.add_argument(
        "--check-loads",
        action="store_true",
        help="carrega offline os exports candidatos 20L/12L e roda 4 casos estruturais",
    )
    parser.add_argument("--stage", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--budget-s", type=float, default=120.0)
    parser.add_argument("--no-log-run", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root)
    ledger = build_ledger(root=root, train_summary=args.train_summary)
    structural = None
    if args.check_loads:
        structural = structural_check(
            ledger,
            stage=args.stage,
            seed=args.seed,
            timeout_s=args.timeout_s,
            budget_s=args.budget_s,
        )
    report = build_report(ledger, structural, root=root)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"[P13-T04] verificados={report['all_verified']} "
        f"estrutural={'ok' if (structural or {}).get('all_loaded') else 'n/a'} -> {report_path}",
        flush=True,
    )

    if structural and structural["all_loaded"] and not args.no_log_run:
        from experiments import log as exp_log

        latencies = [
            float(result["metrics"]["latency_ms"]["p50"] or 0.0)
            for result in structural["artifacts"]
            if result.get("loaded")
        ]
        candidate_20l = next(
            (
                entry
                for entry in ledger["artifacts"]
                if entry["path"].endswith("exports/tuned-20L.cact")
            ),
            None,
        )
        run = exp_log.new_run(
            config={
                "task": "P13-T04",
                "stage": structural["stage"],
                "seed": structural["seed"],
                "cache_key": (ledger["batch"] or {}).get("cache_key"),
                "safe_batch_size": (ledger["batch"] or {}).get("best_batch_size"),
            },
            dataset_version="needle_export-v1 + benchmark_v2 (validação temporal)",
            tool_version="inference/siga_tools_schema.json",
            index_version="not-used-loads",
            bench_version="needle_val-temporal",
            metrics={
                "artifacts_verified": int(report["all_verified"]),
                "exports_loaded": sum(1 for r in structural["artifacts"] if r.get("loaded")),
            },
            latency={
                "p50_ms": (sum(latencies) / len(latencies)) if latencies else 0.0,
                "p95_ms": max(latencies) if latencies else None,
            },
            needle_version=engine_version(),
            needle_depth=None,
            artifact_hash=candidate_20l["sha256"] if candidate_20l else None,
            siga_root=ROOT.parent,
            work_root=ROOT,
            notes="P13-T04: consolidação + carregamento offline 20L/12L; nenhuma época nova",
        )
        exp_log.save(run, ROOT / f"experiments/runs/{run['experiment_id']}.json")
        print(f"[P13-T04] run {run['experiment_id']} registrado", flush=True)

    ok = report["all_verified"] and (structural is None or structural["all_loaded"])
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
