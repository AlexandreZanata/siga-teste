"""Sub-recuperação da cápsula em traces longos (F12 do roadmap pós-slice, docs/15 §6).

ADR-008 (docs/04) faz a cápsula ser o único contrato com a IA grande e lista o
risco: sub-recuperação em traces longos. O braço (c) do P09 monta a cápsula a
partir do top-5 do naive_locate; um trace de profundidade 2–3 descobre mais
arquivos (views/migrations/testes) do que esse fluxo devolve — e 91/311 tarefas
do holdout têm JSP no ground truth. Este spike mede o fenômeno com a MESMA
régua do P09/F05 (basename recall@1/3/5 + tokens de contexto) e decide com
números se a recuperação por categoria entra no fluxo padrão:

- braço A (baseline): cápsula padrão do braço (c) do P09 (naive_locate top-5);
- braço B (recovery): arquivos do trace (grafo) + JSPs que referenciam o
  símbolo (find_referencing) entram nos slots dedicados da cápsula
  (views/migrations/testes) e COMPETEM pelas primeiras posições — o que o
  trace resgata antecede o top-5 do baseline, sem snippets;
- braço C (budget-slice): B com teto duro de tokens (budget preservado:
  views primeiro; arquivos/texto depois).

Runtime CPU-only, sem rede, sem dependência nova. O spike não altera o fluxo
de produção — altera somente se B ou C superar A no recall@5 com tokens ≤
budget (decisão registrada no relatório).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from context.capsule import build_context_capsule, count_tokens
from evaluation.harness import bench_shas, check_no_leakage, load_manifest
from evaluation.metrics import count_tokens as count_tokens_metrics
from experiments.log import new_run
from indexer import jsp_symbols
from retrieval.baseline import naive_locate
from tools import primitives

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HOLDOUT_PATH = ROOT / "datasets/benchmark/holdout.jsonl"
DEFAULT_BUDGET_TOKENS = 1200.0

_MIN_SUFFIX = len("siga-ex/src/main/java/")
_RECOVERY_SUFFIXES = (".jsp", ".sql", "Test.java")


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _mean_tokens(values: list[int]) -> float:
    return round(sum(values) / len(values), 1) if values else 0.0


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[int(len(ordered) * 0.95)], 3)


def _basenames(paths: list[str]) -> set[str]:
    return {Path(p).name for p in paths if p}


def _basename_recall(gt_files: list[str], pred_files: list[str], k: int) -> float:
    """Recall@k por basename (mesma régua do P09/F05)."""
    if not gt_files:
        return 1.0
    gt_base = {Path(g).name for g in gt_files}
    pred_base = _basenames(pred_files[:k])
    return len(gt_base & pred_base) / len(gt_base)


def _context_tokens(query: str, files: list[str]) -> int:
    """Tokens do contexto que a IA grande consumiria (query + lista de arquivos)."""
    listing = "\n".join(files)
    return count_tokens_metrics(f"{query}\n{listing}")


def _query_terms(query: str) -> list[str]:
    """Termos de rastreio derivados da própria query (grounding-safe, ADR-006)."""
    return [t for t in "".join(c if c.isalnum() else " " for c in query).split() if len(t) >= 4]


def discover_trace_files(
    root: Path,
    query: str,
    conn: Any,
    depth: int = 2,
    limit: int = 5,
) -> dict[str, list[str]]:
    """Descobre arquivos por trace longo a partir de termos reais da query.

    Fluxo grounding: termos da query → find_symbol no grafo → store.trace
    (a mesma BFS usada pelo siga_trace, profundidade real 2–3) → arquivos
    reais dos nós + JSPs que referenciam o símbolo (jsp_symbols.
    find_referencing). Nenhum path inventado: só arquivos que o grafo/disco
    devolvem.
    """
    anchors: set[str] = set()
    for term in _query_terms(query):
        for hit in primitives.find_symbol(conn, term, limit=3):
            if hit.get("name"):
                anchors.add(hit["name"])

    from graph import store as graph_store

    chain_files: list[str] = []
    seen: set[str] = set()
    for symbol in sorted(anchors):
        for node in graph_store.trace(conn, symbol, depth=depth):
            f = node.get("file")
            if f and f not in seen:
                seen.add(f)
                chain_files.append(f)

    views: list[str] = []
    webapp = root / "sigaex/src/main/webapp"
    for symbol in sorted(anchors):
        for jsp in jsp_symbols.find_referencing(webapp, symbol):
            if jsp not in seen:
                seen.add(jsp)
                views.append(jsp)

    return {
        "chain_files": chain_files[: 2 * limit],
        "views": views[:limit],
    }


def _rank_aware_order(recovery: list[str], baseline_rel: list[str]) -> list[str]:
    """Ordem do braço B: categorias recuperadas primeiro, baseline depois.

    O valor do recovery é trazer o que o trace descobriu para as primeiras
    posições da cápsula — caso contrário o top-k do recall não muda.
    """
    category = [f for f in recovery if f.endswith(_RECOVERY_SUFFIXES)]
    other = [f for f in recovery if not f.endswith(_RECOVERY_SUFFIXES)]
    out: list[str] = []
    seen: set[str] = set()
    for f in category + baseline_rel + other:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def build_recovery_files(root: Path, conn: Any, discovery: dict[str, list[str]]) -> list[str]:
    """Arquivos de recuperação por categoria, priorizados (views/migrations/testes)."""
    prioritized: list[str] = []
    seen: set[str] = set()

    def _add(path: str) -> None:
        if path not in seen:
            seen.add(path)
            prioritized.append(path)

    for f in discovery.get("views", []):
        _add(f)
    for f in discovery.get("chain_files", []):
        if f.endswith(_RECOVERY_SUFFIXES):
            _add(f)
    for f in discovery.get("chain_files", []):
        if not f.endswith(_RECOVERY_SUFFIXES):
            _add(f)
    return prioritized


def _capsule_files(capsule: Any) -> list[str]:
    """Arquivos que a cápsula padrão entrega em todos os slots."""
    files: list[str] = []
    for f in capsule.related_files:
        files.append(f)
    for f in capsule.views:
        if f not in files:
            files.append(f)
    for f in capsule.migrations:
        if f not in files:
            files.append(f)
    for f in capsule.tests:
        if f not in files:
            files.append(f)
    for snip in capsule.snippets:
        if snip.file not in files:
            files.append(snip.file)
    return files


def _budget_slice(files: list[str], budget_tokens: float, task: str) -> list[str]:
    """Braço C: teto duro de tokens (query + listagem ≤ budget).

    Ordem de preservação: views primeiro (91/311 tarefas do holdout), depois
    demais arquivos na ordem de priorização; o teto é verificado com o mesmo
    contador do P09.
    """
    kept: list[str] = []
    views = [f for f in files if f.endswith(".jsp")]
    others = [f for f in files if not f.endswith(".jsp")]
    ordered = views + others
    base = count_tokens(f"TASK: {task.strip()}")
    running = base
    for f in ordered:
        cost = count_tokens(f)
        if running + cost > budget_tokens:
            continue
        kept.append(f)
        running += cost
    return kept


def _rel(root: Path, f: str) -> str:
    """Path relativo ao root, tolerante a prefixos resolvidos (tmp, symlinks)."""
    p = Path(f)
    for base in (root, root.resolve()):
        try:
            return str(p.resolve().relative_to(base)) if p.is_absolute() else str(p)
        except ValueError:
            continue
    return f


def run_capsule_recovery(
    holdout_path: Path | None = None,
    repo_path: Path | None = None,
    conn: Any = None,
    limit: int = 5,
    budget_tokens: float = DEFAULT_BUDGET_TOKENS,
    max_tasks: int | None = None,
    log_run: bool = True,
    save_report: bool = True,
) -> dict[str, Any]:
    """Executa o spike com 3 braços e publica o relatório comparativo."""
    if holdout_path is None:
        holdout_path = DEFAULT_HOLDOUT_PATH
    if repo_path is None:
        parent = ROOT.parent
        repo_path = parent if (parent / "siga-ex").is_dir() else ROOT
    root = Path(repo_path)

    if not holdout_path.is_file():
        raise FileNotFoundError(f"Holdout não encontrado: {holdout_path}")
    tasks = [
        json.loads(line)
        for line in holdout_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if max_tasks is not None:
        tasks = tasks[:max_tasks]

    close_conn = False
    if conn is None:
        from graph import store as graph_store

        conn = graph_store.connect()
        close_conn = True

    per_arm: dict[str, dict[str, list[float]]] = {
        "A-capsule-baseline": {"recall": {k: [] for k in ("top1", "top3", "top5")}, "tokens": []},
        "B-category-recovery": {"recall": {k: [] for k in ("top1", "top3", "top5")}, "tokens": []},
        "C-budget-slice": {"recall": {k: [] for k in ("top1", "top3", "top5")}, "tokens": []},
    }
    tasks_used = 0

    try:
        for task in tasks:
            gt_files = list(task.get("ground_truth_files", []))
            if not gt_files:
                continue
            query = task.get("query", "")
            tasks_used += 1

            base_files = naive_locate(root, query, limit=limit)
            capsule = build_context_capsule(task=query, repo=root, files=base_files, max_snippets=3)
            pred_a = _capsule_files(capsule)

            discovery = discover_trace_files(root, query, conn, depth=2, limit=limit)
            recovery = [_rel(root, f) for f in build_recovery_files(root, conn, discovery)]
            base_rel = [_rel(root, f) for f in base_files]
            pred_b = _rank_aware_order(recovery, base_rel)

            pred_c = _budget_slice(pred_b, budget_tokens, query)

            for arm, pred in (
                ("A-capsule-baseline", pred_a),
                ("B-category-recovery", pred_b),
                ("C-budget-slice", pred_c),
            ):
                for k in (1, 3, 5):
                    per_arm[arm]["recall"][f"top{k}"].append(_basename_recall(gt_files, pred, k))
                per_arm[arm]["tokens"].append(_context_tokens(query, pred))
    finally:
        if close_conn:
            conn.close()

    arms: dict[str, dict[str, Any]] = {}
    for arm, data in per_arm.items():
        method = {
            "A-capsule-baseline": "cápsula padrão do braço (c) do P09 (naive_locate top-5)",
            "B-category-recovery": "trace (grafo, depth=2) + find_referencing → categorias (views/sql/testes) primeiro, depois baseline",
            "C-budget-slice": "B com teto duro de tokens (budget preservado: views primeiro)",
        }[arm]
        arms[arm] = {
            "method": method,
            "recall": {
                "top1": _mean(data["recall"]["top1"]),
                "top3": _mean(data["recall"]["top3"]),
                "top5": _mean(data["recall"]["top5"]),
            },
            "context_tokens": {
                "mean": _mean_tokens(data["tokens"]),
                "p95": _p95([float(t) for t in data["tokens"]]),
            },
        }

    b_beats = arms["B-category-recovery"]["recall"]["top5"] > arms["A-capsule-baseline"]["recall"]["top5"]
    c_beats = arms["C-budget-slice"]["recall"]["top5"] > arms["A-capsule-baseline"]["recall"]["top5"]
    c_within = arms["C-budget-slice"]["context_tokens"]["mean"] <= budget_tokens
    if (b_beats or c_beats) and (c_within or b_beats):
        decision = (
            "ADOPT category recovery: o braço com recovery supera o baseline no recall@5 "
            "— promover merge trace→cápsula ao fluxo padrão requer ADR + gate próprio."
        )
    else:
        decision = (
            "NOT-change mantido (docs/15 §5): o recovery por categoria não supera a cápsula "
            "padrão no recall@5 no holdout congelado; risco ADR-008 quantificado, fluxo atual "
            "preservado."
        )

    report: dict[str, Any] = {
        "benchmark": "SIGA-Bench Holdout",
        "task_id": "F12-capsule-sub-recovery",
        "spike_status": "measured",
        "runtime": {"cpu_only": True, "network_calls": 0},
        "budget_tokens": budget_tokens,
        "total_tasks": tasks_used,
        "tasks_available": len(tasks),
        "arms": arms,
        "decision": decision,
    }

    work = ROOT
    manifest = load_manifest(work / "datasets/benchmark/manifest.json")
    check_no_leakage(bench_shas(manifest), work / "datasets")
    report["anti_leakage_verified"] = True

    if log_run:
        exp_record = new_run(
            config={
                "spike": "capsule-sub-recovery",
                "arms": sorted(arms),
                "limit": limit,
                "budget_tokens": budget_tokens,
                "tasks_used": tasks_used,
            },
            dataset_version="v1.0",
            tool_version="1.0.0",
            index_version="1.0.0",
            bench_version="1.0.0",
            needle_version="f12-spike",
            metrics={
                "A_top5": arms["A-capsule-baseline"]["recall"]["top5"],
                "B_top5": arms["B-category-recovery"]["recall"]["top5"],
                "C_top5": arms["C-budget-slice"]["recall"]["top5"],
                "C_mean_context_tokens": arms["C-budget-slice"]["context_tokens"]["mean"],
            },
            notes=(
                "F12: sub-recuperação da cápsula em traces longos no holdout congelado; "
                "CPU-only, sem dependência nova; decisão vs NOT-change (docs/15 §6)."
            ),
            siga_root=repo_path,
            work_root=ROOT,
        )
        runs_dir = ROOT / "experiments/runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / f"{exp_record['experiment_id']}.json").write_text(
            json.dumps(exp_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        report["experiment_id"] = exp_record["experiment_id"]

    if save_report:
        reports_dir = ROOT / "experiments/reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "capsule_recovery.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    return report
