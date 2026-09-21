# 21 — Treinamento e benchmark reais do Needle na RTX 4060 Laptop

> **Tarefa deste documento:** `P13-T00`
>
> **Commit exato:** `docs(training): [P13-T00] define real Needle training and benchmark plan`
>
> **Estado:** plano aprovado para execução incremental; nenhum treino é considerado real antes dos gates deste documento.
>
> **Substitui como fonte operacional:** as partes simuladas de `docs/09`, P07/P08 e relatórios que usam `evaluation.NeedleTunedModel` sem carregar pesos.
>
> **Execução passo a passo:** `docs/22-real-needle-training-runbook.md`.
>
> **Plano de fechamento e limites de tempo:** `docs/24-real-nano-jev-mcp-delivery.md`. Em conflito operacional, o funil curto e os critérios de parada do docs/24 prevalecem para as tarefas ainda abertas.

## 1. Objetivo e fronteira de verdade

Objetivo: treinar um adapter LoRA real para Needle 3, exportar pesos `.cact`, executar inferência real e comparar o especialista contra baselines determinísticas em um benchmark novo, cego e sem contaminação.

Este plano separa quatro coisas que não podem voltar a ser misturadas:

1. **Simulador de política:** regras/regex/hash em Python; serve para testar a tubulação, nunca mede qualidade de modelo.
2. **Needle base real:** engine oficial + checkpoint oficial, sem LoRA.
3. **Needle tuned real:** checkpoint oficial + adapter LoRA realmente treinado + `.cact` exportado.
4. **Sistema completo:** Needle real escolhendo tools, tools executando sobre o SIGA e uma IA grande consumindo a cápsula.

Relatórios anteriores que instanciam `evaluation.NeedleTunedModel` permanecem históricos, mas passam a ser classificados como `simulated_policy`. Não podem ser usados para afirmar acurácia, latência, RAM, quantização ou ganho de um modelo Needle real.

## 2. Hardware-alvo medido em 2026-09-21

Inventário inicial e validação posterior nesta máquina:

- SO: Pop!_OS/Linux x86-64, kernel `7.1.5-76070105-generic`.
- CPU: Intel Core i7-13620H, 10 cores / 16 threads, AVX2/AVX-VNNI.
- RAM: 31 GiB físicos; apenas 7,3 GiB disponíveis no momento da auditoria.
- Swap: 19 GiB; 11 GiB estavam em uso — sinal de pressão de memória antes de qualquer treino.
- Disco: 73 GiB livres no filesystem do projeto, 84% ocupado.
- GPU integrada: Intel Raptor Lake-P UHD.
- GPU dedicada: NVIDIA AD107M, `GeForce RTX 4060 Max-Q / Mobile`, PCI `10de:28a0`.
- Driver validado: `580.173.02`; módulos `nvidia`, `nvidia_modeset`, `nvidia_drm` e `nvidia_uvm` carregados.
- GPU validada por `nvidia-smi`: 8.188 MiB totais e 7.804 MiB livres no preflight registrado.
- JAX validado: versão 0.11.2, backend `gpu`, dispositivo `[CudaDevice(id=0)]`.
- Treino real observado: pico de 7.652 MiB de VRAM e 100% de utilização no probe batch 4; batch 2 concluiu com segurança.
- ML local: o import `torch` resolve para um namespace incompleto, sem versão e sem `torch.cuda`; isso é irrelevante para Needle, que treina em JAX, mas prova que o ambiente Python atual não é confiável para treino.

A RTX 4060 e o acesso de compute já estão comprovados. Novas sessões continuam executando o preflight porque sandbox, modo gráfico ou carga concorrente podem retirar o acesso sem alterar o hardware físico.

## 3. Como o agente menor deve acessar a RTX 4060

### 3.1 Responsabilidade humana quando o preflight regredir

Alterar driver, modo gráfico ou reiniciar a máquina exige autorização e execução humana. O agente não usa `sudo`, não instala driver do sistema e não reinicia o notebook.

No Pop!_OS, o operador deve preferir **Compute** — iGPU renderiza a interface e a NVIDIA fica disponível para CUDA — ou **NVIDIA**. A documentação do System76 prevê:

