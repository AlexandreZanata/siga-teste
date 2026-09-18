# Research — SIGA Needle Expert (índice, Phase 0 preenche)

Pergunta central: `nano specialist + deterministic repository intelligence + large LLM` é superior a `large LLM sozinho` para desenvolvimento no SIGA, medido por `task_success >= X` com `tokens << Y`, `custo << C`?

Referência inicial obrigatória: https://cactuscompute.com/blog/needle — não presumir que representa o estado atual; localizar docs atuais de Needle 2/3, Python API, tool calling, LoRA, confidence, dataset format, export, subnetworks.

Linhas de pesquisa (cada uma com porquê importa / o que reutilizar / limitações / referência) em `docs/00-research.md` (Phase 0):

- agent distillation, small LM agents, tool-calling distillation, on-policy distillation
- repository-level understanding, code knowledge graphs, RepoNav, SWE-bench, SWE-smith
- AST/symbol/graph retrieval, code RAG, function-calling fine-tuning, context compression, agent memory distillation

Questionamento obrigatório (falsificar a ideia — 17 perguntas do plano, ex.: Needle é o melhor? O que o graph determinístico já resolve? Onde há latência sem ganho? Quais args violam grounding? Qual menor dataset/subnetwork? Como evitar leakage Git→bench? Como medir economia real?) — respondido com evidência em `docs/16-risks-open-questions.md` + `docs/17-first-experiment.md`.

Primeiro experimento (vertical slice `siga-ex`+`sigaex`, locate+trace, 500–2k exemplos, holdout 200–500, large-alone vs large+graph vs large+Needle): `docs/17-first-experiment.md`.
