# 00 — Research: Needle atual + trabalhos relacionados

> Fonte inicial obrigatória: https://cactuscompute.com/blog/needle (Needle 26M, 12/05/2026). Estado atual verificado em 2026-09-18 via docs Python, guias de tools/fine-tuning e repo `cactus-compute/needle`. Não presumir que o artigo original cobre Needle 2/3.

## 1. Needle: do artigo ao estado atual

### 1.1 Artigo inicial (Needle 26M)

- 26M parâmetros, single-shot function calling; 6000 tok/s prefill, 1200 tok/s decode em consumer devices.
- Tese: `tool calling ≈ retrieval + argument extraction + structured generation`, não raciocínio geral. Cross-attention como primitiva; FFN desperdiçado nessa escala.
- Arquitetura: Simple Attention Networks — só atenção + gating, sem MLPs. Generaliza para qualquer tarefa com conhecimento externo estruturado (RAG/tool use).
- Treino: 200B tokens pretrain (16× TPU v6e, 27h) + 2B tokens function-calling sintetizado via Gemini (45min), 15 categorias (timers, messaging, navigation, smart home...).
- Limite declarado: vence FunctionGemma-270M/Qwen-0.6B/Granite-350M/LFM2.5-350M em single-shot, mas perde em conversação; "small models can be finicky — test on your own tools, finetune".
- Ref: https://cactuscompute.com/blog/needle ; pesos Apache-2.0 (`Cactus-Compute/needle`), engine Cactus com licença source-available própria.

### 1.2 Needle 2 (atual estável para deploy)

- 45M parâmetros, binário único 14MB, sessão completa em ~28MB RAM; CQ2-bit (Cactus Quants) + engine própria.
- Contrato: texto entra, JSON sai; gramática byte-level compilada dos schemas garante chamada bem-formada.
- Confidence calibrada via learned head; threshold para agir/escalar.
- Tool retrieval embutido: catálogo grande → head contrastiva elege top-5 por turno; gramática restrita ao subset; não-selecionado = inalcançável.
- Memória limitada: sliding window 256 tokens com tools como KV sinks.
- Pacote Python: `pip install cactus-needle` (runtime) + `cactus-needle[train]` (JAX). Engine baixada uma vez do HF e cacheada; offline/air-gapped documentado.
- Refs: https://github.com/cactus-compute/needle ; https://huggingface.co/Cactus-Compute/needle2 ; https://pypi.org/project/cactus-needle

### 1.3 Needle 3 (foco atual da Cactus)

- Modelo foundation 8–29MB para tiny devices; `needle.Needle(tools, system, weights, tool_index_path, buffer_size, auto_date, generation)`; `generation=2` mantém deploys antigos.
- `agent.run(query, max_steps=8)` executa funções e devolve `results`; `agent.complete(text)` = um turno (você executa e realimenta).
- Tools em 3 formas: função decorada (`@needle.tool`, docstring = descrição, `Args:` = descrições, default = opcional, `Literal` = conjunto fechado), Pydantic, JSON-schema cru / string. Nomes Java/camelCase viram aliases snake_case sem colisão.
- Resposta: `{type, function_calls[{name, arguments}], suppressed_calls, reasoning, confidence, prefill_tps, decode_tps, peak_ram_mb}`. `[]` = recusa off-topic (sem fallback free-text). `suppressed_calls` = confiança <0.1 ou gate de grounding.
- Contrato de grounding (crítico para nosso tool design): argumentos contêm só valores evidenciados no input; opcional sem evidência é omitido; requerido sem evidência e sem default suprime a chamada; reparo determinístico (split names, telefones, quotes verbatim, datas contra fato `date:`, polaridade do verbo, enums, rotas `from X to Y`).
- `system` = fatos (`date/locale/device/battery/network/location/user/assistant`), nunca instruções.
- Ambientes prontos: `needle.environments.{smart_home,media_player,productivity,wearable,kitchen_appliance,data_capture}` com 32 casos congelados cada + `run_tests(min_confidence)`.
- Ref: https://cactuscompute.com/blog/needle-python-docs (18/09/2026)

