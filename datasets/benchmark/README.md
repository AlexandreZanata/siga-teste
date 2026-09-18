# datasets/benchmark/ — holdout isolado (P04-T02, docs/10 ADR-018)

**PROIBIDO para treino.** Nenhum SHA daqui pode aparecer em
`datasets/{raw,canonical,verified}` — `make test-contract` quebra o build se aparecer.

- `manifest.json`: T1/T2 congelados + seed de 9 SHAs + ponteiro do holdout.
- `holdout.jsonl`: 311 tarefas `commit-localization` (120 train / 120 valid / 71 test),
  freeze via `evaluation/freeze_holdout.py` (seed 42, 1–8 arquivos de código do slice).
  Cada linha: `{id, repo_commit, parent_commit, date, query, task_type,
  ground_truth_files, source, split, category}`.
- Tarefa = prever `ground_truth_files` a partir de `query` (mensagem do commit)
  no estado `parent_commit` (N-1) vs diff real (N).
- Slots reservados para a P06 (teachers, fora deste freeze): `ambiguous`,
  `off-topic`, `no-tool`, `insufficient` (~1/8 off-topic, docs/00 §1.5).
