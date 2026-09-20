"""Chassi genérico do SIGA Needle Expert (docs/20 §2).

Tudo que é independente de projeto vive aqui; o que é específico de um
projeto vive em `profiles/<projeto>/project.json` (contrato em
`core.profile`). O core nunca importa packages acoplados ao SIGA
(`tools`, `retrieval`, `graph`, `indexer`...) — apenas stdlib e o próprio
`core`. Regra enforceada por `tests/test_boundaries.py`.
"""

from core.profile import (
    ProjectProfile,
    ProfileError,
    from_dict,
    load_profile,
)

__all__ = [
    "ProjectProfile",
    "ProfileError",
    "from_dict",
    "load_profile",
]
