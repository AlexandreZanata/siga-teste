"""Biblioteca de contexto como parte da cápsula (G06, docs/18 §4).

As páginas `docs/context/<modulo>.md` (lote 1 do G05 + lotes 2–N gerados por
`scripts/gen_context_docs.py`) viram contexto selecionável para `siga_context`:
a cápsula passa a apontar as páginas dos módulos onde os símbolos/arquivos
âncora vivem — por existência real (mapeamento símbolo→módulo por `rglob` no
clone), nunca por inferência.

Decisão de custo: a cápsula carrega **ponteiros** (`module`, `page`,
`anchor_symbols`) e não o corpo das páginas — a página completa é lida sob
demanda (`read_page`/`pages_for`). Custo adicional por chamada: O(módulos ×
pocas rglobs) com cache por (clone, página).

Só stdlib + `tools.primitives`; determinístico (ordenação estável).
"""

from __future__ import annotations

from pathlib import Path

CONTEXT_DIR = Path(__file__).resolve().parent.parent / "docs" / "context"
INDEX_NAME = "INDEX.md"

# Páginas do lote 1 (G05) têm módulo implícito pelo nome do arquivo.
_BATCH1_MODULES = ("siga-ex", "sigaex")

_page_cache: dict[tuple[str, str], str] = {}
_module_cache: dict[tuple[str, str], str | None] = {}


def available_pages(context_dir: Path | None = None) -> list[str]:
    """Páginas de módulo existentes (exclui o índice), ordenadas."""
    directory = Path(context_dir) if context_dir else CONTEXT_DIR
    if not directory.is_dir():
        return []
    return sorted(
        p.name
        for p in directory.glob("*.md")
        if p.name != INDEX_NAME
    )


def read_page(name: str, context_dir: Path | None = None) -> str:
    """Lê uma página sob demanda (com cache por processo)."""
    directory = Path(context_dir) if context_dir else CONTEXT_DIR
    key = (str(directory), name)
    if key not in _page_cache:
        path = directory / name
        if not path.is_file():
            raise FileNotFoundError(f"página inexistente: {path}")
        _page_cache[key] = path.read_text(encoding="utf-8")
    return _page_cache[key]


def module_of_symbol(
    symbol: str,
    clone: Path,
    context_dir: Path | None = None,
) -> str | None:
    """Módulo dono do símbolo: único `<Nome>.java` no clone → nome do módulo.

    Existência real como fonte (rglob no clone); `None` se 0 ou 2+ arquivos
    (ambíguo → não adivinhar). Cacheado por processo.
    """
    key = (str(clone), symbol)
    if key in _module_cache:
        return _module_cache[key]
    # Entrada tipo caminho (absoluta, com separador ou terminando em .java)
    # não é símbolo: a rota de arquivos (pages_for) já resolve por prefixo;
    # aqui evita rglob com padrão não-relativo (NotImplementedError).
    if not symbol or "/" in symbol or "\\" in symbol or symbol.endswith(".java"):
        _module_cache[key] = None
        return None
    hits = sorted(clone.rglob(f"{symbol}.java"))
    result: str | None = None
    if len(hits) == 1:
        try:
            module = hits[0].relative_to(clone).parts[0]
        except ValueError:
            module = None
        pages = available_pages(context_dir)
        page_name = f"{module}.md"
        if module and page_name in pages:
            result = module
    _module_cache[key] = result
    return result


def pages_for(
    symbols: list[str],
    files: list[str],
    clone: Path,
    context_dir: Path | None = None,
) -> list[dict]:
    """Ponteiros das páginas relevantes aos símbolos/arquivos da cápsula.

    - símbolo → módulo via `module_of_symbol` (existência real);
    - arquivo → módulo pelo primeiro segmento do caminho, quando a página existe;
    - sem correspondência → entrada vazia (nunca sugestão inventada).
    """
    modules: set[str] = set()
    for sym in symbols:
        m = module_of_symbol(sym, clone, context_dir)
        if m:
            modules.add(m)
    for f in files:
        parts = Path(f).parts
        if parts:
            page_name = f"{parts[0]}.md"
            if page_name in available_pages(context_dir):
                modules.add(parts[0])
    out: list[dict] = []
    for module in sorted(modules):
        page_name = f"{module}.md"
        page_path = Path(context_dir) / page_name if context_dir else CONTEXT_DIR / page_name
        out.append({"module": module, "page": page_name, "path": str(page_path)})
    return out
