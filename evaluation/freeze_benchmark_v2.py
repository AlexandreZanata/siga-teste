"""Congelamento do benchmark v2 cego e splits temporais (P13-T02, docs/21 §5, docs/22 §5).

Splits temporais estritos:
- Train: commits anteriores a T1 (2021-01-01)
- Valid: T1 <= commit < T2 (2021-01-01 a 2023-01-01)
- Test cego: commit >= T2 (2023-01-01 a 2026-09-21) — 300 tarefas
- Adversarial: conjunto externo de off-topic, no-tool, queries vagas e homônimos

Isolamento absoluto: dados de test são blind e inacessíveis ao pipeline de treino.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from evaluation.freeze_holdout import candidate_shas
from evaluation.harness import commit_task

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = ROOT.parent
BENCHMARK_V2_DIR = ROOT / "datasets/benchmark_v2"

T1_CUTOFF = "2021-01-01"
T2_CUTOFF = "2023-01-01"
T_END = "2030-01-01"

ADVERSARIAL_TASKS = [
    {
        "id": "adv-offtopic-01",
        "query": "Qual é a previsão do tempo para Brasília amanhã?",
        "task_type": "off-topic",
        "category": "adversarial",
        "expected_tool": None,
        "answers": [],
        "source": "curated_adversarial",
    },
    {
        "id": "adv-offtopic-02",
        "query": "Receita de bolo de cenoura com cobertura de chocolate",
        "task_type": "off-topic",
        "category": "adversarial",
        "expected_tool": None,
        "answers": [],
        "source": "curated_adversarial",
    },
    {
        "id": "adv-offtopic-03",
        "query": "Explique a teoria da relatividade geral de Einstein",
        "task_type": "off-topic",
        "category": "adversarial",
        "expected_tool": None,
        "answers": [],
        "source": "curated_adversarial",
    },
    {
        "id": "adv-vague-01",
        "query": "documento",
        "task_type": "vague-query",
        "category": "adversarial",
        "expected_tool": "siga_locate",
        "answers": [{"name": "siga_locate", "arguments": {"query": "documento"}}],
        "source": "curated_adversarial",
    },
    {
        "id": "adv-vague-02",
        "query": "processo",
        "task_type": "vague-query",
        "category": "adversarial",
        "expected_tool": "siga_locate",
        "answers": [{"name": "siga_locate", "arguments": {"query": "processo"}}],
        "source": "curated_adversarial",
    },
    {
        "id": "adv-homonym-01",
        "query": "ExDocumento vs CpDocumento localização de classes",
        "task_type": "homonym",
        "category": "adversarial",
        "expected_tool": "siga_locate",
        "answers": [{"name": "siga_locate", "arguments": {"query": "ExDocumento"}}],
        "source": "curated_adversarial",
    },
    {
        "id": "adv-homonym-02",
        "query": "Buscar Pessoa no contexto de ExPessoa ou DpPessoa",
        "task_type": "homonym",
        "category": "adversarial",
        "expected_tool": "siga_locate",
        "answers": [{"name": "siga_locate", "arguments": {"query": "ExPessoa"}}],
        "source": "curated_adversarial",
    },
    {
        "id": "adv-missing-args-01",
        "query": "Executar rastreamento de dependências sem informar o símbolo",
        "task_type": "missing-args",
        "category": "adversarial",
        "expected_tool": None,
        "answers": [],
        "source": "curated_adversarial",
    },
    {
        "id": "adv-missing-args-02",
        "query": "Calcular impacto da alteração sem especificar arquivo",
        "task_type": "missing-args",
        "category": "adversarial",
        "expected_tool": None,
        "answers": [],
        "source": "curated_adversarial",
    },
    {
        "id": "adv-foreign-schema-01",
        "query": "SELECT * FROM users WHERE id = 123",
        "task_type": "foreign-query",
        "category": "adversarial",
        "expected_tool": None,
        "answers": [],
        "source": "curated_adversarial",
    },
]


def compute_sha256(path: Path) -> str:
    """Calcula hash SHA-256 de um arquivo."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_benchmark_v2(
    repo: str | Path = DEFAULT_REPO,
    out_dir: str | Path = BENCHMARK_V2_DIR,
    seed: int = 20260921,
    train_size: int = 200,
    valid_size: int = 200,
    test_size: int = 300,
) -> dict[str, Any]:
    """Congela o Benchmark v2 com splits temporais estritos e isolamento de teste."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    # 1. Coleta candidatos por split temporal
    train_pool = candidate_shas(repo, "1970-01-01", T1_CUTOFF)
    valid_pool = candidate_shas(repo, T1_CUTOFF, T2_CUTOFF)
    test_pool = candidate_shas(repo, T2_CUTOFF, T_END)

    train_picked = sorted(rng.sample(train_pool, min(train_size, len(train_pool))))
    valid_picked = sorted(rng.sample(valid_pool, min(valid_size, len(valid_pool))))
    test_picked = sorted(rng.sample(test_pool, min(test_size, len(test_pool))))

    holdout_file = out_path / "holdout.jsonl"
    all_tasks = []

    for split, picked in (("train", train_picked), ("valid", valid_picked), ("test", test_picked)):
        for sha in picked:
            task = commit_task(repo, sha)
            task["split"] = split
            task["category"] = "commit-localization"
            task["benchmark_version"] = 2
            all_tasks.append(task)

    with holdout_file.open("w", encoding="utf-8") as fh:
        for t in all_tasks:
            fh.write(json.dumps(t, sort_keys=True, ensure_ascii=False) + "\n")

    # 2. Grava conjunto adversarial
    adversarial_file = out_path / "adversarial.jsonl"
    with adversarial_file.open("w", encoding="utf-8") as fh:
        for adv in ADVERSARIAL_TASKS:
            fh.write(json.dumps(adv, sort_keys=True, ensure_ascii=False) + "\n")

    # 3. Grava README do benchmark v2
    readme_file = out_path / "README.md"
    readme_content = f"""# Benchmark v2 — Holdout Temporal Cego (P13-T02)

