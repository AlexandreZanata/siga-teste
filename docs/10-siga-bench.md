# 10 — SIGA-Bench: benchmark isolado, temporal, antes do treino

> Métrica central em `docs/01 §5`; avaliação e baselines em `docs/11`. Decisões em ADR resumido.

## ADR-018 — Bench congelado antes do treino, em paths distintos

- **Decision:** `datasets/benchmark/` (holdout 200–500 + `manifest.json` com T1/T2 e SHAs) é criado e congelado na P04, antes de qualquer LoRA; nenhum arquivo sob esse prefixo pode ser lido pelo treino — teste automático quebra o build se um SHA do bench aparecer em `raw|canonical|verified`.
- **Reason:** contaminação Git→bench é o modo de falha silencioso nº 1 deste projeto; separação por path + SHA é verificável por máquina, promessa não é.
- **Alternatives:** split aleatório; bench gerado depois do treino.
- **Advantages:** generalização real medida (splits temporais `docs/07 §3`); auditoria trivial.
- **Disadvantages:** bench menor no início (200–500).
- **Risks:** vazamento via snippets copiados — mitigado por verificação de conteúdo além de SHA na P04.
- **Validate:** teste de isolamento roda em todo `make verify` a partir da P04.

## 1. Composição do holdout

Locate file/symbol, trace, impacto, history/co-change, testes relacionados + ambíguas, off-topic (`answers: []`), no-tool, insuficiente. Tarefas derivadas de commits reais (mensagem→arquivos; estado N-1→região vs diff N) + sintéticas da factory, sempre com ground truth determinístico (path/símbolo existe no commit do bench).

## 2. Métricas (todas por run, registradas em `experiments/log.py`)

File/Symbol Recall@1/3/5; Tool Selection Accuracy; Tool Sequence Success; Argument Exact Match; Invalid Tool Call Rate; No-Tool Accuracy; Path/Symbol Hallucination Rate; Trace Accuracy; Impact Recall; Mean Tool Calls; latência P50/P95; Context Capsule Tokens; Large Input/Output Tokens; End-to-End Task Success; custo; Time To First Relevant File.
