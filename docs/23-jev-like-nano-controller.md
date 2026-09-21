# 23 — Fase JEV-like: controlador tipado para precisão, velocidade e economia

> **Fase operacional proposta:** `P14`, executada somente após os gates relevantes de `P13` produzirem um baseline Needle real.
>
> **Tarefa deste documento:** `P14-T00`.
>
> **Commit planejado:** `docs(jev): [P14-T00] define typed nano controller phase`.
>
> **Entrada:** plano arquitetural fornecido pelo operador, `docs/21-real-needle-training-benchmark.md`, `docs/22-real-needle-training-runbook.md`, contratos das cinco tools e resultados reais do benchmark v2.
>
> **Saída esperada:** um controlador local JEV-like que decida `o que fazer agora`, `quando parar` e `quando escalar`, sem substituir o graph, o retrieval, o Needle nem a IA grande.
>
> **Integração de produto:** `docs/24-real-nano-jev-mcp-delivery.md`. P14 escolhe a policy; P15 mede MCP e edição real.

## 1. Objetivo em uma frase

Transformar o nano-modelo em um controlador de decisões curtas, tipadas, calibradas e verificáveis para reduzir chamadas inúteis de tools e da IA grande, preservando ou aumentando a taxa de patches corretos.

O objetivo não é fazer o nano-modelo escrever código. Ele deve preparar uma cápsula suficiente e entregar à IA grande apenas o contexto necessário para produzir o patch:

```text
tarefa
  → controlador JEV-like
  → retrieval/graph/git/tools determinísticos
  → controlador decide continuar, parar ou escalar
  → context capsule mínima
  → IA grande escreve o patch uma única vez
  → testes/verifier
```

O sucesso da fase é medido pelo fluxo completo de codificação, não apenas por acurácia de classificação.

## 2. O que “JEV-like” significa neste projeto

Jev, da TypeSafe AI, é apresentado como um modelo de decisão System One: recebe um estado, avalia perguntas tipadas e devolve valores estruturados com probabilidades. A documentação oficial expõe três primitivas:

- **Choice:** escolhe uma opção e devolve distribuição e confiança;
- **Score:** posiciona o estado numa escala ordenada e devolve distribuição e confiança;
- **Noul:** estima a probabilidade de uma afirmação binária.

As perguntas devem ser atômicas e independentes; decisões compostas ficam em código. Essa separação combina com a arquitetura do SIGA:

```text
pesos       = padrões de navegação e decisão
graph       = fatos estruturais
retrieval   = código atual
verifier    = verdade executável
IA grande   = raciocínio aberto e escrita do patch
```

Neste repositório, `JEV-like` significa reproduzir o **contrato operacional**, não alegar reprodução do produto proprietário:

```text
estado compacto + perguntas tipadas
  → probabilidades calibradas
  → policy determinística aplica masks, budgets e thresholds
  → ação permitida, nova observação, stop ou escalada
```

### 2.1 Limite de evidência

Em 2026-09-21, a TypeSafe publicou documentação, anúncio técnico e workflow evals, mas não foi localizada uma especificação científica aberta suficiente para reproduzir pesos, arquitetura, sampler ou o treinamento RLCD do Jev oficial. Portanto:

- números de velocidade/custo publicados pela TypeSafe são alegações do fornecedor, não metas comprovadas deste projeto;
- o nome do componente local é **controlador JEV-like**, nunca “Jev local”;
- nenhuma API TypeSafe é dependência da arquitetura;
- o caminho primário é local/offline;
- comparação com Jev hospedado é opcional, usa somente dados públicos/sintéticos e exige autorização humana para rede, credencial e custo.

## 3. Responsabilidades que não podem ser misturadas

### 3.1 Nano Search / Needle

Responde **o quê e onde procurar**:

- candidatos de símbolo;
- arquivos e snippets prováveis;
- argumentos grounded para uma tool;
- ranking dos resultados.

### 3.2 Controlador JEV-like

Responde **o que fazer depois**:

