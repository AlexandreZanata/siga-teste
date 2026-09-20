# Protocolo EVAL-MCP — avaliação manual em IDEs de agente (G01)

Fonte: `docs/18-mcp-eval-suite.md` (§3 suite, §4 checker, §5 G01).
Este protocolo é a operação; o artefato congelado é a verdade.

## 1. Artefatos

| Artefato | Papel |
|---|---|
| `eval/mcp_suite/tasks.jsonl` | 60 tarefas congeladas (20/10/10/10/10) com ground truth determinístico + provenance (`siga_head_commit`, regra de seleção) |
| `eval/mcp_suite/prompts/NNN.md` | Prompts coláveis (001–060) — **nunca contêm ground truth** |
| `experiments/reports/mcp_suite_check.json` + run | Resultados por modelo/IDE, com provenance |

Regra de seleção (documentada no provenance do artefato): holdout de
`datasets/benchmark/` ordenado por id → 20 `locate` com GT existente no HEAD →
10 de cada derivado (`trace`/`impact`/`history`/`context`) calculado pelo
mesmo caminho que o braço B executa (`mcp.server.dispatch`).## 2. Braços

- **Braço A (baseline)**: IDE de agente **sem** as tools MCP — só repo + ripgrep.
- **Braço B (tratamento)**: mesma IDE **com** o servidor MCP (`mcp/server.py`, 5
  métodos via stdio, token local `SIGA_MCP_TOKEN_FILE`, rate 60/60s).

Braços separados por sessão limpa; mesmo modelo/versão de IDE; mesmas 60
tarefas. A cada tarefa, cronometrar e registrar em
`eval/mcp_suite/runs/<modelo>-<ide>-<data>.jsonl` (docs/18 §3):

```json
{"task_id": "mcp-locate-001", "braco": "A|B", "resposta": "texto colado",
 "arquivos": ["..."], "simbolos": ["..."], "tokens_proxy": 0,
 "latency_ms": 0, "chamadas_mcp": []}
```

`tokens_proxy` = whitespace (mesmo de `mcp/server.py`); custo em tokens da IDE
quando visível, senão proxy + declaração explícita.

## 3. Formato de resposta (obrigatório)

Os prompts terminam com o formato exato; o checker cego parseia:

```
### RESPOSTA

FILE: <caminho/relativo.ext>
SYMBOL: <NomeClasse>
COMMIT: <sha>   (só nas tarefas history, se conhecido)
```

Linhas fora do bloco `### RESPOSTA` são ignoradas. Paths são normalizados
(`../`, `./`, prefixos de `git show`, trailing commentary).

## 4. Avaliação (checker cego — G01)

O operador extrai a `resposta` do run para `answers/NNN-<modelo>-<braco>.md`
e roda:

```bash
python -m evaluation.mcp_suite_check --all-answers eval/mcp_suite/answers/<modelo>/
```

Métricas por tarefa e agregadas (média):

- **recall@k** = fração dos arquivos do GT presentes na resposta
  (k = |GT|; reuso de `evaluation.metrics.recall_at_k`);
- **hallucination_rate** = fração de arquivos citados que não estão no GT
  (`evaluation.metrics.hallucination_rate`);
- **out_of_repo** = paths que não existem no checkout do bench
  (`siga_head_commit`) — guarda anti-leakage no nível de arquivo;
- **commit_recall** (só history): shas citados vs GT (cobertura do GT).

Report + run com provenance (modelo, IDE, `siga_head_commit`, tasks artifact).
**Sem sucesso falso**: tarefa sem GT congelado aborta o checker.

Limite de escopo do G01 (docs/18 §3): o veredito rico — File/Symbol
Recall@1/3/5, Tool Accuracy, Argument Exact Match, `task_success` A vs B,
`effective_token_reduction`, latência P50/P95 — vive em
`evaluation/mcp_suite_score.py` (**G02**), que lerá os `runs/`. Este checker
valida honestamente a superfície de arquivos/commits.

## 4b. Scoring A/B (G02)

Com os `runs/*.jsonl` preenchidos, o harness emite o veredito:

```bash
python -m evaluation.mcp_suite_score                # lê eval/mcp_suite/runs/
python -m evaluation.mcp_suite_score --runs <arquivo.jsonl>
```

- Veredito por tarefa: `exact` (recall = precision = 1) / `partial`
  (recall@|GT| ≥ 0.5 e precision ≥ 0.5) / `fail`; `task_success = partial ou
  melhor` (history: cobertura dos commits do GT);
