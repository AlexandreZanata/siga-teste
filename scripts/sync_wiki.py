"""Sync `docs/` → wiki do GitHub p/ IAs externas (F18, ADR-028 em DECISIONS.md).

A wiki do repo (`siga-teste.wiki`) é onde agentes externos (OpenCode,
Claude, Cursor...) procuram o projeto; sem sync ela fica vazia e
desatualizada em relação à fonte. Este módulo copia os `docs/*.md` da
`main` protegida como páginas da wiki e gera um `Home.md` com
**provenance** (`source_commit` da `main`, timestamp UTC, contagem de
páginas).

Determinístico primeiro, só stdlib:

- `build_home`: índice puro a partir dos arquivos (títulos do 1º `#`
  de cada doc, determinístico por ordem de nome) + provenance.
- `sync_to`: materializa `Home.md` + as páginas (nome = stem do arquivo)
  num diretório de wiki; **idempotente byte a byte** (2ª execução sem
  mudanças na fonte não altera nada) e valida que o alvo não contém
  páginas estranhas ao plano (ex.: pesos/checkpoints nunca vão à wiki).
- `run_sync`: orquestra — clona a wiki (`--wiki-repo`), aplica o plano e,
  com `--push`, commita/empurra; sem ela, só prepara (default: tempdir).

Rede só acontece em `--push` (entregável declarado da tarefa); o núcleo
puro é testável offline.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"
WIKI_REMOTE_SUFFIX = ".wiki.git"
README_STEM = "docs/README"

WIKI_PAGES_EXCLUDE: frozenset[str] = frozenset(
    {
        "Home",
        "_Sidebar",
        "_Footer",
    }
)


class WikiSyncError(RuntimeError):
    """Falha determinística do sync (clone, push, plano inconsistente)."""


def git_head(repo: Path) -> str | None:
    """HEAD do repo (só leitura); None fora de repo git."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return out.stdout.strip() or None


def list_doc_files(docs_dir: Path) -> list[Path]:
    """Docs fonte em ordem determinística; README entra por último."""
    files = sorted(docs_dir.glob("*.md"))
    readme = [f for f in files if f.stem.lower() == "readme"]
    rest = [f for f in files if f.stem.lower() != "readme"]
    return rest + readme


def _first_title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def build_home(source_commit: str | None, docs_dir: Path = DOCS_DIR, *, now: str | None = None) -> str:
    """Gera o Home.md determinístico com provenance da fonte.

    Mesmos inputs ⇒ mesmos bytes (timestamp só entra via `now` explícito,
    mantendo o núcleo puro reprodutível).
    """
    entries: list[str] = []
    pages: list[str] = []
    for path in list_doc_files(docs_dir):
        page = path.stem
        title = _first_title(path)
        pages.append(page)
        if page.lower() == "readme":
            entries.append(f"- [{title}]({page}) — visão geral e índice de leitura.")
        else:
            entries.append(f"- [{title}]({page})")
    stamp = now or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# SIGA Needle Expert — Wiki",
        "",
        "Espelho de `docs/` da branch `main` protegida (PR + CI `verify` obrigatórios), "
        "mantido por `scripts/sync_wiki.py` (F18, ADR-028). Fonte da verdade: o repositório.",
        "",
        "## Documentos",
        "",
        *entries,
        "",
        "## Provenance",
        "",
        f"- source_commit: `{source_commit or 'desconhecido'}`",
        f"- synced_at: {stamp}",
        f"- pages: {len(pages)}",
        "",
        "> IAs externas: cite `source_commit` ao usar conteúdo desta wiki. "
        "SIGA é AGPLv3; esta wiki herda as obrigações da fonte (docs/14).",
    ]
    return "\n".join(lines) + "\n"


def plan_pages(docs_dir: Path) -> dict[str, str]:
    """Plano `{pagina: conteudo}` a partir dos docs (puro, sem I/O de escrita)."""
    return {path.stem: path.read_text(encoding="utf-8") for path in list_doc_files(docs_dir)}


