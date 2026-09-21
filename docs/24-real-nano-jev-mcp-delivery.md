# 24 — Plano de finalização real: Nano → JEV-like → MCP → edição do SIGA

> **Fonte operacional para as fases abertas:** P13, P14 e P15.
>
> **Tarefa deste documento:** `P15-T00`; commit planejado `docs(plan): [P15-T00] define real nano delivery path`.
>
> **Objetivo:** chegar rapidamente a um nano-modelo real e mensurável, usar decisões JEV-like para controlar custo e parada, disponibilizar a cadeia por MCP e provar utilidade em edição real do SIGA.
>
> **Regra central:** nenhuma execução longa existe para “ver o que acontece”. Toda run tem hipótese, orçamento, progresso, checkpoint e critério de aborto definidos antes de começar.

## 1. Resultado de produto

A entrega final é esta cadeia, executada com artefatos reais:

```text
issue de desenvolvimento
  → nano real localiza arquivos, símbolos e trechos
  → graph/Git/tools devolvem fatos atuais do repositório
  → policy JEV-like decide continuar, parar ou escalar
  → MCP entrega cápsula curta a uma IA de codificação
  → IA propõe patch em worktree temporário
  → compilador/testes/verifier avaliam o patch
  → telemetria mede precisão, tempo, tokens e falhas
```

O nano não precisa escrever código. Seu trabalho é reduzir o espaço de busca e entregar contexto correto, rápido e pequeno. A policy JEV-like não substitui o nano: ela avalia suas saídas e decide a próxima ação. A IA grande continua responsável por raciocínio aberto e escrita do patch.

## 2. Estado real já disponível

Não repetir trabalho que já produziu evidência:

- RTX 4060 Laptop comprovada no JAX/CUDA;
- checkpoint Needle 3 e ambiente isolado disponíveis;
- dataset v2 congelado e temporal;
- adapter real treinado com 350 registros, 3 épocas e 237 passos;
- exportações reais `tuned-20L.cact` e `tuned-12L.cact`;
- dataset verificado de 2.000 registros já existe, com 1.400 `train` e 600 `valid`;
- smoke N=100 e busca de batch já cumpriram sua função de diagnóstico.

Ainda não está provado:

- acurácia válida do modelo real, porque o B1 atual mistura seleção com execução de tools e perde parte do ground truth no harness;
- menor profundidade não inferior;
- ganho do controlador JEV-like;
- benefício do nano real dentro do MCP e em edição de código real.

Portanto, o próximo gasto útil é corrigir a medição. Repetir o smoke ou iniciar 5k antes disso é desperdício.

## 3. Regras para impedir runs gigantescas

### 3.1 Funil obrigatório

Cada candidato passa por estas etapas e para na primeira falha:

1. **Teste estrutural:** 2–4 casos, máximo 2 minutos.
2. **Microbench:** 8–16 casos estratificados, máximo 5 minutos.
3. **Validation curta:** até 60 casos, máximo 20 minutos.
4. **Validation completa:** somente para o candidato vencedor, máximo 30 minutos.
5. **Test cego:** uma única abertura, depois de pesos, thresholds e configuração congelados.

Uma configuração reprovada não continua para mais seeds, profundidades ou datasets.

### 3.2 Orçamentos e watchdog

- Nenhum comando pode ficar opaco por mais de 60 segundos: imprimir etapa, contagem e tempo estimado.
- Inferência isolada tem timeout por tarefa; o padrão inicial é 120 segundos e deve cair após o P95 ser medido.
- Um screening de treino usa uma seed e tem orçamento de 60 minutos na RTX 4060.
- Se a projeção ultrapassar o orçamento em 25%, interromper preservando checkpoint e telemetria.
- OOM, NaN, perda do device, ausência de progresso ou throttling sustentado invalidam a run.
- Retomada usa checkpoint idempotente; nunca reinicia do zero por conveniência.
- Treino exige JAX `gpu`. A engine `.cact` pode ser CPU-only se essa for a implementação oficial disponível, mas isso deve ser registrado e a avaliação deve permanecer limitada por timeout.

### 3.3 Não executar novamente

- busca `1 → 2 → 4 → 8 → 16` completa em toda seed;
- B1 com `Needle.run(max_steps=8)` e schemas sem funções executáveis;
- benchmark base CPU de horas para desbloquear o treino;
- cinco passagens completas por configuração;
- produto cartesiano `dataset × rank × seed × depth`;
- 5k/10k sem ganho demonstrado no degrau anterior;
- subnetworks 8/4/2 antes de 12L provar não inferioridade;
- DAgger/on-policy antes de existir telemetria real do MCP.

