# 15 — Roadmap: milestones, DoD, estrutura, ordem, 20 tasks, NOT-build e cobertura das 30 entregas

## 1. Cobertura das 30 entregas do planejamento (tudo coberto; nada adiado)

| # | Entrega | Onde |
|---|---------|------|
| 1 | Executive Summary | `README.md` (objetivo, princípio, arquitetura, status, medições) |
| 2 | Repository Analysis | `docs/02` |
| 3 | Needle Technical Analysis | `docs/00` + `docs/03` |
| 4 | Architecture Proposal | `docs/04` + `ARCHITECTURE.md` |
| 5 | Deterministic Components | `docs/05` (+ Fase 03 implementa) |
| 6 | ML Components | `docs/03`, `docs/04`, `docs/09` |
| 7 | Tool Architecture | `docs/06` |
| 8 | Repository Graph Design | `docs/05 §2` |
| 9 | Dataset Generation Strategy | `docs/07` |
| 10 | Teacher Strategy | `docs/08` |
| 11 | Verification Strategy | `docs/08` (verifier) + `docs/05 §3` + `docs/10` (ADR-018) |
| 12 | Benchmark Design | `docs/10` |
| 13 | Training Plan | `docs/09` |
| 14 | Evaluation Plan | `docs/11` |
| 15 | Context Capsule Design | `docs/04` (ADR-008) + `docs/06` (`siga_context`); formato fino na Fase 09 |
| 16 | MCP/API Design | `docs/12` |
| 17 | Security and Privacy | `docs/13` |
| 18 | License/Provenance Notes | `docs/14` (sem parecer jurídico) |
| 19 | Hardware Requirements | `docs/13 §1` |
| 20 | Risks | `docs/16` (1ª parte) + `docs/03` (L1–L6) |
| 21 | Open Questions | `docs/16` (17 perguntas) |
| 22 | Alternatives Considered | `docs/16` (final) + ADRs em `docs/03`–`05` |
| 23 | Vertical Slice Experiment | `docs/17 §1` |
| 24 | Milestones | §2 abaixo |
| 25 | Definition of Done | §3 abaixo (+ `.local/MASTER_PLAN.md`) |
| 26 | Repository structure | `README.md` + `docs/04 §2` |
| 27 | Order of implementation | `ROADMAP.md` + §2 abaixo |
| 28 | First 20 engineering tasks | §4 abaixo |
| 29 | NOT build yet | §5 abaixo |
| 30 | Go/no-go V1 | `docs/17 §2–§3` |

## 2. Milestones (ordem obrigatória, gate anterior fecha o próximo)

P00 planejamento (este commit) → P01 toolchain+boundaries+tracking+CI → P02 indexer+graph+incremental → P03 baseline determinístico → P04 bench congelado → P05 tools+simulador+golds → P06 factory 500 golds → P07 LoRA+curvas → P08 menor subnetwork → P09 cápsula+3 braços → P10 MCP → P11 on-policy+auditoria+release local. Detalhes em `.local/phases/*.md`.

## 3. Definition of Done (V1 slice)

`make verify` em checkout limpo; bench isolado com 19 métricas; 7 baselines comparadas; curvas 100→10k; subnetwork mínima; `task_success >= X` com tokens/custo <<; sem segredo, sem contaminação, sem TODO sem ID (verificado em P11-T02 por `scripts/final_audit.py`). Completo em `.local/MASTER_PLAN.md` (Definição final de pronto).

## 4. Primeiras 20 tasks de engenharia (pós-P00)

E01–E03 (P01): boundaries `tests/test_boundaries.py`; `experiments/log.py`; CI sem deploy. E04–E06 (P02): indexer Java Tree-sitter no slice; JSP/SQL/Maven/Git; SQLite+FTS5+incremental. E07–E08 (P03): `search_text` rg+outline; callgraph+impacto 1-hop. E09–E10 (P04): harness temporal+manifest; holdout 200–500 + 19 métricas. E11–E13 (P05): primitivas; 5 semânticas; simulador+100 golds. E14–E15 (P06): factory multi-teacher+verifier; hard negatives+500 golds. E16–E17 (P07): export+base-vs-tuned; LoRA+curvas. E18 (P08): compressão 20→2L. E19 (P09): cápsula JSON-vs-texto+3 braços. E20 (P10): MCP fino + demo via cliente externo.

## 5. Explicitamente NÃO construir ainda

Embeddings/RAG; Neo4j/K8s/microservices; dataset >2k antes das curvas; clientes acoplados; telemetria de uso; 2-bit shipped (só Cactus Platform); reescrita de JSP/SQL pelo nano; portal/checkout/billing (fora do domínio).

## 6. Pós-slice (P11-T02, 2026-09-18) — milestones cumpridos, próximos 20, NOT-build

Milestones P00–P11 cumpridos com gate: 18 docs; toolchain+CI verde; indexer+graph+incremental; baseline determinístico; bench 311 isolado; 5 tools+simulador+100 golds; factory 500 golds; LoRA+curvas (sweet spot 2k–5k); subnetwork 12L 4-bit; cápsula texto −11,37% vs JSON; 3 braços (GO condicional); MCP desacoplado; on-policy 0,9841→1,0. Evidência em `experiments/reports/` + `experiments/runs/` (ver `scripts/final_audit.py`).

Próximos 20 tasks concretos (pós-V1, cada um com gate próprio antes de escalar):
F01 fallback puro-Python do `search_text` sem `rg` (robustez CI/offline); F02 congelar `subnetwork_compression.json` contra jitter de latência; F03 fixture SIGA mínima no CI p/ testes hoje pulados (16+5+2 skips); F04 baseline small-coder tradicional (fecha baseline 7); F05 spike RAG/embeddings vs graph (candidato a baseline 3); F06 expansão 2k com error analysis (degrau ADR-017); F07 comparação Tree-sitter vs JavaParser/JDT (gatilho P02); F08 co-change sem chamada direta (lacunas `1a47b862`/`fecfd9ce`); F09 queries vagas 1–2 palavras (recall hoje ~0); F10 edição real ponta a ponta (além de localização); F11 julgamento de reescrita JSP/SQL; F12 traces longos: sub-recuperação da cápsula (risco ADR-008); F13 monitoramento do gatilho ADR-009 (tuned vs determinístico por janela); F14 MCP com auth + rate limit antes de qualquer exposição; F15 val-loss tracking infra p/ próximos LoRAs; F16 SLOs de hardware (P50/P95/RAM por profundidade); F17 proteção de branch `main` (exigir PR + CI verde); F18 REMOVIDO — sync `docs/`→wiki descontinuado, fonte única passa a ser `docs/` no repo (ver ADR-031; script mantido como utilitário manual opcional); F19 decisão 2-bit Cactus com números; F20 revalidar GO com edição real (critério docs/17 estendido).

NOT-build atualizado (continua proibido sem ADR + gate): distribuir pesos; acoplar clientes ao core; dataset >10k; servir 2-bit; telemetria de uso; MCP público sem auth; reescrita JSP/SQL pelo nano; portal/checkout/billing; wiki do GitHub / sync `docs/`→wiki (F18 removido, uso só manual e opcional).
