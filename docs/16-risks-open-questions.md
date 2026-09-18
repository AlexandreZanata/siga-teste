# 16 — Risks, open questions (17 falsificáveis) e alternativas

> Cada resposta cita evidência e o doc/ADR correspondente. O que falta medir vira gatilho no slice (`docs/17`).

1. **Needle é o melhor?** Não provado; é o baseline experimental (ADR-005, `docs/03`). Alternativas vivas: small coder, graph+reranker, large-alone.
2. **O que o graph determinístico já resolve?** Tudo citável por `file:linha` (símbolos, refs, callers, migrations) — P03 publica o teto antes de qualquer LLM.
3. **Onde Needle agrega?** Escolha de tool + extração de args em queries ambíguas PT-BR; o resto é determinístico.
4. **Latência sem ganho?** Sim, risco real: cada turno soma inferência local; mitigado por trajetórias ≤4 calls e P50 medido (`docs/10 §2`).
5. **Tarefas que precisam do nano?** Locate vago, desambiguação entre tools/símbolos homônimos, decisão de parar e compactar.
6. **100% determinísticas?** Leitura de símbolo, callers/callees, diff, history, outline, busca literal, update incremental.
7. **Args incompatíveis com grounding?** Paths/símbolos/tabelas gerados de memória (ADR-006 proíbe).
8. **Tools compatíveis?** Args = spans da tarefa ou results anteriores + defaults (ADR-014).
9. **Menor dataset p/ benefício?** Hipótese: centenas p/ seleção, milhares p/ grounding (`docs/00 §1.5`); curvas 100→10k decidem (ADR-017).
10. **Menor subnetwork?** Hipótese: 4L (relato oficial passa DeepSeek V4 Flash; verificar, não aceitar).
11. **Quando 100M é desnecessário?** Quando P03 resolve sem LLM — o slice quantifica.
12. **Dezenas de MB com qualidade?** Needle 2 = 14MB/28MB RAM; P08 fatia 20→2L e mede.
13. **Melhor baseline sem treino?** Needle base + 5 tools + suite 32 casos (`docs/03`, final).
14. **Anti-leakage?** Splits T1/T2 + prefixo isolado + teste SHA por build (ADR-018).
15. **Economia real?** `effective_token_reduction` + `task_success_delta` por `experiment_id` (ADR-019).
16. **Atualizar com mudanças?** `git pull` + reindex incremental versionado (`docs/05 §3`), sem retreino.
17. **Jamais nos pesos?** Fatos mutáveis: código atual, paths, SHAs, tabelas, rotas, preços/dados (ADR-001).

## Alternativas consideradas (resumo)

Controlador por regras+reranker (plano B, ADR-009); embeddings/RAG (adiado p/ depois da P03, ADR-012); Neo4j/K8s (rejeitados na V1, ADR-011/`docs/01 §7`); tool única `jump` (fusão trace+locate rejeitada — golds distintos, `docs/06 §2`).