- próxima ação;
- continuar ou parar;
- contexto suficiente ou insuficiente;
- necessidade de testes/history/impact;
- risco e necessidade de escalar para a IA grande.

### 3.3 Graph, retrieval e Git

Continuam sendo fontes factuais. O controlador não memoriza paths atuais, relações de chamada ou conteúdo do HEAD.

### 3.4 IA grande

Recebe a cápsula final e escreve/revisa código. Não deve ser chamada entre cada etapa determinística quando o controlador local puder resolver a decisão.

## 4. Arquitetura-alvo

```text
                         TAREFA/ISSUE
                              │
                              ▼
                  ┌──────────────────────┐
                  │ State Builder v1     │
                  │ refs, budgets, mask  │
                  └──────────┬───────────┘
                             ▼
                  ┌──────────────────────┐
                  │ JEV-like Controller  │
                  │ Choice/Score/Noul    │
                  └──────┬───────┬───────┘
                         │       │
                  continue      stop/escalate
                         │       │
            ┌────────────┼───────┘
            ▼            ▼
        Nano Search   Policy/Gates
            │            │
       ┌────┼────────────┼───────────┐
       ▼    ▼            ▼           ▼
     locate trace      impact      history/context
       └────┴────────────┴───────────┘
                         │
                         ▼
                Context Capsule v3
                         │
                         ▼
                 Large Coding Agent
                         │
                         ▼
                  patch → verifier
```

O modelo sugere; a policy em Python decide se a sugestão é válida. Masks de ação, contratos de schema, orçamento, existência de símbolos e permissões continuam determinísticos.

## 5. Contrato JEV-like v1

### 5.1 Estado canônico

O estado de decisão deve conter somente evidência disponível naquele passo:

```json
{
  "contract_version": "jev-like-v1",
  "episode_id": "sha256:...",
  "step": 2,
  "repo_commit": "<sha>",
  "task": "Adicionar validação antes de assinar um documento",
  "observations": [
    {
      "source": "siga_locate",
      "refs": [
        {"path": "sigaex/.../ExDocumentoController.java", "symbol": "ExDocumentoController", "score": 0.91}
      ]
    }
  ],
  "last_action": "siga_locate",
  "last_status": "ok",
  "budgets": {"tool_calls_left": 4, "context_tokens_left": 1200},
  "allowed_actions": ["siga_trace", "siga_impact", "siga_history", "siga_context", "stop", "escalate"]
}
```

Regras:

- paths sempre relativos ao repositório;
- nenhum ground truth, expected tool, `task_type` oculto ou resposta do benchmark;
- observações truncadas por política explícita, nunca silenciosamente;
- `allowed_actions` é produzido por regras, não pelo modelo;
- o estado carrega referências e resumos mínimos, não arquivos completos;
- campos e ordem são canônicos para permitir hashing e replay.

### 5.2 Representação eficiente do estado

O JSON acima é o formato de persistência/auditoria. A entrada do modelo deve comparar, sem presumir vencedor:

1. JSON canônico compacto;
2. cápsula de texto compacto existente;
3. texto compacto JEV-like com IDs e referências;
4. features tabulares para baselines não generativos.

O relatório local `capsule_format_comparison.json` mediu texto compacto com 11,37% menos tokens que JSON no benchmark histórico, mas isso ainda precisa ser revalidado no benchmark v2 real e para **acurácia de decisão**, não apenas tokenização.

Exemplo de estado compacto candidato:

```text
TASK adicionar validação antes de assinar documento
STEP 2 CALLS_LEFT 4 TOKENS_LEFT 1200
LAST locate ok
REF 0.91 sigaex/.../ExDocumentoController.java :: ExDocumentoController
ALLOW trace impact history context stop escalate
```

### 5.3 Perguntas atômicas

Todas podem ser calculadas num único forward pass multi-head, mas cada resposta preserva semântica independente:

