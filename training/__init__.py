"""Módulo de treinamento e exportação para o Needle (P07-T01, docs/09).

Implementa:
- export_needle: pipeline CANONICAL -> NEEDLE EXPORT
- utilitários de exportação e preparação de dados para o Cactus Needle
"""

from training.compress import (
    STEP_DEPTHS,
    calculate_footprint,
    evaluate_subnetwork_progression,
    find_smallest_viable_subnetwork,
    publish_compression_report,
)
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
from training.onpolicy import (
    PatchedStudent,
    accuracy,
    correct_failure,
    learn_patch,
    mine_failures,
    run_onpolicy_loop,
    select_target_regions,
)

__all__ = [
    "DATASET_SIZES",
    "DEPTHS",
    "STEP_DEPTHS",
    "PatchedStudent",
    "accuracy",
    "calculate_footprint",
    "canonical_to_needle_record",
    "correct_failure",
    "evaluate_subnetwork_progression",
    "export_canonical_to_needle",
    "find_smallest_viable_subnetwork",
    "learn_patch",
    "mine_failures",
    "publish_compression_report",
    "publish_lora_curves",
    "run_dataset_progression",
    "run_depth_progression",
    "run_onpolicy_loop",
    "select_target_regions",
]
