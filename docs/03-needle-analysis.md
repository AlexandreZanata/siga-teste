# 03 — Needle analysis: adequação, grounding, limitações, alternativas, baseline

> Base factual em `docs/00-research.md`. Aqui: julgamento arquitetural para o SIGA. Formato ADR resumido por decisão. Opinião não é fato.

## ADR-005 — Needle como controlador do SIGA Expert (baseline experimental, não dogma)

- **Decision:** adotar Needle 2/3 (`cactus-needle`, pinado na P07) como baseline experimental do controlador; manter alternativas vivas até o vertical slice decidir com números.
- **Reason:** casa com a tese (`docs/00 §1`): retrieval+extração em vez de raciocínio; 5 tools visíveis sem retrieval interno; gramática garante JSON válido (elimina classe inteira de erros de parse); LoRA barato + subnetworks até 2L + offline 28MB atendem hardware de dev; `reasoning` de 1 linha casa com trajetórias curtas.
- **Alternatives:** (a) small coder tradicional (Qwen-0.6B/FunctionGemma-270M) como controlador; (b) grafo determinístico + reranker por embeddings, sem LLM controlador; (c) IA grande fazendo retrieval direto.
- **Advantages:** menor modelo da fronteira tamanho×qualidade em tool-calling single-shot; fine-tune local barato; contrato `[]` p/ off-topic já resolve parte dos hard negatives.
- **Disadvantages:** single-shot por natureza — multi-hop (`locate→trace→context`) exige loop `run()/complete()` externo; sem free-text (cápsula final precisa de outro componente); modelos pequenos são "finicky" (dito pelo próprio vendor).
- **Risks:** transferência smart-home→Java/VRaptor/JSP não provada; PT-BR fragmenta ~1.7× o tokenizer.
- **Validate:** vertical slice (`docs/17`, P00-T05): Needle base vs tuned vs determinístico puro vs large-alone. Se tuned ≤ determinístico+regras, Needle é refutado como controlador e vira extrator (ver ADR-009).

## ADR-006 — Fluxo grounding-safe obrigatório

- **Decision:** todo argumento de tool que nomeia artefato de código (path, classe, método, tabela, JSP, migration) só pode vir de (a) span da tarefa do usuário ou (b) resultado real de tool anterior. Nunca de geração livre.
- **Reason:** contrato oficial do Needle (`docs/00 §1.4`, regra 1): sem span → opcional omitido, requerido suprime a chamada. Inventar `ExDocumentoController.java` "de memória" é exatamente o modo de falha que o grounding gate pune.
- **Alternatives:** permitir ao modelo propor paths e validar depois (gerar→verificar→corrigir).
- **Advantages:** path/symbol hallucination tende a zero por construção; cada passo é auditável.
- **Disadvantages:** primeiro passo (`siga_locate`) carrega todo o peso — query ruim = cascata ruim; exige retrieval textual forte antes de qualquer símbolo.
- **Risks:** queries vagas ("arrumar tramitação") sem span aproveitável.
- **Validate:** métricas `Path/Symbol Hallucination Rate` no bench (P04); ablacionar `locate(query livre)` vs `locate(spans extraídos deterministicamente)`.

## Limitações estruturais conhecidas + mitigação

| # | Limitação | Mitigação no design | Alternativa se falhar |
|---|-----------|---------------------|----------------------|
| L1 | Janela 256 tokens c/ tools como KV sinks; 5 tools visíveis | 5 tools semânticas compactas (descrições curtas, enums fechados); catálogo maior = 2 turnos | Reranker externo + 1 tool por turno |
| L2 | `confidence=None` em pesos tuned | Roteamento por validação própria (verifier determinístico), nunca por confidence em tuned | Manter base p/ decisão + tuned p/ chamada |
| L3 | Sem multi-hop nativo; `max_steps=8` no `run()` | Loop externo `complete()` com estado no backend; trajetórias gold curtas (2–4 calls) | Controlador por regras p/ hops fixos |
| L4 | Tokenizer fragmenta PT-BR (~1.7×) | Budget 1024 medido em PT-BR na P04; queries canônicas curtas | Vocabulário SIGA como `Literal`/enums |
| L5 | `.cact` amarrado à versão do engine | Pinar `cactus-needle` + engine no lockfile; rebuild versionado como artefato de experimento | — |
| L6 | `[]` (recusa) indistinguível entre "off-topic" e "faltou span" | Telemetria de `suppressed_calls` + `validation.ungrounded` no dataset | Threshold próprio sobre verifier |

## Baseline sem treinamento (resposta à pergunta 13 do plano)

Antes de qualquer LoRA: Needle base + 5 tools + descrições PT-BR curtas + suite congelada de 32 casos por ambiente (padrão `needle.environments`). Essa baseline já mede tool selection, grounding e `[]`-rate — e é o piso que o fine-tune precisa bater.
