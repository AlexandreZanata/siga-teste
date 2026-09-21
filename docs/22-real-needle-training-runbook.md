# 22 — Runbook: aplicar o treinamento real do Needle na RTX 4060

> Documento operacional de execução. O desenho científico e os critérios estão em `docs/21-real-needle-training-benchmark.md`.
>
> O funil curto, os orçamentos e a continuidade P13→P14→P15 estão em `docs/24-real-nano-jev-mcp-delivery.md`.
>
> Este runbook não autoriza `sudo`, instalação de driver, upload, Cactus Platform, push ou PR. Essas ações continuam dependendo de autorização humana explícita.

## 1. Resultado esperado

Ao final da fase P13 devem existir evidências reproduzíveis desta cadeia:

```text
RTX 4060 visível ao JAX
  → Needle 3 base real
  → dataset temporal não contaminado
  → adapter LoRA real
  → tuned-20L.cact real
  → subnetworks reais
  → benchmark modelo/tools/sistema
  → ADR GO ou NO-GO
```

Um resultado é real somente quando o run registra backend JAX `gpu`, nome/UUID da RTX 4060, versões, hashes do checkpoint/adapter/`.cact`, config, seed e métricas calculadas a partir da saída da engine oficial.

## 2. Política rápida para o agente executor

- Executar exatamente a primeira tarefa P13 ainda não concluída.
- Uma issue, uma branch, um commit, um PR.
- Executar todos os gates locais antes do commit.
- Depois de PR autorizado, registrar URL/SHA e encerrar sem esperar ou consultar continuamente o CI.
- Nunca editar o clone `../`; ele é somente leitura.
- Nunca usar o simulador `evaluation.NeedleTunedModel` como modelo.
- Nunca passar `task_type`, expected tool ou ground truth ao Needle.
- Treino nunca cai de GPU para CPU: JAX deve registrar backend `gpu` na RTX 4060.
- A engine oficial `.cact` pode executar em CPU quando não houver backend CUDA publicado; registrar isso explicitamente, aplicar timeout por tarefa e nunca repetir benchmark de horas.
- Sempre treino e modelo reais com pesos carregados; simulação proibida em qualquer forma.
- Todo loop de avaliação com limite seguro e log de progresso com flush por tarefa (`[i/N]`).
- Nunca usar test para escolher hiperparâmetro.
- Nunca commitar pesos, caches, secrets ou telemetria bruta.
- Se uma condição obrigatória falhar, registrar `BLOCKED` e parar sem fabricar sucesso.

## 3. Preparação humana da GPU

A GPU foi validada como NVIDIA GeForce RTX 4060 Laptop, driver 580.173.02, 8.188 MiB e JAX 0.11.2 com backend `gpu`. Esta preparação só é necessária se um novo preflight deixar de enxergar `nvidia-smi`, `/dev/nvidia*` ou `CudaDevice(id=0)`.

O operador humano deve:

1. Conectar o notebook à energia e fechar cargas pesadas.
2. Selecionar modo **Compute** no Pop!_OS; se incompatível, selecionar **NVIDIA**.
3. Reiniciar a máquina.
4. Confirmar no terminal do host:

```bash
sudo system76-power graphics
nvidia-smi -L
nvidia-smi
```

Para trocar pelo terminal, quando necessário e autorizado:

```bash
sudo system76-power graphics compute
# ou
sudo system76-power graphics nvidia
```

O agente não executa estes comandos com `sudo`.

## 4. P13-T01 — ambiente CUDA/JAX/Needle

### 4.1 Pré-voo read-only

Executar:

```bash
git status --short --branch
lspci -nn | rg -i 'nvidia|vga|3d'
nvidia-smi -L
nvidia-smi --query-gpu=index,name,uuid,driver_version,memory.total,memory.free,temperature.gpu,power.limit --format=csv,noheader
find /dev -maxdepth 1 -name 'nvidia*' -print
free -h
df -h .
```

Bloquear se:

- `nvidia-smi` falhar;
- `/dev/nvidia0` ou `/dev/nvidiactl` estiver ausente/inacessível;
- RAM disponível for menor que 12 GiB;
- disco livre for menor que 40 GiB;
- houver outra carga relevante na GPU.

### 4.2 Ambiente isolado

Criar a virtualenv em path ignorado pelo Git:

```bash
python3 -m venv data/venvs/needle3-cu12
source data/venvs/needle3-cu12/bin/activate
python -m pip install --upgrade pip
python -m pip install "cactus-needle[train,gpu]"
```

Não instalar Torch/Transformers: o treino oficial do Needle usa JAX/Flax/Optax.

Verificar:

