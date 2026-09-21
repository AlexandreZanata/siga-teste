"""Testes do smoke LoRA N=100 — P13-T04 (docs/21 §6 R1, docs/22 §7).

Herméticos e rápidos: nenhum teste executa treino real, engine nativa ou GPU.
A prova de GPU (preflight com subprocessos reais) acontece apenas no run,
não na suíte unitária.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from training import lora_smoke


def _fake_export(tmp_path: Path, n_tool: int = 87, n_off: int = 13) -> Path:
    """Export mínimo no formato cactus-needle-v2 (query/tools/answers/reasoning)."""
    path = tmp_path / "needle_train.jsonl"
    tools = [{"type": "function", "function": {"name": "siga_locate", "parameters": {}}}]
    with path.open("w", encoding="utf-8") as fh:
        for i in range(n_tool):
            fh.write(
                json.dumps(
                    {
                        "query": f"Localize ClasseExemplo{i}",
                        "tools": tools,
                        "answers": [{"name": "siga_locate", "arguments": {"query": f"ClasseExemplo{i}"}}],
                        "reasoning": "nome literal na consulta",
                    }
                )
                + "\n"
            )
        for i in range(n_off):
            fh.write(
                json.dumps(
                    {
                        "query": f"Off-topic {i} pergunta genérica",
                        "tools": tools,
                        "answers": [],
                        "reasoning": "fora do escopo SIGA",
                    }
                )
                + "\n"
            )
    return path


def test_build_train100_deterministic_and_stratified(tmp_path):
    source = _fake_export(tmp_path, n_tool=87, n_off=13)
    out_a = tmp_path / "a.jsonl"
    out_b = tmp_path / "b.jsonl"
    info = lora_smoke.build_train100(source, out_a)
    lora_smoke.build_train100(source, out_b)
    assert info["records"] == 100
    assert info["offtopic"] >= 13  # ceil(100/8) = 13 garante >= 1/8
    assert out_a.read_bytes() == out_b.read_bytes()  # determinismo por seed
    records = [json.loads(ln) for ln in out_a.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert all(r.get("answers") is not None for r in records)
    n_off = sum(1 for r in records if not r["answers"])
    assert n_off / 100 >= 1 / 8


def test_build_train100_raises_when_source_short(tmp_path):
    source = _fake_export(tmp_path, n_tool=50, n_off=10)
    with pytest.raises(RuntimeError) as excinfo:
        lora_smoke.build_train100(source, tmp_path / "x.jsonl")
    assert "BLOCKED" in str(excinfo.value)


def test_gpu_preflight_blocks_without_nvidia_smi():
    def fail_run(*args, **kwargs):
        raise FileNotFoundError("nvidia-smi não encontrado")

    with pytest.raises(RuntimeError) as excinfo:
        lora_smoke.gpu_preflight(run=fail_run)
    assert "BLOCKED" in str(excinfo.value)


def test_gpu_preflight_blocks_on_wrong_gpu():
    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        result = Result()
        if "nvidia-smi" in cmd and "-L" in cmd:
            result.stdout = "GPU 0: NVIDIA T4 (UUID: GPU-xxx)\n"
        elif "nvidia-smi" in cmd:
            result.stdout = "0, NVIDIA T4, GPU-xxx, 580.1, 16384, 15000, 40"
        elif str(kwargs.get("env", {})).find("CUDA") >= 0 or cmd[0].endswith("python"):
            result.stdout = "0.11.2\ncpu\n[CpuDevice(id=0)]\n"
        return result

    with pytest.raises(RuntimeError) as excinfo:
        lora_smoke.gpu_preflight(run=fake_run)
    assert "RTX 4060" in str(excinfo.value)


def test_gpu_preflight_blocks_when_jax_is_cpu():
    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        result = Result()
        if "nvidia-smi" in cmd and "-L" in cmd:
            result.stdout = "GPU 0: NVIDIA GeForce RTX 4060 Laptop GPU (UUID: GPU-c8f4)\n"
        elif "nvidia-smi" in cmd:
            result.stdout = "0, NVIDIA GeForce RTX 4060 Laptop GPU, GPU-c8f4, 580.1, 8188, 7804, 50"
        elif cmd[0].endswith("python"):
            result.stdout = "0.11.2\ncpu\n[CpuDevice(id=0)]\n"
        return result

    with pytest.raises(RuntimeError) as excinfo:
        lora_smoke.gpu_preflight(run=fake_run)
    assert "backend gpu obrigatório" in str(excinfo.value)


def test_decide_best_batch_stops_before_first_failure():
    attempts = [
        {"batch_size": 1, "status": "ok"},
        {"batch_size": 2, "status": "ok"},
        {"batch_size": 4, "status": "ok"},
        {"batch_size": 8, "status": "oom"},
        {"batch_size": 16, "status": "error"},
    ]
    assert lora_smoke.decide_best_batch(attempts) == 4


def test_decide_best_batch_raises_when_all_fail():
    attempts = [{"batch_size": 1, "status": "oom"}]
    with pytest.raises(RuntimeError) as excinfo:
        lora_smoke.decide_best_batch(attempts)
    assert "BLOCKED" in str(excinfo.value)


def test_finetune_command_matches_runbook_and_offline():
    venv_bin = Path("/tmp/venv/bin")
    cmd, env = lora_smoke.finetune_command(
        venv_bin, Path("train-100.jsonl"), Path("adapter.safetensors"), batch_size=4
    )
    assert cmd[0] == str(venv_bin / "needle")
    assert cmd[1] == "finetune"
    assert "--batch-size" in cmd and cmd[cmd.index("--batch-size") + 1] == "4"
    assert "--lora-rank" in cmd and cmd[cmd.index("--lora-rank") + 1] == "16"
    assert "--lora-alpha" in cmd and cmd[cmd.index("--lora-alpha") + 1] == "32"
    assert "--lr" in cmd and cmd[cmd.index("--lr") + 1] == "1e-4"
    assert "--max-len" in cmd and cmd[cmd.index("--max-len") + 1] == "256"
    assert "--seed" in cmd and cmd[cmd.index("--seed") + 1] == "0"
    assert "--val-split" in cmd and cmd[cmd.index("--val-split") + 1] == "0.1"
    assert "--generate" not in cmd  # nunca gera dados externos
    assert env["CUDA_VISIBLE_DEVICES"] == "0"
    assert env["HF_HUB_OFFLINE"] == "1"


def test_build_runner_is_offline_and_uses_official_build():
    assert "build_main" in lora_smoke.BUILD_RUNNER  # build oficial do pacote
    assert "fetch_weights = lambda" in lora_smoke.BUILD_RUNNER  # base local, sem re-download
    assert "upload=False" in lora_smoke.BUILD_RUNNER  # nunca envia pesos


def test_export_tuned_blocks_without_base_archive(tmp_path):
    with pytest.raises(RuntimeError) as excinfo:
        lora_smoke.export_tuned(
            tmp_path / "python",
            tmp_path / "adapter.safetensors",
            tmp_path / "tuned-20L.cact",
            base_archive=tmp_path / "missing.cact",
        )
    assert "BLOCKED" in str(excinfo.value)


def test_run_finetune_attempt_classifies_oom_and_timeout(tmp_path):
    """Status real do desfecho: rc!=0 com OOM no log vira 'oom', nunca 'ok'."""
    dataset = _fake_export(tmp_path)
    log_path = tmp_path / "train.log"

    class FakeProc:
        def __init__(self):
            self.returncode = 1

        def poll(self):
            return 0

        def wait(self):
            return 1

    def fake_runner(cmd, **kwargs):
        kwargs["stdout"].write("epoch 1 loss=0.5\nCUDA out of memory\n")
        kwargs["stdout"].flush()
        return FakeProc()

    result = lora_smoke.run_finetune_attempt(
        Path("/tmp/venv/bin"),
        dataset,
        tmp_path / "adapter.safetensors",
        1,
        log_path,
        tmp_path / "tele.csv",
        runner=fake_runner,
    )
    assert result["status"] == "oom"


def test_run_finetune_attempt_success_requires_adapter(tmp_path):
    dataset = _fake_export(tmp_path)
    log_path = tmp_path / "train2.log"

    class FakeProc:
        returncode = 0

        def poll(self):
            return 0

        def wait(self):
            return 0

    def fake_runner(cmd, **kwargs):
        kwargs["stdout"].write("epoch 1 loss=0.5 val_loss=0.6\n")
        kwargs["stdout"].flush()
        return FakeProc()

    result = lora_smoke.run_finetune_attempt(
        Path("/tmp/venv/bin"),
        dataset,
        tmp_path / "adapter2.safetensors",
        1,
        log_path,
        tmp_path / "tele2.csv",
        runner=fake_runner,
    )
    # sem arquivo de adapter no disco → não pode ser 'ok' mesmo com rc=0
    assert result["status"] == "error"
