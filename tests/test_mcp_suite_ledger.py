"""Testes da planilha-livro de replicação da suite EVAL-MCP (G04).

Propriedades: linhas derivadas do scorer (não digitadas), idempotência pela
chave (modelo, ide, braço, run_file), ordenação determinística e header
canônico com abort em divergência. Fixtures sintéticas, sem rede.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.mcp_suite_ledger import (  # noqa: E402
    HEADER,
    KEY,
    ledger_row,
    read_ledger,
    update_ledger,
    write_ledger,
)

A_SHA = "a" * 40
B_SHA = "b" * 40

TASKS = {
    "mcp-locate-001": {
        "id": "mcp-locate-001",
        "kind": "locate",
        "method": "siga.locate",
        "args": {"query": "q"},
        "ground_truth": {"files": ["a/b/C.java"]},
    },
    "mcp-trace-001": {
        "id": "mcp-trace-001",
        "kind": "trace",
        "method": "siga.trace",
        "args": {"symbol": "ExMobil", "depth": 2},
        "ground_truth": {"files": ["x/ExMobil.java"], "anchor": "ExMobil"},
    },
    "mcp-history-001": {
        "id": "mcp-history-001",
        "kind": "history",
        "method": "siga.history",
        "args": {"target": "x.java"},
        "ground_truth": {
            "commits": [{"sha": A_SHA, "date": None, "subject": "s"}, {"sha": B_SHA, "date": None, "subject": "t"}],
            "files": [],
        },
    },
}


@pytest.fixture()
def tasks_path(tmp_path: Path) -> Path:
    p = tmp_path / "tasks.jsonl"
    p.write_text(json.dumps({"tasks": list(TASKS.values())}), encoding="utf-8")
    return p


def _write_run(tmp_path: Path, name: str, runs: list[dict]) -> Path:
    f = tmp_path / name
    f.write_text("\n".join(json.dumps(r) for r in runs) + "\n", encoding="utf-8")
    return f


def test_ledger_row_derives_metrics_from_scorer(tmp_path, tasks_path):
    run = _write_run(
        tmp_path,
        "probe-ide-20260920.jsonl",
        [
            {"task_id": "mcp-locate-001", "braco": "A", "arquivos": ["a/b/C.java"], "tokens_proxy": 100, "latency_ms": 10, "chamadas_mcp": []},
            {"task_id": "mcp-trace-001", "braco": "B", "arquivos": ["x/ExMobil.java"], "simbolos": ["ExMobil"], "tokens_proxy": 40, "latency_ms": 20, "chamadas_mcp": [{"method": "siga.trace"}]},
        ],
    )
    rows = ledger_row(run, tasks_path, modelo="probe", ide="ide", data="20260920", now="T1")
    assert [r["braco"] for r in rows] == ["A", "B"]
    a, b = rows
    assert a["task_success"] == "1.0" and a["n_tasks"] == "1" and a["mean_mcp_calls"] == "0.0"
    assert b["task_success"] == "1.0" and b["mean_mcp_calls"] == "1.0"
    assert a["run_file"] == str(run) and a["modelo"] == "probe" and a["ide"] == "ide"
    assert a["generated_at"] == "T1" and b["generated_at"] == "T1"
    assert set(rows[0].keys()) == set(HEADER)


def test_ledger_row_date_from_filename(tmp_path, tasks_path):
    run = _write_run(tmp_path, "m-ide-20260102.jsonl", [{"task_id": "mcp-locate-001", "braco": "A", "arquivos": [], "latency_ms": 1}])
    rows = ledger_row(run, tasks_path, modelo="m", ide="ide")
    assert rows[0]["data"] == "20260102"
    run2 = _write_run(tmp_path, "semdata.jsonl", [{"task_id": "mcp-locate-001", "braco": "A", "arquivos": [], "latency_ms": 1}])
    rows2 = ledger_row(run2, tasks_path, modelo="m", ide="ide")
    assert rows2[0]["data"] == ""


def test_ledger_row_invalid_date_aborts(tmp_path, tasks_path):
    run = _write_run(tmp_path, "r.jsonl", [{"task_id": "mcp-locate-001", "braco": "A", "arquivos": [], "latency_ms": 1}])
    with pytest.raises(SystemExit, match="AAAAMMDD"):
        ledger_row(run, tasks_path, modelo="m", ide="ide", data="20-09-20")


def test_update_ledger_idempotent_by_key():
    base = [{k: "v" for k in HEADER} for _ in range(2)]
    base[0].update({"modelo": "m1", "ide": "i", "braco": "A", "run_file": "r1", "task_success": "0.5"})
    base[1].update({"modelo": "m2", "ide": "i", "braco": "A", "run_file": "r2"})
    new = [dict(base[0], task_success="0.9", generated_at="T2")]
    merged = update_ledger(base, new)
    assert len(merged) == 2
    m1 = next(r for r in merged if r["modelo"] == "m1")
    assert m1["task_success"] == "0.9" and m1["generated_at"] == "T2"


def test_update_ledger_deterministic_order():
    rows = []
    for m in ("zeta", "alpha"):
        for b in ("B", "A"):
            rows.append({**{k: "" for k in HEADER}, "modelo": m, "ide": "i", "braco": b, "run_file": "r", "data": "d"})
    merged = update_ledger([], rows)
    keys = [(r["modelo"], r["braco"]) for r in merged]
    assert keys == [("alpha", "A"), ("alpha", "B"), ("zeta", "A"), ("zeta", "B")]


def test_ledger_roundtrip_and_header_guard(tmp_path):
    csv_path = tmp_path / "replication.csv"
    write_ledger(csv_path, [])
    assert csv_path.read_text(encoding="utf-8") == ",".join(HEADER) + "\n"
    rows = [{**{k: "" for k in HEADER}, "modelo": "m", "ide": "i", "braco": "A", "run_file": "r"}]
    write_ledger(csv_path, rows)
    assert read_ledger(csv_path)[0]["modelo"] == "m"
    # header divergente aborta
    bad = tmp_path / "bad.csv"
    bad.write_text("wrong,header\n1,2\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="cabeçalho inesperado"):
        read_ledger(bad)


def test_key_columns_present_in_header():
    assert set(KEY) <= set(HEADER)
    assert HEADER[0] == "modelo" and HEADER[1] == "ide" and HEADER[2] == "braco"