```bash
sudo system76-power graphics
sudo system76-power graphics compute
# ou, se compute não funcionar neste notebook:
sudo system76-power graphics nvidia
```

Depois da troca é obrigatório reiniciar. Em modo híbrido, PRIME é relevante para renderização, mas treinamento JAX/CUDA continua dependendo de driver e device nodes; variáveis de GLX/Vulkan não substituem o gate CUDA.

### 3.2 Gate de pré-voo do agente

O agente executa estes checks read-only antes de instalar dependências ou iniciar treino:

```bash
lspci -nn | rg -i 'nvidia|vga|3d'
nvidia-smi -L
nvidia-smi --query-gpu=index,name,uuid,driver_version,memory.total,memory.free,temperature.gpu,power.limit --format=csv,noheader
find /dev -maxdepth 1 -name 'nvidia*' -print
free -h
df -h .
```

Depois de instalar o ambiente isolado do P13-T01:

```bash
CUDA_VISIBLE_DEVICES=0 python -c \
  'import jax; print(jax.default_backend()); print(jax.devices())'
```

Treino GPU só é liberado se, na mesma sessão:

- `nvidia-smi -L` listar exatamente a RTX 4060;
- `/dev/nvidia0` e `/dev/nvidiactl` estiverem acessíveis;
- o driver satisfizer o mínimo do JAX escolhido;
- `jax.default_backend()` for `gpu`;
- `jax.devices()` listar um dispositivo NVIDIA;
- `CUDA_VISIBLE_DEVICES=0` selecionar apenas a GPU dedicada;
- houver pelo menos 12 GiB de RAM do host disponíveis e 40 GiB de disco livres;
- nenhuma outra carga estiver consumindo VRAM relevante;
- o notebook estiver conectado à energia e com ventilação desobstruída.

Qualquer falha produz `BLOCKED`, grava o diagnóstico e encerra. É proibido cair para CPU em qualquer forma — `cpu_smoke` e qualquer experimento CPU estão proibidos, sem exceção. Sem GPU liberada não há run: registra-se `BLOCKED` e para.

### 3.3 Processo e isolamento

- Treino roda em subprocesso próprio, nunca dentro do servidor MCP.
- O processo recebe `CUDA_VISIBLE_DEVICES=0` e um diretório de artefatos explícito.
- JAX, Cactus Needle e CUDA são instalados numa virtualenv dedicada e fixados em lockfile.
- O ambiente de treino não herda `PYTHONPATH` de outros projetos.
- O agente registra stdout/stderr sem imprimir tokens, chaves ou dados pessoais.
- Pesos, checkpoints, caches e datasets brutos ficam em paths ignorados pelo Git; só manifestos, hashes, configs e métricas entram no commit.
- Durante o run, `nvidia-smi` amostra uso de VRAM, GPU, potência e temperatura a cada segundo em arquivo local.
- Se temperatura alcançar o limite térmico reportado pelo próprio driver, se houver throttling sustentado, OOM, NaN ou perda do device, o run é inválido e interrompido.

## 4. Stack real e reproduzível

A trilha local usa o pacote oficial `cactus-needle` e JAX CUDA. A documentação oficial atual indica:

```bash
python -m pip install "cactus-needle[train,gpu]"
needle finetune train.jsonl --epochs 3 --out adapter.safetensors
needle build checkpoints/needle3.safetensors \
  --lora adapter.safetensors --layers 20 --out tuned-20L.cact
```

Regras:

- Não adicionar essas dependências ao runtime principal antes do ADR e lock do P13-T01.
- Não usar PyTorch/Transformers para o treino Needle; o pipeline oficial é JAX/Flax/Optax.
- Começar com CUDA 12, pois o extra GPU oficial observado resolve `jax[cuda12]`; JAX exige driver NVIDIA compatível. CUDA 13 só entra após compatibilidade comprovada e novo lock.
- Registrar versões de Python, `cactus-needle`, JAX, jaxlib, Flax, Optax, driver e runtime CUDA.
- Fazer download do checkpoint/engine uma vez, calcular SHA-256 e depois executar offline.
- Nunca usar `needle generate-data --generate` ou Cactus Platform sem autorização humana: podem consumir API/quota e enviar dados externamente.
- O caminho primário é treino local. Plataforma hospedada é uma baseline opcional e separada, nunca o resultado local.