Benchmark oficial cego para avaliação real do modelo Needle 3 na RTX 4060.

## Isolamento e Blind Test
- **Test Cego:** {len(test_picked)} tarefas derivadas de commits >= {T2_CUTOFF}.
- **Inacessível ao Treinador:** Proibido carregar ou consultar tarefas de split `test` em qualquer etapa de treinamento, fine-tuning ou geração de dados.
- **Validação Temporal:** {len(valid_picked)} tarefas de commits entre {T1_CUTOFF} e {T2_CUTOFF}.
- **Treino Holdout:** {len(train_picked)} tarefas de commits anteriores a {T1_CUTOFF}.
- **Adversarial:** {len(ADVERSARIAL_TASKS)} consultas off-topic, vagas, homônimos e de recusa.

## Hashes Criptográficos
Gerados deterministicamente com seed {seed}.
"""
    readme_file.write_text(readme_content, encoding="utf-8")

    # 4. Grava manifest.json
    manifest = {
        "version": 2,
        "branch": "desenvolvimento",
        "t1": T1_CUTOFF,
        "t2": T2_CUTOFF,
        "seed": seed,
        "counts": {
            "train": len(train_picked),
            "valid": len(valid_picked),
            "test": len(test_picked),
            "adversarial": len(ADVERSARIAL_TASKS),
            "total_holdout": len(all_tasks),
        },
        "splits": {
            "train": train_picked,
            "valid": valid_picked,
            "test": test_picked,
        },
        "files": {
            "holdout.jsonl": compute_sha256(holdout_file),
            "adversarial.jsonl": compute_sha256(adversarial_file),
            "README.md": compute_sha256(readme_file),
        },
    }

    manifest_file = out_path / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    m = freeze_benchmark_v2()
    print("Benchmark v2 gerado com sucesso:")
    print(f"  Train: {m['counts']['train']}")
    print(f"  Valid: {m['counts']['valid']}")
    print(f"  Test: {m['counts']['test']} (cego, >= {T2_CUTOFF})")
    print(f"  Adversarial: {m['counts']['adversarial']}")
    print(f"  Total: {m['counts']['total_holdout']}")
