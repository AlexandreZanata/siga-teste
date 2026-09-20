# Decisions (ADRs resumidos)

Formato por decisão: Decision / Reason / Alternatives / Advantages / Disadvantages / Risks / How we validate. Opinião não é fato.

## ADR-001 — Separar pesos ≠ graph ≠ retrieval

- **Decision:** fatos estruturais e código atual nunca entram nos pesos; vivem em graph + retrieval com reindex incremental.
- **Reason:** commits não devem exigir retreino; fatos mudam rápido, padrões mudam devagar.
- **Alternatives:** memorizar SIGA nos pesos; embeddings puros sem graph.
- **Advantages:** atualização barata (`git pull` + reindex); menor dataset; menos hallucination de paths.
- **Disadvantages:** infra de indexação incremental para manter.
- **Risks:** drift índice↔código se updater falhar.
- **Validate:** Phase 2 mede precisão do graph puro; Phase 11 mede custo de update incremental.

## ADR-002 — V1 simples: Python + SQLite/DuckDB + Tree-sitter + ripgrep + Git

- **Decision:** sem K8s/microservices/Neo4j/vector-infra sem necessidade comprovada.
- **Reason:** simplicidade, precisão, manutenção, updates incrementais, CPU-friendly.
- **Alternatives:** Neo4j, LSIF/SCIP pesado, embeddings distribuídos.
- **Validate:** Phase 2 compara precisão/latência/custo; ADR revisita se SLO falhar.

## ADR-003 — Ferramentas: poucas semânticas sobre primitivas determinísticas

- **Decision:** Needle vê `siga_locate/trace/impact/history/context`; primitivas (`find_symbol`, `find_callers`, `read_symbol`, ...) ficam no backend.
- **Reason:** minimizar overlap, respeitar grounding (args vêm de resultados reais, não inventados), seguir guias Cactus de tool design.
- **Alternatives:** dezenas de tools primitivas expostas.
- **Validate:** Phase 5 mede tool selection accuracy, invalid call rate, path/symbol hallucination.

## ADR-004 — Execução por microfases locais (este repo)

- **Decision:** replicar padrão `.local/` (uma microtarefa, uma validação, um commit local, sem push automático).
- **Reason:** permite IAs baratas executarem com segurança e rastreabilidade; barato errar cedo.
- **Alternatives:** plano monolítico executado por IA cara.
- **Validate:** `PROGRESS.md` + `make verify` em cada tarefa; auditoria final P12.

## ADR-023 — GO condicional V1 + release candidate local (P11-T02)

> ADRs 005–022 vivem em `docs/00–17`; a numeração aqui segue a sequência global.

- **Decision:** GO condicional para o slice (executar, sem escalar pesos/distribuição/clientes) + release candidate local reproduzível sem publicar.
- **Reason:** números com evidência: on-policy 1,0 vs large-alone 0,0 (delta +0,3923 vs graph 0,3891) com redução 0,9934 vs arquivos brutos; `make verify` verde; bench isolado; sem segredo/TODO sem ID (regra P11-T02 em `scripts/final_audit.py`).
- **Alternatives:** NO-GO geral (refutado: b=0,3891 > a=0,0); NO-GO controlador/ADR-009 (refutado: tuned ≥ graph em todas as leituras); escalar agora (rejeitado: sem baseline 7, sem RAG, sem edição real).
- **Advantages:** decisão falsificável registrada com `experiment_id`; próximos 20 tasks em `docs/15 §6`.
- **Disadvantages:** slice cobre localização, não edição real (F10 pendente).
- **Risks:** overfit ao holdout de localização; mitigado por splits temporais + gate F20.
- **Validate:** `experiments/reports/final_audit.json` + run final; revalidar no F20 antes de qualquer distribuição.

## ADR-027 — Proteção da `main`: PR obrigatório + CI `verify` verde (F17)

