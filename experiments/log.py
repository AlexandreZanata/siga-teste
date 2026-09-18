"""Experiment tracking mínimo e reproduzível (P01-T02, docs/15 §3).

Só stdlib. Nenhum import de packages do projeto (ver tests/test_boundaries.py).
`config_hash` é determinístico: mesmos inputs -> mesmo hash.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def config_hash(config: dict) -> str:
    """SHA-256 hex do config em forma canônica (chaves ordenadas, sem espaço)."""
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def git_head(path: str | Path) -> str | None:
    """HEAD do repo em path (somente leitura); None se não for repo git."""
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return out.stdout.strip() or None


def hardware_info() -> dict:
    """Fatos de hardware/ambiente via stdlib (sem PII, sem segredos)."""
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0],
    }


def _utcnow_compact(now: str | None) -> tuple[str, str]:
    if now is not None:
        dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
    else:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y%m%d-%H%M%S"), dt.isoformat(timespec="seconds")


def new_run(
    *,
    config: dict,
    dataset_version: str,
    tool_version: str,
    index_version: str,
    bench_version: str,
    metrics: dict | None = None,
    latency: dict | None = None,
    needle_version: str | None = None,
    needle_depth: int | None = None,
    artifact_hash: str | None = None,
    notes: str = "",
    now: str | None = None,
    siga_root: str | Path | None = None,
    work_root: str | Path | None = None,
) -> dict:
    """Monta um registro válido pelo schema; `now` fixo torna o run reproduzível."""
    stamp, iso = _utcnow_compact(now)
    digest = config_hash(config)
    return {
        "experiment_id": f"{stamp}-{digest[:12]}",
        "date": iso,
        "siga_commit": git_head(siga_root) if siga_root is not None else None,
        "sigateste_commit": git_head(work_root) if work_root is not None else None,
        "needle_version": needle_version,
        "needle_depth": needle_depth,
        "artifact_hash": artifact_hash,
        "dataset_version": dataset_version,
        "tool_version": tool_version,
        "index_version": index_version,
        "bench_version": bench_version,
        "metrics": metrics or {},
        "hardware": hardware_info(),
        "latency": latency or {"p50_ms": 0.0, "p95_ms": None},
        "notes": notes,
    }


def _check_type(value: object, expected: object, field: str) -> None:
    kinds = expected if isinstance(expected, list) else [expected]
    ok = False
    for kind in kinds:
        if kind == "string" and isinstance(value, str):
            ok = True
        elif kind == "integer" and isinstance(value, int) and not isinstance(value, bool):
            ok = True
        elif kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            ok = True
        elif kind == "object" and isinstance(value, dict):
            ok = True
        elif kind == "null" and value is None:
            ok = True
    if not ok:
        raise ValueError(f"campo {field!r} fora do schema (valor={value!r})")


def validate_record(record: dict, schema: dict | None = None) -> None:
    """Valida registro contra o schema (manual, sem dependências). Levanta ValueError."""
    schema = schema or _load_schema()
    for field in schema["required"]:
        if field not in record:
            raise ValueError(f"campo obrigatório ausente: {field!r}")
    properties = schema["properties"]
    for field, spec in properties.items():
        if field in record:
            _check_type(record[field], spec["type"], field)
    latency = record["latency"]
    for field in schema["properties"]["latency"]["required"]:
        if field not in latency:
            raise ValueError(f"campo obrigatório ausente: latency.{field!r}")


def save(record: dict, path: str | Path) -> Path:
    """Persiste registro validado (JSON ordenado, indent 2)."""
    validate_record(record)
    out = Path(path)
    out.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return out


def load(path: str | Path) -> dict:
    """Lê e valida registro persistido."""
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_record(record)
    return record
