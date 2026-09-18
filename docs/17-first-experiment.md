# 17 — First experiment: vertical slice + go/no-go V1

## 1. Desenho (menor fatia que prova ou refuta a ideia)

- **Slice:** `siga-ex` (506 Java) + `sigaex` (270 Java + 597 JSPs), `docs/02`.
- **Tarefas:** localização de funcionalidade (`locate` + `trace`); 500–2.000 exemplos treino, holdout 200–500 isolado (`docs/10`).
- **Braços:** (a) large-alone; (b) large + graph determinístico; (c) large + Needle Expert (base, depois tuned).
- **Leituras:** `task_success`, `effective_token_reduction`, P50/P95, custo, `task_success_delta` (`docs/11`).

## 2. Critérios go/no-go p/ V1

- **GO:** (c) ≥ (a) em success com tokens << e custo <<; e (c) > (b) em alguma leitura (selection, grounding PT-BR ou cápsula) — senão o nano não paga o próprio custo.
- **NO-GO controlador:** tuned ≤ (b) ⇒ ADR-009 (Needle vira extrator, regras assumem).
- **NO-GO geral:** (b) ≤ (a) ⇒ nem o graph ajuda; revisar premissas antes de qualquer LoRA.

## 3. Recomendação atual (pré-evidência, P00)

**GO condicional p/ executar o slice** (P01–P09): custo baixo (SQLite+rg+LoRA local), reversível (plano B reaproveita tudo), e a pergunta central (`RESEARCH.md`) só se responde com números. Não é GO p/ escalar dataset, distribuir pesos ou acoplar clientes — isso exige o slice passando nos critérios acima.