```json
{
  "next_action": {
    "type": "choice",
    "options": ["siga_locate", "siga_trace", "siga_impact", "siga_history", "siga_context", "stop", "escalate"]
  },
  "context_sufficient": {
    "type": "noul",
    "statement": "O estado contém evidência suficiente para montar a cápsula e entregar a tarefa à IA grande"
  },
  "expected_information_gain": {
    "type": "score",
    "levels": ["nenhum", "baixo", "médio", "alto"]
  },
  "escalation_needed": {
    "type": "noul",
    "statement": "A próxima decisão exige raciocínio aberto da IA grande"
  },
  "decision_risk": {
    "type": "score",
    "levels": ["reversível", "baixo", "alto", "crítico"]
  }
}
```

Não criar uma pergunta separada para cada detalhe possível. Uma head só entra se sua resposta mudar uma ação de código e tiver label verificável.

### 5.4 Resposta normalizada

```json
{
  "next_action": {
    "choice": "siga_trace",
    "probabilities": {
      "siga_trace": 0.71,
      "siga_context": 0.14,
      "siga_history": 0.06,
      "siga_impact": 0.04,
      "stop": 0.03,
      "escalate": 0.02
    }
  },
  "context_sufficient": {"probability": 0.12},
  "expected_information_gain": {"score": 2.7, "confidence": 0.77},
  "escalation_needed": {"probability": 0.08},
  "decision_risk": {"score": 0.4, "confidence": 0.91}
}
```

`confidence` não é aceita como verdade por ter sido emitida pelo modelo. Probabilidades são calibradas no validation temporal e auditadas por ECE, Brier score, NLL e curvas risco-cobertura.

## 6. Policy determinística sobre as decisões

O controlador nunca executa diretamente uma tool. A policy aplica estas regras:

1. remover ações fora de `allowed_actions` e renormalizar probabilidades;
2. bloquear `trace`, `impact` e `context` sem símbolo observado realmente existente;
3. obter argumentos somente da task ou de observações anteriores;
4. impedir repetição da mesma chamada com os mesmos argumentos e mesmo estado;
5. respeitar orçamento de calls/tokens/tempo;
6. aplicar thresholds calibrados por risco;
7. com incerteza alta, coletar evidência barata ou escalar; nunca adivinhar;
8. `stop` só é aceito quando gates determinísticos mínimos de cobertura passam;
9. ações mutáveis/destrutivas permanecem fora desta fase.

Fluxo provisório, ajustado apenas pelo validation:

```text
ação inválida                         → remover
evidência obrigatória ausente         → locate/context determinístico
P(escalate) acima do threshold         → IA grande
P(context_sufficient) alto + gates OK  → stop
next_action confiante                  → executar tool read-only
incerteza alta + budget disponível     → obter evidência barata
incerteza alta + budget esgotado       → escalar
```

O threshold é por consequência, não um número global: um `locate` read-only pode aceitar risco maior que um `stop` prematuro.

## 7. Dataset de trajetórias

### 7.1 Unidade de treino

Uma linha representa um estado de uma trajetória, não a tarefa inteira:

```json
{
  "episode_id": "...",
  "step": 2,
  "repo_commit": "...",
  "state": "<estado sem ground truth>",
  "allowed_actions": ["siga_trace", "siga_context", "stop", "escalate"],
  "labels": {
    "next_action": "siga_trace",
    "context_sufficient": false,
    "expected_information_gain": 3,
    "escalation_needed": false,
    "decision_risk": 0
  },
  "verification": {
    "action_schema_valid": true,
    "arguments_grounded": true,
    "coverage_delta": 0.31,
    "eventual_tests_passed": true
  },
  "provenance": {
    "source": "verified_replay",
    "teacher": "deterministic_verifier",
    "prompt_version": "jev-like-v1",
    "timestamp": "...",
    "license": "AGPLv3"
  }
}
```

### 7.2 Como produzir labels confiáveis

Ordem de autoridade:

1. verifier/test/graph/Git;
2. ganho marginal medido após executar a ação;
3. trajetória humana ou de agente que terminou em patch válido;
4. teacher grande como proposta;
5. consenso de teachers apenas como sinal auxiliar.

