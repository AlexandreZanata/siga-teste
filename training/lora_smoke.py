"""Smoke LoRA N=100 na RTX 4060 — P13-T04 (docs/21 §6 R1, docs/22 §7).

Treino REAL via CLI oficial `needle finetune` (cactus-needle pinado na venv
`data/venvs/needle3-cu12`, backend JAX `gpu`), um processo novo por tentativa
de batch (1→2→4→8→16), seed 0, 1 época, rank 16 / alpha 32 / lr 1e-4 /
max_len 256 / val_split 0.1 — defaults oficiais, sem tuning (docs/22 §7.1).

Regras inegociáveis desta fase (docs/21 §3.2, docs/22 §2/§6.1):
- GPU obrigatória: `nvidia-smi` + `jax.devices()` devem provar a RTX 4060
  antes de qualquer treino; sem GPU registra BLOCKED e para. Fallback para
  CPU é proibido em qualquer forma (não existe `cpu_smoke`).
- Pesos reais somente: `evaluation.NeedleTunedModel` é simulador e nunca
  produz métrica desta fase.
- Telemetria GPU amostrada 1/s; GPU ociosa sustentada, timeout, OOM ou NaN
  invalidam a tentativa (docs/22 §6.1).
- Pesos/adapters/.cact/logs brutos ficam em `data/` (ignorado pelo Git);
  só hashes, configs e métricas seguem para relatórios/runs commitáveis.
- Sem rede externa de treino: `--generate` nunca é usado (quota/upload
  proibidos sem autorização); `HF_HUB_OFFLINE=1` por padrão.

Uso: `python -m training.lora_smoke` (requer venv pinada e GPU liberada).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / "data/venvs/needle3-cu12"
CHECKPOINT = ROOT / "data/needle-real/checkpoints/needle3.safetensors"
TRAIN_EXPORT = ROOT / "datasets/needle_export/needle_train.jsonl"
TRAIN100 = ROOT / "data/needle-real/v1/train-100.jsonl"
RUN_DIR = ROOT / "data/needle-real/runs/P13-T04"

BATCH_CANDIDATES = (1, 2, 4, 8, 16)
LORA_RANK = 16
LORA_ALPHA = 32
LEARNING_RATE = "1e-4"
MAX_LEN = 256
EPOCHS = 1
SEED = 0
VAL_SPLIT = "0.1"
MIN_OFFTOPIC_FRACTION = 1 / 8  # docs/21 §5.1

GPU_IDLE_ABORT_SAMPLES = 90  # 90 s consecutivos com GPU ociosa abortam (docs/22 §6.1)
MAX_ATTEMPT_SECONDS = 3600

LOSS_RE = re.compile(r"(?i)\b(?:val[_ ]?)?loss\b[^0-9\n]{0,40}?([0-9]+\.[0-9]+)")
BAD_NUM_RE = re.compile(r"(?i)\b(nan|inf|infinity)\b")
OOM_RE = re.compile(r"(?i)(out of memory|resource_exhausted|\boom\b)")


def sha256_of(path: Path) -> str:
    """SHA-256 hex de um arquivo (leitura em blocos, pesos podem ter centenas de MB)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gpu_preflight(
    venv_python: Path | None = None, run=subprocess.run
) -> dict[str, str]:
    """Prova a RTX 4060 antes de qualquer treino (docs/21 §3.2, docs/22 §4.1).

    Levanta RuntimeError (BLOCKED) se `nvidia-smi` não listar a RTX 4060 ou se
    o JAX da venv pinada não reportar backend `gpu` com CudaDevice — fallback
    para CPU é proibido em qualquer forma.
    """
    venv_python = venv_python or (VENV / "bin/python")
    blocked = "BLOCKED: sem GPU provada não há run — CPU é proibida (docs/21 §3.2); diagnóstico: {0}"

    try:
        listing = run(
            ["nvidia-smi", "-L"], capture_output=True, text=True, timeout=30, check=True
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(blocked.format(f"nvidia-smi indisponível ({exc})")) from exc
    first_gpu = listing.splitlines()[0].strip() if listing.strip() else ""
    if "4060" not in first_gpu:
        raise RuntimeError(blocked.format(f"RTX 4060 não listada por nvidia-smi -L: {first_gpu!r}"))

    try:
        queried = run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,uuid,driver_version,memory.total,memory.free,temperature.gpu",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(blocked.format(f"nvidia-smi query falhou ({exc})")) from exc
    fields = [f.strip() for f in queried.splitlines()[0].split(",")]
    name, uuid, driver, mem_total, mem_free, temperature = fields[1], fields[2], fields[3], fields[4], fields[5], fields[6]

    probe_cmd = "import jax; print(jax.__version__); print(jax.default_backend()); print(jax.devices())"
    try:
        probe = run(
            [str(venv_python), "-c", probe_cmd],
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
            env={**os.environ, "CUDA_VISIBLE_DEVICES": "0"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(blocked.format(f"jax probe falhou ({exc})")) from exc
    lines = [ln for ln in probe.stdout.strip().splitlines() if ln.strip()]
    if len(lines) < 3:
        raise RuntimeError(blocked.format(f"jax probe sem saída esperada: {probe.stdout!r}"))
    jax_version, backend, devices = (lines[0].strip(), lines[1].strip(), "; ".join(ln.strip() for ln in lines[2:]))
    if backend != "gpu" or "CudaDevice" not in devices:
        raise RuntimeError(
            blocked.format(f"jax backend={backend!r} devices={devices!r} — backend gpu obrigatório")
        )
    return {
        "gpu": name,
        "uuid": uuid,
        "driver": driver,
        "memory_total_mib": mem_total,
        "memory_free_mib": mem_free,
        "temperature_gpu_c": temperature,
        "jax_version": jax_version,
        "jax_backend": backend,
        "jax_devices": devices,
        "cuda_visible_devices": "0",
    }


def build_train100(
    source: Path = TRAIN_EXPORT, out: Path = TRAIN100, seed: int = SEED
) -> dict[str, object]:
    """Deriva `train-100.jsonl` determinístico do export de treino (docs/22 §7).

    Seleção estratificada por seed fixa: 13 off-topic (garante ≥ 1/8, docs/21
    §5.1) + 87 com-tool, embaralhados com `random.Random(seed)`. Cada linha
    preserva o registro original verbatim (json equivalente ao do export).
    """
    records = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(records) < 100:
        raise RuntimeError(
            f"BLOCKED: export de treino tem {len(records)} registros (< 100) — "
            "nunca truncar silenciosamente o N do smoke (docs/22 §7)."
        )
    offtopic = [r for r in records if not r.get("answers")]
    with_tool = [r for r in records if r.get("answers")]
    rng = random.Random(seed)
    rng.shuffle(offtopic)
    rng.shuffle(with_tool)
    n_offtopic = math.ceil(len(records[:100]) * MIN_OFFTOPIC_FRACTION)
    picked = offtopic[:n_offtopic] + with_tool[: 100 - n_offtopic]
    rng.shuffle(picked)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for rec in picked:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {
        "path": str(out),
        "records": len(picked),
        "offtopic": n_offtopic,
        "sha256": sha256_of(out),
        "seed": seed,
    }


def finetune_command(
    venv_bin: Path,
    dataset: Path,
    adapter_out: Path,
    batch_size: int,
    epochs: int = EPOCHS,
    seed: int = SEED,
) -> tuple[list[str], dict[str, str]]:
    """Comando exato do docs/22 §7.1 (argumentos confirmados no CLI 3.0.4).

    `CUDA_VISIBLE_DEVICES=0` é obrigatório; `HF_HUB_OFFLINE=1` garante
    execução offline (sem quota/upload); `--generate` nunca é usado.
    """
    cmd = [
        str(venv_bin / "needle"),
        "finetune",
        str(dataset),
        "--checkpoint",
        str(CHECKPOINT),
        "--epochs",
        str(epochs),
        "--batch-size",
        str(batch_size),
        "--max-len",
        str(MAX_LEN),
        "--lora-rank",
        str(LORA_RANK),
        "--lora-alpha",
        str(LORA_ALPHA),
        "--lr",
        LEARNING_RATE,
        "--val-split",
        VAL_SPLIT,
        "--seed",
        str(seed),
        "--out",
        str(adapter_out),
    ]
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "0", "HF_HUB_OFFLINE": "1"}
    return cmd, env


BUILD_RUNNER = '''"""Runner offline do export `.cact` (P13-T04).

Usa o `build_main` OFICIAL do pacote pinado (merge LoRA, rung de camadas,
write_export W4A8) substituindo apenas o re-download forçado do arquivo base
publicado pelo arquivo já baixado/verificado em P13-T01 (docs/21 §4:
download uma vez, depois offline; docs/22 §2: sem envio/quota externa).
O CLI `needle build` não é usado aqui porque chama
`fetch_weights(3, force=True)`, que exige rede a cada build.
"""
import argparse
import sys

from needle.agent import fetch
from needle.model.finetune import build_main

base_archive, checkpoint, adapter, out, layers = sys.argv[1:6]
fetch.fetch_weights = lambda *a, **k: base_archive
build_main(
    argparse.Namespace(
        lora=adapter,
        layers=int(layers),
        out=out,
        platform=None,
        checkpoint=checkpoint,
        upload=False,
    )
)
'''


def export_tuned(
    venv_python: Path,
    adapter: Path,
    out_cact: Path,
    layers: int = 20,
    base_archive: Path | None = None,
) -> Path:
    """Exporta `tuned-20L.cact` offline via build oficial + arquivo base local."""
    base_archive = base_archive or (ROOT / "data/needle-real/checkpoints/needle3.cact")
    if not base_archive.exists():
        raise RuntimeError(
            f"BLOCKED: arquivo base publicado ausente ({base_archive}) — baixe uma vez "
            "com autorização antes do export offline (docs/21 §4)."
        )
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    runner = RUN_DIR / "_build_tuned_offline.py"
    runner.write_text(BUILD_RUNNER, encoding="utf-8")
    cmd = [
        str(venv_python),
        str(runner),
        str(base_archive),
        str(CHECKPOINT),
        str(adapter),
        str(out_cact),
        str(layers),
    ]
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "0", "HF_HUB_OFFLINE": "1"}
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=1800)
    (RUN_DIR / "build_tuned.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0 or not out_cact.exists() or out_cact.stat().st_size == 0:
        raise RuntimeError(
            f"BLOCKED: export .cact falhou (rc={proc.returncode}); log: {(RUN_DIR / 'build_tuned.log')}"
        )
    return out_cact


class GpuTelemetry(threading.Thread):
    """Amostra `nvidia-smi` 1/s em CSV e detecta GPU ociosa sustentada (docs/22 §6.1)."""

    def __init__(self, csv_path: Path) -> None:
        super().__init__(daemon=True)
        self.csv_path = csv_path
        self._stop_event = threading.Event()
        self.peak_vram_mib = 0
        self.peak_util_pct = 0
        self.peak_temp_c = 0
        self.idle_streak = 0
        self.gpu_idle_sustained = False

    def run(self) -> None:
        with self.csv_path.open("w", encoding="utf-8") as fh:
            fh.write("ts,util_pct,vram_mib,temp_c\n")
            fh.flush()
            while not self._stop_event.is_set():
                try:
                    out = subprocess.run(
                        [
                            "nvidia-smi",
                            "--query-gpu=utilization.gpu,memory.used,temperature.gpu",
                            "--format=csv,noheader,nounits",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    ).stdout
                    util, vram, temp = (int(f.strip()) for f in out.splitlines()[0].split(","))
                except (OSError, subprocess.SubprocessError, ValueError, IndexError):
                    util, vram, temp = -1, -1, -1
                fh.write(f"{int(time.time())},{util},{vram},{temp}\n")
                fh.flush()
                self.peak_vram_mib = max(self.peak_vram_mib, max(vram, 0))
                self.peak_util_pct = max(self.peak_util_pct, max(util, 0))
                self.peak_temp_c = max(self.peak_temp_c, max(temp, 0))
                # GPU ociosa = 0% util E quase nenhuma VRAM alocada (contexto carregado
                # mostra VRAM > 200 MiB mesmo antes dos kernels).
                if util == 0 and 0 <= vram < 200:
                    self.idle_streak += 1
                    if self.idle_streak >= GPU_IDLE_ABORT_SAMPLES:
                        self.gpu_idle_sustained = True
                else:
                    self.idle_streak = 0
                self._stop_event.wait(1.0)

    def stop(self) -> None:
        self._stop_event.set()


def run_finetune_attempt(
    venv_bin: Path,
    dataset: Path,
    adapter_out: Path,
    batch_size: int,
    log_path: Path,
    telemetry_csv: Path,
    epochs: int = EPOCHS,
    seed: int = SEED,
    offline: bool = True,
    runner=subprocess.Popen,
) -> dict[str, object]:
    """Uma tentativa de treino em processo novo com limites do docs/22 §6.1.

    Nunca transforma OOM/timeout/GPU-ociosa em sucesso: o status reflete o
    desfecho real e a decisão de batch usa apenas tentativas `ok`.
    """
    cmd, env = finetune_command(venv_bin, dataset, adapter_out, batch_size, epochs, seed)
    if not offline:
        env = {**env, "HF_HUB_OFFLINE": "0"}
    adapter_out.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log_fh:
        proc = runner(cmd, stdout=log_fh, stderr=subprocess.STDOUT, env=env, cwd=str(ROOT))
        telemetry = GpuTelemetry(telemetry_csv)
        telemetry.start()
        deadline = started + MAX_ATTEMPT_SECONDS
        timed_out = False
        idle_aborted = False
        while proc.poll() is None:
            if telemetry.gpu_idle_sustained:
                proc.terminate()
                idle_aborted = True
                break
            if time.monotonic() > deadline:
                proc.terminate()
                timed_out = True
                break
            time.sleep(1.0)
        rc = proc.wait()
        telemetry.stop()
        telemetry.join(timeout=10)
    elapsed = time.monotonic() - started
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    losses = [float(v) for v in LOSS_RE.findall(log_text)]
    finite_losses = [v for v in losses if math.isfinite(v)]
    has_bad_number = bool(BAD_NUM_RE.search(log_text))
    oom = rc != 0 and bool(OOM_RE.search(log_text))
    adapter_ok = adapter_out.exists() and adapter_out.stat().st_size > 0
    if rc == 0 and adapter_ok and finite_losses and not has_bad_number:
        status = "ok"
    elif oom:
        status = "oom"
    elif timed_out:
        status = "timeout"
    elif idle_aborted:
        status = "gpu_idle"
    else:
        status = "error"
    return {
        "batch_size": batch_size,
        "status": status,
        "returncode": rc,
        "losses_seen": losses[:8],
        "final_loss": finite_losses[-1] if finite_losses else None,
        "elapsed_s": round(elapsed, 1),
        "peak_vram_mib": telemetry.peak_vram_mib,
        "peak_util_pct": telemetry.peak_util_pct,
        "peak_temp_c": telemetry.peak_temp_c,
        "adapter": str(adapter_out),
        "log": str(log_path),
        "offline": offline,
    }


def decide_best_batch(attempts: list[dict[str, object]]) -> int:
    """Maior batch `ok` antes da primeira falha (docs/21 §6 R1: parar no maior
    batch sem OOM; não transformar OOM em sucesso)."""
    best = None
    for attempt in attempts:
        if attempt["status"] == "ok":
            best = int(attempt["batch_size"])  # type: ignore[arg-type]
        else:
            break
    if best is None:
        raise RuntimeError(
            "BLOCKED: nenhuma tentativa de batch concluiu sem erro — não há adapter smoke "
            "(docs/22 §2: falha obrigatória registra BLOCKED, nunca sucesso fabricado)."
        )
    return best


def batch_search(
    venv_bin: Path,
    dataset: Path,
    run_dir: Path,
    candidates: tuple[int, ...] = BATCH_CANDIDATES,
    epochs: int = EPOCHS,
    seed: int = SEED,
) -> dict[str, object]:
    """Busca de capacidade de batch em processos novos, com flush por tentativa."""
    attempts: list[dict[str, object]] = []
    for bs in candidates:
        adapter = run_dir / f"_probe_bs{bs}.safetensors"
        result = run_finetune_attempt(
            venv_bin,
            dataset,
            adapter,
            bs,
            run_dir / f"finetune_bs{bs}.log",
            run_dir / f"telemetry_bs{bs}.csv",
            epochs=epochs,
            seed=seed,
        )
        attempts.append(result)
        print(
            f"[batch {bs}] status={result['status']} loss={result['final_loss']} "
            f"{result['elapsed_s']}s peak_vram={result['peak_vram_mib']}MiB",
            flush=True,
        )
        snapshot = {
            "attempts": attempts,
            "seed": seed,
            "epochs": epochs,
            "dataset_sha256": sha256_of(dataset),
            "checkpoint_sha256": sha256_of(CHECKPOINT),
        }
        (run_dir / "batch_probe.json").write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        if result["status"] != "ok":
            break
    best = decide_best_batch(attempts)
    return {**snapshot, "best_batch_size": best}  # type: ignore[name-defined]


def main() -> int:
    started = time.monotonic()
    preflight = gpu_preflight()
    print("[preflight] " + json.dumps(preflight, ensure_ascii=False), flush=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    data_info = build_train100()
    print(f"[data] train-100: {data_info}", flush=True)

    search = batch_search(VENV / "bin", TRAIN100, RUN_DIR)
    best = int(search["best_batch_size"])  # type: ignore[arg-type]

    # O adapter vencedor da busca já é o treino smoke final (mesmo comando,
    # mesma seed/dataset/config — só muda o caminho de saída): copiado para o
    # caminho canônico do runbook em vez de re-treinar.
    adapter = RUN_DIR / "adapter.safetensors"
    winner = Path(str(next(a for a in search["attempts"] if int(a["batch_size"]) == best)["adapter"]))  # type: ignore[index,union-attr]
    if adapter.resolve() != winner.resolve():
        adapter.write_bytes(winner.read_bytes())
    print(f"[adapter] {adapter} sha256={sha256_of(adapter)}", flush=True)

    cact = export_tuned(VENV / "bin/python", adapter, RUN_DIR / "tuned-20L.cact", layers=20)
    print(f"[export] {cact} sha256={sha256_of(cact)}", flush=True)

    summary = {
        "task": "P13-T04",
        "preflight": preflight,
        "dataset": data_info,
        "checkpoint_sha256": sha256_of(CHECKPOINT),
        "config": {
            "epochs": EPOCHS,
            "seed": SEED,
            "max_len": MAX_LEN,
            "lora_rank": LORA_RANK,
            "lora_alpha": LORA_ALPHA,
            "lr": LEARNING_RATE,
            "val_split": VAL_SPLIT,
        },
        "batch_search": search,
        "adapter_sha256": sha256_of(adapter),
        "tuned_cact_sha256": sha256_of(cact),
        "elapsed_total_s": round(time.monotonic() - started, 1),
    }
    (RUN_DIR / "train_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("[done] " + json.dumps({k: summary[k] for k in ("adapter_sha256", "tuned_cact_sha256")}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