### 3.4 Perfil rápido correto

- **B1:** chamar `Needle.complete()` uma vez; não executar tools; começar com 128 tokens e subir para 256 apenas se houver truncamento medido.
- **B2:** usar `Needle.run()` somente com funções Python reais registradas; começar com três passos e orçamento explícito.
- **Qualidade:** uma passagem por tarefa. Repetição serve apenas para medir latência num subconjunto fixo de 20 casos.
- **Treino:** uma seed para screening; seeds `0`, `17`, `42` somente para o finalista.
- **Batch:** reutilizar o maior batch já comprovado para a mesma combinação de checkpoint, comprimento, rank e precisão. Nova busca usa no máximo dois candidatos vizinhos e um probe curto.
- **JAX:** cache persistente de compilação, shapes constantes e sincronização host/device somente ao registrar métricas.

## 4. Fase P13 — fechar o nano real

### P13-T03 — corrigir o harness neural real

Entrega:

- B1 de uma única geração;
- ground truth mantido no scorer e nunca enviado ao prompt;
- validação completa dos argumentos contra JSON Schema;
- timeout por tarefa, checkpoint/resume e progresso;
- B2 separado, com callables reais.

Gate: 16 casos terminam em até 5 minutos, sem loop `unknown tool`, e a métrica de tool selection usa `expected_tool` real.

Commit: `fix(evaluation): [P13-T03] bound real Needle evaluation`

### P13-T04 — consolidar artefatos existentes sem novo treino

Entrega:

- hashes e manifests dos adapters/exports já produzidos;
- carregamento offline de 20L e 12L;
- registro do batch seguro e chave de cache da configuração;
- classificação explícita do N=100 como smoke e do N=350 como candidato real.

Gate: artefatos carregam e 4 casos estruturais executam; nenhuma nova época.

Commit: `chore(training): [P13-T04] consolidate real Needle artifacts`

### P13-T05 — avaliar o candidato real de 350 registros

Executar 20L/seed 0 no funil 4 → 16 → 60. Comparar com regras determinísticas no mesmo conjunto. O baseline Needle base completo não bloqueia: uma amostra curta caracteriza compatibilidade, não uma run de horas.

Gate para avançar: schema 1,0; invalid calls 0; no-tool ≥ 0,95; zero referência inventada; precisão superior à regra ou erro analisável coberto pelo dataset 2k.

Commit: `feat(evaluation): [P13-T05] validate real Needle candidate`

### P13-T06 — screening 2k com uma seed

Exportar `gold_2000.jsonl` para um dataset Needle imutável com 1.400 train/600 valid, sem ler o test. Treinar rank 16, uma seed, até três épocas, usando batch/cache comprovados. Comparar contra P13-T05 na mesma validation.

Gate: ganho funcional sem regressão de grounding/no-tool dentro do orçamento de 60 minutos; sem ganho, manter N=350 e encerrar escala. Não executar 5k nesta fase.

Commit: `feat(training): [P13-T06] screen verified 2k Needle data`

### P13-T07 — confirmar somente o vencedor

Executar seeds restantes `17` e `42` apenas para a configuração vencedora. Exportar primeiro 20L, 16L e 12L. Profundidades 8L/4L/2L só entram se 12L ficar dentro da margem de não inferioridade.

Gate: três seeds, dispersão publicada, menor modelo dentro de 1 ponto percentual do 20L e nenhuma regressão de schema/grounding.

Commit: `feat(training): [P13-T07] confirm real Needle finalist`

### P13-T08 — congelar o modelo

Congelar pesos, hashes, configuração, thresholds de parsing, B1/B2 de validation e abrir o test uma única vez. Emitir `GO_NANO_REAL`, `GO_20L_ONLY`, `GO_RULES_ONLY` ou `NO_GO`.

Commit: `docs(decisions): [P13-T08] freeze real nano model decision`

## 5. Fase P14 — usar JEV-like para avaliar e controlar o nano

O JEV-like recebe o estado e as saídas do nano. Ele não deve aumentar o custo antes de provar que reduz chamadas inúteis ou stop prematuro.

### P14-T01 — contrato, masks e replay

Unificar schema de estado, Choice/Score/Noul, action masks, budgets e gravação/replay determinístico.

### P14-T02 — dataset temporal de decisões

Gerar estados a partir de trajetórias reais do nano P13 e rotular com graph, Git, testes e ganho marginal. Isolar episódios inteiros por split.

### P14-T03 — baseline barato E0/E1

Comparar regras com probe linear/MLP sobre features congeladas. Uma seed, máximo 30 minutos. Sem ganho em J1/J2, escolher `GO_RULES_ONLY` e não treinar controlador neural.

