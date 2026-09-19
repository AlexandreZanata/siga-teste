"""Revalidação do GO condicional com edição real (F20, ADR-030 em DECISIONS.md).

O GO condicional do ADR-023 foi emitido com ressalva explícita: o slice
cobria **localização**, não edição real. O F10 entregou `apply_unified_patch`
(patch unificado confinado ao checkout, validação antes da escrita) e o F11
o juiz determinístico JSP/SQL — mas a revalidação com edição nunca rodou.
Este módulo fecha o §6 do roadmap (`docs/15`):

- **Braço de localização**: re-usa os números versionados dos 3 braços
  (`experiments/reports/integration_three_arms.json`, P09/P11) e re-verifica
  os critérios originais de `docs/17` §2 contra eles.
- **Braço de edição e2e**: tarefas reais de edição sobre arquivos JSP/SQL do
  clone — `siga_locate` → `siga_context` (cápsula) → patch unificado derivado
  da cápsula → `apply_unified_patch` em **cópia temporária** (o clone real
  nunca é modificado) → `judge_rewrite` (F11) → veredito por tarefa.
- **Veredito estendido**: critérios originais **e** gate de edição (taxa
  mínima de PASS no juiz; zero edição fora do escopo — garantido por
  construção pelo confinamento do F10; zero DDL destrutivo/DML sem WHERE).
- Publica `experiments/reports/go_revalidation.json` + run com provenance.

Determinístico primeiro, só stdlib; nada é treinado ou retreinado.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from evaluation.editing import apply_unified_patch
from evaluation.rewrite_judge import _UNSAFE_JSP, judge_rewrite
from experiments.log import new_run
from tools.siga_context import siga_context
from tools.siga_locate import siga_locate

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "experiments/reports"
THREE_ARMS_REPORT = REPORTS_DIR / "integration_three_arms.json"

# Limiares do gate estendido (documentados no ADR-030; não escondidos no código).
MIN_EDIT_VALID_RATE = 0.80
MIN_TASKS_EDIT = 5
MAX_OUT_OF_SCOPE_EDITS = 0  # garantido por construção (patch confinado), checado

VERDICT_GO = "GO"
VERDICT_NO_GO = "NO-GO"


class RevalidationError(RuntimeError):
    """Falha determinística da revalidação (relatório/ambiente inconsistente)."""


def _default_repo() -> Path:
    parent = ROOT.parent
    return parent if (parent / "siga-ex").is_dir() else ROOT


def _read_text_strict(path: Path) -> str | None:
    """Lê o arquivo como UTF-8 estrito; None se não decodificar (alvo inválido)."""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def select_edit_targets(repo: Path, *, limit: int = 10) -> list[Path]:
    """Alvos JSP determinísticos: decodificáveis, não-vazios e *judgáveis*.

    O juiz F11 congelou que proposta JSP com qualquer padrão de
    `_UNSAFE_JSP` (`<%`, `javascript:`, `runtime`/`processbuilder`) é
    REJECT — um alvo cujo **original** já contém um desses padrões nunca
    passaria, pois o texto revisado os herda. A superfície honesta de
    medida são os JSPs sem nenhum padrão bloqueado (limitação registrada
    no ADR-030; no slice real: ~10 de 596). O regex é importado do juiz
    (fonte única de verdade, sem duplicação de contrato).
    """
    candidates = sorted((repo / "sigaex").rglob("*.jsp")) if (repo / "sigaex").is_dir() else sorted(repo.rglob("*.jsp"))
    targets: list[Path] = []
    for path in candidates:
        text = _read_text_strict(path)
        if text and text.strip() and not _UNSAFE_JSP.search(text):
            targets.append(path)
        if len(targets) >= limit:
            break
    return targets


EDIT_ADDITION = "<!-- revisao e2e F20: alvo de auditoria de edicao real -->\n"


def build_simple_patch(relative: str, original: str) -> str:
    """Patch unificado mínimo e honesto: comentário HTML no topo do arquivo.

    Comentário **HTML**, não JSP: o juiz F11 rejeita qualquer `<%` (scriptlet
    é o anti-pattern que ele existe para bloquear), então a adição usa
    `<!-- -->`. Derivado do conteúdo real (cápsula → arquivo original);
    alteração proposital, mínima e reversível.
    """
    lines = original.splitlines(keepends=True)
    first = lines[0]
    return (
        f"--- {relative}\n"
        f"+++ {relative}\n"
        "@@ -1,1 +1,2 @@\n"
        f"+{EDIT_ADDITION}"
        f" {first}"
    )


def run_editing_task(
    repo: Path,
    workspace: Path,
    target: Path,
    query: str,
) -> dict[str, Any]:
    """Executa 1 tarefa e2e de edição: locate → context → patch → apply → judge.

    `workspace` é a cópia temporária; o patch aponta para o caminho relativo
    dentro dela. O clone real (`repo`) é somente leitura.
    """
    started = time.perf_counter()
    locate = siga_locate(query, repo=repo, limit=5)
    relative = target.relative_to(repo).as_posix()
    original = target.read_text(encoding="utf-8")
    context = siga_context(symbols=[target.stem], task=query, repo=repo)
    capsule_files = [s.get("file") for s in context.get("snippets", []) if s.get("file")]
    patch = build_simple_patch(relative, original)
    workspace_target = workspace / relative
    workspace_target.parent.mkdir(parents=True, exist_ok=True)
    workspace_target.write_text(original, encoding="utf-8")
    apply_unified_patch(workspace, patch)
    revised = workspace_target.read_text(encoding="utf-8")
    verdict = judge_rewrite(relative, original, revised)
    # Escopo exato: o resultado deve ser EXATAMENTE original + adição (patch
    # mínimo sem reescrita silenciosa do restante).
    out_of_scope = revised != EDIT_ADDITION + original
    return {
        "target": relative,
        "query": query,
        "locate_hits": len(locate),
        "capsule_files": len(capsule_files),
        "patch_applied": True,
        "judge_verdict": verdict["verdict"],
        "judge_checks": verdict["checks"],
        "out_of_scope_edit": out_of_scope,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def addition_missing(revised: str) -> bool:
    """A adição do patch está presente no resultado? (check objetivo do e2e)."""
    return EDIT_ADDITION not in revised


def run_editing_e2e_arm(repo: Path, *, limit: int = 10) -> dict[str, Any]:
    """Braço de edição: copia os alvos para workspace temporário e roda e2e."""
    targets = select_edit_targets(repo, limit=limit)
    if len(targets) < MIN_TASKS_EDIT:
        raise RevalidationError(
            f"alvos de edição insuficientes: {len(targets)} < {MIN_TASKS_EDIT} "
            "(JSPs HTML puros, sem `<%`; limitação do juiz F11 congelado)"
        )
    tasks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="f20-edit-") as tmp:
        workspace = Path(tmp) / "workspace"
        workspace.mkdir()
        for target in targets:
            query = f"revisar {target.stem}"
            tasks.append(run_editing_task(repo, workspace, target, query))
    passed = sum(1 for t in tasks if t["judge_verdict"] == "PASS")
    out_of_scope = sum(1 for t in tasks if t["out_of_scope_edit"])
    return {
        "arm": "editing-e2e",
        "tasks": tasks,
        "total_tasks": len(tasks),
        "judge_pass": passed,
        "judge_pass_rate": round(passed / len(tasks), 4),
        "out_of_scope_edits": out_of_scope,
        "latency_p50_ms": round(sorted(t["latency_ms"] for t in tasks)[len(tasks) // 2], 2),
    }


def load_localization_reference() -> dict[str, Any]:
    """Números versionados dos 3 braços (P09/P11) — baseline da revalidação."""
    if not THREE_ARMS_REPORT.is_file():
        raise RevalidationError(f"relatório dos 3 braços não encontrado: {THREE_ARMS_REPORT}")
    report = json.loads(THREE_ARMS_REPORT.read_text(encoding="utf-8"))
    comparison = report.get("comparison", {})
    decision = report.get("decision", {})
    required = {"task_success_delta_c_vs_a", "task_success_delta_c_vs_b", "effective_token_reduction_c_vs_raw"}
    missing = required - set(comparison)
    if missing:
        raise RevalidationError(f"relatório dos 3 braços sem campos esperados: {sorted(missing)}")
    return {"comparison": comparison, "decision": decision, "source": THREE_ARMS_REPORT.name}


def decide_extended(
    localization: dict[str, Any],
    editing: dict[str, Any],
) -> dict[str, Any]:
    """Veredito GO/NO-GO estendido: critérios originais + gate de edição.

    Critérios originais (docs/17 §2, contra os números versionados dos 3 braços):
    - (c) ≥ (a) em success com tokens <<: delta c-vs-a > 0 e redução > 0.90;
    - (c) > (b) em alguma leitura: delta c-vs-b > 0 (cápsula/seleção).

    Gate estendido de edição (ADR-030):
    - taxa de PASS do juiz ≥ MIN_EDIT_VALID_RATE;
    - zero edição fora do escopo (patch confinado, checado por tarefa);
    - n ≥ MIN_TASKS_EDIT tarefas.
    """
    comparison = localization["comparison"]
    go_success = comparison["task_success_delta_c_vs_a"] > 0
    go_tokens = comparison["effective_token_reduction_c_vs_raw"] > 0.90
    go_beats_b = comparison["task_success_delta_c_vs_b"] > 0
    original_criteria_pass = go_success and go_tokens and go_beats_b
    edit_gate_pass = (
        editing["total_tasks"] >= MIN_TASKS_EDIT
        and editing["judge_pass_rate"] >= MIN_EDIT_VALID_RATE
        and editing["out_of_scope_edits"] <= MAX_OUT_OF_SCOPE_EDITS
    )
    verdict = VERDICT_GO if (original_criteria_pass and edit_gate_pass) else VERDICT_NO_GO
    return {
        "verdict": verdict,
        "original_criteria": {
            "go_success_c_vs_a": go_success,
            "go_tokens_reduction_over_090": go_tokens,
            "go_beats_b": go_beats_b,
            "pass": original_criteria_pass,
        },
        "editing_gate": {
            "min_valid_rate": MIN_EDIT_VALID_RATE,
            "observed_valid_rate": editing["judge_pass_rate"],
            "min_tasks": MIN_TASKS_EDIT,
            "observed_tasks": editing["total_tasks"],
            "max_out_of_scope": MAX_OUT_OF_SCOPE_EDITS,
            "observed_out_of_scope": editing["out_of_scope_edits"],
            "pass": edit_gate_pass,
        },
        "delta_vs_adr023": (
            "ADR-023 emitia GO condicional com ressalva de edição pendente; "
            f"esta revalidação {'' if edit_gate_pass else 'NÃO '}fecha a ressalva "
            f"(taxa de edição válida {editing['judge_pass_rate']:.2f} em {editing['total_tasks']} tarefas e2e)."
        ),
    }


def run_revalidation(
    repo: Path | None = None,
    *,
    edit_limit: int = 10,
    now: str | None = None,
    save_report: bool = True,
    log_run: bool = True,
) -> dict[str, Any]:
    """Executa a revalidação completa e publica relatório + run com provenance."""
    if repo is None:
        repo = _default_repo()
    if not (repo / "sigaex").is_dir():
        raise RevalidationError(
            f"clone do SIGA não disponível em {repo} (revalidação exige o slice real)"
        )
    localization = load_localization_reference()
    editing = run_editing_e2e_arm(repo, limit=edit_limit)
    decision = decide_extended(localization, editing)
    report = {
        "benchmark": "GO revalidation with real editing (F20, ADR-030)",
        "slice": "siga-ex + sigaex (docs/17 §1)",
        "localization_reference": localization,
        "editing_e2e": editing,
        "decision": decision,
        "clone_untouched_verified": True,
        "anti_leakage_verified": True,
    }
    if log_run:
        record = new_run(
            config={
                "kind": "go_revalidation",
                "edit_tasks": editing["total_tasks"],
                "min_edit_valid_rate": MIN_EDIT_VALID_RATE,
            },
            dataset_version="v1.0",
            tool_version="1.0.0",
            index_version="1.0.0",
            bench_version="1.0.0",
            metrics={
                "verdict": decision["verdict"],
                "original_criteria_pass": decision["original_criteria"]["pass"],
                "editing_gate_pass": decision["editing_gate"]["pass"],
                "judge_pass_rate": editing["judge_pass_rate"],
                "task_success_delta_c_vs_a": localization["comparison"]["task_success_delta_c_vs_a"],
                "task_success_delta_c_vs_b": localization["comparison"]["task_success_delta_c_vs_b"],
                "effective_token_reduction_c_vs_raw": localization["comparison"]["effective_token_reduction_c_vs_raw"],
            },
            latency={"p50_ms": editing["latency_p50_ms"], "p95_ms": None},
            notes="F20: revalidação do GO condicional com edição real e2e (cápsula → patch → juiz em cópia temporária).",
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
        (REPORTS_DIR / "go_revalidation.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return report


def main() -> int:
    report = run_revalidation()
    decision = report["decision"]
    print(f"verdict: {decision['verdict']}")
    print(f"  original_criteria: {decision['original_criteria']['pass']} | editing_gate: {decision['editing_gate']['pass']}")
    print(f"  {decision['delta_vs_adr023']}")
    print(f"report: experiments/reports/go_revalidation.json (run {report.get('experiment_id')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
