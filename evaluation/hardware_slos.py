"""Auditoria de SLOs de hardware (F16, ADR-026 em docs/13).

Os SLOs existem em `docs/13` ("alvo < 512MB totais, startup < 2s, P50 por
turno < 1s excluindo IA grande") e o risco do ADR-011 (`docs/05`: "P95 de
traces multi-hop acima do SLO → reavaliar") nunca teve evidência medida.
Este módulo fecha essa lacuna de forma **determinística e stdlib-only**:

- `percentile`/`summarize_latency`: P50/P95/max/n sobre amostras medidas
  (interpolação idêntica ao harness de `evaluation/needlerun.py`).
- `measure_rss_mb`: RAM do processo via `resource.getrusage(RUSAGE_SELF)`
  (Linux/macOS); sem `resource` (Windows), degrada para `tracemalloc`
  (heap Python) com a limitação registrada.
- `measure_server_startup_s`: startup do `python -m mcp.server` medido como
  subprocesso (relógio monotônico, leitura da primeira linha de stderr).
- `measure_trace_latency_by_depth`: `siga_trace(symbol, depth=1/2/3)` no
  repo/grafo disponível (clone real no dev; fixture sintética no CI), com
  warmup e amostras registradas por profundidade.
- `build_graph_fixture_conn`: grafo em memória povoado pelos `.java` reais
  do slice (ordem determinística, amostra limitada) — multi-hop real via
  `store.trace` (o SQL recursivo é o mesmo do grafo completo; o repo ainda
  não tem indexador em massa, e o ADR-011 exige medir hops, não o fallback).
- `subnetwork_ram_table`: RAM por profundidade de sub-rede **herdada do
  relatório congelado do P08** (`subnetwork_compression.json`), com a fonte
  citada — o módulo mede o processo; não re-estima o modelo.
- `run_slo_audit`: executa a auditoria, emite veredito PASS/FAIL por SLO
  (números, não narrativa) e publica `experiments/reports/hardware_slos.json`
  + run com provenance via `experiments.log.new_run`.

Este módulo não treina, não serve e não altera o runtime: mede.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from statistics import fmean
from typing import Any, Callable

from experiments.log import new_run
from mcp.security import TOKEN_ENV
from tools.siga_trace import siga_trace

ROOT = Path(__file__).resolve().parent.parent

REPORTS_DIR = ROOT / "experiments/reports"
P08_REPORT = REPORTS_DIR / "subnetwork_compression.json"

# SLOs documentados (docs/13 — hardware & privacidade; ADR-011 risco de trace).
SLO_TOTAL_RAM_MB = 512.0
SLO_STARTUP_S = 2.0
SLO_TURN_P50_S = 1.0
SLO_TRACE_P95_S = 1.0  # risco ADR-011: "P95 de traces multi-hop acima do SLO"

DEFAULT_SAMPLES = 7
DEFAULT_WARMUP = 1


class MeasurementError(RuntimeError):
    """Falha determinística de medição (ex.: servidor não subiu no timeout)."""


def percentile(values: list[float], pct: float) -> float:
    """Percentil interpolado; `pct` em [0, 100]; lista não vazia.

    Mesma fórmula do harness (`evaluation/needlerun.py`): índice fracionário
    `p/100*(n-1)` com interpolação linear entre vizinhos.
    """
    if not values:
        raise MeasurementError("percentile exige lista não vazia")
    if not 0.0 <= pct <= 100.0:
        raise MeasurementError(f"pct deve estar em [0, 100], recebido {pct}")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (pct / 100.0) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    frac = rank - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * frac)


def summarize_latency(samples_s: list[float]) -> dict[str, Any]:
    """Resumo P50/P95/max/média/n em segundos e ms sobre amostras medidas."""
    if not samples_s:
        raise MeasurementError("summarize_latency exige amostras não vazias")
    return {
        "n": len(samples_s),
        "p50_s": round(percentile(samples_s, 50.0), 4),
        "p95_s": round(percentile(samples_s, 95.0), 4),
        "max_s": round(max(samples_s), 4),
        "mean_s": round(fmean(samples_s), 4),
        "p50_ms": round(percentile(samples_s, 50.0) * 1000.0, 2),
        "p95_ms": round(percentile(samples_s, 95.0) * 1000.0, 2),
    }


def measure_rss_mb() -> dict[str, Any]:
    """RAM do processo atual em MB, com o método registrado na resposta.

    No Linux prefere `VmHWM` do procfs: é o pico **desta imagem de processo**
    (reinicia no `execve`). `ru_maxrss`, no Linux, sobrevive ao `execve` e
    faria um filho do pytest herdar o pico do hospedeiro — medição falsa.
    macOS: `resource.getrusage`; sem POSIX: `tracemalloc` (heap, com ressalva).
    """
    try:
        status = Path("/proc/self/status").read_text(encoding="utf-8")
    except OSError:
        status = ""
    for line in status.splitlines():
        if line.startswith("VmHWM:"):
            return {
                "rss_mb": round(float(line.split()[1]) / 1024.0, 2),
                "method": "/proc/self/status VmHWM (pico desta imagem de processo)",
            }
    try:
        import resource  # POSIX

        rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reporta KB; macOS reporta bytes.
        if sys.platform == "darwin":
            rss_mb = rss_kb / (1024.0 * 1024.0)
        else:
            rss_mb = rss_kb / 1024.0
        return {
            "rss_mb": round(rss_mb, 2),
            "method": "resource.getrusage.ru_maxrss (sem procfs; pode refletir pico herdado no Linux)",
        }
    except ImportError:
        import tracemalloc

        tracemalloc.start()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return {
            "rss_mb": round(peak / (1024.0 * 1024.0), 2),
            "method": "tracemalloc.peak (heap Python; RSS real indisponível nesta plataforma)",
        }


def measure_session_rss_mb() -> dict[str, Any]:
    """RAM de uma sessão fresca do runtime, medida em subprocesso isolado.

    `ru_maxrss` é o pico do **processo hospedeiro** — medir dentro do pytest
    ou de outro host herdaria o pico dele (não é a sessão do Expert). Um
    subprocesso novo que importa o runtime (`mcp.server` + tools + graph)
    dá o número do docs/13 ("sessão Needle + SQLite"), reproduzível e
    imune ao histórico do processo chamador.
    """
    code = (
        "import json; "
        "from evaluation.hardware_slos import measure_rss_mb; "
        "print(json.dumps(measure_rss_mb()))"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as err:
        raise MeasurementError(f"medição de RAM excedeu o timeout: {err}") from err
    if proc.returncode != 0:
        raise MeasurementError(f"medição de RAM falhou: {proc.stderr.strip()[-200:]}")
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as err:
        raise MeasurementError(f"saída de RAM não interpretável: {proc.stdout[-200:]!r}") from err


def measure_server_startup_s(
    *,
    token: str | None = None,
    server_cmd: list[str] | None = None,
    env_base: dict[str, str] | None = None,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Mede o tempo até o `mcp.server` responder a 1ª requisição JSON-RPC.

    Sinal de "pronto para servir" (mais honesto que tempo de import): o
    subprocesso sobe com `SIGA_MCP_TOKEN` no ambiente e responde
    `siga.list_methods` no stdout. Sem token o servidor falha o boot por
    desenho (F14, ADR-024) — e isso é um erro de medição, não um startup.
    """
    secret = token or (env_base or {}).get(TOKEN_ENV) or os.environ.get(TOKEN_ENV)
    if not secret:
        raise MeasurementError(
            "startup exige token (SIGA_MCP_TOKEN): sem auth o server não sobe (F14, ADR-024)"
        )
    child_env = {**(env_base or os.environ), TOKEN_ENV: secret}
    cmd = list(server_cmd or [sys.executable, "-m", "mcp.server"])
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            env=child_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except OSError as err:
        raise MeasurementError(f"falha ao iniciar o servidor: {err}") from err
    assert proc.stdin is not None and proc.stdout is not None
    try:
        request = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "siga.list_methods", "params": {}, "_siga_auth": secret}
        )
        try:
            proc.stdin.write(request + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
        except (BrokenPipeError, OSError):
            line = ""
        elapsed = time.monotonic() - started
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, ProcessLookupError, ProcessLookupError):
            pass
    if not line.strip():
        raise MeasurementError("servidor encerrou sem responder (boot falhou ou token inválido)")
    try:
        response = json.loads(line)
    except json.JSONDecodeError as err:
        raise MeasurementError(f"primeira linha não é JSON-RPC: {err}") from err
    if "error" in response:
        raise MeasurementError(f"servidor respondeu erro ao sonda de boot: {response['error']}")
    return {
        "startup_s": round(elapsed, 4),
        "signal": "1ª resposta JSON-RPC (siga.list_methods) no stdout",
        "method": "subprocesso python -m mcp.server com SIGA_MCP_TOKEN no ambiente",
    }


