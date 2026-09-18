# 13 — Security, privacy e hardware

> Runtime local como premissa em `docs/01 §7` e `.local/MASTER_PLAN.md`. Sem parecer jurídico (ver `docs/14`).

## ADR-021 — Runtime 100% local; teachers externos só no dataset público

- **Decision:** inference + graph + índice + Needle rodam locais (CPU, sem GPU obrigatória); modelos teachers externos (DeepSeek/Gemini/Muse) só tocam snippets do SIGA público durante a factory, nunca código privado no runtime.
- **Reason:** o core deve servir a repositórios privados no futuro; nenhum fato estrutural ou código pode exigir rede.
- **Alternatives:** API hospedada do Expert; teachers no loop de runtime.
- **Advantages:** privacidade por construção; custo de runtime ≈ eletricidade; `needle fetch` + cache HF documentam setup air-gapped (`docs/00 §1.3`).
- **Disadvantages:** sem telemetria de uso real p/ active learning (opt-in explícito futuro, P11).
- **Risks:** vazamento acidental via prompts de geração — mitigado por allowlist de paths do slice público + revisão de provenance.
- **Validate:** teste P10 demonstra sessão completa com rede bloqueada (`HF_HUB_OFFLINE=1`).

## 1. Requisitos de hardware (runtime V1)

Dev comum: CPU x86_64/ARM64, ~28MB RAM p/ sessão Needle 2 + SQLite do slice (28M de `src/`, `docs/05 §1`) + folga do orquestrador — alvo < 512MB totais, startup < 2s, P50 por turno < 1s excluindo IA grande. Treino LoRA (P07) é a única etapa que admite GPU (JAX/CUDA ou Metal), fora do runtime. Telemetria da lib desativada (`NEEDLE_TELEMETRY=0`).