- Métricas docs/10 §2: Recall@1/3/5 de arquivo e símbolo, Tool Selection
  Accuracy e Argument Exact Match (braço B), Hallucination Rate, latência
  P50/P95, `tokens_proxy`;
- **A vs B** (≥ 5 tarefas por braço): `effective_token_reduction = 1 −
  tok_B/tok_A` sempre com `task_success_delta` — redução de tokens com queda
  de success = `failure_token_reduction_with_regression` (docs/11 §1);
- Report + run com provenance em `experiments/reports/mcp_suite_score.json`.

Run com `task_id` fora do artefato congelado **aborta** (nunca sucesso falso).

## 5. Segurança e contaminação

- Checkout do SIGA somente leitura durante o benchmark; nenhuma tarefa pede escrita.
- O modelo não vê `tasks.jsonl` (GT). Prompts são gerados dele, mas sem GT.
- **O agente respondente nunca viu o GT**: o mesmo agente não pode ter gerado
  nem lido `tasks.jsonl` (regra "o modelo não vê `tasks.jsonl`"); a rodada de
  referência (G03) é operada por **operador limpo** em sessão que nunca abriu
  o artefato congelado;
- O mesmo artefato congelado serve todos os modelos/IDEs (comparabilidade).
- Anti-leakage: GT veio do `dispatch` real, não da resposta de nenhum modelo;
  o checker valida existência real dos paths citados no commit do bench.
- Anti-leakage do GT de impact/history: o próprio alvo (`args.target`) é
  excluído do GT — é input da pergunta, nunca descoberta a medir.

## 6. Replicação multi-modelo/IDE (G04)

A planilha-livro `eval/mcp_suite/replication.csv` é o índice canônico de
replicação: uma linha por `(modelo, ide, braço, run_file)`, métricas
**derivadas do scorer** (`score_run_file`) — nunca redigidas à mão.

Ciclo por par modelo/IDE (Freebuff, OpenCode, Cursor, Codex, ...):

1. Operador limpo executa os braços A e B conforme §2 (60 tarefas cada,
   sessão limpa por braço, mesmo modelo/versão de IDE);
2. Registra os runs em `eval/mcp_suite/runs/<modelo>-<ide>-<data>.jsonl`
   (formato §2; um arquivo por par modelo/IDE/data);
3. Lança na planilha:

   ```bash
   python -m evaluation.mcp_suite_ledger --runs eval/mcp_suite/runs/<modelo>-<ide>-<data>.jsonl \
     --modelo <modelo> --ide <ide>
   ```

   A linha é idempotente pela chave `(modelo, ide, braço, run_file)` —
   reexecutar substitui a linha anterior; header divergente aborta;
4. Compara entre pares: colunas `task_success`, `mean_recall_at_k`,
   `mean_hallucination_rate`, `tokens_proxy_total`, `p50/p95_ms`,
   `mean_mcp_calls`; A×B por par vem do scorer (§4b, regra docs/11).

Requisitos de replicação (o que torna a linha comparável):

- mesmo artefato congelado `tasks.jsonl` (HEAD do SIGA no provenance);
- mesmo modelo+versão e IDE+versão; sessão limpa por braço; sem acesso ao
  GT pelo agente respondente;
- `notas` registra desvios (ex.: versão da IDE, limitações do braço B).

### Instruções de replicação rápidas (novo par modelo/IDE)

```bash
# 1. checkout do siga-teste no HEAD congelado; SIGA em ../ (somente leitura)
# 2. braço A: IDE sem MCP → colar prompts 001–060, colher respostas
# 3. braço B: mesma IDE com mcp/server.py via stdio (SIGA_MCP_TOKEN_FILE, rate 60/60s)
# 4. montar o run JSONL no formato §2
# 5. checar cegamente:  python -m evaluation.mcp_suite_check --all-answers <dir>
# 6. score A/B:         python -m evaluation.mcp_suite_score
# 7. lançar na planilha: python -m evaluation.mcp_suite_ledger --runs <run.jsonl> --modelo ... --ide ...
```

## 7. Segurança MCP (braço B)

- Token de sessão via `SIGA_MCP_TOKEN_FILE`; sem token o servidor não sobe
  (fail-closed, F14/ADR-024);
- Rate limit 60 requisições/60s por token;
- Cliente nunca importa o core; os 5 métodos via stdio.