O teacher pode sugerir `trace`; a label só é positiva se o replay mostrar ganho verificável ou se fizer parte de uma trajetória válida não dominada por alternativa mais barata.

### 7.3 Labels de stop e escalada

`stop=true` exige, conforme o tipo de tarefa:

- arquivo/símbolo alvo coberto;
- fluxo principal coberto quando aplicável;
- testes ou superfícies de teste identificados;
- nenhuma referência inexistente no HEAD;
- cápsula dentro do orçamento;
- próxima tool com ganho marginal abaixo do threshold.

`escalation_needed=true` exige evidência de que o caminho local falhou, ficou ambíguo ou envolve raciocínio/edição que o controlador não deve fazer. Não rotular toda tarefa difícil como escalada: comparar se uma tool barata resolveria a incerteza primeiro.

### 7.4 Splits e contaminação

Herdar os cutoffs temporais do benchmark v2 de P13:

- train anterior a `T1`;
- validation entre `T1` e `T2`;
- test cego a partir de `T2`;
- adversarial separado.

Todos os passos do mesmo `episode_id` pertencem ao mesmo split. O trainer não lê queries, refs, SHAs ou labels do test. Estados derivados de uma execução sobre commit futuro nunca entram em treino anterior.

## 8. Estratégia de modelos: simples antes de compartilhado

### E0 — Regras atuais

Baseline sem ML para `next_action`, `stop` e `escalate`. Mede quanto do problema é solucionável deterministicamente.

### E1 — Probe linear/MLP pequeno

Usar features congeladas do nano real ou features tabulares e treinar apenas heads pequenas. Objetivo: provar que há sinal no dataset antes de alterar o encoder.

### E2 — Controlador separado

Micro-modelo dedicado recebe o estado compacto e produz as perguntas tipadas. Serve como baseline de isolamento e evita negative transfer para search.

### E3 — Encoder Needle congelado + heads JEV-like

Reusar embeddings/hidden states do nano, congelar o backbone e treinar:

```text
shared encoder congelado
  ├── retrieval/ranking head existente
  ├── next_action head
  ├── stop head
  ├── escalation head
  └── information_gain/risk heads
```

### E4 — Multi-task parcial

Somente se E3 superar E1/E2 sem degradar retrieval, descongelar gradualmente as últimas camadas. Função de perda candidata:

```text
L = λ_action · CE(next_action)
  + λ_stop · BCE(stop)
  + λ_escalate · BCE(escalate)
  + λ_gain · ordinal_loss(information_gain)
  + λ_risk · ordinal_loss(risk)
  + λ_rank · retrieval_loss
```

Pesos `λ` são escolhidos no validation. Test não participa. Se o multi-task reduzir recall/ranking, manter encoder congelado ou controlador separado.

### E5 — On-policy / DAgger-like

Depois do primeiro controlador estável:

1. executar a policy em tarefas novas;
2. coletar estados que ela realmente visita;
3. consultar teacher/verifier apenas nesses estados;
4. incorporar erros verificados ao train de nova versão;
5. nunca retroalimentar o test congelado.

Isso combate o desvio entre estados de demonstração e estados causados pelos próprios erros do controlador.

## 9. Calibração, abstention e segurança

Acurácia alta sem confiança calibrada não basta para automatizar `stop` e escalada.

Procedimento:

1. treinar no train temporal;
2. ajustar temperature scaling somente no validation;
3. medir ECE, adaptive ECE, Brier e NLL;
4. produzir risk-coverage curve;
5. escolher thresholds por custo do erro;
6. congelar thresholds antes do test;
7. reportar cobertura junto da acurácia.

Erros têm custos diferentes:

```text
stop falso positivo      = crítico: entrega contexto insuficiente
ação com arg inventado   = proibido: grounding fail
tool extra read-only     = custo de latência/tokens
escalada desnecessária   = custo da IA grande
escalada omitida         = risco de patch incorreto
```

