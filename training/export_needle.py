"""Exportador de dados canônicos para o formato de fine-tuning do Needle (P07-T01, docs/07 §1 e docs/00 §1.5).

Pipeline RAW -> CANONICAL -> NEEDLE EXPORT (ADR-015 em docs/07):
- Converte registros canônicos para o formato exato esperado pelo `needle finetune`:
  {query, tools, answers[{name, arguments}], reasoning, [system]}
- Preserva regras de grounding e recusa:
  * off-topic e no-tool -> answers: []
  * chamadas de ferramenta -> answers: [{"name": ..., "arguments": ...}]
- Separa splits temporais (train < 2020 <= valid < 2024)
- Gera hashes criptográficos SHA-256 reproduzíveis
- Verifica anti-leakage contra os SHAs do benchmark
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from evaluation.harness import bench_shas, check_no_leakage, load_manifest
from tools.selector import SIGA_TOOLS

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "datasets/benchmark/manifest.json"
DEFAULT_SYSTEM_FACTS = "date: 2026-09-18, locale: pt-BR, repo: SIGA, environment: siga-needle-expert"


def compute_file_sha256(path: Path) -> str:
    """Calcula o hash SHA-256 do conteúdo de um arquivo."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_to_needle_record(
    record: dict[str, Any],
    available_tools: list[str] | None = None,
    system_facts: str = DEFAULT_SYSTEM_FACTS,
) -> dict[str, Any]:
    """Converte um único registro canônico para o formato do Needle."""
    query = record.get("query", "")
    answers = record.get("answers", [])
    reasoning = record.get("reasoning", "")

    # Se a lista de tools disponíveis não foi especificada, usa as 5 ferramentas canônicas
    if available_tools is None:
        declared_tools = list(SIGA_TOOLS.keys())
    else:
        declared_tools = list(available_tools)

    # Formata a lista de respostas conforme schema do Needle
    # Tarefas off-topic e no-tool devem ter answers: []
    formatted_answers: list[dict[str, Any]] = []
    task_type = record.get("task_type", "")
    subcategory = record.get("subcategory", "")

    no_tool_types = {
        "off-topic",
        "no-tool",
        "ambiguous-incomplete",
        "insufficient",
        "refusal",
        "clarification_needed",
    }
    is_no_tool = (
        task_type in no_tool_types
        or subcategory in no_tool_types
        or record.get("tools") == []
        or record.get("final") in ("OFF_TOPIC", "CLARIFICATION_NEEDED", "NO_TOOL")
    )

    if not is_no_tool and answers:
        for ans in answers:
            if isinstance(ans, dict) and "name" in ans:
                formatted_answers.append({
                    "name": ans["name"],
                    "arguments": ans.get("arguments", {}),
                })

    needle_obj: dict[str, Any] = {
        "query": query,
        "tools": declared_tools,
        "answers": formatted_answers,
        "reasoning": reasoning,
        "system": system_facts,
    }
    return needle_obj


def export_canonical_to_needle(
    canonical_path: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Executa o pipeline de exportação CANONICAL -> NEEDLE EXPORT com separação temporal."""
    if canonical_path is None:
        canonical_path = ROOT / "datasets/canonical/v1/canonical.jsonl"
    if output_dir is None:
        output_dir = ROOT / "datasets/needle_export"

    if not canonical_path.is_file():
        raise FileNotFoundError(f"Arquivo canônico não encontrado: {canonical_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    records = [
        json.loads(line)
        for line in canonical_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    train_records: list[dict[str, Any]] = []
    val_records: list[dict[str, Any]] = []
    full_records: list[dict[str, Any]] = []

    for rec in records:
        exported = canonical_to_needle_record(rec)
        full_records.append(exported)

        split = rec.get("split", "train")
        if split == "valid":
            val_records.append(exported)
        else:
            train_records.append(exported)

    # Gravação dos arquivos JSONL exportados
    train_file = output_dir / "needle_train.jsonl"
    val_file = output_dir / "needle_val.jsonl"
    full_file = output_dir / "needle_full.jsonl"

    for file_path, data in [
        (train_file, train_records),
        (val_file, val_records),
        (full_file, full_records),
    ]:
        with file_path.open("w", encoding="utf-8") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    # Hashes SHA-256 reproduzíveis
    train_hash = compute_file_sha256(train_file)
    val_hash = compute_file_sha256(val_file)
    full_hash = compute_file_sha256(full_file)

    # Verificação anti-leakage contra o benchmark
    manifest = load_manifest(MANIFEST_PATH)
    bench_keys = bench_shas(manifest)
    check_no_leakage(bench_keys, ROOT / "datasets")

    metadata = {
        "export_version": "v1.0",
        "source_canonical": str(canonical_path.relative_to(ROOT)),
        "total_records": len(full_records),
        "train_records": len(train_records),
        "val_records": len(val_records),
        "hashes": {
            "needle_train": train_hash,
            "needle_val": val_hash,
            "needle_full": full_hash,
        },
        "format": "cactus-needle-v2",
        "anti_leakage_verified": True,
    }

    manifest_file = output_dir / "manifest.json"
    manifest_file.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return metadata