```bash
CUDA_VISIBLE_DEVICES=0 python -c 'import jax; print(jax.__version__); print(jax.default_backend()); print(jax.devices())'
needle --help
needle finetune --help
needle build --help
```

O gate passa apenas se `jax.default_backend()` imprimir `gpu` e `jax.devices()` identificar NVIDIA. Capturar versões resolvidas e criar um lock versionado no escopo da tarefa; o primeiro install não é o lock definitivo.

### 4.3 Checkpoint e execução offline

Baixar uma vez, com rede autorizada:

```bash
needle download needle3.safetensors --out data/needle-real/checkpoints
needle fetch
```

Calcular SHA-256, registrar origem/versão e então testar `HF_HUB_OFFLINE=1`. Falha offline significa ambiente ainda incompleto.

## 5. P13-T02 — construir dataset e benchmark v2

### 5.1 Cutoffs

Selecionar e congelar antes do treino:

- train: commits anteriores a `T1`;
- validation temporal: `T1 ≤ commit < T2`;
- test cego: `commit ≥ T2`;
- adversarial: off-topic, no-tool, queries vagas, homônimos e schemas semelhantes.

O test deve conter 200–500 tarefas e não pode ser lido por trainer, gerador ou agente executor das respostas.

### 5.2 Arquivo Needle

Cada linha de treino:

```json
{"query":"Localize ExDocumentoController","tools":[{"name":"siga_locate","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}],"answers":[{"name":"siga_locate","arguments":{"query":"ExDocumentoController"}}],"reasoning":"ExDocumentoController aparece literalmente na consulta"}
```

Regras obrigatórias:

- `answers: []` em pelo menos 1/8 do treino para off-topic/no-tool;
- argumentos copiados da query ou de observação anterior;
- campos opcionais sem evidência omitidos;
- schemas parecidos representados por hard negatives;
- nenhuma linha com `task_type`, expected answer ou GT no prompt;
- P99 de tokens define `max-len`; nenhum exemplo truncado.

O CLI local usa `--val-split` interno para acompanhar loss. A validation temporal permanece separada e é avaliada externamente; ela é a fonte da escolha de configuração.

## 6. P13-T03 — baseline Needle 3 real

Exportar as cinco tools para JSON Schema aceito pelo Needle. Rodar o checkpoint base diretamente:

```bash
CUDA_VISIBLE_DEVICES=0 needle run \
  --checkpoint data/needle-real/checkpoints/needle3.safetensors \
  --tools data/needle-real/tools/siga-tools.json \
  --query "Localize ExDocumentoController"
```

Depois criar o adapter isolado em `inference/` e executar B1 no benchmark de desenvolvimento. Salvar a saída bruta antes de qualquer normalização.

Gate:

- engine oficial carregada;
- output parseável pelo contrato Needle;
- schema validation real;
- nenhum import do simulador;
- latência e hardware registrados.

### 6.1 B1 rápido e semanticamente correto

O B1 antigo chamou `Needle.run(max_steps=8, max_new_tokens=512)` com schemas sem funções executáveis. Isso transforma uma decisão isolada em até nove gerações, produz `unknown tool` e não mede corretamente B1. O checkpoint parcial é apenas diagnóstico histórico e não deve ser retomado no perfil antigo.

Fluxo obrigatório:

1. B1 chama `Needle.complete()` exatamente uma vez e não executa tools.
2. Começar com `max_new_tokens=128`; subir para 256 somente se houver truncamento registrado.
3. Manter `expected_tool`, `task_type` e demais labels no scorer, passando ao modelo apenas query/system/schemas.
4. Executar 4 → 16 → até 60 tarefas de validation; falha em um estágio impede o próximo.
5. Aplicar timeout por tarefa e checkpoint JSONL idempotente.
6. O baseline base usa amostra curta pareada; uma run CPU de horas não bloqueia o modelo novo.

### 6.2 Limites seguros para avaliação

O B1 base de 2026-09-21 consumiu horas em CPU sem produzir evidência proporcional. Não repetir. Para as próximas avaliações:

- Registrar o backend real da engine. Não atribuir GPU a uma engine CPU-only.
- B1 não recebe `max_steps`; B2 começa em três passos e só aumenta por erro demonstrado.
- Treino mantém telemetria da RTX 4060; inferência registra wall-clock, CPU/RAM e GPU quando aplicável.
- Progresso obrigatório: `print(f"[{i+1}/{n}] ...", flush=True)` por tarefa — rodada opaca acima de 30 min é defeito do harness, não do modelo.
- Critério de aborto: 120 s por tarefa inicialmente, 60 s sem progresso de treino, projeção 25% acima do orçamento, OOM/NaN/throttling ou perda do device.

