# Architecture — SIGA Needle Expert (stub vivo, Phase 0 detalha)

> Este arquivo é o índice versionado. O detalhamento executável vive em `docs/00–17` (gerados na Phase 0) e o passo-a-passo operacional em `.local/phases/`.

## Conceito

```text
Developer → Large Coding Agent → SIGA Needle Expert → Repository Tools
→ AST / Code Graph / Git / Search → Context Capsule → Large Coding Agent → Code Modification
```

Nano-modelo = controlador/navegador. Code Graph = memória factual. IA grande = engenheira.

## Decisão central

Separar `pesos ≠ graph ≠ retrieval`. Ver `DECISIONS.md` (ADR-001).

## Módulos V1 (Python simples)

- `indexer/` — java / jsp / sql / maven / git (Tree-sitter/JavaParser + ripgrep + Git)
- `graph/` — SQLite/DuckDB (nodes/edges do plano; sem Neo4j sem ADR)
- `retrieval/` + `tools/` — `siga_locate/trace/impact/history/context` sobre primitivas determinísticas
- `task_factory/` + `teachers/` + `verifier/` — multi-teacher com verificação AST/Git, não consenso LLM
- `datasets/` — `raw → canonical → verified → benchmark` (JSONL versionado + provenance)
- `training/` + `models/` + `evaluation/` — baseline → LoRA → subnetworks, `SIGA-Bench` antes do treino
- `inference/` + `context/` + `mcp/` — runtime CPU-friendly local + MCP server (OpenCode é cliente, não arquitetura)

Detalhamento completo: `docs/04-system-architecture.md`, `docs/05-repository-intelligence.md`, `docs/06-tool-design.md` (Phase 0).