A policy deve ter opção explícita de rejeição: baixa confiança não vira escolha forçada.

## 10. Benchmark da Fase 23

### 10.1 Braços

Executar as mesmas tarefas, mesma ordem e mesmo ambiente:

- **A — regras + graph:** controlador determinístico atual;
- **B — nano real + graph:** Needle treinado em P13, sem heads JEV-like;
- **C — nano + policy JEV-like sem treino:** contrato/masks/regras apenas;
- **D — nano + controlador separado:** E2;
- **E — encoder compartilhado + heads:** E3/E4;
- **F — IA grande direta:** referência de qualidade/custo, não runtime local.

Jev hospedado pode ser braço exploratório `X`, nunca requisito. Ele não recebe código proprietário e não escolhe o vencedor por si só.

### 10.2 Três níveis de avaliação

#### J1 — decisão isolada

- next-action accuracy e macro-F1;
- top-2 recall;
- stop precision/recall;
- escalation precision/recall;
- ECE/Brier/NLL;
- schema validity e ações impossíveis.

#### J2 — replay sequencial

- task/trajectory success;
- número de tool calls úteis e desperdiçadas;
- cobertura da cápsula por passo;
- passos até primeiro arquivo relevante;
- taxa de loops/repetições;
- early-stop incorreto;
- taxa de escalada e large-model calls evitadas.

#### J3 — codificação ponta a ponta

- issue → cápsula → patch → testes;
- first-pass test success;
- task success cego;
- tempo até patch válido;
- tokens de entrada/saída da IA grande;
- custo total;
- P50/P95 e peak RAM/VRAM;
- número de interações com a IA grande.

J3 é o gate final, mas sua execução ocorre em P15 sobre o MCP real e o candidato P14 congelado. P14 prepara contratos, replay, calibração e decisão do controlador; não repete o benchmark end-to-end em cada experimento intermediário.

### 10.3 Estatística

- três seeds (`0`, `17`, `42`) para modelos treinados;
- mesmas tarefas pareadas por braço;
- bootstrap pareado 95%;
- contagens absolutas além de percentuais;
- erros separados por tipo de tarefa e risco;
- test aberto uma vez após configuração congelada;
- claims de velocidade usam wall-clock medido, nunca latência simulada.

## 11. Critérios GO / NO-GO

`GO_JEV_CONTROLLER` exige simultaneamente, contra o melhor braço anterior:

- `task_success` não inferior: limite inferior do IC95% do delta ≥ −1 ponto percentual;
- schema validity = 1,0;
- zero argumentos/paths/símbolos inventados;
- nenhum early-stop incorreto no subconjunto crítico e taxa global ≤ 1%;
- redução ≥ 25% em tool calls desperdiçadas;
- redução ≥ 25% em tokens enviados à IA grande;
- redução ≥ 20% no tempo mediano até patch verificado;
- redução ≥ 25% em chamadas da IA grande ou custo equivalente;
- overhead P95 do controlador ≤ 10% do P95 end-to-end;
- ECE ≤ 0,05 no test e curva risco-cobertura publicada;
- três seeds sem regressão operacional relevante.

`GO_SHARED_ENCODER` exige ainda:

- recall/ranking do nano não inferior ao baseline real de P13;
- aumento de parâmetros ≤ 5% sobre o nano real;
- aumento de peak RSS ≤ 20%;
- latência/RAM total melhores que dois modelos separados, ou ganho de qualidade estatisticamente sustentado que justifique o custo.

Se o controlador melhorar classificação mas não reduzir tempo/custo da codificação, o resultado é `NO_GO_SYSTEM`. Se E1 linear igualar E3/E4, manter a solução simples.

## 12. Execução na RTX 4060 e runtime CPU-friendly

