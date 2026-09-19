"""Testes da auditoria de SLOs de hardware (F16, ADR-026 em docs/13).

- `percentile`/`summarize_latency`: fórmula idêntica ao harness (interpolação);
- `measure_rss_mb`: método registrado, valor positivo plausível;
- `measure_trace_latency_by_depth`: 3 profundidades com amostras e resumo,
  sobre o clone real (dev) ou fixture sintética (CI);
- `evaluate_slo_compliance`: veredito PASS/FAIL/NOT_RUN determinístico;
- `subnetwork_ram_table`: herda o relatório P08 congelado com fonte citada;
- `run_slo_audit`: artefatos publicados com provenance e sem contaminação.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from experiments.log import validate_record
from evaluation.hardware_slos import (
    MeasurementError,
    SLO_STARTUP_S,
    SLO_TOTAL_RAM_MB,
    SLO_TRACE_P95_S,
    evaluate_slo_compliance,
    measure_rss_mb,
    measure_trace_latency_by_depth,
    percentile,
    run_slo_audit,
    subnetwork_ram_table,
    summarize_latency,
)

ROOT = Path(__file__).resolve().parent.parent
SIGA = ROOT.parent


def _siga_available() -> bool:
    return (SIGA / "siga-ex").is_dir()


class FakeClock:
    """Relógio monotônico controlável (1ms por leitura)."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 0.001
        return self.now


def test_percentile_matches_harness_formula():
    samples = [0.1] * 9 + [0.9]  # p95: rank 8.55 → 0.1 + 0.8*0.55
    assert percentile(samples, 50.0) == pytest.approx(0.1)
    assert percentile(samples, 95.0) == pytest.approx(0.54)
    assert percentile([0.5], 95.0) == 0.5
    assert percentile([3.0, 1.0, 2.0], 50.0) == 2.0
    with pytest.raises(MeasurementError):
        percentile([], 50.0)
    with pytest.raises(MeasurementError):
        percentile([0.1], 101.0)


def test_summarize_latency_reports_all_fields():
    summary = summarize_latency([0.10, 0.12, 0.14, 0.16, 0.18])
    assert summary["n"] == 5
    assert summary["p50_s"] == pytest.approx(0.14)
    assert summary["max_s"] == 0.18
    assert summary["p95_ms"] == pytest.approx(summary["p95_s"] * 1000.0)
    with pytest.raises(MeasurementError):
        summarize_latency([])


def test_measure_rss_mb_reports_method_and_plausible_value():
    ram = measure_rss_mb()
    assert ram["rss_mb"] > 0
    assert ram["rss_mb"] < SLO_TOTAL_RAM_MB * 10  # processo Python comum
    assert "method" in ram


def test_measure_session_rss_mb_is_fresh_process():
    """Sessão medida em subprocesso: imune ao pico do processo hospedeiro."""
    from evaluation.hardware_slos import measure_session_rss_mb

    session = measure_session_rss_mb()
    assert session["rss_mb"] > 0
    assert session["rss_mb"] < SLO_TOTAL_RAM_MB, "runtime sem IA carregada deve caber no SLO"
    assert "method" in session


def test_measure_trace_latency_by_depth_real_or_fixture(tmp_path: Path):
    if _siga_available():
        repo, symbol, conn = SIGA, "ExDocumentoController", None
    else:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "Aluno.java").write_text("public class Aluno {}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "seed"],
            check=True,
        )
        symbol, conn = "Aluno", None
    audit = measure_trace_latency_by_depth(symbol, repo, conn, samples=2, warmup=0)
    assert set(audit["by_depth"]) == {"1", "2", "3"}
    for depth in audit["by_depth"].values():
        assert depth["n"] == 2
        assert depth["p95_s"] >= depth["p50_s"] >= 0
        assert len(depth["samples_s"]) == 2
    assert audit["worst_p95_s"] == max(d["p95_s"] for d in audit["by_depth"].values())


def test_evaluate_slo_compliance_pass_fail_and_not_run():
    good = {
        "ram": {"rss_mb": 120.0},
        "startup": {"startup_s": 0.8},
        "trace_by_depth": {"by_depth": {"2": {"p50_s": 0.05}}, "worst_p95_s": 0.2},
    }
    result = evaluate_slo_compliance(good)
    assert result["all_pass"] is True
    assert all(c["pass"] is True for c in result["checks"].values())

    bad = {
        "ram": {"rss_mb": SLO_TOTAL_RAM_MB + 1},
        "startup": {"startup_s": 0.8},
        "trace_by_depth": {"by_depth": {"2": {"p50_s": 0.05}}, "worst_p95_s": SLO_TRACE_P95_S + 0.5},
    }
    result_bad = evaluate_slo_compliance(bad)
    assert result_bad["all_pass"] is False
    assert result_bad["checks"]["total_ram_under_512mb"]["pass"] is False
    assert result_bad["checks"]["trace_p95_multi_hop_under_1s"]["pass"] is False

    not_run = {
        "ram": {"rss_mb": 120.0},
        "startup": {"startup_s": None},
        "trace_by_depth": {"by_depth": {"2": {"p50_s": 0.05}}, "worst_p95_s": 0.2},
    }
    result_nr = evaluate_slo_compliance(not_run)
    assert result_nr["checks"]["startup_under_2s"]["pass"] is None
    assert result_nr["all_pass"] is False  # auditoria incompleta nunca é verde


