# Decisions (ADRs resumidos)

Formato por decisão: Decision / Reason / Alternatives / Advantages / Disadvantages / Risks / How we validate. Opinião não é fato.

## ADR-001 — Separar pesos ≠ graph ≠ retrieval

- **Decision:** fatos estruturais e código atual nunca entram nos pesos; vivem em graph + retrieval com reindex incremental.
- **Reason:** commits não devem exigir retreino; fatos mudam rápido, padrões mudam devagar.
- **Alternatives:** memorizar SIGA nos pesos; embeddings puros sem graph.
- **Advantages:** atualização barata (`git pull` + reindex); menor dataset; menos hallucination de paths.
- **Disadvantages:** infra de indexação incremental para manter.
- **Risks:** drift índice↔código se updater falhar.
- **Validate:** Phase 2 mede precisão do graph puro; Phase 11 mede custo de update incremental.

## ADR-002 — V1 simples: Python + SQLite/DuckDB + Tree-sitter + ripgrep + Git

- **Decision:** sem K8s/microservices/Neo4j/vector-infra sem necessidade comprovada.
- **Reason:** simplicidade, precisão, manutenção, updates incrementais, CPU-friendly.
- **Alternatives:** Neo4j, LSIF/SCIP pesado, embeddings distribuídos.
- **Validate:** Phase 2 compara precisão/latência/custo; ADR revisita se SLO falhar.

## ADR-003 — Ferramentas: poucas semânticas sobre primitivas determinísticas

- **Decision:** Needle vê `siga_locate/trace/impact/history/context`; primitivas (`find_symbol`, `find_callers`, `read_symbol`, ...) ficam no backend.
- **Reason:** minimizar overlap, respeitar grounding (args vêm de resultados reais, não inventados), seguir guias Cactus de tool design.
- **Alternatives:** dezenas de tools primitivas expostas.
- **Validate:** Phase 5 mede tool selection accuracy, invalid call rate, path/symbol hallucination.

## ADR-004 — Execução por microfases locais (este repo)

- **Decision:** replicar padrão `.local/` (uma microtarefa, uma validação, um commit local, sem push automático).
- **Reason:** permite IAs baratas executarem com segurança e rastreabilidade; barato errar cedo.
- **Alternatives:** plano monolítico executado por IA cara.
- **Validate:** `PROGRESS.md` + `make verify` em cada tarefa; auditoria final P12.

## ADR-023 — GO condicional V1 + release candidate local (P11-T02)

> ADRs 005–022 vivem em `docs/00–17`; a numeração aqui segue a sequência global.

- **Decision:** GO condicional para o slice (executar, sem escalar pesos/distribuição/clientes) + release candidate local reproduzível sem publicar.
- **Reason:** números com evidência: on-policy 1,0 vs large-alone 0,0 (delta +0,3923 vs graph 0,3891) com redução 0,9934 vs arquivos brutos; `make verify` verde; bench isolado; sem segredo/TODO sem ID (regra P11-T02 em `scripts/final_audit.py`).
- **Alternatives:** NO-GO geral (refutado: b=0,3891 > a=0,0); NO-GO controlador/ADR-009 (refutado: tuned ≥ graph em todas as leituras); escalar agora (rejeitado: sem baseline 7, sem RAG, sem edição real).
- **Advantages:** decisão falsificável registrada com `experiment_id`; próximos 20 tasks em `docs/15 §6`.
- **Disadvantages:** slice cobre localização, não edição real (F10 pendente).
- **Risks:** overfit ao holdout de localização; mitigado por splits temporais + gate F20.
- **Validate:** `experiments/reports/final_audit.json` + run final; revalidar no F20 antes de qualquer distribuição.

> Novas decisões entram aqui via tarefas com `docs(...): ...` e referência à fase.
