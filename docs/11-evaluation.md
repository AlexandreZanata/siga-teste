# 11 — Evaluation: protocolo, 7 baselines e critério de sucesso

> Bench em `docs/10`; métrica central em `docs/01 §5`; plano B em `docs/04` ADR-009. Decisões em ADR resumido.

## ADR-019 — Comparar 7 baselines, sempre com `task_success_delta`

- **Decision:** todo resultado é relatado contra as 7 baselines (1 IA grande direta; 2 +ripgrep; 3 +embeddings/RAG; 4 +graph determinístico sem Needle; 5 Needle base; 6 Needle tuned; 7 small coder tradicional), com `effective_token_reduction` sempre acompanhado de `task_success_delta`.
- **Reason:** a pergunta do projeto não é "Needle funciona?" e sim "nano+graph+LLM ≻ LLM sozinho?" (`docs/01`); sem as 7, qualquer ganho é anedota.
- **Alternatives:** comparar só large-alone vs final.
- **Advantages:** isola o valor marginal do Needle (4 vs 6) e do graph (1 vs 4); plano B (ADR-009) tem gatilho numérico direto.
- **Disadvantages:** 7× custo de eval por degrau (mitigado: holdout 200–500, slice pequeno).
- **Risks:** custo de IA grande no bench — precificado e registrado por run.
- **Validate:** tabela padrão por `experiment_id` a partir da P04; `tuned ≤ determinístico ⇒ plano B`.

## 1. Critério de sucesso (go/no-go por degrau)

`task_success >= X` com `input tokens << Y`, `custo << C`, latência total aceitável. Redução de tokens com queda relevante de success = fracasso, sem exceção. Cada run registra: `experiment_id`, commits (SIGA+siga-teste), Needle version/depth, artifact hash, dataset/tool/index/bench versions, métricas (`docs/10 §2`), hardware, latência, data.
