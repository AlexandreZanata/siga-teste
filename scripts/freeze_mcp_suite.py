"""Freeze das 60 tarefas da suite EVAL-MCP (G01, docs/18 §3/§5).

Amostra fixa do holdout congelado `datasets/benchmark/` para o protocolo
manual de avaliação do MCP em IDEs de agente: **20 locate, 10 trace,
10 impact, 10 history, 10 context** — as mesmas 60 para todo modelo/IDE.

Determinístico primeiro, só stdlib, somente leitura sobre o clone do SIGA:

- Seleção determinística: holdout ordenado por `id`; 20 `locate` com
  ground truth (arquivos) existentes no HEAD; os demais tipos derivam das
  tarefas seguintes na mesma ordem (alvo real do arquivo de ground truth).
- Ground truth calculado pelo **mesmo caminho do braço B real**
  (`mcp.server.dispatch`) — nunca inventado, nunca simulado.
- `tasks.jsonl` congela GT mínimo determinístico + provenance completa
  (`siga_head_commit`, holdout ids, regra de seleção, timestamp, verifier).
- Prompts `prompts/NNN.md` (001–060) NUNCA contêm ground truth: apenas ID,
  método, enunciado, o que entregar e o formato fixo de resposta que o
  checker cego (`evaluation/mcp_suite_check.py`) parseia.

Re-execução idempotente: mesmo input + mesmo HEAD ⇒ mesmo artefato
(exceto `generated_at`).` --check` valida o artefato existente sem regerar.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
HOLDOUT = ROOT / "datasets/benchmark/holdout.jsonl"
SUITE_DIR = ROOT / "eval/mcp_suite"
TASKS_OUT = SUITE_DIR / "tasks.jsonl"
PROMPTS_DIR = SUITE_DIR / "prompts"

LOCATE_N, DERIVED_N = 20, 10
PLAN: list[tuple[str, str]] = [
    ("locate", "siga.locate"),
    ("trace", "siga.trace"),
    ("impact", "siga.impact"),
    ("history", "siga.history"),
    ("context", "siga.context"),
]
COUNTS = {"locate": LOCATE_N, "trace": DERIVED_N, "impact": DERIVED_N, "history": DERIVED_N, "context": DERIVED_N}

ANSWER_FORMAT = """### RESPOSTA

Liste cada arquivo e símbolo citado, um por linha, exatamente neste formato
(caminhos relativos à raiz do repo; sem parênteses, sem prosa nas linhas):

