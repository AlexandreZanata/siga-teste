# 01 — Problem definition: SIGA Needle Expert

## 1. O que é

Nano-coprocessador (baseline: Needle 2/3, `docs/00-research.md`) que, dada uma tarefa de desenvolvimento no SIGA, decide quais ferramentas de repository intelligence usar, navega no grafo/código/Git e devolve uma **cápsula mínima de contexto** para uma IA grande fazer o raciocínio complexo e a edição final. Não substitui a IA grande para programar.

## 2. Responsabilidades do nano

Compreender intenção → escolher tools → localizar arquivos/classes/métodos/símbolos → identificar controllers/APIs/entidades/regras/JSPs-SQL-migrations → seguir call graphs (callers/callees) → dependências → Git history → implementações semelhantes → impacto → testes relacionados → recuperar mínimo necessário → gerar cápsula estruturada.

Fora do escopo do nano: edição final, raciocínio arquitetural aberto, geração de código longo, decisões de produto.

## 3. Fluxo

```text
Developer → Large Coding Agent → SIGA Needle Expert → Repository Tools
→ AST / Code Graph / Git / Search → Context Capsule → Large Coding Agent → Code Modification
```

## 4. Separação de conhecimento (ADR-001 em `../DECISIONS.md`)

1. **Pesos:** arquitetura geral, vocabulário SIGA, padrões, como investigar, sequências de tools, quando pedir mais contexto, como compactar. Nunca fatos mutáveis.
2. **Graph:** arquivos, módulos, classes, métodos, símbolos, refs, callers/callees, imports, herança, endpoints, controllers, entities, DAOs, JSPs, SQL, migrations, tests, deps Maven, relações.
3. **Retrieval:** conteúdo exato atual, snippets, diffs recentes, configs. Novo commit = `git pull` + reindex incremental, sem retreino.

## 5. Métrica central

```text
effective_token_reduction = 1 - tokens_with_expert / tokens_without_expert
```

Sempre junto com `task_success_delta`. Sucesso exige `task_success >= X` com `tokens << Y`, `latência <= Z` (ou menor no total) e `custo << C`. Redução de tokens com queda relevante de success é fracasso. Métricas completas em `docs/10-siga-bench.md` + `docs/11-evaluation.md` (P00-T04).

## 6. Casos de uso V1 (slice `siga-ex` + `sigaex`)

Locate file/symbol, trace endpoint→view, impacto 1-hop, history/co-change, testes relacionados, queries ambíguas/off-topic/no-tool/insuficientes. Detalhes do experimento em `docs/17-first-experiment.md` (P00-T05).

## 7. Non-goals V1

Substituir IA grande; memorizar SIGA nos pesos; K8s/microservices/Neo4j sem ADR; dataset massivo antes de curvas 100→10k; benchmark contaminado; envio de código privado a serviços externos no runtime.