A versão efetivamente usada nos artefatos locais é `cactus-needle 3.0.4`; o lock e o manifest do run continuam sendo a autoridade, não este texto.

## 5. Dados: novo contrato sem contaminação

O export H06 atual tem apenas 29 registros e declara `bench_derived=true`. Ele pode servir para depurar formato, mas não pode treinar um modelo que será avaliado na mesma suíte.

O P13 cria quatro conjuntos disjuntos:

1. **Train:** trajetórias verificadas derivadas de commits anteriores ao cutoff `T1`; sem IDs, queries, snippets ou SHAs do teste.
2. **Validation:** janela temporal posterior a train e anterior a `T2`; usada para early stopping e escolha de rank.
3. **Test cego:** 200–500 tarefas derivadas de commits em/apos `T2`; congelado antes do primeiro treino e inacessível ao trainer.
4. **Adversarial externo:** consultas off-topic, vagas, PT-BR, homônimos, argumentos ausentes e schemas parecidos, escritas sem consultar as respostas do test.

Cada registro preserva `repo_commit`, source, teacher, prompt version, timestamp, verifier, licença e hashes. O manifest registra os cutoffs e SHA-256 de cada arquivo.

### 5.1 Regras de formato Needle

- Um JSON por linha com `query`, catálogo `tools`, `answers` e `reasoning` curto.
- Argumentos só podem copiar valores presentes na consulta ou em observações reais anteriores.
- Campo opcional sem evidência é omitido; campo requerido sem evidência produz `answers: []` ou uma etapa `locate`, nunca valor inventado.
- Pelo menos 1/8 dos exemplos de treino deve ser off-topic/no-tool, conforme recomendação oficial.
- Similar-tool e consultas ambíguas entram deliberadamente.
- `task_type`, expected tool, ground truth e resposta correta nunca entram no prompt de inferência.
- Medir tokens renderizados. Usar o menor `--max-len` que cubra o P99 sem truncamento; começar em 256, subir para 512/1024 somente com evidência.
- Qualquer truncamento silencioso invalida o run.

### 5.2 Sequência agentiva e grounding

`trace`, `impact` e `context` exigem símbolo real. O benchmark não autoriza o modelo a inventá-lo diretamente da memória:

```text
tarefa → locate(query verbatim) → candidatos reais → trace/impact(symbol real) → context
```

O scorer valida cada chamada contra o schema antes de executar. Tool correta com argumentos de outra tool é `invalid_call`, não acerto parcial.

## 6. Funil de treinamento na RTX 4060

Cada degrau é um experimento independente, com config, hashes e seed, mas não forma um produto cartesiano. Uma seed faz screening; somente o vencedor recebe três seeds. Cada configuração começa em 4–16 casos, avança para validation maior apenas se passar e obedece aos orçamentos do docs/24 §3.

### R0 — Base real e ambiente

- Rodar Needle 3 base real nas tools SIGA e na suite oficial de smoke.
- Rodar 4 casos estruturais e, se couber no orçamento, 16 casos internos sem LoRA. Não executar baseline de horas.
- Confirmar JSON bem-formado, execução offline e latência real.
- Gate: zero crash, zero chamada fora do schema, artefato base com SHA conhecido.

### R1 — Smoke LoRA de 100 exemplos

- 100 train + validation temporal, seed 0, 1 época.
- Executar uma única vez. A evidência local já produzida encerra este degrau; não repetir smoke.
- Busca de batch completa é proibida nas próximas seeds. Reutilizar o batch comprovado por chave `checkpoint + max_len + rank + dtype`; se a configuração mudar, testar no máximo dois batches vizinhos com probe curto.
- Rank 16, alpha 32, LR `1e-4`, clipping 1.0; defaults oficiais, sem tuning ainda.
- Gate: loss finito, adapter carregável, build 20L concluído e inferência tuned diferente do base em pelo menos um caso esperado.

### R2 — Candidato de 500 exemplos totais

