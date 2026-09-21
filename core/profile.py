"""Perfil de projeto — contrato declarativo do chassi genérico (J01, docs/20 §2).

O que é genérico vive em `core/`; o que é específico de um projeto vive num
perfil (`profiles/<projeto>/project.json`). Nenhum path, glob ou nome de
símbolo do SIGA aparece aqui: o perfil declara linguagens, globs de
código/teste, comando de teste, estratégia de símbolos, seeds do bench e a
estratégia de descoberta de módulos.

Formato: JSON (não YAML). Motivo registrado no ADR-034: `yaml` não está na
allowlist V1 de dependências (AGENTS.md §3) e `json` é stdlib — mesmo
conteúdo sem dependência nova.

Validação é fail-closed: perfil incompleto, com estratégia desconhecida ou
JSON malformado levanta `ProfileError` citando o arquivo — nunca sucesso
falso (regra AGENTS.md §4).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REQUIRED_FIELDS: tuple[str, ...] = (
    "name",
    "languages",
    "code_globs",
    "test_globs",
    "test_command",
    "module_discovery",
)

STRATEGIES_DISCOVERY: frozenset[str] = frozenset({"maven", "gradle", "glob", "explicit"})
STRATEGIES_SYMBOL: frozenset[str] = frozenset({"suffix", "annotation", "explicit"})

# Globs de código quando NENHUM perfil está ativo (chassi neutro: qualquer
# projeto comum em Java/JSP/SQL/Python é buscável sem configuração).
DEFAULT_RUNTIME_GLOBS: tuple[str, ...] = ("**/*.java", "**/*.jsp", "**/*.sql", "**/*.py")

# Resolução do perfil ativo (docs/20 §2): env > sentinela ao lado do repo > default.
PROFILE_ENV_VAR = "PROJECT_PROFILE"
PROFILE_FILENAME = "project.json"


class ProfileError(ValueError):
    """Perfil ausente, malformado ou fora do schema (fail-closed)."""


@dataclass(frozen=True)
class ProjectProfile:
    """Contrato imutável do que varia por projeto (docs/20 §2)."""

    name: str
    languages: tuple[str, ...]
    code_globs: tuple[str, ...]
    test_globs: tuple[str, ...]
    test_command: tuple[str, ...]
    module_discovery: str
    module_roots: tuple[str, ...] = ()
    scope_modules: tuple[str, ...] = ()
    symbol_strategy: str = "suffix"
    symbol_suffixes: tuple[str, ...] = field(default_factory=tuple)
    bench_seed_tasks: tuple[str, ...] = field(default_factory=tuple)
    source: str = ""

    def code_scope_modules(self) -> tuple[str, ...]:
        """Prefixos de diretório do escopo de busca, normalizados com barra final.

        Vazio = repositório inteiro (sem priorização de slice). O runtime de
        busca (`retrieval`, `tools`) deriva destes prefixos o que antes era
        hardcode de projeto (constante de slice e globs de módulo):
        - priorização de ranking (arquivos do escopo antes do resto);
        - `find_references`/`find_callers` e fallback do locate — globs
          `<modulo>**` restritos ao escopo.
        """
        return tuple(m if m.endswith("/") else f"{m}/" for m in self.scope_modules)

    def to_dict(self) -> dict[str, Any]:
        """Serialização estável (listas; determinismo para hash/testes)."""
        return {
            "name": self.name,
            "languages": list(self.languages),
            "code_globs": list(self.code_globs),
            "test_globs": list(self.test_globs),
            "test_command": list(self.test_command),
            "module_discovery": self.module_discovery,
            "module_roots": list(self.module_roots),
            "scope_modules": list(self.scope_modules),
            "symbol_strategy": self.symbol_strategy,
            "symbol_suffixes": list(self.symbol_suffixes),
            "bench_seed_tasks": list(self.bench_seed_tasks),
            "source": self.source,
        }


def _require_str_list(data: dict[str, Any], key: str) -> tuple[str, ...]:
    value = data[key]
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
        raise ProfileError(f"campo '{key}' deve ser lista de strings não vazias")
    return tuple(value)


def from_dict(data: Any, source: str = "<memory>") -> ProjectProfile:
    """Constrói o perfil validando o schema — falha citando o arquivo de origem."""
    if not isinstance(data, dict):
        raise ProfileError(f"{source}: conteúdo deve ser um objeto JSON")
    missing = [k for k in REQUIRED_FIELDS if k not in data]
    if missing:
        raise ProfileError(f"{source}: campos obrigatórios ausentes: {', '.join(missing)}")
    name = data["name"]
    if not isinstance(name, str) or not name.strip():
        raise ProfileError(f"{source}: campo 'name' deve ser string não vazia")
    discovery = data["module_discovery"]
    if discovery not in STRATEGIES_DISCOVERY:
        raise ProfileError(
            f"{source}: module_discovery '{discovery}' inválida "
            f"(permitidas: {', '.join(sorted(STRATEGIES_DISCOVERY))})"
        )
    scope_modules = data.get("scope_modules", ())
    if not isinstance(scope_modules, (list, tuple)) or not all(
        isinstance(v, str) and v for v in scope_modules
    ):
        raise ProfileError(f"{source}: campo 'scope_modules' deve ser lista de strings não vazias")
    symbol_strategy = data.get("symbol_strategy", "suffix")
    if symbol_strategy not in STRATEGIES_SYMBOL:
        raise ProfileError(
            f"{source}: symbol_strategy '{symbol_strategy}' inválida "
            f"(permitidas: {', '.join(sorted(STRATEGIES_SYMBOL))})"
        )
    test_command = _require_str_list(data, "test_command")
    return ProjectProfile(
        name=name.strip(),
        languages=_require_str_list(data, "languages"),
        code_globs=_require_str_list(data, "code_globs"),
        test_globs=_require_str_list(data, "test_globs"),
        test_command=test_command,
        module_discovery=discovery,
        module_roots=tuple(data.get("module_roots", ())),
        scope_modules=tuple(scope_modules),
        symbol_strategy=symbol_strategy,
        symbol_suffixes=tuple(data.get("symbol_suffixes", ())),
        bench_seed_tasks=tuple(data.get("bench_seed_tasks", ())),
        source=source,
    )


def load_profile(path: str | Path) -> ProjectProfile:
    """Carrega e valida um `project.json` — erro sempre cita o arquivo."""
    p = Path(path)
    if not p.is_file():
        raise ProfileError(f"perfil não encontrado: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfileError(f"{p}: JSON malformado (linha {exc.lineno}, coluna {exc.colno})") from exc
    return from_dict(data, source=str(p))


def _default_profile() -> ProjectProfile:
    """Chassi neutro quando nenhum perfil está ativo (nunca sucesso falso:
    comportamento documentado, globs genéricos, sem escopo de slice)."""
    return from_dict(
        {
            "name": "default",
            "languages": ["generic"],
            "code_globs": list(DEFAULT_RUNTIME_GLOBS),
            "test_globs": ["**/test_*.py", "**/*_test.py", "**/*Test.java"],
            "test_command": ["true"],
            "module_discovery": "glob",
        },
        source="<runtime default>",
    )


def _detect_profile(root: str | Path | None) -> ProjectProfile | None:
    """Perfil do projeto dono do checkout, por walk-up a partir da raiz
    informada (ou cwd): primeiro diretório com `profiles/*/project.json`.

    - exatamente 1 perfil → carregado;
    - vários → fail-closed citando os caminhos (humano resolve com
      `$PROJECT_PROFILE`);
    - nenhum → None (default neutro).

    Genérico: nenhum nome de projeto no chassi — o perfil é quem declara
    o projeto (docs/20 §2).
    """
    marker = Path(root).resolve() if root is not None else Path.cwd().resolve()
    while True:
        profiles_dir = marker / "profiles"
        if profiles_dir.is_dir():
            found = sorted(profiles_dir.glob(f"*/{PROFILE_FILENAME}"))
            if len(found) == 1:
                return load_profile(found[0])
            if len(found) > 1:
                listing = ", ".join(str(p) for p in found)
                raise ProfileError(
                    f"múltiplos perfis em {profiles_dir} ({listing}); "
                    f"defina ${PROFILE_ENV_VAR} para desambiguar"
                )
            return None
        if marker == marker.parent:
            return None
        marker = marker.parent


def active_profile(root: str | Path | None = None) -> ProjectProfile:
    """Perfil ativo do runtime (docs/20 §2), em ordem de prioridade:

    1. `$PROJECT_PROFILE` — caminho de um `project.json` (fail-closed: caminho
       inválido levanta `ProfileError`, nunca cai silenciosamente no default);
    2. perfil detectado no checkout (`profiles/<projeto>/project.json` a partir
       da raiz informada/cwd, subindo; ambíguo → fail-closed);
    3. default neutro (`DEFAULT_RUNTIME_GLOBS`, escopo = repo inteiro).
    """
    env_path = os.environ.get(PROFILE_ENV_VAR, "").strip()
    if env_path:
        return load_profile(env_path)
    detected = _detect_profile(root)
    if detected is not None:
        return detected
    return _default_profile()


def runtime_scope_modules(root: str | Path | None = None) -> tuple[str, ...]:
    """Escopo do slice do perfil ativo (substitui a constante de slice antiga)."""
    return active_profile(root).code_scope_modules()