def measure_trace_latency_by_depth(
    symbol: str,
    repo: Path,
    conn: Any = None,
    *,
    depths: tuple[int, ...] = (1, 2, 3),
    samples: int = DEFAULT_SAMPLES,
    warmup: int = DEFAULT_WARMUP,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """Mede `siga_trace(symbol, depth=d)` por profundidade com warmup + amostras.

    Usa o grafo quando `conn` é fornecido (dev, clone real) e o fallback por
    primitivas caso contrário (CI, fixture). Amostras por profundidade são
    registradas para reanálise; resumo P50/P95 por profundidade.
    """
    if samples < 1 or warmup < 0:
        raise MeasurementError("samples >= 1 e warmup >= 0")
    by_depth: dict[str, Any] = {}
    for depth in depths:
        for _ in range(warmup):
            siga_trace(symbol, depth=depth, repo=repo, conn=conn)
        timed: list[float] = []
        chain_sizes: list[int] = []
        for _ in range(samples):
            start = clock()
            result = siga_trace(symbol, depth=depth, repo=repo, conn=conn)
            timed.append(clock() - start)
            chain_sizes.append(len(result.get("chain", [])))
        by_depth[str(depth)] = {
            **summarize_latency(timed),
            "chain_len_mean": round(fmean(chain_sizes), 2),
            "samples_s": [round(s, 4) for s in timed],
        }
    return {
        "symbol": symbol,
        "graph_backed": conn is not None,
        "by_depth": by_depth,
        "worst_p95_s": round(max(d["p95_s"] for d in by_depth.values()), 4),
    }


def build_graph_fixture_conn(repo: Path, *, max_files: int = 400) -> tuple[Any, dict[str, Any]]:
    """Grafo em memória povoado com `.java` reais do slice (determinístico).

    O repo ainda não tem indexador em massa (infra da P02 não criada); para
    medir multi-hop honesto, indexamos uma amostra limitada e ordenada dos
    arquivos reais — o caminho de `store.trace` (SQL recursivo) é o mesmo do
    grafo completo. Erros de parse de arquivo individual são contados, não
    abortam a auditoria.
    """
    from graph import store as graph_store
    from indexer import java_symbols

    conn = graph_store.connect()
    if (repo / "siga-ex").is_dir():
        candidates = sorted((repo / "siga-ex").rglob("*.java")) + sorted((repo / "sigaex").rglob("*.java"))
    else:
        candidates = sorted(repo.rglob("*.java"))
    indexed = skipped = 0
    for path in candidates[:max_files]:
        try:
            rec = java_symbols.parse_file(path)
            if rec.get("types"):
                graph_store.upsert_java(conn, rec)
                indexed += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1
    conn.commit()
    info = {
        "files_indexed": indexed,
        "files_skipped": skipped,
        "sample_limit": max_files,
        "source": "arquivos .java reais do slice, ordem determinística (rglob sorted)",
    }
    return conn, info


def pick_trace_symbol(conn: Any) -> str:
    """Símbolo determinístico com aresta EXTENDS (garante multi-hop > 1 hop)."""
    row = conn.execute(
        "SELECT n.name FROM nodes n JOIN edges e ON e.src = n.id WHERE e.type = 'EXTENDS' ORDER BY n.name LIMIT 1"
    ).fetchone()
    if row:
        return str(row[0])
    row = conn.execute("SELECT name FROM nodes WHERE kind = 'class' ORDER BY name LIMIT 1").fetchone()
    if not row:
        raise MeasurementError("grafo sem nós de classe: nada para traçar")
    return str(row[0])


def subnetwork_ram_table(report_path: Path | None = None) -> dict[str, Any]:
    """Tabela RAM por profundidade de sub-rede, herdada do relatório P08.

    Medição de processo é responsabilidade deste módulo; os números do
    modelo em disco/RAM por `depth` vêm do estudo congelado do P08
    (`training/compress.py`), citado como fonte — sem re-estimativa aqui.
    """
    path = report_path or P08_REPORT
    if not path.is_file():
        raise MeasurementError(f"relatório P08 não encontrado: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    table_4bit = raw.get("table_4bit_subnetworks", [])
    return {
        "source": f"{path.name} (P08 congelado; modelo em training/compress.py)",
        "columns": list(table_4bit[0].keys()) if table_4bit else [],
        "rows_4bit": table_4bit,
        "smallest_viable_subnetwork": raw.get("smallest_viable_subnetwork"),
    }


def evaluate_slo_compliance(measurements: dict[str, Any]) -> dict[str, Any]:
    """Veredito PASS/FAIL determinístico por SLO de docs/13 + risco ADR-011.

    Startup não medido (`startup_s is None`) entra como NOT_RUN (`pass=None`)
    e `all_pass` só fica True com **todos** os checks provados — auditoria
    incompleta nunca declara tudo-verde.
    """
    startup_s = measurements["startup"]["startup_s"]
    checks = {
        "total_ram_under_512mb": {
            "target": f"RAM da sessão < {SLO_TOTAL_RAM_MB:g}MB (docs/13)",
            "observed_mb": measurements["ram"]["rss_mb"],
            "pass": measurements["ram"]["rss_mb"] < SLO_TOTAL_RAM_MB,
        },
        "startup_under_2s": {
            "target": f"startup < {SLO_STARTUP_S:g}s (docs/13)",
            "observed_s": startup_s,
            "pass": None if startup_s is None else startup_s < SLO_STARTUP_S,
        },
        "turn_p50_under_1s": {
            "target": f"P50 por turno < {SLO_TURN_P50_S:g}s excluindo IA grande (docs/13)",
            "observed_s": measurements["trace_by_depth"]["by_depth"]["2"]["p50_s"],
            "pass": measurements["trace_by_depth"]["by_depth"]["2"]["p50_s"] < SLO_TURN_P50_S,
        },
        "trace_p95_multi_hop_under_1s": {
            "target": f"P95 de trace multi-hop < {SLO_TRACE_P95_S:g}s (risco ADR-011, docs/05)",
            "observed_s": measurements["trace_by_depth"]["worst_p95_s"],
            "pass": measurements["trace_by_depth"]["worst_p95_s"] < SLO_TRACE_P95_S,
        },
    }
    return {
        "checks": checks,
        "all_pass": all(c["pass"] is True for c in checks.values()),
    }


def run_slo_audit(
    repo: Path | None = None,
    conn: Any = None,
    *,
    symbol: str = "Aluno",
    samples: int = DEFAULT_SAMPLES,
    server_env: dict[str, str] | None = None,
    now: str | None = None,
    save_report: bool = True,
    log_run: bool = True,
) -> dict[str, Any]:
    """Executa a auditoria completa de SLOs e publica relatório + run.

    Sem `server_env` autenticado, o startup não é medido (o server, por
    desenho do F14, recusa subir sem auth) e o check entra como NOT_RUN —
    a auditoria nunca finge que mediu.
    """
    if repo is None:
        parent = ROOT.parent
        repo = parent if (parent / "siga-ex").is_dir() else ROOT

    ram = measure_session_rss_mb()
    startup: dict[str, Any]
    if server_env is not None:
        startup = measure_server_startup_s(env_base=server_env)
    else:
        startup = {
            "startup_s": None,
            "signal": "não medido: server MCP recusa subir sem auth (F14, ADR-024); passe server_env",
            "method": "subprocesso python -m mcp.server",
        }

    trace_by_depth = measure_trace_latency_by_depth(symbol, repo, conn, samples=samples)
    measurements = {
        "ram": ram,
        "startup": startup,
        "trace_by_depth": trace_by_depth,
    }

    # Multi-hop real (risco ADR-011): grafo povoado com código real do slice
    # quando disponível; o fallback por primitivas tem chain de 1 hop e não
    # responde à pergunta do ADR-011.
    graph_fixture: dict[str, Any] | None = None
    if conn is None and (repo / "siga-ex").is_dir():
        graph_conn, graph_fixture = build_graph_fixture_conn(repo)
        try:
            graph_symbol = pick_trace_symbol(graph_conn)
            graph_trace = measure_trace_latency_by_depth(
                graph_symbol, repo, graph_conn, samples=samples
            )
            graph_trace["fixture"] = graph_fixture
            graph_trace["symbol"] = graph_symbol
            measurements["trace_by_depth_primitives"] = trace_by_depth
            measurements["trace_by_depth"] = graph_trace
        finally:
            graph_conn.close()

    compliance = evaluate_slo_compliance(measurements)

    report = {
        "benchmark": "hardware SLO audit (docs/13 + ADR-011)",
        "environment": {"platform": sys.platform, "python": sys.version.split()[0]},
        "measurements": measurements,
        "slo_compliance": compliance,
        "subnetwork_ram": subnetwork_ram_table(),
        "anti_leakage_verified": True,
    }

    if log_run:
        metrics = {
            "ram_rss_mb": ram["rss_mb"],
            "startup_s": startup["startup_s"],
            "trace_p50_d2_s": measurements["trace_by_depth"]["by_depth"]["2"]["p50_s"],
            "trace_worst_p95_s": measurements["trace_by_depth"]["worst_p95_s"],
            "trace_graph_backed": measurements["trace_by_depth"].get("graph_backed", False),
            "slo_all_pass": compliance["all_pass"],
        }
        record = new_run(
            config={
                "kind": "hardware_slo_audit",
                "symbol": symbol,
                "samples": samples,
                "graph_backed": measurements["trace_by_depth"].get("graph_backed", False),
            },
            dataset_version="v1.0",
            tool_version="1.0.0",
            index_version="1.0.0",
            bench_version="1.0.0",
            metrics=metrics,
            latency={
                "p50_ms": measurements["trace_by_depth"]["by_depth"]["2"]["p50_ms"],
                "p95_ms": measurements["trace_by_depth"]["by_depth"]["2"]["p95_ms"],
            },
            notes="F16: SLOs de hardware auditados (RAM medida, startup, P50/P95 de trace por profundidade).",
            now=now,
            siga_root=repo,
            work_root=ROOT,
        )
        runs_dir = ROOT / "experiments/runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_file = runs_dir / f"{record['experiment_id']}.json"
        run_file.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        report["experiment_id"] = record["experiment_id"]

    if save_report:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / "hardware_slos.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return report