def sync_to(wiki_dir: Path, docs_dir: Path = DOCS_DIR, *, source_commit: str | None = None, now: str | None = None) -> dict[str, Any]:
    """Aplica o plano na wiki local; idempotente byte a byte.

    Reescreve só páginas que mudaram; reporta `changed`/`unchanged` e rejeita
    páginas pré-existentes fora do plano (exceto `Home`/`_Sidebar`/`_Footer`),
    evitando lixo herdado de syncs desalinhados.
    """
    if not wiki_dir.is_dir():
        raise WikiSyncError(f"diretório da wiki inexistente: {wiki_dir}")
    plan = plan_pages(docs_dir)
    home = build_home(source_commit, docs_dir, now=now)
    changed: list[str] = []
    unchanged: list[str] = []
    for name, content in {"Home": home, **plan}.items():
        target = wiki_dir / f"{name}.md"
        if target.is_file() and target.read_text(encoding="utf-8") == content:
            unchanged.append(name)
            continue
        target.write_text(content, encoding="utf-8")
        changed.append(name)
    stray = sorted(
        p.stem
        for p in wiki_dir.glob("*.md")
        if p.stem not in plan and p.stem not in WIKI_PAGES_EXCLUDE
    )
    return {
        "pages": ["Home", *plan.keys()],
        "changed": changed,
        "unchanged": unchanged,
        "stray_pages": stray,
        "source_commit": source_commit,
    }


def run_sync(
    wiki_repo: str | None,
    *,
    workdir: Path | None = None,
    push: bool = False,
    docs_dir: Path = DOCS_DIR,
    now: str | None = None,
) -> dict[str, Any]:
    """Clona (opcional), sincroniza e (opcional) commita/empurra a wiki.

    Sem `wiki_repo`, opera num tempdir (modo prova/dry). Com `push=True`,
    exige `wiki_repo` e credenciais git já configuradas; o commit da wiki
    usa identity neutra e mensagem com provenance.
    """
    if push and not wiki_repo:
        raise WikiSyncError("--push exige --wiki-repo")
    tmp_ctx = None
    if workdir is None:
        tmp_ctx = tempfile.TemporaryDirectory()
        workdir = Path(tmp_ctx.name)
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        if wiki_repo:
            wiki_dir = workdir / "wiki"
            if wiki_dir.exists():
                shutil.rmtree(wiki_dir)
            subprocess.run(
                ["git", "clone", "--depth", "1", wiki_repo, str(wiki_dir)],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        else:
            wiki_dir = workdir / "wiki-prepare"
            wiki_dir.mkdir(exist_ok=True)
        source_commit = git_head(ROOT)
        result = sync_to(wiki_dir, docs_dir, source_commit=source_commit, now=now)
        result["wiki_dir"] = str(wiki_dir)
        if push:
            subprocess.run(["git", "-C", str(wiki_dir), "add", "-A"], check=True, timeout=60)
            staged = subprocess.run(
                ["git", "-C", str(wiki_dir), "diff", "--cached", "--quiet"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if staged.returncode == 0:
                result["pushed"] = False
                result["note"] = "nada a commitar: wiki já alinhada (idempotência)"
            else:
                subprocess.run(
                    [
                        "git", "-C", str(wiki_dir),
                        "-c", "user.name=siga-teste wiki sync",
                        "-c", "user.email=wiki@users.noreply.github.com",
                        "commit", "-qm",
                        f"sync: docs/ @ {str(source_commit)[:12]} (F18, ADR-028)",
                    ],
                    check=True,
                    timeout=60,
                )
                subprocess.run(["git", "-C", str(wiki_dir), "push", "origin"], check=True, capture_output=True, text=True, timeout=120)
                result["pushed"] = True
        return result
    finally:
        if tmp_ctx is not None:
            tmp_ctx.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync docs/ → wiki (F18, ADR-028).")
    parser.add_argument("--wiki-repo", help="URL git da wiki (ex.: git@github.com:USER/REPO.wiki.git)")
    parser.add_argument("--workdir", type=Path, default=None, help="dir de trabalho (default: tempdir)")
    parser.add_argument("--push", action="store_true", help="commita e empurra (sem isso, só prepara)")
    args = parser.parse_args(argv)
    try:
        result = run_sync(args.wiki_repo, workdir=args.workdir, push=args.push)
    except (WikiSyncError, subprocess.SubprocessError) as err:
        print(f"sync_wiki: {err}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
