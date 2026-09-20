# 19 — Pós-treino rumo a 99% de identificação de arquivos via MCP (contexto referencial)

> Bench em `docs/10`; avaliação em `docs/11`; MCP em `docs/12`; suite EVAL-MCP em `docs/18` (baseline ref1: B success 0.483, file recall@1 0.46/@5 0.547). Decisões em ADR resumido (`DECISIONS.md`).

## 1. Ponto de partida medido (ref1, sem chute)

Braço B (com MCP, 60 tarefas): `task_success` 0.483, recall@k 0.473, hallucination 0.286, p50 157ms; braço A: success 0.267, hallucination 0.522. Por método (A/B): locate .15/.25, trace .00/1.00, impact .20/.30, history .10/.10, context 1.00/1.00. Diagnóstico: o MCP já resolve trace e ajuda em locate/impact; os gargalos até 99% são **locate fino**, **history (commit recall)** e **hallucination em arquivos movidos** (12 citações B-history fora do HEAD — ferramenta devolve paths de commits antigos).

## 2. Tese: contexto referencial, nunca despejo

A IA grande nunca recebe milhares de arquivos. O MCP entrega **referências** — `{path, símbolo, âncora de conteúdo, repo_commit}` — mais snippets mínimos só do que será aberto. Regra de ouro: **ID primeiro, conteúdo sob demanda**. Isso mantém o `effective_token_reduction` alto enquanto o recall sobe: cada degrau de recall precisa vir acompanhado de `task_success_delta ≥ 0` (`docs/11 §1`).

## 3. Degraus com gate (nenhum degrau sem o anterior verde)

| Degrau | Alvo file recall@5 (bench congelado) | Alavanca principal |
|---|---|---|
| H01 | 0.65 | failure mining da ref1 + índice por módulo (24 shards) |
| H02 | 0.75 | history reescrito sobre `git log --follow` + paths resolvidos no HEAD |
| H03 | 0.85 | teacher agentivo (runs verificados viram gold) + LoRA v1 |
| H04 | 0.92 | cápsula referencial v2 (IDs + snippets sob demanda) + subnetwork |
| H05 | 0.99 | on-policy final + auditoria de contaminação + GO |

Cada degrau: 1 tarefa = 1 commit, `make verify` verde, report + run com provenance. Se um degrau subir tokens sem subir success, é fracasso e volta um degrau.

## 4. Como cada gargalo fecha

- **Locate fino:** shard do índice por módulo Maven + FTS por nome de arquivo/classe; `siga.locate` passa a devolver (candidato, shard, score) e o juiz descarta fora do módulo da tarefa.
- **History:** reescrever `siga_history` sobre `git log --follow --name-status` com resolução de renomeações para o HEAD; GT de impact/history exclui o próprio alvo (já vale no G01).
- **Arquivos movidos:** validador `existe-no-HEAD` no envelope do MCP — path morto chega marcado, nunca como fato.
- **Dados de treino sem API key:** as refs G03 (e futuras, multi-IDE) viram trajetórias gold após verificação determinística — mesmo padrão da factory P06, com o agente-IDE como teacher e o verifier como ground truth (consenso LLM nunca é ground truth).
- **Modelo:** LoRA sobre o Needle base com as trajetórias gold (padrão P07), curvas 100→500→2k, compressão P08 depois. Treino CPU-only, offline.

## 5. Fluxo do dev SIGA (o que muda no dia a dia)

`localizar → contexto referencial → abrir só o necessário → patch seguro (F10) → juiz (F11) → gates`. A IA grande trabalha com dezenas de referências, não milhares de arquivos; a edição continua em checkout isolado com `apply_unified_patch`. DoD do H05: file recall@5 ≥ 0.99 no holdout congelado, `task_success_delta ≥ 0` vs H04, `make verify` verde em checkout limpo, ADR de GO.
