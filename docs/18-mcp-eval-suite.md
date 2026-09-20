# 18 — Suite EVAL-MCP + biblioteca de contexto SIGA (protocolo sem API key)

> Bench em `docs/10`; avaliação e baselines em `docs/11`; MCP em `docs/12`; roadmap em `docs/15 §6`. Decisões em ADR resumido (`DECISIONS.md`).

## 1. Objetivo duplo

1. Medir se o MCP (`mcp/server.py`, 5 métodos `siga.locate/trace/impact/history/context`, contrato `mcp/schema.json`) aumenta precisão e economiza de verdade, em qualquer modelo, via IDE de agente — sem API key, só com instrução colável.
2. Mapear o SIGA em microfases e sumarizar como biblioteca de contexto para dev (`docs/context/`), tudo com grounding — nenhum path/símbolo inventado.

## 2. Reuso obrigatório (não reinventar)

- Holdout congelado `datasets/benchmark/` + manifest T1/T2 (`docs/10`, ADR-018).
- Métricas `docs/10 §2` + 7 baselines e `effective_token_reduction` sempre com `task_success_delta` (`docs/11`, ADR-019).
- Harness `evaluation/harness.py`, `evaluation/metrics.py`; envelope `{result, provenance, cost}` do `mcp/server.py` (função `dispatch`).
- Contrato `tests/contract/test_mcp_contract.py`; cliente referência `mcp/client.py` como oráculo, nunca como executor LLM.
- Segurança MCP: auth fail-closed + rate limit (F14, ADR-024 em `docs/12 §2`).

## 3. Suite EVAL-MCP (protocolo manual)

Amostra fixa: 60 tarefas do holdout (20 locate, 10 trace, 10 impact, 10 history, 10 context). Mesmas 60 para todo modelo/IDE. Cada tarefa vira `eval/mcp_suite/prompts/NNN.md` com ID, enunciado verbatim, o que entregar e proibição de inventar path/símbolo.

Dois braços por modelo/IDE (Freebuff, OpenCode, Cursor, Codex):
- Braço A — sem MCP: só repo + ripgrep.
- Braço B — com MCP: os 5 métodos via stdio, token local `SIGA_MCP_TOKEN_FILE`, rate 60/60s. Cliente nunca importa o core.

Execução manual por tarefa: colar prompt na IDE, cronometrar, registrar em `eval/mcp_suite/runs/<modelo>-<ide>-<data>.jsonl` — `{task_id, braço, resposta, arquivos/símbolos citados, tokens_proxy (whitespace, mesmo de `mcp/server.py`), latência_ms, chamadas MCP}`. Custo em tokens da IDE quando visível, senão proxy + declaração explícita.

Veredito determinístico offline (`evaluation/mcp_suite_score.py`): File/Symbol Recall@1/3/5, Tool Accuracy, Argument Exact Match, Hallucination Rate, `task_success` A vs B, `effective_token_reduction = 1 - tok_B/tok_A`, latência P50/P95, taxa de recusa correta off-topic. Redução de tokens com queda de success = fracasso (`docs/11 §1`). Anti-leakage: checker valida que path/símbolo existe no commit do bench; bench nunca entra no prompt além da tarefa atual.

## 4. Biblioteca de contexto (microfases em paralelo)

Mapear os 24 módulos Maven em lotes de 2–3 por tarefa (`siga-ex`, `sigaex`, `siga-cp`, `siga-wf`, demais). Cada lote gera `docs/context/<modulo>.md` — responsabilidade, entry points (controllers/BL/entidades/JSP/SQL), como adicionar feature/corrigir bug, armadilhas — validado por `siga_locate/trace` real. Índice `docs/context/INDEX.md` com `source_commit`. Snippets mínimos com provenance, AGPLv3 respeitado (`docs/14`).

## 5. Microfases (1 tarefa = 1 commit, gates `make verify`)

- `G01` — freeze das 60 tarefas + prompts + checker cego.
- `G02` — harness de scoring + proxy de tokens + relatório A/B.
- `G03` — rodada de referência local (qualquer IDE) + baseline A vs B publicada.
- `G04` — protocolo multi-modelo/IDE (planilha de runs + instruções de replicação).
- `G05` — biblioteca contexto lote 1 (núcleo: `siga-ex`, `sigaex`).
- `G06` — lotes 2–N + índice + integração `siga_context`.
- `G07` — decisão GO/NO-GO MCP com números (novo ADR).

## 6. DoD

60/60 tarefas com veredito por modelo, `make verify` verde (unit/integration/contract), `docs/context/` cobrindo os 24 módulos sem path inventado, ADR de decisão publicado. Nenhum bloqueio pode citar wiki (F18 removido, ADR-031).