### 1.4 Tool design (regras oficiais que adotamos)

De https://cactuscompute.com/blog/designing-tools-for-needle :

1. Todo argumento é um span do request; `reasoning` deriva cada um (`'living room' -> room`). Se valor não estará no request, não exigir — usar `default`.
2. Uma tool por ação; descrição = ações cobertas, não categoria; sem instruções no texto (lido como fato).
3. Nomes que usuários diriam; enums com palavras reais; pares polares como tools separadas ou um enum.
4. Formatos na descrição (`"the place after 'from'"`, `"City, ST"`, ISO date); spans de rota, quotes, telefones, MIME, unidades resolvidos se o parâmetro disser o que quer.
5. Restrições na gramática (`Field(gt/le/pattern/min_length/... )`, `Literal`), não em prosa — inválido vira irrepresentável.
6. `triggers` (regex) para fraseados que descrição não enumera; match restringe gramática e exige chamada (mas não burla negação/contradição).
7. ≤5 tools por turno; acima disso retrieval top-5. Catálogo grande: dois turnos (escolhe tool, depois declara só ela).
8. Testar ambiente com suite congelada (positivos, `[]` quando falta valor/cobertura/negação/out-of-bounds, 2 chamadas ordenação-insensível), no engine shipped + threshold de produção.

Implicação direta: nossas 5 tools semânticas devem ter args extraídos da tarefa ou de resultados anteriores reais — nunca inventar path/símbolo (ver `docs/06-tool-design.md` na P00-T03).

### 1.5 Fine-tuning / LoRA / dataset / export / subnetworks

De https://cactuscompute.com/blog/finetuning-needle + `needle` CLI:

- LoRA rank 16 nas 5 projeções de atenção de cada layer, base congelada, merged no export; engine/tokenizer/confidence-head intocados; saída `.cact` via `weights=`.
- Formato JSONL, um objeto por linha: `{query, tools, answers[{name, arguments}], reasoning, [system]}`. `reasoning` opcional mas recomendado — ensina grounding, não só seleção.
- Regras: só valores presentes; off-topic com `"answers": []` (~1/8 do gerador; sem eles o modelo chama tool para tudo); ambíguas entre tools semelhantes; caber em `--max-len` (default 1024, silenciosamente truncado).
- Comandos: `needle generate-data --tools tools.json --num-samples 500` / `--augment data.jsonl`; `needle finetune data.jsonl --epochs 10 --out adapter.safetensors` (defaults: batch 16, lr 1e-4 warmup+cosine, clip 1.0, rank 16/alpha 32, val-split 0.1); `needle build --lora adapter.safetensors [--layers N] [--bits 2|4] --out tuned.cact`.
- Loss cobre só `reasoning` + chamada; começa ~1.0 (boilerplate já previsto); julgar pela tendência; val-loss subindo = overfit. Datasets pequenos: 200 ex × batch 16 = 13 steps/época → usar 10–30 épocas. Seleção move primeiro (centenas de ex); grounding exige milhares com reasoning variado; se acerta tool e erra valor, aumentar dados/variação, depois `--lora-rank 32`.
- Subnetworks: treina em 20 layers full, `build --layers 2..20` fatia; 2 layers fine-tuned já roda em devices mínimos; de 4 layers p/ cima tuned passa DeepSeek V4 Flash em DroidCall/Mobile Actions no relato oficial (verificar no nosso bench, não aceitar como fato).
- Não muda: confidence (`None` em tuned — rotear por validação própria), tokenizer (não-inglês fragmenta ~1.7×), bits locais (4-bit; 2-bit shipped só na Cactus Platform).
- Telemetria anônima opt-out (`NEEDLE_TELEMETRY=0`/`DO_NOT_TRACK=1`).

### 1.6 O que falta confirmar antes de P07

- Versão exata `cactus-needle` + engine pinada no nosso lockfile (P01/P07).
- Reproduzir `needle.environments.smart_home.run_tests()` no nosso hardware como smoke.
- Medir fragmentação PT-BR no tokenizer e impacto no budget 1024.
- Validar que `confidence=None` em tuned não quebra nosso roteamento (usar validação própria desde P04).

