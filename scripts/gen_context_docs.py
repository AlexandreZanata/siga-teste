"""Gerador determinístico da biblioteca de contexto — lotes 2–N (G06, docs/18 §4).

Lote 1 (G05) cobriu `siga-ex` e `sigaex` à mão com grounding verificado; este
gerador estende a biblioteca aos **demais módulos Maven ativos** do clone
(somente leitura) com a mesma garantia: **nenhum path ou símbolo inventado**.

Como o grounding é garantido (regra docs/18 §4):

- todo path citado é construído a partir de `rglob` real do clone no HEAD
  (path só entra na página se existir em disco);
- todo símbolo citado (classes ancinho por categoria de diretório) é verificado
  por `siga_locate` real antes de entrar na página;
- contagens (`*.java`, `*.jsp`, `*.sql`) são medidas, não estimadas;
- `INDEX.md` é regenerado a partir das páginas existentes, com `source_commit`
  resolvido por `git -C <clone> rev-parse HEAD`.

Determinístico: mesma árvore → mesmos bytes (ordenação estável em todas as
etapas). `--check` reconstrói em memória e compara byte a byte (nunca sucesso
falso). Só stdlib + tools deste repo.

Uso:

    python -m scripts.gen_context_docs            # gera/atualiza docs/context/
    python -m scripts.gen_context_docs --check    # valida sem escrever
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from tools.siga_locate import siga_locate

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PACKAGE_ROOT / "docs" / "context"

# Lote 1 (G05) já coberto por páginas manuais — o gerador não as toca.
BATCH_1 = {"siga-ex", "sigaex"}
INDEX_NAME = "INDEX.md"

# Papéis documentados por módulo (docs/00–05, análise P00-T02). Módulo sem
# papel mapeado sai da geração (nunca inventar responsabilidade).
ROLES: dict[str, str] = {
    "siga-ex": "core de negócio documental (entidades, BL, logic, DAO)",
    "sigaex": "camada web do expediente (controllers VRaptor/Spring + JSPs)",
    "siga-base": "base compartilhada (propriedades, utilitários, DpPessoa/DpLotacao)",
    "siga-ws": "serviços SOAP/expostos de integração do expediente",
    "siga-rel": "infraestrutura de relatórios dinâmicos (templates Freemarker)",
    "siga-cp": "núcleo corporativo (configurações, personas, arquivos blob, migrações)",
    "siga-sinc-lib": "biblioteca de sincronização (LRI/legado)",
    "siga-ldap": "integração LDAP do núcleo",
    "siga-web-common": "infra web comum (JPA, Freemarker padrão, suporte JEE)",
    "siga-spring-module": "colagem Spring compartilhada entre módulos web",
    "siga-dump": "exportação/dump de dados",
    "siga": "módulo web raiz (portais, principal, legacy VRaptor do corpo)",
    "sigawf": "camada web do workflow (controllers + JSPs de procedimento)",
    "siga-wf": "núcleo de workflow (WfBL, modelos de procedimento, migrações)",
    "siga-ext": "extensões pontuais do expediente",
    "siga-ldap-cli": "cliente leve de LDAP",
    "siga-jwt": "emissão/validação de JWT para APIs",
    "siga-oidc": "autenticação OIDC (SSO)",
    "siga-integracao": "integrações externas do expediente (serviços e clients)",
    "siga-vraptor-module-old": "módulo VRaptor legado (mantido por compatibilidade)",
    "siga-vraptor-module": "tags/componentes VRaptor compartilhados",
    "sigagc": "gestão de contratos (web + integração)",
    "sigasr": "SIGA-SR (solicitações/requisições: web + núcleo)",
    "sigatp": "SIGA-TP (acompanhamento processual/tabelas: web + núcleo)",
}

# Sufixos de classe por categoria de diretório (padrão observado nos 24 módulos).
ANCHOR_SUFFIXES: dict[str, tuple[str, ...]] = {
    "business_logic": ("BL",),
    "controller": ("Controller",),
    "persistence": ("Dao",),
    "service": ("Service", "ServiceImpl"),
}
CATEGORY_LABELS: dict[str, str] = {
    "business_logic": "Regra de negócio",
    "controller": "Controllers",
    "persistence": "Acesso a dados",
    "service": "Serviços",
}


def _list_modules(clone: Path) -> list[str]:
    """Módulos Maven ativos: diretórios com src/ no clone (ordem estável)."""
    return sorted(
        p.name
        for p in clone.iterdir()
        if p.is_dir() and (p / "pom.xml").is_file() and (p / "src").is_dir()
    )


def _measure(clone: Path, module: str) -> dict[str, int]:
    """Contagens reais de arquivos de produção (`src/main`) por tipo.

    Mesmo critério do lote 1 (G05): só código de produção — `src/test` fora.
    """
    src = clone / module / "src" / "main"
    return {
        kind: sum(1 for _ in src.rglob(f"*.{kind}"))
        for kind in ("java", "jsp", "sql")
    }


def _anchor_symbols(clone: Path, module: str) -> dict[str, list[str]]:
    """Classes ancinho por categoria: existência em disco + resolução real.

    Um símbolo só entra na página se (1) o arquivo existe no clone e
    (2) `siga_locate` o resolve — grounding duplo (disco + tool).
    """
    out: dict[str, list[str]] = {}
    src = clone / module / "src"
    for category, suffixes in ANCHOR_SUFFIXES.items():
        found: list[str] = []
        for suffix in suffixes:
            pattern = f"*{suffix}.java"
            for path in sorted(src.rglob(pattern)):
                name = path.stem
                if name.endswith(suffix) and name not in found:
                    candidates = siga_locate(name, repo=clone, limit=1)
                    # grounding duplo: hit de símbolo OU o próprio arquivo <Nome>.java
                    resolved = any(
                        c.get("symbol") == name
                        or (c.get("file") or "").endswith(f"/{name}.java")
                        for c in candidates
                    )
                    if resolved:
                        found.append(name)
        out[category] = sorted(set(found))
    return out


def _render_page(clone: Path, module: str, role: str, source_commit: str) -> str:
    """Renderiza a página do módulo; só inclui o que foi verificado."""
    m = _measure(clone, module)
    anchors = _anchor_symbols(clone, module)
    parts = sorted(set(anchors["business_logic"] + anchors["controller"] + anchors["persistence"] + anchors["service"]))
    if not parts and m["java"] + m["jsp"] == 0:
        raise ValueError(f"módulo {module!r} sem conteúdo verificado — nada a documentar")

    lines: list[str] = []
    lines.append(f"# {module} — {role}")
    lines.append("")
    lines.append(
        f"> Biblioteca de contexto SIGA (docs/18 §4, G06 — gerada por "
        f"`scripts/gen_context_docs.py`). Fonte de grounding: clone do SIGA em "
        f"`../` @ `{source_commit[:12]}` — cada símbolo abaixo foi resolvido por "
        f"`siga_locate` real e as contagens são medidas no HEAD."
    )
    lines.append("")
    lines.append(f"- **source_commit (SIGA):** `{source_commit}`")
    size_bits = [f"{m['java']} arquivos `.java`"]
    if m["jsp"]:
        size_bits.append(f"{m['jsp']} JSPs")
    if m["sql"]:
        size_bits.append(f"{m['sql']} migrações/SQLs")
    lines.append(f"- **Tamanho medido:** {'; '.join(size_bits)}.")
    lines.append("")
    lines.append("## Responsabilidade")
    lines.append("")
    lines.append(f"Módulo **{role}** do SIGA (mapeamento do `pom.xml` raiz e docs/00–05).")
    lines.append("")
    entry = False

    def _flush(category: str) -> None:
        nonlocal entry
        symbols = anchors.get(category, [])
        if not symbols:
            return
        entry = True
        lines.append(f"### {CATEGORY_LABELS[category]}")
        lines.append("")
        for name in symbols:
            hits = sorted((clone / module / "src").rglob(f"{name}.java"))
            if not hits:
                continue
            rel = hits[0].relative_to(clone).as_posix()
            lines.append(f"- `{rel}` — símbolo `{name}` (resolvido por `siga_locate`).")
        lines.append("")

    _flush("business_logic")
    _flush("controller")
    _flush("service")
    _flush("persistence")
    if not entry:
        lines.append("### Entry points")
        lines.append("")
        lines.append(
            "Módulo sem classes BL/Controller/DAO no padrão comum — navegar pela "
            "árvore `src/` (contagens acima) e pelo índice `INDEX.md`."
        )
        lines.append("")
    lines.append("## Como usar")
    lines.append("")
    lines.append(
        "- Para reverificar um símbolo citado: "
        "`python -c \"from tools.siga_locate import siga_locate; "
        "print(siga_locate('<Simbolo>', repo='..'))\"`;"
    )
    lines.append("- Página gerada deterministicamente: regenerar com "
                 "`python -m scripts.gen_context_docs` após atualizar o clone.")
    lines.append("")
    lines.append("## Provenance")
    lines.append("")
    lines.append(
        "- Gerada por G06 (docs/18 §4) a partir do clone real; verificação "
        "determinística via `tools/siga_locate.py`;"
    )
    lines.append(
        "- Conteúdo derivado de código AGPLv3 — herda as obrigações da licença "
        "(`docs/14`). Sem parecer jurídico."
    )
    lines.append("")
    return "\n".join(lines)


def _render_index(clone: Path, pages: dict[str, str], source_commit: str) -> str:
    lines: list[str] = []
    lines.append("# Biblioteca de contexto SIGA — índice")
    lines.append("")
    lines.append(
        "> Biblioteca de contexto para devs e IAs (docs/18 §4, G05/G06). Cada página é "
        "gerada/validada contra o clone real do SIGA — **nenhum path ou símbolo "
        "inventado**: existência no HEAD e resolução por `siga_locate` (tools "
        "determinísticas deste repo)."
    )
    lines.append("")
    lines.append(f"- **source_commit (SIGA):** `{source_commit}`")
    lines.append(
        "- **Regra:** página desatualizada = recalcular contra o HEAD atual e "
        "atualizar o `source_commit` acima; disparidade entre páginas é sempre "
        "detectável por este campo."
    )
    lines.append("")
    lines.append("## Páginas")
    lines.append("")
    lines.append("| Módulo | Papel | Página | Tamanho medido |")
    lines.append("|---|---|---|---|")
    for module in sorted(set(pages) | BATCH_1):
        m = _measure(clone, module)
        size_bits = [f"{m['java']} `.java`"]
        if m["jsp"]:
            size_bits.append(f"{m['jsp']} JSPs")
        if m["sql"]:
            size_bits.append(f"{m['sql']} SQLs")
        role = ROLES.get(module, "ver página")
        lines.append(f"| `{module}` | {role} | [{module}.md]({module}.md) | {', '.join(size_bits)} |")
    lines.append("")
    covered = sorted(set(pages) | BATCH_1)
    lines.append("## Cobertura")
    lines.append("")
    lines.append(
        f"- **{len(covered)} de 24 módulos Maven ativos** (`pom.xml` raiz) — "
        "lote 1 (núcleo `siga-ex`, `sigaex`) + lotes 2–N (G06, docs/18 §4);"
    )
    lines.append("- Convenção de nome: `docs/context/<modulo>.md`.")
    lines.append("")
    lines.append("## Como usar")
    lines.append("")
    lines.append(
        "- Dev/IA chegando num domínio: começar pela página do módulo; "
        "`siga_locate` para achar símbolos citados; `siga_trace` para o fluxo;"
    )
    lines.append(
        "- Agente com MCP: `siga_context` embute as páginas relevantes no campo "
        "`context_library` da cápsula (integração G06)."
    )
    lines.append("")
    lines.append("## Licença")
    lines.append("")
    lines.append(
        "Conteúdo derivado de código AGPLv3 (SIGA) — herda as obrigações da "
        "licença (`docs/14`). Sem parecer jurídico."
    )
    lines.append("")
    return "\n".join(lines)


def build_plan(clone: Path) -> tuple[str, dict[str, str]]:
    """Constrói o plano completo (páginas novas + INDEX) em memória."""
    head = subprocess.run(
        ["git", "-C", str(clone), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True, timeout=15,
    ).stdout.strip()
    modules = [m for m in _list_modules(clone) if m not in BATCH_1 and m in ROLES]
    pages: dict[str, str] = {}
    for module in modules:
        pages[module] = _render_page(clone, module, ROLES[module], head)
    pages[INDEX_NAME] = _render_index(clone, pages, head)
    return head, pages


def run(out_dir: Path, clone: Path, *, check: bool = False) -> int:
    _, pages = build_plan(clone)
    changed: list[str] = []
    for name, content in sorted(pages.items()):
        filename = name if name == INDEX_NAME else f"{name}.md"
        path = out_dir / filename
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                changed.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if check:
        if changed:
            print(f"check: DESATUALIZADO — {len(changed)} página(s) divergente(s): {changed}")
            return 1
        print(f"check: ok — {len(pages)} páginas em sincronia com o HEAD do clone")
        return 0
    print(f"geradas/atualizadas: {sorted(pages)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera docs/context dos módulos 2–N (G06).")
    parser.add_argument("--check", action="store_true", help="valida sem escrever (exit 1 se divergir)")
    parser.add_argument("--clone", default=str(PACKAGE_ROOT.parent), help="raiz do clone do SIGA")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="diretório de saída")
    args = parser.parse_args(argv)
    return run(Path(args.out), Path(args.clone), check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
