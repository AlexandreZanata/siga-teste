# Roadmap — SIGA Needle Expert (espelho versionado do `.local/MASTER_PLAN.md`)

Fases obrigatórias em ordem (nenhuma começa sem o exit gate da anterior):

1. `P00` Research + contrato de execução
2. `P01` Fundação Python reproduzível
3. `P02` Repository intelligence (indexer + graph)
4. `P03` Baseline determinístico (sem LLM)
5. `P04` SIGA-Bench (antes do treino, sem contaminação)
6. `P05` Tool environment (5 tools semânticas + primitivas)
7. `P06` Teacher data factory (DeepSeek + Gemini + Muse)
8. `P07` Needle fine-tuning (baseline → LoRA)
9. `P08` Compressão por subnetworks (menor modelo viável)
10. `P09` Context capsule + integração large model
11. `P10` MCP/API para agentes externos
12. `P11` On-policy improvement + avaliação final
13. `P12` Release local, privacidade, licença
14. `P13` Evidência real: Needle 3 em JAX/CUDA na RTX 4060 + benchmark v2 não contaminado (`docs/21`)
15. `P14` Controlador JEV-like: decisões tipadas, calibração, stop/escalada e economia e2e (`docs/23`)

Detalhes, tarefas `PXX-TYY`, validações e commits exatos: `.local/MASTER_PLAN.md` + `.local/phases/*.md`.

Definição de pronto e métrica central (`effective_token_reduction` com `task_success_delta`): `docs/10-siga-bench.md`, `docs/11-evaluation.md`, `docs/15-roadmap.md` (Phase 0).
