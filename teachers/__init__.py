"""Módulo teachers (P06-T01, ADR-016 em docs/08).

Multi-teacher data factory com prompts versionados:
- DeepSeek V4.1 Flash
- Gemini 3.8 Flash
- Muse Spark 1.3
"""

from teachers.generator import (
    generate_candidate_for_teacher,
    generate_multi_teacher_candidates,
    load_teacher_prompt,
)
from teachers.selection import (
    build_canonical_gold_record,
    process_task_to_gold,
    score_candidate,
    select_shortest_correct,
)

__all__ = [
    "load_teacher_prompt",
    "generate_candidate_for_teacher",
    "generate_multi_teacher_candidates",
    "score_candidate",
    "select_shortest_correct",
    "build_canonical_gold_record",
    "process_task_to_gold",
]