### P14-T04 — E2 versus E3, somente se E1 mostrar sinal

Comparar controlador separado com heads sobre encoder congelado. Não descongelar o backbone. E4 multi-task fica adiado até E3 provar ganho sem reduzir recall do nano.

### P14-T05 — calibração e abstention

Ajustar temperature scaling no validation, publicar ECE/Brier/NLL e risk-coverage, congelar thresholds e impedir stop em baixa confiança.

### P14-T06 — confirmação e decisão

Executar seeds restantes somente no finalista e emitir `GO_RULES_ONLY`, `GO_SEPARATE_CONTROLLER`, `GO_SHARED_FROZEN_HEADS` ou `NO_GO_JEV`. DAgger fica para depois da telemetria P15.

## 6. Fase P15 — MCP real e edição do SIGA

### P15-T01 — runtime MCP do candidato congelado

Integrar nano P13 + policy P14 ao MCP existente. As cinco tools são callables reais, read-only e grounded. O servidor expõe versão dos pesos, perfil do projeto, repo commit, latência e motivo de stop/escalada.

Commit: `feat(mcp): [P15-T01] serve real nano controller`

### P15-T02 — benchmark de navegação do SIGA

Medir tarefas reais de:

- localizar arquivo, classe, método, JSP, SQL e teste;
- resolver homônimos;
- encontrar referências, callers/callees e histórico;
- recuperar trecho mínimo correto;
- montar cápsula com arquivos e símbolos existentes.

Métricas: File/Symbol Recall@1/3/5, MRR, exact args, hallucination, time-to-first-relevant-file, chamadas úteis/desperdiçadas, tokens, P50/P95 e peak RSS.

Commit: `feat(evaluation): [P15-T02] benchmark SIGA code navigation`

### P15-T03 — suíte congelada de edição

Criar tarefas representativas de Java, JSP e SQL com patch esperado ou critérios executáveis. Toda edição ocorre em worktree/checkout temporário; o clone `../` continua somente leitura. Verificar aplicação do patch, escopo, compilação/testes relevantes e ausência de mudança fora do alvo.

Commit: `feat(evaluation): [P15-T03] freeze SIGA editing suite`

### P15-T04 — teste ponta a ponta pareado

Comparar nas mesmas tarefas:

- regras + graph + IA de código;
- nano + graph + IA de código;
- nano + JEV-like + MCP + IA de código.

Usar a mesma IA, prompt, orçamento e verifier. Medir first-pass test success, task success, tempo até patch válido, tokens/custo da IA grande, número de interações e regressões.

Commit: `feat(evaluation): [P15-T04] benchmark MCP code editing`

### P15-T05 — hardening e generalização

Congelar contrato MCP, timeouts, cache, observabilidade, segurança e perfil SIGA. Validar o chassi em um segundo repositório público pequeno usando outro `project.json`, outro dataset/adaptador e os mesmos contratos genéricos. Nenhum path ou símbolo do SIGA entra no core.

Commit: `docs(decisions): [P15-T05] finalize reusable MCP specialist`

## 7. Gates finais

O projeto termina esta trilha somente quando:

- o nano escolhido tem pesos reais, hash, três seeds e test cego aberto uma vez;
- B1 não executa tools e B2 executa callables reais com orçamento;
- o JEV-like reduz custo/tempo sem piorar retrieval nem introduzir stop incorreto crítico;
- o MCP encontra arquivos, símbolos e trechos reais com zero invenção;
- patches são aplicados somente em ambiente temporário e avaliados por testes/verifier;
- o braço final não é inferior em task success e melhora tempo, tokens ou custo;
- o runtime final permanece local, offline e orientado por `project.json`;
- outro sistema pode reutilizar o chassi trocando perfil, dataset, adapter e benchmark, sem fork do core.

## 8. Prompt executor — exatamente 5 linhas

```text
Trabalhe em siga-teste conforme AGENTS.md; leia .local/PROGRESS.md e docs/21–24 e execute somente a primeira P13/P14/P15 ainda aberta.
Antes de agir, audite a evidência existente e nunca repita smoke, batch search, benchmark ou treino já válido; B1 usa uma geração e B2 somente callables reais.
Toda run deve ter GPU/engine explícita, timeout, progresso, checkpoint, orçamento e aborto por projeção; uma seed faz screening e três seeds apenas confirmam o vencedor.
Preserve splits temporais e test cego, meça precisão, grounding, P50/P95, tokens e sucesso de patch; nunca use simulação como evidência neural.
Rode os gates locais, faça um único commit da microtarefa, atualize PROGRESS e encerre sem push/PR nem espera pelo CI salvo autorização humana explícita.
```