- Reutilizar o ambiente JAX/CUDA e o preflight aprovados em P13.
- Treinar heads em processo separado com `CUDA_VISIBLE_DEVICES=0`.
- Começar com encoder congelado e batch determinado por medição; não herdar batch hipotético.
- Registrar GPU, driver, versões, seed, config, peak VRAM/RAM, temperatura e hashes.
- Fazer export/quantização somente após validar FP32/BF16.
- Runtime final deve executar offline em CPU no notebook.
- Pesos, caches e estados com código ficam ignorados; entram no Git apenas schemas, configs, hashes e métricas agregadas.
- Nenhum dado do SIGA é enviado a Jev, teacher ou API externa sem autorização explícita e revisão de licença/privacidade.

## 13. Plano de microtarefas — uma por ciclo

P14 usa o mesmo funil curto do docs/24: uma seed para screening, três apenas para o finalista, e interrupção imediata quando uma baseline mais simples empata.

- `P14-T00`: este plano, fontes e contrato de evidência. Commit `docs(jev): [P14-T00] define typed nano controller phase`.
- `P14-T01`: schemas, action masks, budgets, instrumentação e replay read-only. Commit `feat(controller): [P14-T01] define replayable JEV-like contract`.
- `P14-T02`: dataset temporal de estados produzidos pelo nano real e auditoria de leakage por episódio. Commit `feat(dataset): [P14-T02] freeze JEV-like decision dataset`.
- `P14-T03`: baseline E0 + probe E1, uma seed e até 30 minutos. Sem ganho, emitir `GO_RULES_ONLY` e pular modelos neurais. Commit `feat(evaluation): [P14-T03] screen cheap typed controllers`.
- `P14-T04`: comparar E2 separado com E3 sobre encoder congelado somente se E1 mostrar sinal. E4/descongelamento não entra nesta fase. Commit `feat(training): [P14-T04] compare frozen JEV-like controllers`.
- `P14-T05`: calibrar, aplicar abstention e validar J1/J2. Commit `feat(evaluation): [P14-T05] calibrate JEV-like decisions`.
- `P14-T06`: confirmar seeds restantes apenas no vencedor e congelar policy/thresholds. Commit `docs(decisions): [P14-T06] freeze JEV-like controller decision`.

Não iniciar `P14-T01` antes de P13 produzir um nano real e baseline real. Resultados históricos baseados em `evaluation.NeedleTunedModel` são simulação e não podem dimensionar heads, RAM, latência ou ganho de qualidade desta fase.

DAgger/on-policy e E4 ficam adiados até P15 produzir falhas reais do MCP. O benchmark J3 A–F sai desta fase e passa a P15, evitando repetir uma avaliação cara em arquiteturas ainda transitórias.

## 14. Riscos e mitigação

- **Negative transfer:** heads de decisão pioram retrieval. Mitigar congelando encoder, medindo head por head e mantendo modelo separado como baseline.
- **Stop prematuro:** otimização de custo encerra investigação cedo. Mitigar com gate determinístico, threshold conservador e métrica específica.
- **Confiança falsa:** softmax alto não significa probabilidade calibrada. Mitigar com temperature scaling, Brier/ECE e abstention.
- **Teacher bias:** IA grande ensina seus próprios hábitos caros. Mitigar com ganho marginal executado e verifier acima do teacher.
- **Compounding errors:** um erro muda todos os estados seguintes. Mitigar com replay e DAgger-like em estados on-policy.
- **Overfitting ao SIGA:** controlador memoriza nomes. Mitigar com paths relativos abstraídos, hard negatives, splits temporais e segundo perfil de projeto.
- **Otimização da métrica errada:** action accuracy sobe, patch success cai. Mitigar com J3 como gate final.
- **Vendor lock-in:** contrato copia SDK fechado. Mitigar com schema interno, adapter opcional e nenhuma dependência no core.
- **Vazamento de código:** estado enviado externamente. Mitigar mantendo caminho primário offline e proibindo API externa por padrão.

## 15. Fontes e como influenciam o plano

### Jev / TypeSafe — fontes oficiais, não paper peer-reviewed

