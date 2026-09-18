# 06 — Tool design: 5 semânticas sobre primitivas determinísticas

> Regras oficiais Cactus em `docs/00 §1.4`. Grounding obrigatório em `docs/03` ADR-006. Cada decisão em ADR resumido; overlap só quando justificado abaixo.

## ADR-013 — Poucas tools semânticas visíveis; primitivas internas

- **Decision:** Needle vê exatamente 5 tools; as 12 primitivas vivem no backend, compostas deterministicamente.
- **Reason:** regra oficial "uma tool por ação" + "≤5 por turno" (`docs/00 §1.4`, itens 2 e 7): 5 nomes distinguíveis maximizam tool selection; primitivas expostas virariam 17+ opções e forçariam o modelo a inventar args de navegação.
- **Alternatives:** dezenas de primitivas expostas; tool única `jump` (tese RepoNavigator).
- **Advantages:** seleção vira "escolher o nome" (ponto forte do modelo); args restantes são spans/results reais.
- **Disadvantages:** backend maior; rigidez se faltar primitiva.
- **Risks:** tool errada no top-5 = turno perdido — mitigado por 2-turnos em catálogo ambíguo.
- **Validate:** tool selection accuracy + invalid call rate na P05; ablacionar 5 vs 17 expostas.

## 1. As 5 tools (contratos)

| Tool | Ação (descrição = ações, não categoria) | Args (todos grounding-safe) | Retorna |
|------|------------------------------------------|-----------------------------|---------|
| `siga_locate` | Localiza arquivos/símbolos/componentes de uma funcionalidade | `query` (span da tarefa), `kind?` (`Literal[file,symbol,controller,entity,jsp,migration,test]`, default omitido) | candidatos reais `file::symbol` + score |
| `siga_trace` | Traça fluxo endpoint→controller→BL→entidade→persistência→view | `symbol` (símbolo real de passo anterior), `depth?` (int 1–3, default 2) | cadeia A→B→C com paths |
| `siga_impact` | Efeitos de modificar arquivo/classe/método/feature | `target` (símbolo/path real), `hops?` (default 1) | callers/callees, testes, tabelas |
| `siga_history` | Mudanças semelhantes e co-change no Git | `target` (símbolo/path real) ou `query` (span), `since?` (default janela do split) | commits (SHA), diffs, `CHANGED_WITH` |
| `siga_context` | Cápsula final mínima p/ IA grande | `symbols[]` (reais), `task` (verbatim da tarefa) | cápsula (formato na P09) |

Primitivas internas (nunca visíveis): `repo_tree, find_file, find_symbol, find_references, find_callers, find_callees, search_text, read_symbol, get_file_outline, git_history, git_diff, find_related_tests, find_migration`.

## 2. Matriz de overlap (sem overlap injustificado)

| Par | Distinção | Justificativa |
|-----|-----------|---------------|
| `locate` × `search_text` | `locate` é semântica ranqueada p/ o modelo; `search_text` é primitiva literal interna | `locate` compõe `search_text`+graph; modelo nunca vê a primitiva |
| `trace` × `impact` | `trace` segue fluxo p/ frente (execução); `impact` expande vizinhança (callers + testes + tabelas) | direções opostas; golds distintos |
| `history` × `impact` | `history` = passado (commits); `impact` = presente (grafo) | fontes disjuntas (Git vs AST) |
| `context` × demais | `context` não recupera nada novo; só compacta símbolos já validados | única tool de escrita da cápsula |
| `trace` × `history` (implementações semelhantes) | semelhantes via `history` (co-change real), não via `trace` | evita duplicar "find analog" como 6ª tool |

## ADR-014 — Args com defaults, nunca requeridos sem span

- **Decision:** todo parâmetro cujo valor pode não estar na tarefa é opcional com default (`kind?`, `depth?=2`, `hops?=1`, `since?`); `query`/`symbol`/`target` vêm de span ou result anterior.
- **Reason:** regra oficial 1 (`docs/00 §1.4`): requerido sem span suprime a chamada (`suppressed_calls`) — transformaria dúvida em recusa silenciosa.
- **Alternatives:** tudo requerido + reparo posterior.
- **Advantages:** nunca `[]` por schema mal desenhado; `[]` passa a significar "off-topic de verdade".
- **Disadvantages:** defaults errados em queries atípicas.
- **Risks:** modelo omite `kind` sempre → `locate` genérico; dataset precisa premiar `kind` correto.
- **Validate:** taxa de `suppressed_calls` por falta de arg ≈ 0 nos golds da P05.