- **Decision:** `main` protegida via branch protection do GitHub: pull request obrigatório (0 aprovações exigidas — mantenedor único; o gate é PR aberto + CI verde), status check `verify` obrigatório para merge, force push e deleção da branch negados; `enforce_admins` desligado, preservando bypass administrativo documentado.
- **Reason:** a regra disciplinar do `AGENTS.md` (nunca push direto; 1 tarefa = 1 issue = 1 branch = 1 commit = 1 PR) vira **mecanismo**: 17 tarefas consecutivas (F01–F16, P11) já seguiram esse fluxo e o `verify.yml` já roda em `pull_request` desde o P01 — a proteção torna obrigatório o que já era prática, com enforcement no servidor.
- **Alternatives:** rulesets (mais flexível, desnecessário para 1 branch + 1 check); exigir 1 aprovação humana (inviável em mantenedor único; viraria rubber-stamp); `enforce_admins=true` (bloquearia correção urgente se o CI falhar por infraestrutura).
- **Advantages:** push direto acidental é rejeitado pelo servidor, não pela disciplina; force-push e deleção impossíveis por credencial comum; histórico linear de PRs com CI auditável por tarefa.
- **Disadvantages:** bypass administrativo permanece possível (risco residual aceito e registrado); todo merge passa a depender do GitHub Actions.
- **Risks:** CI vermelho por infraestrutura trava merges — mitigado pelo bypass admin + re-run do workflow; check com nome errado daria proteção falsa — mitigado validando a resposta da API na ativação (`contexts=["verify"]`, mesmo nome do job do `verify.yml`).
- **Validate:** `gh api` confirma `required_pull_request_reviews` ativo, `required_status_checks.contexts=["verify"]`, `allow_force_pushes=false`, `allow_deletions=false`; o merge do próprio F17 acontece pelo fluxo protegido.

## ADR-028 — Wiki do GitHub como espelho read-only de `docs/` (F18) — SUPERSEDED por ADR-031

> Status: revogado. Mantido aqui por histórico; exigência removida em ADR-031. `scripts/sync_wiki.py` segue como utilitário manual opcional, sem gate.

- **Decision:** `scripts/sync_wiki.py` copia os `docs/*.md` (00–17 + README, 19 páginas) para a wiki do repositório com `Home.md` gerado contendo provenance (`source_commit` da `main` protegida, `synced_at`, contagem de páginas). O sync é idempotente byte a byte, determinístico (ordem alfabética; README por último), rejeita páginas estranhas ao plano (`Home`/`_Sidebar`/`_Footer` são os únicos nomes reservados) e só acessa rede em `--push` (clone raso + commit identity neutra + push). Sem pesos, checkpoints ou índices na wiki — NOT-build intocado; sem conversão de cross-references (continuam apontando ao repo).
- **Reason:** IAs externas consultam a wiki antes do repo; sem sync, wiki vazia ≠ `docs/` da `main` — dois pontos de verdade divergentes. Espelho com `source_commit` citável mantém a provenance exigida pelo AGENTS.md também fora do Git.
- **Alternatives:** GitHub Pages (site extra p/ manter, fora do escopo V1); wiki manual (desatualiza na 1ª edição); converter docs em páginas de app (acopla conteúdo a código).
- **Advantages:** única fonte de verdade (`docs/` na `main` protegida); wiki pública e fresca p/ agentes externos; idempotência permite cron/manual sem efeito colateral; núcleo puro testável offline.
- **Disadvantages:** segunda cópia do conteúdo (mitigada: wiki carrega `source_commit` e avisa que o repo é a fonte); cross-references `docs/04 §3` não viram links clicáveis na wiki.
- **Risks:** wiki com dado desalinhado se o sync ficar para trás — mitigado por `source_commit` visível no Home (defasagem é detectável, não invisível); push da wiki exige SSH/config do operador — fora do núcleo, erro é explícito.
- **Validate:** 8 testes (determinismo, idempotência byte a byte, espelho igual aos docs, stray pages, modo prepare sem rede, push exige repo); sync real pós-merge com evidência no `PROGRESS.md` (páginas + commit da wiki).

## ADR-029 — Servir 4-bit local; 2-bit permanece NOT-build, com gatilhos de revisitação (F19)

