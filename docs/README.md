# docs/ — planejamento versionado (Phase 0 gera os 18 documentos)

A Phase 0 (`P00`, `.local/phases/00-research-contract.md`) produz exatamente:

```text
docs/00-research.md
docs/01-problem-definition.md
docs/02-siga-repository-analysis.md
docs/03-needle-analysis.md
docs/04-system-architecture.md
docs/05-repository-intelligence.md
docs/06-tool-design.md
docs/07-dataset-strategy.md
docs/08-teacher-pipeline.md
docs/09-training-strategy.md
docs/10-siga-bench.md
docs/11-evaluation.md
docs/12-mcp-integration.md
docs/13-security-privacy.md
docs/14-license-provenance.md
docs/15-roadmap.md
docs/16-risks-open-questions.md
docs/17-first-experiment.md
```

Pós-slice (fora da Phase 0, cada um com gate próprio):

```text
docs/18-mcp-eval-suite.md
docs/19-pos-treino-99-recall.md
docs/20-mcp-qualquer-projeto.md
docs/21-real-needle-training-benchmark.md
docs/22-real-needle-training-runbook.md
docs/23-jev-like-nano-controller.md
docs/24-real-nano-jev-mcp-delivery.md
```

Regras:

- Nenhum doc presume estado atual do Needle sem verificar docs oficiais atuais.
- Toda decisão arquitetural usa formato ADR resumido (ver `../DECISIONS.md`).
- Nenhum benchmark contamina dataset (splits temporais Git).
- Licença AGPLv3: sem parecer jurídico, só riscos e pontos para revisão.

Enquanto a Phase 0 não conclui, `ARCHITECTURE.md`, `ROADMAP.md`, `RESEARCH.md` e `DECISIONS.md` na raiz são a fonte versionada.
