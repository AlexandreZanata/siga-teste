# 05 — Repository intelligence: indexer + code graph

> Escala e alvos em `docs/02-siga-repository-analysis.md`. Decisões em ADR resumido; cada tecnologia justificada por simplicidade, precisão, performance, manutenção, updates incrementais, portabilidade e facilidade p/ agentes.

## 1. Dimensionamento (medido 2026-09-18, `desenvolvimento`)

Slice V1 (`siga-ex` 6.3M + `sigaex` 22M de `src/`; 506 + 270 Java; 597 JSPs em `sigaex`): cabe inteiro em SQLite local com folga de ordens de magnitude. Conclusão: nenhuma database distribuída se justifica na V1.

## ADR-010 — Parser Java: Tree-sitter primeiro, JavaParser como reserva

- **Decision:** extração Java via Tree-sitter (`tree-sitter-java`) com gramática tolerante a código legado; JavaParser (ou JDT/Spoon) só se a precisão em `siga-ex`/`sigaex` ficar abaixo do alvo na P02.
- **Reason:** simplicidade + portabilidade (binding Python, sem JVM no runtime) + robustez a arquivos que não compilam isolados; precisão suficiente p/ símbolos/refs/imports/herança.
- **Alternatives:** Eclipse JDT (precisão máxima, exige JVM + classpath Maven resolvido); Spoon/srcML (reescrita/AST rico, pesado p/ V1); language servers/SCIP/LSIF (indexação cara, overkill p/ 776 arquivos).
- **Advantages:** incremental, CPU-friendly, sem toolchain Java no índice.
- **Disadvantages:** resolução de tipos aproximada (overloads, generics complexos).
- **Risks:** call graph impreciso em polimorfismo VRaptor/Spring.
- **Validate:** P02 mede precisão de símbolos/callers em amostra etiquetada de `ExBL.java`, `ExTramiteBL.java`, `ExDocumentoController.java`; gatilho de troca documentado.

## ADR-011 — Store: SQLite (WAL) como padrão; DuckDB sob avaliação

- **Decision:** SQLite em WAL p/ nodes/edges + FTS5 p/ busca textual; DuckDB avaliado na P02 apenas para agregações analíticas (centralidade, co-change).
- **Reason:** manutenção zero, arquivo único versionável por hash, updates incrementais triviais, portabilidade total; FTS5 cobre `search_text` sem serviço extra.
- **Alternatives:** Neo4j (consultas de grafo expressivas, servidor + ops injustificáveis); Tantivy dedicado (ótimo, mas segundo índice p/ manter).
- **Advantages:** `git pull` + reindex incremental = `UPDATE` por arquivo; backup = copiar arquivo.
- **Disadvantages:** traversals profundos em SQL recursivo em vez de Cypher.
- **Risks:** P95 de traces multi-hop acima do SLO → reavaliar.
- **Validate:** P02 publica latência P50/P95 de `trace` 3-hop no slice.

## ADR-012 — Busca textual: ripgrep como primitiva, FTS5 como índice

- **Decision:** `search_text` = ripgrep sobre checkout real (verdade atual) + FTS5 sobre corpus indexado (rápido); divergência entre eles = sinal de drift do índice.
- **Reason:** precisão (rg lê o código atual, não o índice) + performance; sem infra de embeddings na V1.
- **Alternatives:** embeddings/RAG vetorial (recall semântico, custo + drift + GPU).
- **Advantages:** zero dependência nova; resultados citáveis por `file:linha`.
- **Disadvantages:** sinônimos PT-BR ("tramitação" vs "trâmite" vs "movimentação") exigem normalização própria.
- **Risks:** recall baixo em queries vagas — mitigado por `siga_locate` com expansão de vocabulário SIGA aprendida no dataset.
- **Validate:** Recall@5 do determinístico publicado na P03 antes de qualquer embedding.

## 2. Schema do graph (V1)

Nodes: `repository, module, file, package, class, interface, enum, method, field, endpoint, controller, entity, DAO, service, JSP, table, migration, test, commit, feature`.
Edges: `CONTAINS, DEFINES, CALLS, CALLED_BY, EXTENDS, IMPLEMENTS, IMPORTS, USES, ENDPOINT, HANDLED_BY, VIEW, ENTITY, PERSISTED_BY, READS_TABLE, WRITES_TABLE, MIGRATION, TESTED_BY, DEPENDS_ON, CHANGED_WITH, MODIFIED_BY`.
Entidades JPA detectadas por `@Entity` (ex.: `siga-ex/.../ex/ExDocumento.java`); controllers por sufixo `*Controller.java` + rotas VRaptor (`siga-vraptor-module/.../SigaRoutesParser.java`); migrations Flyway por `siga-cp/.../db/migration/CORPORATIVO_UTF8_V*.sql`; tests por `*Test*.java` (61 arquivos — esparso, ver `docs/02 §9`).

## 3. Updates incrementais

`git pull` → `git diff --name-only OLD..NEW` → reparse só afetados → `UPDATE` + invalidação de edges de saída → hash do índice versionado em `experiments/log.py`. Full reindex só como reconciliação semanal ou sob divergência rg×FTS5.
