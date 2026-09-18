# 07 — Dataset strategy: JSONL versionado, provenance total, splits temporais

> Formato Needle em `docs/00 §1.5`; isolamento do bench em `docs/10`; teachers em `docs/08`. Decisões em ADR resumido.

## ADR-015 — Pipeline RAW → CANONICAL → NEEDLE EXPORT, nunca direto

- **Decision:** três estágios versionados independentemente: `RAW` (saída bruta dos teachers) → `CANONICAL` (normalizado + verificado) → `NEEDLE EXPORT` (JSONL no formato exato do `needle finetune`).
- **Reason:** desacopla o projeto do formato atual da Cactus; se o formato mudar, só o exportador muda; verificação e bench continuam válidos.
- **Alternatives:** treinar direto no formato da lib; dataset monolítico sem estágios.
- **Advantages:** reprodutibilidade por estágio (hash por arquivo); re-export barato; auditoria do que foi descartado (`rejected/` preserva motivo).
- **Disadvantages:** mais código de pipeline.
- **Risks:** drift entre estágios se schemas não forem testados — mitigado por `test-contract` do formato canonical.
- **Validate:** P06 publica hashes e taxas de aprovação por estágio.

## 1. Layout (paths distintos — bench nunca aqui)

```text
datasets/
  raw/         # saída bruta por teacher: {teacher}/{prompt_version}/{data}.jsonl
  canonical/   # normalizado + verificado: v{N}/canonical.jsonl + report.json
  verified/    # subset gold aprovado p/ treino
  rejected/    # descartados com {reason, verifier_version}
  benchmark/   # PROIBIDO p/ treino — ver docs/10 (holdout isolado, outro prefixo de SHA)
```

Regra inviolável: nenhum SHA de commit presente em `benchmark/` pode aparecer em `raw|canonical|verified`, testada automaticamente na P04/P06.

## 2. Registro canonical (campos obrigatórios)

`{id, repo_commit, task_type, query, tools, trajectory[], answers[], reasoning, verification{verifier_version, checks[]}, teacher, source(git|synthetic|human), difficulty, score, prompt_version, timestamp, generator_version, license}`.

`trajectory[]` = passos `OBSERVATION→ACTION→TOOL ARGS→RESULT`, sem prosa; `reasoning` = 1 linha factual estilo `"'tramitação' -> query"` (formato exigido pelo Needle, `docs/00 §1.5`).

## 3. Splits temporais (definidos aqui, aplicados na P04/P06)

Corte por data de commit no `desenvolvimento`: `train` < T1 < `valid` < T2 < `test`/bench. T1/T2 congelados no `benchmark/manifest.json` antes de qualquer treino. Random split é proibido (vazaria futuro no passado).

## 4. Composição e progressão

Categorias (`docs/08 §2`): locate file/symbol, trace, endpoint/controller/JSP/migration, análogos via co-change, impacto, testes relacionados, bug/feature localization, ambíguas, off-topic (`answers: []`, ~1/8), no-tool, insuficiente + mutações (SWE-smith como modelo, `docs/00` item 2). Hard negatives obrigatórios: tools semelhantes, args parecidos, homônimos (`ExModelo` vs `ExModeloController`), módulos vizinhos.
Progressão científica: 100 gold manuais → 500 → 2k → 5k → 10k; só escala com análise de erros (curvas em `docs/09`).