- TypeSafe AI, **Introducing System One Models & Jev**: estado não estruturado → decisões tipadas/probabilísticas, sampler paralelo e RLCD como descrição do fornecedor. <https://typesafe.ai/blog/introducing-system-one-models-and-jev>
- TypeSafe, **Introduction**: Choice, Score e Noul; perguntas atômicas e composição em código. <https://docs.typesafe.ai/introduction>
- TypeSafe, **Choice**: opções fechadas, distribuição completa e confiança. <https://docs.typesafe.ai/primitives/choice>
- TypeSafe, **Score**: níveis ordenados, distribuição e score interpolado. <https://docs.typesafe.ai/primitives/score>
- TypeSafe, **Noul**: decisão binária probabilística. <https://docs.typesafe.ai/primitives/noul>
- TypeSafe, **Confidence**: thresholds dependem do risco; baixa confiança deve coletar evidência, pedir revisão ou recusar. <https://docs.typesafe.ai/confidence>
- TypeSafe, **Workflow evals**: decompor policy em perguntas estreitas e regras programáticas. <https://evals.typesafe.ai/>
- TypeSafe AI, **System One Adapter**: referência aberta para comparar o mesmo contrato contra LLMs, com telemetria de retries, tokens e latência. <https://github.com/typesafe-ai/system-one-adapter-python>

### Papers que sustentam a implementação JEV-like

- Caruana, **Multitask Learning** (1997): representação compartilhada pode transferir sinal entre tarefas relacionadas; sustenta E3/E4, mas não dispensa medir negative transfer. <https://doi.org/10.1023/A:1007379606734>
- Guo et al., **On Calibration of Modern Neural Networks** (ICML 2017): redes modernas podem ser mal calibradas; temperature scaling é baseline obrigatório. <https://proceedings.mlr.press/v70/guo17a.html>
- Geifman & El-Yaniv, **SelectiveNet** (ICML 2019): opção de rejeição e análise risco-cobertura sustentam abstention em vez de ação forçada. <https://proceedings.mlr.press/v97/geifman19a.html>
- Ross, Gordon & Bagnell, **DAgger** (AISTATS 2011): políticas sequenciais precisam treinar nos estados que suas próprias ações induzem; sustenta uma etapa on-policy futura, somente após P15 produzir estados reais. <https://proceedings.mlr.press/v15/ross11a.html>
- Yao et al., **ReAct** (ICLR 2023): alternância entre ação e observação sustenta a avaliação por trajetória, sem importar o raciocínio textual para o nano. <https://arxiv.org/abs/2210.03629>
- Schick et al., **Toolformer** (NeurIPS 2023): aprender quando e como usar tools sustenta labels de ação, argumentos e stop verificados. <https://proceedings.neurips.cc/paper/2023/hash/d842425e4bf79ba039352da0f658a906-Abstract-Conference.html>
- Chen, Zaharia & Zou, **FrugalGPT** (TMLR): cascatas condicionais podem reduzir custo sem fixar uma única IA para todas as tarefas; sustenta nano → IA grande. <https://arxiv.org/abs/2305.05176>
- Ong et al., **RouteLLM** (2024): routing aprende o trade-off qualidade/custo a partir de preferências; sustenta a head de escalada, que ainda precisa de validação local. <https://arxiv.org/abs/2406.18665>

## 16. Definição de pronto

A Fase 23/P14 termina apenas quando:

1. o contrato JEV-like for versionado e fail-closed;
2. episódios puderem ser reproduzidos passo a passo;
3. dataset temporal e test cego tiverem auditoria de contaminação;
4. regras e probe forem comparados; modelos separados/heads compartilhadas entram somente se o probe demonstrar sinal;
5. probabilidades estiverem calibradas e thresholds congelados;
6. a policy final estiver congelada e pronta para o J3 de P15;
7. um ADR escolher `GO_SHARED_FROZEN_HEADS`, `GO_SEPARATE_CONTROLLER`, `GO_RULES_ONLY` ou `NO_GO_JEV`;
8. nenhuma conclusão usar pesos simulados como evidência neural real.
