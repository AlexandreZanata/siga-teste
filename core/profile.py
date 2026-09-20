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
    symbol_strategy: str = "suffix"
    symbol_suffixes: tuple[str, ...] = field(default_factory=tuple)
    bench_seed_tasks: tuple[str, ...] = field(default_factory=tuple)
    source: str = ""

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
