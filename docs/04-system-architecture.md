# 04 — System architecture: nano-controlador + graph + IA grande

> Fluxo e separação definidos em `docs/01-problem-definition.md`. Aqui: componentes, fronteiras e ADRs.

## 1. Componentes e fluxo

```text
Developer → Large Coding Agent → [SIGA Expert]
  → Needle (decide tool + args grounding-safe, docs/03 ADR-006)
  → Tools semânticas (docs/06) → primitivas determinísticas
  → Graph (docs/05) + código atual (retrieval) + Git
  → Context Capsule mínima → Large Coding Agent → edição
```

O backend executa tools, alimenta resultados ao Needle via `complete()`, aplica verifier determinístico a cada passo e aborta/escala em `[]`, `suppressed_calls` ou falha de grounding. Nenhum path/símbolo gerado livremente atravessa sem existir no graph.

## ADR-007 — Backend orquestra, Needle decide

- **Decision:** loop multi-hop (`run()`/`complete()`, até N passos) vive no backend Python; Needle decide apenas "qual tool + quais args" por turno.
- **Reason:** Needle é single-shot por natureza (`docs/03` L3); estado, budget de passos e validação são responsabilidade determinística testável.
- **Alternatives:** `agent.run()` da lib como loop principal.
- **Advantages:** controle de custo/latência, abort determinístico, provenance por passo.
- **Disadvantages:** mais código próprio de orquestração.
- **Risks:** divergir do comportamento validado da lib.
- **Validate:** suite congelada por ambiente (padrão `needle.environments`) roda nos dois loops na P05.

## ADR-008 — Cápsula como único contrato com a IA grande

- **Decision:** a IA grande recebe apenas a cápsula (`context/capsule.py`), nunca acesso livre ao repo via Expert.
- **Reason:** é onde mora a economia (`effective_token_reduction`); isola medição de custo×success.
- **Alternatives:** Expert como MCP genérico de busca livre.
- **Advantages:** medição limpa dos 3 braços do slice; sem vazamento de contexto.
- **Disadvantages:** cápsula ruim = teto do success.
- **Risks:** sub-recuperação em traces longos.
- **Validate:** comparar JSON vs texto compacto na P09; `task_success_delta` decide.

## ADR-009 — Plano B se o Needle falhar como controlador

- **Decision:** se o slice refutar ADR-005, rebaixar Needle a extrator (`needle.extract` p/ spans/args) e promover controlador por regras + reranker sobre o graph determinístico.
- **Reason:** decisão falsificável exige saída honrosa documentada antes do experimento.
- **Alternatives:** insistir em LoRA maior; trocar de vendor sem critério.
- **Advantages:** trabalho de graph/tools/dataset é reaproveitado integralmente.
- **Disadvantages:** dois controladores para manter durante a transição.
- **Risks:** apego ao modelo (sunk cost).
- **Validate:** gatilho numérico no slice (P00-T05/`docs/17`): tuned ≤ determinístico ⇒ aciona plano B.

## 2. Mapa de módulos (implementado nas Fases 1–10)

`indexer/` (java/jsp/sql/maven/git) → `graph/` (SQLite) → `retrieval/` + `tools/` (5 semânticas + primitivas) → `inference/` (orquestrador + Needle) → `context/` (cápsula) → `mcp/` (servidor fino). Transversal: `task_factory/` + `teachers/` + `verifier/` → `datasets/` → `training/` → `evaluation/` + `experiments/`. Fronteiras testadas em `tests/test_boundaries.py` (P01-T01): `tools/inference` não importam `teachers`; `training` não importa `mcp`.
