"""Módulo de treinamento e exportação para o Needle (P07-T01, docs/09).

Implementa:
- export_needle: pipeline CANONICAL -> NEEDLE EXPORT
- utilitários de exportação e preparação de dados para o Cactus Needle
"""

from training.export_needle import (
    canonical_to_needle_record,
    export_canonical_to_needle,
)

__all__ = [
    "canonical_to_needle_record",
    "export_canonical_to_needle",
]
