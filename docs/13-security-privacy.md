# 13 — Security, privacy e hardware

> Runtime local como premissa em `docs/01 §7` e `.local/MASTER_PLAN.md`. Sem parecer jurídico (ver `docs/14`).

## ADR-026 — Auditoria determinística dos SLOs de hardware antes de confiar neles (F16)

- **Decision:** os SLOs de `docs/13` §1 e o risco do ADR-011 passam a ser auditados por `evaluation/hardware_slos.py` com medidas reais e veredito PASS/FAIL determinístico: RAM do processo via `resource.getrusage` (fallback `tracemalloc` com método registrado), startup do `mcp.server` como subprocesso até a 1ª resposta JSON-RPC (`SIGA_MCP_TOKEN` no ambiente — sem auth o server não sobe, F14/ADR-024), latência P50/P95 de `siga_trace` por profundidade 1–3 sobre grafo povoado com código real do slice (amostra determinística de até 400 `.java`; fallback por primitivas registrado à parte) e tabela RAM por profundidade de sub-rede **herdada do relatório congelado do P08** com fonte citada. Auditoria incompleta entra como NOT_RUN — nunca sucesso falso. Resultado em `experiments/reports/hardware_slos.json` + run com provenance.
- **Reason:** os alvos (< 512MB, startup < 2s, P50 < 1s) e o risco "P95 de traces multi-hop acima do SLO → reavaliar" existiam desde o P00 sem nenhuma medição; RAM só existia por fórmula (P08) e o gate "reavaliar" do ADR-011 era inacionável sem evidência.
- **Alternatives:** benchmarking contínuo em CI (frágil e lento — ruído de runner vira falso FAIL); APM/telemetria (proibido: telemetria desativada por design e docs/13); nova lib de profiling (viola standard-first).
- **Advantages:** evidência reprodutível em < 2s no dev; veredito idêntico entre máquinas para as mesmas medidas; refuta ou confirma o risco do ADR-011 com número, não narrativa; provenance herda o schema já validado.
- **Disadvantages:** medição de processo (`ru_maxrss`) reflete o pico do processo auditado, não o orquestrador completo; fixture de grafo limitada a 400 arquivos até existir indexador em massa (o caminho SQL do trace, porém, é o mesmo).
- **Risks:** ruído de máquina compartilhada — mitigado por warmup + ≥7 amostras + percentis; sobe o `max_files` quando o indexador em massa existir.
- **Validate:** auditoria real publicada (RAM 22,5MB via VmHWM, startup 0,044s, P95 3-hop 12,1ms com cadeia de 980 nós — risco ADR-011 refutado, 4/4 PASS); testes cobrem fórmula de percentil do harness, compliance PASS/FAIL/NOT_RUN, tabela P08 e artefatos com provenance.

## ADR-021 — Runtime 100% local; teachers externos só no dataset público

- **Decision:** inference + graph + índice + Needle rodam locais (CPU, sem GPU obrigatória); modelos teachers externos (DeepSeek/Gemini/Muse) só tocam snippets do SIGA público durante a factory, nunca código privado no runtime.
- **Reason:** o core deve servir a repositórios privados no futuro; nenhum fato estrutural ou código pode exigir rede.
- **Alternatives:** API hospedada do Expert; teachers no loop de runtime.
- **Advantages:** privacidade por construção; custo de runtime ≈ eletricidade; `needle fetch` + cache HF documentam setup air-gapped (`docs/00 §1.3`).
- **Disadvantages:** sem telemetria de uso real p/ active learning (opt-in explícito futuro, P11).
- **Risks:** vazamento acidental via prompts de geração — mitigado por allowlist de paths do slice público + revisão de provenance.
- **Validate:** teste P10 demonstra sessão completa com rede bloqueada (`HF_HUB_OFFLINE=1`).

## 1. Requisitos de hardware (runtime V1)

Dev comum: CPU x86_64/ARM64, ~28MB RAM p/ sessão Needle 2 + SQLite do slice (28M de `src/`, `docs/05 §1`) + folga do orquestrador — alvo < 512MB totais, startup < 2s, P50 por turno < 1s excluindo IA grande. Treino LoRA (P07) é a única etapa que admite GPU (JAX/CUDA ou Metal), fora do runtime. Telemetria da lib desativada (`NEEDLE_TELEMETRY=0`). Desde F16/ADR-026 esses alvos são auditados com medidas reais (`evaluation/hardware_slos.py` → `experiments/reports/hardware_slos.json`); risco ADR-011 (P95 multi-hop) medido e refutado no slice.
