# 08 — Teacher pipeline: multi-teacher com verificação determinística

> Estratégia de dados em `docs/07`; treino em `docs/09`. Decisões em ADR resumido.

## ADR-016 — Três teachers, nenhuma fonte de verdade

- **Decision:** gerar cada tarefa com DeepSeek V4.1 Flash, Muse Spark 1.3 e Gemini 3.8 Flash (prompts versionados por teacher); resposta só vira gold se passar no verifier determinístico; consenso LLM nunca é ground truth.
- **Reason:** diversidade de fraseados PT-BR e de trajetórias; verificação por AST/símbolo/Git elimina alucinação compartilhada pelos teachers.
- **Alternatives:** teacher único; votação por maioria como verdade.
- **Advantages:** ~3× trajetórias candidatas por tarefa; seleção da mais curta correta ensina comportamento operacional, não prosa.
- **Disadvantages:** 3× custo de geração (aceitável: temos ampla inferência; geração ≠ runtime).
- **Risks:** teachers externos veem snippets do SIGA público — ok p/ dataset experimental público; runtime final permanece local (`docs/13`, P00-T05).
- **Validate:** P06 publica taxa de aprovação por teacher e divergência entre eles.

## 1. Fluxo

```text
TASK → 3 teachers (trajetórias candidatas) → execução real das tools
→ verifier (AST/symbol/grep/Git/diff/testes) → score
→ trajetória curta e correta → datasets/canonical/ → gold
```

## 2. Categorias geradas

Locate file/symbol; trace execução; endpoint/controller/JSP/migration; implementação análoga (via `CHANGED_WITH` real); impacto; dependências; testes relacionados; bug/feature localization (estado N-1 vs diff N real); ambíguas; off-topic; no-tool; insuficiente. Mutações (condição invertida, validação removida, enum/annotation/import trocados, SQL/JSP/endpoint quebrados) com ciclo investigar→corrigir→compilar/testar quando aplicável.

## 3. Regras de trajetória

Só `OBSERVATION→ACTION→ARGS→RESULT→FINAL`; `reasoning` de 1 linha derivando cada arg de span ou result anterior (ADR-006, `docs/03`); args com paths/símbolos copiados de resultados reais; `answers: []` obrigatório em off-topic (~1/8, `docs/00 §1.5`); cada registro carrega provenance completa (`docs/07 §2`).
