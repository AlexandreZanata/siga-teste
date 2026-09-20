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

## 5. Segurança e contaminação

- Checkout do SIGA somente leitura durante o benchmark; nenhuma tarefa pede escrita.
- O modelo não vê `tasks.jsonl` (GT). Prompts são gerados dele, mas sem GT.
- O mesmo artefato congelado serve todos os modelos/IDEs (comparabilidade).
- Anti-leakage: GT veio do `dispatch` real, não da resposta de nenhum modelo;
  o checker valida existência real dos paths citados no commit do bench.
- Anti-leakage do GT de impact/history: o próprio alvo (`args.target`) é
  excluído do GT — é input da pergunta, nunca descoberta a medir.