def test_subnetwork_ram_table_inherits_p08():
    table = subnetwork_ram_table()
    assert table["source"].startswith("subnetwork_compression.json")
    assert table["rows_4bit"], "P08 deve ter linhas 4-bit"
    row = table["rows_4bit"][0]
    assert "peak_ram_mb" in row and "depth" in row
    assert table["smallest_viable_subnetwork"]


def test_run_slo_audit_publishes_report_and_run(tmp_path: Path):
    if _siga_available():
        repo, symbol = SIGA, "ExDocumentoController"
    else:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "Aluno.java").write_text("public class Aluno {}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "seed"],
            check=True,
        )
        symbol = "Aluno"
    report = run_slo_audit(repo, None, symbol=symbol, samples=2, save_report=False, log_run=False)
    checks = report["slo_compliance"]["checks"]
    assert checks["total_ram_under_512mb"]["pass"] is True
    # Startup sem server_env é NOT_RUN honesto, nunca sucesso falso.
    assert checks["startup_under_2s"]["pass"] is None
    assert report["slo_compliance"]["all_pass"] is False
    assert report["subnetwork_ram"]["source"].startswith("subnetwork_compression.json")
    # Medição por profundidade no ambiente disponível.
    assert set(report["measurements"]["trace_by_depth"]["by_depth"]) == {"1", "2", "3"}


def test_run_slo_audit_startup_measured_with_token(tmp_path: Path):
    if not _siga_available():
        pytest.skip("startup e2e real exige o clone do SIGA ao lado (executa no dev)")
    report = run_slo_audit(
        SIGA,
        None,
        symbol="ExDocumentoController",
        samples=2,
        server_env={"SIGA_MCP_TOKEN": "slo-token-f16"},
        save_report=False,
        log_run=False,
    )
    startup = report["measurements"]["startup"]
    assert startup["startup_s"] is not None and startup["startup_s"] > 0
    assert startup["startup_s"] < SLO_STARTUP_S * 10  # sinalidade funcionou
    assert report["slo_compliance"]["checks"]["startup_under_2s"]["pass"] is not None


def test_graph_fixture_supports_real_multi_hop(tmp_path: Path):
    """Grafo povoado com código real do slice traça hops > 1 (ADR-011)."""
    from evaluation.hardware_slos import build_graph_fixture_conn, pick_trace_symbol
    from graph import store

    (tmp_path / "Pessoa.java").write_text(
        "package escola;\npublic class Pessoa {\n    public String getNome() { return \"x\"; }\n}\n",
        encoding="utf-8",
    )
    (tmp_path / "Aluno.java").write_text(
        "package escola;\npublic class Aluno extends Pessoa {\n    public void matricular() {}\n}\n",
        encoding="utf-8",
    )
    conn, info = build_graph_fixture_conn(tmp_path)
    try:
        assert info["files_indexed"] == 2
        symbol = pick_trace_symbol(conn)  # determinístico: 1º com EXTENDS
        assert symbol == "Aluno"
        chain = store.trace(conn, symbol, depth=3)
        assert max(step["hop"] for step in chain) >= 1
        assert any(step["name"] == "Pessoa" for step in chain)
    finally:
        conn.close()


def test_run_slo_audit_persists_valid_run_with_provenance(tmp_path: Path, monkeypatch):
    if _siga_available():
        repo, symbol = SIGA, "ExDocumentoController"
    else:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "Aluno.java").write_text("public class Aluno {}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "seed"],
            check=True,
        )
        symbol = "Aluno"
    record = run_slo_audit(
        repo,
        None,
        symbol=symbol,
        samples=2,
        save_report=False,
        log_run=True,
        now="2026-09-19T13:00:00+00:00",
    )
    run_path = ROOT / "experiments/runs" / f"{record['experiment_id']}.json"
    assert run_path.is_file()
    on_disk = json.loads(run_path.read_text(encoding="utf-8"))
    validate_record(on_disk)
    if _siga_available():
        assert on_disk["siga_commit"]
    run_path.unlink()  # o run e2e não deve poluir o histórico versionado