- O export atual contém 350 train + 150 validation temporal. O adapter seed 0/3 épocas já existente deve ser medido antes de qualquer novo treino.
- Começar com 20L/seed 0 no funil 4 → 16 → 60 tarefas.
- Executar seeds `17` e `42` somente se a seed 0 passar o gate funcional.
- Early stopping pela curva real de validation loss; nunca por test.
- Gate: schema-valid 100%, invalid-call 0%, no-tool ≥ 0,95 e nenhum vazamento.

### R3 — Capacidade e grounding

- Rank 32 só é permitido se rank 16 acerta tool mas erra argumentos de forma estatisticamente material.
- Comparar rank 16 vs 32 com mesmo dataset, seeds e orçamento.
- Escolher por validation, não por test.
- Gate: ganho pareado ou manter rank 16 por simplicidade.

### R4 — Screening 2k; 5k diferido

- O `gold_2000.jsonl` já existe com 1.400 train/600 valid; primeiro exportar e auditar, sem regenerar.
- Treinar 2k com uma seed de screening. Só confirmar outras seeds se melhorar validation sem degradar no-tool/grounding.
- 5k e 10k ficam fora do fechamento inicial. Só voltam por análise de erros do MCP real que demonstre diversidade ausente e benefício provável.
- Gate: relatório real `dataset size × seed × accuracy × loss × tempo × VRAM`.

### R5 — Subnetworks reais

- Treinar uma vez no full 20L e exportar primeiro `20, 16, 12` layers com o mesmo adapter.
- Exportar `8, 4, 2` somente se 12L ficar dentro da margem de não inferioridade; caso contrário, profundidades menores não entram no fechamento inicial.
- Benchmarkar cada `.cact`; não simular degradação por hash.
- Local tuned usa o esquema de quantização aceito pelo adapter/build. Não forçar bits conflitantes com QAT.
- Escolher a menor profundidade cuja diferença para 20L esteja dentro da margem de não-inferioridade de 1 ponto percentual e cumpra o SLO.

## 7. Benchmark real em três camadas

### B1 — Modelo isolado

Entrada: `query + system facts + schemas`. Saída: chamada Needle bruta.

Métricas: Tool Selection Accuracy, Argument Exact Match, Schema Validity, Invalid Tool Call Rate, No-Tool Accuracy, grounding e latência de inferência. Não executar tools nesta camada.

### B2 — Agente com tools

Executar a sequência completa em checkout temporário/read-only: modelo → tool → observação → próxima chamada. Medir Tool Sequence Success, File/Symbol Recall@1/3/5, trace/impact, hallucination, número de calls, tokens da cápsula e time-to-first-relevant-file.

### B3 — Sistema A/B cego

Somente depois de B1/B2 verdes:

- A: IA grande sem MCP.
- B: IA grande + graph determinístico.
- C: IA grande + Needle tuned real + tools + cápsula.

Operador/modelo que responde não vê GT. Medir task success, input/output tokens, custo, latência e edição válida. Resultado de B3 não retroalimenta o test; failures viram candidatos de treino para uma versão posterior.

### 7.1 Baselines mínimas

- Regras determinísticas atuais (`tools.selector`) — baseline principal a superar.
- Needle 3 base real 20L em amostra curta e com timeout; se exceder o orçamento, publicar `NOT_COMPLETED` sem bloquear o candidato.
- Needle 3 tuned real 20L.
- Needle tuned real por subnetwork.
- Small coder real, se houver adapter/engine disponível e autorizado; nunca a classe heurística atual.

### 7.2 Estatística e repetição

- Seed `0` para screening; seeds `0`, `17`, `42` somente no candidato final.
- Ordem das tarefas randomizada por seed registrada.
- Aquecer o engine antes de medir. Qualidade usa uma passagem por tarefa; latência usa três repetições somente num subconjunto fixo de 20 casos.
- Reportar P50/P95, média e intervalo bootstrap pareado de 95% para deltas de sucesso.
- A unidade de comparação é a mesma tarefa sob dois braços.
- Publicar contagens absolutas junto das taxas; nunca só percentuais.
- Hardware monitorado: peak VRAM, peak RAM, duração, temperatura, potência e throttling observado.

## 8. Critérios GO / NO-GO

### Gate do modelo

`GO_MODEL` somente se tuned real:

