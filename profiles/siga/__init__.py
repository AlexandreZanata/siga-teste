"""Perfil do projeto-piloto SIGA (docs/20 §2).

Derivado do baseline medido do master plan — nada aqui é inventado: os 25
módulos Maven e as extensões Java/JSP/SQL vêm de `scripts/siga_stats.py` e
do HEAD `48610bd6` do clone. O formato é JSON (não YAML) por decisão do
ADR-034.
"""

from __future__ import annotations

from pathlib import Path

from core.profile import ProjectProfile, load_profile

PROFILE_PATH = Path(__file__).resolve().parent / "project.json"


def load() -> ProjectProfile:
    """Carrega e valida o `project.json` do SIGA (fail-closed)."""
    return load_profile(PROFILE_PATH)
