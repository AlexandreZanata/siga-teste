"""Módulo de treinamento e exportação para o Needle (P07-T01, docs/09).

Implementa:
- export_needle: pipeline CANONICAL -> NEEDLE EXPORT
- utilitários de exportação e preparação de dados para o Cactus Needle
"""

from training.export_needle import (
    canonical_to_needle_record,
    export_canonical_to_needle,
)
from training.lora_progression import (
    DATASET_SIZES,
    DEPTHS,
    publish_lora_curves,
    run_dataset_progression,
    run_depth_progression,
)

__all__ = [
    "DATASET_SIZES",
    "DEPTHS",
    "canonical_to_needle_record",
    "export_canonical_to_needle",
    "publish_lora_curves",
    "run_dataset_progression",
    "run_depth_progression",
]