- carregar um `.cact` com hash registrado;
- executar no engine oficial sem simulador;
- atingir Schema Validity = 1,0 e Invalid Tool Call Rate = 0;
- atingir No-Tool Accuracy ≥ 0,95;
- não introduzir path/symbol hallucination;
- superar a regra determinística em task success, com delta pareado e intervalo de 95% reportados; comparar o Needle base apenas onde o orçamento permitir, sem inventar delta;
- reproduzir o resultado nas três seeds sem dispersão operacionalmente relevante.

Se tuned ≤ regras determinísticas, aplicar ADR-009: manter Needle como experimento/extrator e usar regras como controlador.

### Gate da subnetwork

`GO_SUBNETWORK` somente para a menor depth com queda ≤ 1 ponto percentual vs 20L, schema/grounding intactos e P95 dentro do orçamento provisório de 250 ms por decisão local. O orçamento deve ser reavaliado no B3; não inclui tempo das tools.

### Gate do sistema

`GO_SYSTEM` requer `task_success_delta ≥ 0` contra o melhor braço sem Needle e redução real de tokens/custo. Economia com queda de sucesso é NO-GO.

## 9. Artefatos obrigatórios

Cada run real deve produzir, sem commitar pesos:

- `hardware_preflight.json`;
- `environment.lock` e hash;
- `dataset_manifest.json` com cutoffs e hashes;
- `train_config.json`;
- curva completa `train_loss`/`val_loss`;
- `adapter.safetensors` local + SHA-256 no run;
- `.cact` local por depth + SHA-256 no run;
- métricas B1/B2 e amostras de erros;
- telemetria GPU/RAM local;
- registro em `experiments/runs/` com commits SIGA/siga-teste, versões, seed e status;
- report agregado versionado sem código/snippets proprietários.

Arquivos de pesos, cache, logs brutos e datasets derivados continuam locais/ignorados. Antes do P13-T01, ampliar `.gitignore` para `.cact`, adapters, checkpoints e telemetria bruta.

## 10. Plano de microtarefas — uma por ciclo

P13-T00 a P13-T02 preservam seu histórico. As tarefas abertas são reorganizadas pelo docs/24:

- `P13-T03`: corrigir B1 de uma geração, ground truth do scorer, schema, timeout e B2 com callables. Commit `fix(evaluation): [P13-T03] bound real Needle evaluation`.
- `P13-T04`: consolidar hashes e artefatos existentes, sem novo treino. Commit `chore(training): [P13-T04] consolidate real Needle artifacts`.
- `P13-T05`: validar 20L/seed 0 do candidato de 350 train no funil curto. Commit `feat(evaluation): [P13-T05] validate real Needle candidate`.
- `P13-T06`: exportar 2k e executar uma seed de screening; 5k fica fora. Commit `feat(training): [P13-T06] screen verified 2k Needle data`.
- `P13-T07`: confirmar apenas o vencedor nas seeds restantes e testar 20L/16L/12L. Commit `feat(training): [P13-T07] confirm real Needle finalist`.
- `P13-T08`: congelar pesos/configuração, abrir test uma vez e emitir decisão do nano. Commit `docs(decisions): [P13-T08] freeze real nano model decision`.

B3 sai de P13 e passa a P15, onde será medido dentro do MCP e da edição real. A próxima tarefa é P13-T03; nenhum treino adicional deve começar antes de o harness estar correto.

## 11. Fontes primárias verificadas em 2026-09-21

- Cactus Needle — fine-tuning oficial: <https://github.com/cactus-compute/needle/blob/main/doc/finetuning.md>
- Cactus Needle — contrato atual para agentes: <https://github.com/cactus-compute/needle/blob/main/llms.txt>
- Cactus Needle — dependências e extra GPU: <https://github.com/cactus-compute/needle/blob/main/pyproject.toml>
- JAX — instalação NVIDIA/CUDA: <https://docs.jax.dev/en/latest/installation.html>
- NVIDIA — CUDA Linux installation/verification: <https://docs.nvidia.com/cuda/cuda-installation-guide-linux/>
- System76 — modos gráficos Pop!_OS: <https://support.system76.com/support/graphics-switch-pop>