- **Decision:** o runtime local continua servindo **4-bit** (candidato congelado do P08: d12, 19,2MB disco / 28,6MB RAM, 98,44% tool acc, no-tool 1.0, hallucination 0.0). O NOT-build "servir 2-bit" permanece — agora como decisão falsificável com números (`scripts/quant2bit_decision.py` → `experiments/reports/quant2bit_decision.json`, run `20260919-142045-1788b4e26166`), não como mero costume. A economia do 2-bit (d12: 15,4MB RAM / 9,6MB disco, −13,2MB) é real nas tabelas mas **não resolve problema existente**.
- **Reason:** três razões determinísticas: (1) restrição de plataforma — `docs/00` fixa "2-bit shipped só na Cactus Platform", sem engine local que sirva 2-bit não há artefato para adotar; (2) RAM não-vinculante — F16 mediu sessão de 22,5MB vs SLO de 512MB, com folga > 95%, os ~13MB economizados não compram nada; (3) qualidade só simulada — a paridade de acurácia do P08 vem de simulação determinística; nenhum eval real do 2-bit existe no repo, e adotar seria decidir sobre número não medido.
- **Alternatives:** adotar 2-bit agora (rejeitada pelas 3 razões); adotar só em profundidade menor (pior: d8 d2-bit já perde acurácia — 97,79% — e não existe engine); esperar engine sem registrar gatilhos (decisão invisível não é falsificável).
- **Advantages:** decisão auditável com regras explícitas; trocar 4-bit→2-bit quando (e só quando) os gatilhos dispararem custa executar `run_decision(platform_supports_2bit=True)` + eval real — o mecanismo de reversão está pronto; provenance preservada (P08 congelado + F16 medido, sem alterar `training/compress.py`).
- **Disadvantages:** mantém ~13MB de RAM ociosa acima do mínimo teórico (irrelevante vs SLO); decisão depende de relatórios congelados (recalibrar exige degrau novo do ADR-017).
- **Risks:** gatilhos silenciosos — mitigado: os 3 gatilhos são medíveis e armados/desarmados no próprio relatório (hoje: 0 armados); paridade simulada ser tomada como real por terceiros — mitigado por campo `quantization_is_simulated: true` explícito.
- **Validate:** 7 testes (deltas do P08 congelado; keep_4bit com as 3 razões; adopt_2bit só quando TODAS as regras mudam — plataforma + RAM vinculante; artefatos com provenance); veredito estável contra os relatórios versionados.

## ADR-030 — GO estendido do slice revalidado com edição real e2e (F20)

- **Decision:** a revalidação do GO condicional do ADR-023 (`evaluation/go_revalidation.py` → `experiments/reports/go_revalidation.json`, run `20260919-150200-a0c9d12bbe9d`) roda a cadeia e2e completa (locate → patch unificado → `apply_unified_patch` em workspace isolado → `judge_rewrite`) sobre **toda a superfície JSP elegível do clone real** e emite veredito **GO estendido** com dois gates: os critérios originais do docs/17 (intactos, lidos do report congelado dos 3 braços) e o gate de edição (taxa válida ≥ 0,80, ≥ 5 tarefas, 0 edições fora de escopo). A superfície elegível é definida pelo **contrato congelado do juiz F11** (`_UNSAFE_JSP`, importado do próprio juiz — fonte única de verdade): no clone real, 9 de 596 JSPs; a revalidação cobre 9/9 (cobertura total, não amostra).
- **Reason:** o ADR-023 emitia GO condicional com ressalva explícita (edição não coberta); o F10 entregou `apply_unified_patch` e o F11 o juiz, mas a revalidação com edição nunca tinha rodado. Medido: **9/9 válidas (1,0)**, 0 fora de escopo, p50 194,9ms/tarefa, clone intocado verificado por comparação de arquivos rastreados, anti-leakage verificado; critérios originais passam inalterados — a ressalva do GO está fechada.
- **Alternatives:** medir todos os 596 JSPs (desonesta — alvos cujo original já contém padrão congelado-unsafe rejeitariam mecanicamente qualquer proposta, fabricando falhas no denominador; caso real descoberto: `definirMarcador.jsp` tem `javascript:` na linha 138); amostrar 5 (desnecessário — a superfície elegível é 9, cobertura total é barata); manter GO condicional (deixaria o §6 do roadmap aberto sem motivo).
- **Advantages:** GO não é mais condicional; gate de edição falsificável e re-executável deterministicamente; seletor importa o regex do juiz (contrato não pode divergir silenciosamente); workspace em tempdir com verificação de intocabilidade no teste.
- **Disadvantages:** superfície minúscula (9 JSPs HTML puros) — a evidência é sobre o **pipeline** de edição, não sobre edição em escala de produção; proposta determinística não mede qualidade de teacher real.
- **Risks:** defasagem da superfície se o SIGA ganhar JSPs novos — mitigado por re-execução determinística do módulo; mudança no contrato do juiz invalidaria a superfície — mitigado pela importação direta de `_UNSAFE_JSP`; "GO" ser lido como prontidão de edição em escala — mitigado pelo escopo explícito deste ADR e pelos campos `editing_e2e` no report.
- **Validate:** 9 testes (incl. e2e no clone real com clone intocado e o caso descoberto — alvo com `javascript:` excluído da superfície); run real publicado com provenance, `clone_untouched_verified=true` e `anti_leakage_verified=true`.