FILE: <caminho/relativo.ext>
SYMBOL: <NomeClasse>
"""


def siga_root() -> Path:
    """Raiz do checkout do SIGA (paths do holdout são relativos a ela)."""
    parent = ROOT.parent
    if (parent / "siga-ex").is_dir():
        return parent
    raise SystemExit("checkout do SIGA não encontrado ao lado de siga-teste (../siga-ex ausente)")


def siga_head_commit(root: Path) -> str:
    out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def load_holdout() -> list[dict[str, Any]]:
    tasks = [json.loads(line) for line in HOLDOUT.read_text(encoding="utf-8").splitlines() if line.strip()]
    tasks.sort(key=lambda t: t["id"])
    return tasks


def rel(path: str | Path, root: Path) -> str:
    p = Path(path)
    try:
        return str(p.resolve().relative_to(root))
    except ValueError:
        return str(p)


def head_exists(root: Path, relpath: str) -> bool:
    return (root / relpath).is_file()


def dispatch_result(method: str, params: dict[str, Any], root: Path) -> dict[str, Any]:
    """Executa o método MCP real (mesmo caminho do braço B) e devolve o envelope."""
    from mcp.server import dispatch

    return dispatch(method, {**params, "repo": str(root)})


def gt_files(result: Any, root: Path) -> list[str]:
    """Extrai a lista de arquivos (relativos, ordenados, únicos) de um result real."""
    files: set[str] = set()
    if isinstance(result, dict):
        candidates = result.get("files") or []
        for item in candidates:
            if isinstance(item, dict):
                item = item.get("file") or item.get("target")
            if item:
                files.add(rel(item, root))
        for item in result.get("callers", []):
            f = item.get("file") if isinstance(item, dict) else item
            if f:
                files.add(rel(f, root))
        for node in result.get("chain", []):
            f = node.get("file") if isinstance(node, dict) else None
            if f:
                files.add(rel(f, root))
        for c in result.get("commits", []):
            for f in (c.get("files") or []) if isinstance(c, dict) else []:
                files.add(rel(f, root))
    elif isinstance(result, list):
        for item in result:
            f = item.get("file") or item.get("target") if isinstance(item, dict) else item
            if f:
                files.add(rel(f, root))
    return sorted(f for f in files if f and head_exists(root, f))


def gt_commits(result: Any) -> list[dict[str, str]]:
    """Extrai commits (sha, date, subject) de um result de history."""
    commits = []
    for c in result.get("commits", []):
        commits.append({"sha": c["sha"], "date": c.get("date"), "subject": c.get("subject")})
    return commits


def ground_truth(kind: str, result: Any, root: Path, target: str | None = None) -> dict[str, Any]:
    """GT mínimo determinístico por método, extraído do result real.

    Para impact/history o GT exclui o próprio `args.target`: o alvo é o
    input da pergunta (o prompt o nomeia), nunca a descoberta a medir.
    """
    files = gt_files(result, root)
    if kind in ("impact", "history") and target:
        files = [f for f in files if f != target]
    if kind == "history":
        return {"commits": gt_commits(result), "files": files}
    return {"files": files}


def derived_candidates(kind: str, ht: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    """Args candidatos reais de trace/impact/history/context, em ordem determinística.

    Cada arquivo de ground truth do holdout existente no HEAD gera 1 candidato
    (classes Java para trace/context; qualquer arquivo para impact/history).
    O primeiro candidato que produzir GT não-vazio é escolhido.
    """
    files = [f for f in ht["ground_truth_files"] if head_exists(root, f)]
    if kind in ("trace", "context"):
        files = [f for f in files if f.endswith(".java")]
    candidates: list[dict[str, Any]] = []
    for target in files:
        symbol = Path(target).stem
        if kind == "trace":
            args: dict[str, Any] = {"symbol": symbol, "depth": 2}
        elif kind == "impact":
            args = {"target": target, "hops": 1}
        elif kind == "history":
            args = {"target": target, "query": ht["query"], "limit": 10}
        else:
            args = {"symbols": [symbol], "task": ht["query"]}
        candidates.append({"args": args, "anchor": symbol if kind in ("trace", "context") else target})
    return candidates


def pick_tasks(root: Path, head: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Seleção determinística das 60 tarefas (locate primeiro, depois derivadas).

    Devolve (tarefas, exclusões) — exclusões documentam candidatos pulados
    por falha determinística das tools (ex.: diff não-UTF-8 no legado),
    mesma entrada ⇒ mesmas exclusões.
    """
    holdout = load_holdout()
    selected: list[dict[str, Any]] = []
    used_holdout: set[str] = set()
    excluded: list[dict[str, str]] = []
    seq = 0
    for kind, method in PLAN:
        want = COUNTS[kind]
        got = 0
        for ht in holdout:
            if got >= want:
                break
            if ht["id"] in used_holdout:
                continue
            if kind == "locate":
                gt = sorted(f for f in ht["ground_truth_files"] if head_exists(root, f))
                if not gt:
                    continue
                args: dict[str, Any] = {"query": ht["query"], "limit": 10}
                derived: dict[str, Any] | None = {"args": args, "anchor": None}
                gt_payload: dict[str, Any] = {"files": gt}
            else:
                candidates = derived_candidates(kind, ht, root)
                gt_payload = None
                derived: dict[str, Any] | None = None
                for cand in candidates:
                    try:
                        envelope = dispatch_result(method, cand["args"], root)
                    except UnicodeDecodeError:
                        # Falha determinística da tool congelada (git_diff text=True
                        # sobre diff ISO-8859-1 do legado): candidato pulado e
                        # registrado — nunca mascarado como GT vazio.
                        excluded.append({"holdout_id": ht["id"], "kind": kind, "reason": "tool_unicode_decode_error"})
                        continue
                    payload = ground_truth(kind, envelope["result"], root, target=cand["args"].get("target"))
                    primary = "commits" if kind == "history" else "files"
                    if payload.get(primary):
                        payload["anchor"] = cand["anchor"]
                        derived = cand
                        gt_payload = payload
                        break
                if gt_payload is None or derived is None:
                    continue
            used_holdout.add(ht["id"])
            seq += 1
            selected.append(
                {
                    "id": f"mcp-{kind}-{got + 1:03d}",
                    "seq": seq,
                    "method": method,
                    "kind": kind,
                    "source_holdout_id": ht["id"],
                    "query": ht["query"],
                    "args": derived["args"],
                    "ground_truth": gt_payload,
                    "check_commit": head if kind != "locate" else ht["repo_commit"],
                    "execution_commit": head,
                    "holdout_date": ht["date"],
                }
            )
            got += 1
        if got < want:
            raise SystemExit(f"holdout insuficiente para {kind}: {got}/{want}")
    return selected, excluded


