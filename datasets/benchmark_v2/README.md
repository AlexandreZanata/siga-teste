# Benchmark v2 — Holdout Temporal Cego (P13-T02)

Benchmark oficial cego para avaliação real do modelo Needle 3 na RTX 4060.

## Isolamento e Blind Test
- **Test Cego:** 300 tarefas derivadas de commits >= 2023-01-01.
- **Inacessível ao Treinador:** Proibido carregar ou consultar tarefas de split `test` em qualquer etapa de treinamento, fine-tuning ou geração de dados.
- **Validação Temporal:** 200 tarefas de commits entre 2021-01-01 e 2023-01-01.
- **Treino Holdout:** 200 tarefas de commits anteriores a 2021-01-01.
- **Adversarial:** 10 consultas off-topic, vagas, homônimos e de recusa.

## Hashes Criptográficos
Gerados deterministicamente com seed 20260921.