## 2. Trabalhos relacionados (por que importa / reuso / limite / ref)

1. **SWE-bench (Jimenez et al., 2024)** — padrão-ouro de issue-resolution com testes; importa como metodologia de verificação, não como dataset (Java/VRaptor fora do escopo). Reuso: harness FAIL_TO_PASS/PASS_TO_PASS como inspiração do `verifier/`. Limite: coleta cara, Python-centrado. Ref: https://www.swebench.com/
2. **SWE-smith (Yang et al., NeurIPS 2025 Spotlight)** — toolkit que transforma qualquer repo em SWE-gym; 50k+ instâncias, bugs sintéticos que quebram ≥1 teste. Reuso direto: mutações + ambientes Docker como modelo da nossa `task_factory/mutation`. Limite: exige Docker/Ubuntu, custo de geração (~$1360 p/ 50k). Ref: https://github.com/SWE-bench/SWE-smith ; arXiv:2504.21798
3. **SWE-agent / OpenHands** — agentes com terminal que iteram patch↔teste. Reuso: loop observation→action como formato da trajetória. Limite: multi-tool frágil, contexto enorme — exatamente o custo que queremos cortar. Refs nas docs SWE-bench.
4. **RepoNavigator ("One Tool Is Enough", 2025)** — tese de tool única `jump` p/ definição de símbolo + RL tool-integrated (GRPO), SOTA em localização. Reuso: evidência de que poucas tools boas vencem catálogo grande; inspira `siga_locate/trace`. Limite: Python/SWE-bench; não prova transferência p/ Java/JSP/VRaptor. Ref: arXiv html 2512.20957
5. **RepoGraph (2025)** — code graph repository-wide como plug-in que eleva todos os frameworks no SWE-bench. Reuso: validação da hipótese graph-first; schema nodes/edges como ponto de partida. Limite: grafo sem controlador aprendido — lacuna que Needle tenta preencher. Ref: arXiv:2410.14684
6. **CodexGraph / RepoUnderstander (2024)** — repos como knowledge graph. Reuso: padrões de modelagem (CONTAINS/DEFINES/CALLS). Limite: retrieval sem decisão aprendida de quando parar. Ref: tabela comparativa em RepoGraph.
7. **Open-SWE-Traces (2026)** — destilação dual-mode (thinking/non-thinking) de agentes SWE para Qwen3-Coder-30B (61.7% Verified). Reuso: prova de que trajetórias curtas verificadas destilam; nosso teacher factory segue o padrão com verificação determinística. Limite: 30B — 1000× maior que nosso alvo; não responde "menor modelo viável". Ref: arXiv:2606.16038
8. **RepoDistill / RepoScope (2025–26)** — compressão de conhecimento de repo com budget allocation + RSSG 4-view context. Reuso: ideias de capsule mínima e alocação de contexto. Limite: foco em compressão, não em controlador navegável. Ref: Findings-ACL 2026.217
9. **Function-calling distillation (FunctionGemma-270M, LFM2.5-350M, Apple FM)** — baselines que Needle 2 troca vitórias sendo 5–70× menor. Reuso: baselines alternativas se Needle falhar estruturalmente. Limite: conversacionais, não grounding-estrito. Ref: benchmarks citados em https://github.com/cactus-compute/needle
10. **SCIP/LSIF, Tree-sitter, JavaParser/JDT/Spoon, Tantivy/ripgrep** — infra determinística. Reuso: V1 usa Tree-sitter/JavaParser + ripgrep + SQLite (decisão detalhada em `docs/05`). Limite: precisão Java/JSP exige avaliação própria, não hype. Refs nos repos oficiais.

## 3. Conclusão para o projeto

Needle 2/3 casa com a tese (retrieval+extração, grounding-estrito, 5 tools, LoRA barato, subnetworks até 2L, offline 28MB), mas impõe restrições duras (sem free-text, args só evidenciados, `[]` p/ off-topic, confidence ausente em tuned, catálogo >5 com retrieval). O plano assume Needle como baseline experimental falsificável, não como dogma — P00-T03 documenta limitações/mitigações/alternativas.
