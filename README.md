# SIGA Needle Expert

Nano-coprocessador especializado em compreender e navegar o SIGA/SIGA-Doc.

**Branch base do SIGA:** `desenvolvimento` (nunca `main`).
**Repositório de trabalho:** este repo (`siga-teste`). Nenhuma alteração é feita no clone do SIGA em `../` — ele é somente leitura para indexação e medição.

## Objetivo

Criar um nano-modelo (baseline: Needle da Cactus Compute) que, dada uma tarefa de desenvolvimento, decide quais ferramentas de repository intelligence usar, localiza arquivos/símbolos/fluxos e gera uma cápsula mínima de contexto para uma IA grande finalizar o código.

Objetivo econômico: reduzir tokens, buscas, latência e custo por tarefa sem reduzir taxa de conclusão.

## Princípio central

Separar três conhecimentos:

1. **Modelo/pesos** — arquitetura geral, vocabulário SIGA, como investigar, como compactar.
2. **Repository intelligence / code graph** — fatos estruturais (arquivos, classes, métodos, callers, endpoints, JSPs, SQL, tests, Maven deps).
3. **Código atual / retrieval** — conteúdo exato, snippets, commits recentes. `git pull` + reindex incremental, sem retreino.

## Arquitetura conceitual

```text
Developer → Large Coding Agent → SIGA Needle Expert → Repository Tools
→ AST / Code Graph / Git / Search → Context Capsule → Large Coding Agent → Code Modification
```

## Status

Base profissional criada. Execução por microfases em `.local/` (operacional, ignorado pelo Git — ver `.local/README.md`).

Ordem de leitura:

1. `AGENTS.md`
2. `ARCHITECTURE.md`, `ROADMAP.md`, `RESEARCH.md`, `DECISIONS.md`
3. `docs/` (contratos versionados; Phase 0 preenche os 18 docs de planejamento)
4. `.local/MASTER_PLAN.md` + `.local/PROGRESS.md` + fase atual em `.local/phases/`

## Medição de referência (SIGA `desenvolvimento`, 2026-09-18)

- Arquivos rastreados: ~13.519
- Java: 2.272 (`siga-ex`: 506, `sigaex`: 270)
- JSP: 979
- SQL: 553
- Módulos Maven raiz: 24 ativos (`siga-base`, `siga-cp`, `siga-ex`, `sigaex`, `siga-vraptor-module`, `siga-integracao`, ...; `siga-arq` comentado no `pom.xml`)
- Licença: GNU AGPLv3 (ver `docs/14-license-provenance.md` na Phase 0 — implicações para datasets/checkpoints não são parecer jurídico)
- Entidades centrais (ex.): `AbstractExDocumento`, `ExDocumento`, `ExMobil`, `ExMovimentacao`, `ExFormaDocumento`
- Controllers VRaptor legados em `siga/src/legacy/java/br/gov/jfrj/siga/vraptor/`

> Números são baseline para dimensionar indexer/graph/bench. Não assumir nomes atualizados — validar no código real em cada fase.

## Comandos canônicos

```bash
make fmt-check
make test-unit
make verify
```

Ver `Makefile` e `AGENTS.md`. Gates ainda não implementados falham com mensagem explícita, nunca com sucesso falso.

## Estrutura prevista (V1 simples, sem overengineering)

```text
siga-needle-expert/
├── docs/            # planejamento versionado (Phase 0 gera 00–17)
├── .local/          # plano operacional local (ignorado pelo Git)
├── indexer/         # java / jsp / sql / maven / git
├── graph/           # SQLite/DuckDB + índices
├── retrieval/
├── tools/           # siga_locate/trace/impact/history/context + primitivas
├── task_factory/ teachers/ verifier/
├── datasets/        # raw / canonical / verified / rejected / benchmark
├── training/ models/ evaluation/ inference/ context/ mcp/
├── tests/ experiments/
└── scripts/         # medições read-only do SIGA (nunca alteram ../)
```

Python + SQLite/DuckDB + Tree-sitter/JavaParser + Git + ripgrep como default V1. Sem Kubernetes/microservices sem necessidade comprovada.

## Privacidade / hardware

Runtime final deve operar local (repo + índice + graph + Needle locais), CPU-friendly, sem GPU obrigatória. Teachers externos só na construção do dataset público experimental.