## 7. P13-T03 — corrigir a avaliação antes de treinar

Implementar primeiro o perfil rápido do §6.1. O teste mínimo deve provar:

- uma única geração por tarefa no B1;
- labels presentes no scorer e ausentes no prompt;
- argumentos validados pelo schema completo;
- timeout/checkpoint/resume;
- B2 separado com funções reais.

Gate: 16 casos em até 5 minutos, zero `unknown tool` causado pelo harness e métrica de tool selection calculável.

## 8. P13-T04 — consolidar, não repetir

O N=100, a busca de batch e os exports existentes passam a evidência histórica. Calcular/verificar hashes, carregar 20L/12L offline e registrar a chave da configuração. Não iniciar nova época.

Batch 2 é o fallback comprovado. Batch 4 só volta após shapes constantes no treino/validation e probe curto; não repetir a sequência 1/2/4/8/16.

Ativar cache persistente do JAX antes da primeira compilação:

```bash
export JAX_COMPILATION_CACHE_DIR="$PWD/data/jax-cache/needle3"
export CUDA_VISIBLE_DEVICES=0
```

O wrapper não deve converter `loss` para host em todo passo; sincronizar apenas no intervalo de log e no fim da época. Não editar a virtualenv manualmente: a adaptação precisa ficar versionada no repositório ou ser corrigida upstream.

## 9. P13-T05 — avaliar o candidato real existente

Avaliar o 20L treinado com 350 registros/seed 0 na ordem:

1. quatro casos estruturais;
2. 16 casos estratificados;
3. até 60 casos de validation;
4. B2 curto com tools reais.

Interromper na primeira falha de schema, grounding, no-tool ou orçamento. Não executar seeds adicionais antes desse gate.

## 10. P13-T06 — screening 2k

Exportar o dataset verificado existente para 1.400 train/600 valid. Usar rank 16, uma seed e até três épocas. O test permanece fechado e o treino tem orçamento de 60 minutos.

Somente se superar o candidato P13-T05 sem regressão, avançar. 5k/10k e rank 32 ficam fora; podem voltar por uma nova tarefa sustentada por análise de erros.

## 11. P13-T07 — confirmação do vencedor

Executar seeds `17` e `42` apenas para o vencedor. Exportar 20L, 16L e 12L. Avaliar 8L/4L/2L somente se 12L estiver dentro da margem de 1 ponto percentual.

Qualidade usa uma passagem por tarefa. Para latência, aquecer e repetir três vezes apenas um subconjunto fixo de 20 casos.

## 12. P13-T08 — congelamento e decisão

Congelar pesos, hashes, config, parsing e thresholds. Abrir o test uma vez e emitir `GO_NANO_REAL`, `GO_20L_ONLY`, `GO_RULES_ONLY` ou `NO_GO`.

O benchmark de sistema com IA grande e edição sai de P13. Ele ocorre em P15, depois da policy JEV-like e do MCP real, evitando medir uma arquitetura transitória.

## 13. CI remoto sem espera

Fluxo por microtarefa:

```text
issue → branch → implementar → gates locais → commit → push/PR autorizado
      → registrar URL/SHA → encerrar sem polling
```

O GitHub Actions continua obrigatório para merge pela proteção da `main`, mas o agente não usa `gh run watch`, loops ou esperas. Em outro ciclo, CI vermelho vira correção atômica. Para evitar misturar tarefas enquanto PRs estão abertos, usar branch/worktree separado a partir da base correta.

## 14. Prompt para iniciar com uma IA econômica

Use uma IA econômica com raciocínio médio. Se uma microtarefa falhar por capacidade de raciocínio, escale somente essa microtarefa, sem ampliar o escopo nem afrouxar gates. O prompt operacional tem exatamente cinco linhas:

```text
Trabalhe em siga-teste conforme AGENTS.md; leia .local/PROGRESS.md e docs/21–24 e execute somente a primeira P13/P14/P15 ainda aberta.
Antes de agir, audite a evidência existente e nunca repita smoke, batch search, benchmark ou treino já válido; B1 usa uma geração e B2 somente callables reais.
Toda run deve ter GPU/engine explícita, timeout, progresso, checkpoint, orçamento e aborto por projeção; uma seed faz screening e três seeds apenas confirmam o vencedor.
Preserve splits temporais e test cego, meça precisão, grounding, P50/P95, tokens e sucesso de patch; nunca use simulação como evidência neural.
Rode os gates locais, faça um único commit da microtarefa, atualize PROGRESS e encerre sem push/PR nem espera pelo CI salvo autorização humana explícita.
```

Depois de P13, continuar no controlador de `docs/23`; depois de P14, integrar e medir o produto conforme `docs/24` P15.