## ADR-031 — Remoção da exigência de wiki (F18 descontinuado)

- **Decision:** a wiki do GitHub deixa de ser exigência. Fonte única de verdade passa a ser `docs/` na `main` protegida. `scripts/sync_wiki.py` + `tests/test_sync_wiki.py` são mantidos como utilitário manual opcional, sem gate de DoD e sem sync real obrigatório. Nenhum bloqueio de release pode citar wiki ausente/desatualizada.
- **Reason:** custo operacional (repo wiki só nasce via UI, push exige SSH/config do operador) sem ganho medido para o slice; F20/GO não depende da wiki.
- **Alternatives:** manter sync obrigatório (rejeitado: trava release por infra externa); deletar script + testes (rejeitado: quebra histórico F18 e remove opção manual barata).
- **Advantages:** remove pendência humana única do F18; DoD volta a ser só `make verify` + critérios docs/17.
- **Disadvantages:** IAs externas sem espelho wiki consultam o repo direto.
- **Risks:** nenhum residual relevante.
- **Validate:** `make verify` verde; `docs/15 §6` marca F18 REMOVIDO e NOT-build inclui wiki.

## ADR-032 — Veredito do MCP: CONDICIONAL (G07, docs/18 §5)

- **Decision:** CONDICIONAL — MCP liberado como assistente de dev (locate/trace/context), sem alegação de economia até ref3 cega pós-correções; NO-GO mantido para a meta 0.99 (H05).
- **Reason (números, 60 tarefas cegas por ref):** ref1 (opencode): B 0.483 vs A 0.267 (delta +0.216), −13,7% tokens, `mcp_helps`; ref2 (Freebuff, independente): v1 (pré-F21) B 0.50 vs A 0.55 (delta −0,05), +312% tokens, `mcp_hurts` — history ignorava query (unions de 37–116 arquivos) + trace de 1 nó, corrigidos no F21; v2 (re-run cego do braço B pós-F21) B 0.333 vs A 0.55 (delta −0,217), +281% tokens — dessincronização GT congelado × ferramenta (GT de trace congelado no comportamento antigo de 1 nó; F23) mantém o `mcp_hurts` e reforça a necessidade do gate; cápsula v2 −55% tokens (H04); auditoria gold⊆bench PASS (H05). Regra `evaluation/g07_verdict.py`: refs divergentes ⇒ CONDICIONAL.
- **Alternatives:** GO pleno (rejeitado: ref2 real contradiz); NO-GO geral (rejeitado: ref1 + H-fixes + cápsula mostram valor em trace/locate/context).
- **Advantages:** decisão falsificável com gate explícito (ref3); uso assistido continua rendendo sem prometer economia.
- **Disadvantages:** economia não comprovada; ref3 custa outra rodada cega.
- **Risks:** F21/F22 não re-medidas em rodada cega — mitigado: ref3 é o gate, não opcional.
- **Validate:** `tests/test_g07_verdict.py` (regra); ref3 no protocolo docs/18 com F21/F22 ativas.

> Novas decisões entram aqui via tarefas com `docs(...): ...` e referência à fase.
