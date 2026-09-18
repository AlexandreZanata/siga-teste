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

> Novas decisões entram aqui via tarefas com `docs(...): ...` e referência à fase.