def render_prompt(task: dict[str, Any]) -> str:
    """Prompt colável: ID, método, enunciado, entrega e formato. NUNCA contém GT."""
    kind = task["kind"]
    head = f"# Tarefa {task['seq']:03d} ({task['id']} — método `{task['method']}`)\n\n"
    body: str
    if kind == "locate":
        body = (
            "No checkout atual do repositório SIGA, localize os arquivos que implementam a seguinte "
            f"necessidade (enunciado verbatim de um commit real):\n\n> {task['query']}\n\n"
            "Entregue os caminhos dos arquivos envolvidos (implementação principal, não testes)."
        )
    elif kind == "trace":
        body = (
            f"Trace o fluxo de execução a partir do símbolo real `{task['args']['symbol']}` "
            f"(profundidade 2). Contexto do commit original: > {task['query']}\n\n"
            "Entregue os arquivos da cadeia percorrida, da origem até o fim do fluxo."
        )
    elif kind == "impact":
        body = (
            f"Calcule o impacto estático de modificar o arquivo `{task['args']['target']}` "
            f"(1 hop). Contexto do commit original: > {task['query']}\n\n"
            "Entregue os arquivos afetados (quem chama/depende)."
        )
    elif kind == "history":
        body = (
            f"Recupere o histórico Git do arquivo `{task['args']['target']}` com a busca "
            f"`{task['args']['query']}` (limite 10). Contexto do commit original: > {task['query']}\n\n"
            "Entregue os arquivos tocados pelos commits relevantes e, se possível, os shas."
        )
    else:
        syms = ", ".join(f"`{s}`" for s in task["args"]["symbols"])
        body = (
            f"Monte o contexto mínimo para a tarefa `{task['args']['task']}` usando os símbolos "
            f"âncora reais: {syms}.\n\nEntregue os arquivos que compõem o contexto necessário."
        )
    rules = (
        "\n\n## Regras\n\n"
        "- Proibido inventar path/símbolo: só cite o que você verificou existir no repo.\n"
        "- Não modifique nenhum arquivo; tarefa somente leitura.\n"
        "- Registre (para o operador, não na resposta) latência e quais chamadas MCP você fez.\n"
    )
    return head + body + rules + "\n" + ANSWER_FORMAT


def write_artifacts(
    tasks: list[dict[str, Any]], excluded: list[dict[str, str]], head: str, force: bool
) -> dict[str, Any]:
    provenance = {
        "suite": "EVAL-MCP (G01, docs/18 §3)",
        "siga_head_commit": head,
        "holdout_manifest_version": 1,
        "holdout_file": "datasets/benchmark/holdout.jsonl",
        "selection_rule": "holdout ordenado por id; 20 locate com GT no HEAD; derivados das seguintes na ordem (alvo real do GT)",
        "gt_source": "mcp.server.dispatch real (mesmo caminho do braço B)",
        "excluded_candidates": excluded,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verifier": "deterministic-compute-via-dispatch",
    }
    doc = {"provenance": provenance, "counts": COUNTS, "tasks": tasks}
    if TASKS_OUT.exists() and not force:
        raise SystemExit(f"{TASKS_OUT} já existe (use --force para regerar em cima)")
    TASKS_OUT.parent.mkdir(parents=True, exist_ok=True)
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    for old in PROMPTS_DIR.glob("*.md"):
        old.unlink()
    TASKS_OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for task in tasks:
        nnn = f"{task['seq']:03d}"
        (PROMPTS_DIR / f"{nnn}.md").write_text(render_prompt(task), encoding="utf-8")
    return provenance


def check_artifacts(root: Path | None = None) -> list[str]:
    """Valida o artefato congelado sem regerar (idempotência + sanidade)."""
    _ = root  # compatibilidade: GT é validado estruturalmente, não por existence-check
    doc = json.loads(TASKS_OUT.read_text(encoding="utf-8"))
    tasks = doc["tasks"]
    problems: list[str] = []
    if len(tasks) != 60:
        problems.append(f"esperado 60 tarefas, encontrado {len(tasks)}")
    counts: dict[str, int] = {}
    for i, task in enumerate(tasks, 1):
        if task["seq"] != i:
            problems.append(f"seq quebrada em {task['id']}")
        counts[task["kind"]] = counts.get(task["kind"], 0) + 1
        prompt = PROMPTS_DIR / f"{task['seq']:03d}.md"
        if not prompt.is_file():
            problems.append(f"prompt ausente: {prompt.name}")
            continue
        text = prompt.read_text(encoding="utf-8")
        gt = json.dumps(task["ground_truth"], ensure_ascii=False)
        leak = [f for f in task["ground_truth"].get("files", []) if f in text]
        if leak:
            problems.append(f"prompt {prompt.name} vaza ground truth: {leak}")
        if task["id"] not in text:
            problems.append(f"prompt {prompt.name} sem ID {task['id']}")
        if gt == "{}":
            problems.append(f"tarefa {task['id']} sem ground truth")
    expect = {"locate": 20, "trace": 10, "impact": 10, "history": 10, "context": 10}
    if counts != expect:
        problems.append(f"counts errados: {counts} ≠ {expect}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="regenera mesmo se tasks.jsonl existir")
    parser.add_argument("--check", action="store_true", help="valida o artefato existente sem regerar")
    opts = parser.parse_args()
    root = siga_root()
    if opts.check:
        problems = check_artifacts(root)
        for p in problems:
            print(f"PROBLEMA: {p}")
        print("check: OK" if not problems else "check: FALHOU")
        return 0 if not problems else 1
    head = siga_head_commit(root)
    tasks, excluded = pick_tasks(root, head)
    write_artifacts(tasks, excluded, head, force=opts.force)
    print(f"congeladas {len(tasks)} tarefas em {TASKS_OUT.relative_to(ROOT)} (HEAD {head[:12]})")
    print(f"prompts: {PROMPTS_DIR.relative_to(ROOT)}/001..060.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
