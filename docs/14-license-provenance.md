# 14 — License & provenance: AGPLv3 sem parecer jurídico

> **Não é parecer jurídico.** Apenas riscos e pontos que exigem revisão por profissional habilitado antes de distribuir datasets, checkpoints, índices ou publicar.

## 1. Fatos

SIGA licenciado sob GNU AGPLv3 (`../LICENSE`, `docs/02 §1`). Este repo declara `AGPL-3.0-or-later` (`pyproject.toml`).

## ADR-022 — Provenance obrigatória desde o dia 1

- **Decision:** todo artefato derivado (dataset, checkpoint `.cact`/adapter, índice SQLite, bench, doc com snippet) carrega `{repo_commit, source file, teacher, prompt_version, timestamp, generator/verifier versions, task type, ground-truth source, license}` (`docs/07 §2`).
- **Reason:** sem provenance, qualquer revisão de licença vira arqueologia; com ela, remover/regenerar subconjuntos é mecânico.
- **Alternatives:** provenance parcial ("só commit").
- **Advantages:** auditoria e takedown granulares; publicação científica reproduzível.
- **Disadvantages:** custo de armazenamento de metadados (irrelevante perto do dataset).
- **Risks:** campo ausente em trajetória antiga — teste de contrato do schema canonical barra.
- **Validate:** `test-contract` do formato canonical a partir da P06.

## 2. Pontos p/ revisão profissional

(a) datasets derivados de código AGPL distribuídos externamente; (b) checkpoints LoRA treinados sobre esse código (obra derivada?); (c) índices/grafos com snippets; (d) `siga-teste` aninhado em checkout AGPL; (e) pesos Needle base (Apache-2.0) mesclados com adapter treinado em AGPL; (f) publicação de bench com diffs reais. Uso interno sem distribuição tem risco menor, mas confirmar.
